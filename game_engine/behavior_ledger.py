#!/usr/bin/env python3
"""行为账本（Stage T · T1）：只记「公开发生、所有人都看得见」的行为。

归属规则见 logs/handover/20261017_1150_StageT酒馆系统施工方案.md 第 6 节：
- 记录只来自「牌 / 技能结算确定目标的那一处」，由 card_system / 技能处理器调用 record()；
- 绝不记隐藏信息：不记「该救没救、该闪没闪」，不记手牌区被拿走的牌名；
- 群体牌（南蛮、万箭、桃园、五谷）只记 group，不计任何人的敌意 / 友好；
- 本模块不依赖引擎，只处理 id 与数字，便于单测。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable, Dict, Iterable, List, Optional, Tuple

KINDS = ("hostile", "friendly", "protect", "counter", "transfer", "group")

# 权重：普通 1；意图不明确 / 被动反击 0.5；救援是最强的站队信号 3。
WEIGHT_LOW = 0.5
WEIGHT_NORMAL = 1.0
WEIGHT_HIGH = 3.0
DEFAULT_WEIGHT = {
    "hostile": WEIGHT_NORMAL, "friendly": WEIGHT_NORMAL, "protect": WEIGHT_NORMAL,
    "counter": WEIGHT_LOW, "transfer": WEIGHT_NORMAL, "group": 0.0,
}

# 汇总里给被动 / 转移类标签加后缀，让读者一眼分清性质。
_KIND_SUFFIX = {"counter": "(反击)", "transfer": "(转移)"}
_MERGED_LABEL = "其他"
_MAX_KEY_EVENTS = 5
_PAIRS_PER_LINE = 3
SUMMARY_HEADER = "【引擎确认·行为账本】"


def summary_limit(player_count: int) -> int:
    """汇总长度上限：5 人局约 300 字，8 人局约 600 字，其间线性。"""
    return max(300, 100 * int(player_count) - 200)


@dataclass
class LedgerEntry:
    seq: int
    round: int
    source_id: int
    target_id: Optional[int]
    kind: str
    label: str
    weight: float

    def to_dict(self) -> Dict:
        return asdict(self)


class BehaviorLedger:
    def __init__(self):
        self.entries: List[LedgerEntry] = []
        self._seq = 0
        # 订阅者：每记一条就同步通知一次（聊天调度器据此发现「救主公」）；回调异常不影响记账。
        self.listeners: List[Callable[[LedgerEntry], None]] = []

    # ---------- 写入 ----------

    def record(self, round_no, source_id, target_id, kind, label, weight=None) -> Optional[LedgerEntry]:
        """记一条行为。自己对自己、未知类型、缺来源一律不记，返回 None。"""
        if kind not in KINDS or source_id is None:
            return None
        if kind == "group":
            target_id = None
        elif target_id is None or target_id == source_id:
            return None
        if weight is None:
            weight = DEFAULT_WEIGHT[kind]
        self._seq += 1
        entry = LedgerEntry(self._seq, int(round_no or 0), source_id, target_id, kind, str(label), float(weight))
        self.entries.append(entry)
        for listener in list(self.listeners):
            try:
                listener(entry)
            except Exception:  # noqa: BLE001 - 订阅者永远不能拖垮记账
                pass
        return entry

    def record_group(self, round_no, source_id, label) -> Optional[LedgerEntry]:
        return self.record(round_no, source_id, None, "group", label)

    def remove(self, entries: Iterable[Optional[LedgerEntry]]):
        """撤销刚记的条目（出牌最终失败、牌退回手牌时用）。"""
        doomed = {id(e) for e in entries if e is not None}
        if doomed:
            self.entries = [e for e in self.entries if id(e) not in doomed]

    def snapshot(self) -> List[Dict]:
        """局后日志用：完整流水（均为公开事实）。"""
        return [e.to_dict() for e in self.entries]

    # ---------- 规则 AI 用（6.5） ----------

    def stance_toward(self, subject_id, target_id) -> float:
        """subject 对 target 的立场：正 = 敌意，负 = 友好 / 保护。反击与转移不算站队。"""
        score = 0.0
        for e in self.entries:
            if e.source_id != subject_id or e.target_id != target_id:
                continue
            if e.kind == "hostile":
                score += e.weight
            elif e.kind in ("friendly", "protect"):
                score -= e.weight
        return score

    # ---------- 汇总（6.4） ----------

    def summarize(self, game_state, max_chars: Optional[int] = None) -> str:
        """按「来源→目标」聚合的计数加少量关键事件。没有可汇总的内容时返回空串。"""
        players = list(getattr(game_state, "players", []) or [])
        by_id = {p.id: p for p in players}
        limit = max_chars or summary_limit(len(players))

        def seat(pid) -> str:
            p = by_id.get(pid)
            tag = "(主公)" if p is not None and getattr(p, "identity_revealed", False) \
                and getattr(p, "identity", None) == "lord" else ""
            return f"{pid + 1}号{tag}"

        pairs: Dict[Tuple[int, int], Dict[Tuple[str, str], List[float]]] = {}
        order: List[Tuple[int, int]] = []
        keys: List[LedgerEntry] = []
        for e in self.entries:
            if e.kind == "group":
                continue
            pair = (e.source_id, e.target_id)
            if pair not in pairs:
                pairs[pair] = {}
                order.append(pair)
            slot = pairs[pair].setdefault((e.label + _KIND_SUFFIX.get(e.kind, ""), e.kind), [0, 0.0])
            slot[0] += 1
            slot[1] += e.weight
            if e.weight >= WEIGHT_HIGH:
                keys.append(e)
        if not pairs:
            return ""
        round_no = getattr(game_state, "round_number", None)
        header = f"{SUMMARY_HEADER}（截至第{round_no}轮）" if round_no else SUMMARY_HEADER

        def build(merge_low: bool, drop_pairs: int, key_count: int) -> str:
            segments = []
            kept = order
            if drop_pairs:
                # 先丢总权重最小的来源→目标；同权重丢更早出现的。
                weight_of = {p: sum(v[1] for v in pairs[p].values()) for p in order}
                doomed = set(sorted(order, key=lambda p: (weight_of[p], order.index(p)))[:drop_pairs])
                kept = [p for p in order if p not in doomed]
            for pair in kept:
                parts, low_count = [], 0
                for (label, kind), (count, weight) in pairs[pair].items():
                    if merge_low and weight / count < WEIGHT_NORMAL:
                        low_count += count
                    else:
                        parts.append(f"{label}×{count}")
                if low_count:
                    parts.append(f"{_MERGED_LABEL}×{low_count}")
                segments.append(f"{seat(pair[0])}→{seat(pair[1])}：" + " ".join(parts))
            lines = ["　｜　".join(segments[i:i + _PAIRS_PER_LINE])
                     for i in range(0, len(segments), _PAIRS_PER_LINE)]
            if key_count and keys:
                events = [f"第{e.round}轮 {seat(e.source_id)}{e.label}{seat(e.target_id)}"
                          for e in keys[-key_count:]]
                lines.append("关键事件：" + "；".join(events))
            return "\n".join([header] + lines)

        key_count = min(_MAX_KEY_EVENTS, len(keys))
        text = build(False, 0, key_count)
        if len(text) > limit:                     # 1. 先合并低权重条目
            text = build(True, 0, key_count)
        dropped = 0
        while len(text) > limit and dropped < len(order) - 1:   # 2. 再丢最不重要的来源→目标
            dropped += 1
            text = build(True, dropped, key_count)
        while len(text) > limit and key_count > 0:              # 3. 最后截断最早的关键事件
            key_count -= 1
            text = build(True, dropped, key_count)
        if len(text) > limit:                                   # 兜底：硬截断，保证绝不超限
            text = text[:limit - 1] + "…"
        return text


__all__ = ["BehaviorLedger", "LedgerEntry", "KINDS", "DEFAULT_WEIGHT", "WEIGHT_LOW",
           "WEIGHT_NORMAL", "WEIGHT_HIGH", "SUMMARY_HEADER", "summary_limit"]
