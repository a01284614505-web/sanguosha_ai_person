"""Stage T · T2 认知笔记：每个模型 AI 对其他座位身份的结构化判断（方案第 7 节）。

数据格式（内部以座位 id = player.id 为键；对模型与前端显示的"座位号" = id + 1）::

    {target_id: {"guess": "rebel", "conf": "高", "why": "两次杀主公"}}

规则：
- ``guess`` ∈ lord / loyalist / rebel / spy / unknown；``conf`` ∈ 高 / 中 / 低；``why`` 为 ≤20 字的字符串。
- 逐条校验：非法条目丢弃，保留上一版；其余合法条目照常生效。
- 已揭示身份的座位由引擎自动填写并锁定（``locked``），AI 不能改。读取时按"当前谁已揭示"实时合并，
  所以开了「阵亡暗置」时阵亡者的 ``identity_revealed`` 保持 False，引擎自然不填，阵亡者照常可猜（待确认 J 的推荐）。
- 只在 AI 自己的出牌决策里更新；笔记是独立结构，**不进会话窗口、不参与压缩**，每次出牌决策由 prompt 重新注入。
- AI 阵亡时冻结：之后不再更新，也不再自动填写。
- 每轮结束存一份快照（供局后日志、读人准确率）。
- 规则 AI / 无 Key AI 不写笔记（调用方只在模型决策成功解析后才会调用 ``update``）。

本模块只读引擎的公开状态（谁已揭示身份、谁存活），不读任何手牌。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

GUESSES = ("lord", "loyalist", "rebel", "spy", "unknown")
CONFS = ("高", "中", "低")
WHY_MAX = 20

GUESS_LABEL = {"lord": "主公", "loyalist": "忠臣", "rebel": "反贼", "spy": "内奸", "unknown": "未知"}

_SEAT_KEY_RE = re.compile(r"^[0-9]{1,2}$")
_MARK_TRANS = str.maketrans({"【": "〔", "】": "〕", "\n": " ", "\r": " "})


def clean_why(value: Any) -> Optional[str]:
    """理由必须是字符串；清洗：去首尾空白、系统标记括号换成〔〕，超过 20 字截断保留（调度裁定 2026-10-18）。非字符串返回 None。"""
    if not isinstance(value, str):
        return None
    return value.translate(_MARK_TRANS).strip()[:WHY_MAX]


def validate_entry(raw: Any) -> Optional[Dict[str, str]]:
    """单条笔记校验：三个字段都必须在且合法，否则返回 None（整条丢弃）。"""
    if not isinstance(raw, dict):
        return None
    guess, conf = raw.get("guess"), raw.get("conf")
    if not isinstance(guess, str) or guess not in GUESSES:
        return None
    if not isinstance(conf, str) or conf not in CONFS:
        return None
    why = clean_why(raw.get("why"))
    if why is None:
        return None
    return {"guess": guess, "conf": conf, "why": why}


class CognitiveNotes:
    """每个模型 AI 一份笔记 + 阵亡冻结 + 每轮快照 + 重大事件复核标记。"""

    def __init__(self, engine):
        self.engine = engine
        self._notes: Dict[int, Dict[int, Dict[str, str]]] = {}   # owner_id → target_id → entry
        self._frozen: Dict[int, Dict[int, Dict[str, Any]]] = {}  # 阵亡冻结时的完整视图
        self._death_round: Dict[int, int] = {}
        self._review: set = set()                                # 待提示"局势有变"的 owner
        self._changed = False
        self.snapshots: List[Dict[str, Any]] = []

    # ---------- 基础 ----------

    def _players(self) -> list:
        return list(getattr(getattr(self.engine, "game_state", None), "players", None) or [])

    def _player(self, pid: int):
        return next((p for p in self._players() if p.id == pid), None)

    def ensure(self, owner_id: int):
        self._notes.setdefault(owner_id, {})

    @property
    def owners(self) -> List[int]:
        return sorted(self._notes)

    def is_frozen(self, owner_id: int) -> bool:
        return owner_id in self._frozen

    # ---------- 写入 ----------

    def update(self, owner_id: int, raw: Any) -> Dict[str, List[int]]:
        """应用模型返回的 ``notes``（键 = 座位号 str）。返回 {"accepted": [...], "rejected": [...]}（target_id）。

        整个 raw 不是 dict → 全部忽略；单条非法 → 只丢该条；已揭示身份 / 自己 / 不存在的座位 → 丢弃。
        owner 已阵亡（冻结）→ 全部忽略。
        """
        result: Dict[str, List[int]] = {"accepted": [], "rejected": []}
        owner = self._player(owner_id)
        if owner is None or not getattr(owner, "is_ai", False) or not isinstance(raw, dict):
            return result
        if owner_id in self._frozen or not owner.alive:
            return result
        bucket = self._notes.setdefault(owner_id, {})
        by_id = {p.id: p for p in self._players()}
        for key, value in raw.items():
            if not isinstance(key, str) or not _SEAT_KEY_RE.match(key):
                continue
            target_id = int(key) - 1
            target = by_id.get(target_id)
            if target is None or target_id == owner_id or getattr(target, "identity_revealed", False):
                result["rejected"].append(target_id)
                continue
            entry = validate_entry(value)
            if entry is None:
                result["rejected"].append(target_id)
                continue
            if bucket.get(target_id) != entry:
                self._changed = True
            bucket[target_id] = entry
            result["accepted"].append(target_id)
        return result

    def pop_changed(self) -> bool:
        changed, self._changed = self._changed, False
        return changed

    # ---------- 读取 ----------

    def view(self, owner_id: int) -> Dict[int, Dict[str, Any]]:
        """合并后的笔记：已揭示身份的座位（引擎填，locked）优先于 AI 自己写的；阵亡者返回冻结时的版本。"""
        if owner_id in self._frozen:
            return {tid: dict(entry) for tid, entry in self._frozen[owner_id].items()}
        merged: Dict[int, Dict[str, Any]] = {
            tid: dict(entry, locked=False) for tid, entry in self._notes.get(owner_id, {}).items()
        }
        for p in self._players():
            if p.id == owner_id or not getattr(p, "identity_revealed", False):
                continue
            if p.identity in GUESSES:
                merged[p.id] = {"guess": p.identity, "conf": "高", "why": "身份已公开", "locked": True}
        return {tid: merged[tid] for tid in sorted(merged)}

    def prompt_block(self, owner_id: int) -> str:
        """【仅你可见·你的判断】区块文本；notes 是独立存储，每次出牌决策重新注入（压缩会话也不丢）。"""
        lines = []
        for tid, entry in self.view(owner_id).items():
            tag = "（已公开，引擎填写，不可改）" if entry.get("locked") else \
                f"（把握{entry['conf']}）" + (f"{entry['why']}" if entry["why"] else "")
            lines.append(f"- {tid + 1}号：{GUESS_LABEL[entry['guess']]}{tag}")
        header = "【仅你可见·你的判断】（只有你能看到；引擎只校验格式，不保证对错）"
        if not any(not entry.get("locked") for entry in self.view(owner_id).values()):
            lines.append("（你还没有对任何座位做出自己的判断）")
        return "\n" + header + "\n" + "\n".join(lines) + "\n"

    # ---------- 重大事件 ----------

    def mark_review_all(self):
        """有人阵亡 / 身份揭示后：所有仍存活的笔记所有者，下一次出牌决策提示复核。"""
        for owner_id in self._notes:
            if owner_id not in self._frozen:
                self._review.add(owner_id)

    def consume_review(self, owner_id: int) -> bool:
        if owner_id in self._review:
            self._review.discard(owner_id)
            return True
        return False

    def on_death(self, player):
        """player 阵亡：若它是笔记所有者则冻结（记下阵亡轮次）；并让其余 AI 复核。"""
        if player.id in self._notes and player.id not in self._frozen:
            self._frozen[player.id] = self.view(player.id)
            self._death_round[player.id] = int(getattr(self.engine.game_state, "round_number", 0) or 0)
            self._review.discard(player.id)
        self.mark_review_all()

    # ---------- 快照 ----------

    def snapshot(self, round_number: int):
        """每轮结束调用：为每个笔记所有者存一份合并视图。阵亡者只在阵亡那一轮存最后一份。"""
        for owner_id in self.owners:
            if owner_id in self._frozen and self._death_round.get(owner_id) != round_number:
                continue
            self.snapshots.append({
                "round": round_number,
                "player_id": owner_id,
                "notes": {str(tid): dict(entry) for tid, entry in self.view(owner_id).items()},
            })

    # ---------- 下发给作弊局前端 ----------

    def client_payload(self, reasons: Optional[Dict[int, str]] = None) -> Dict[str, Any]:
        """全部 AI 笔记 + 各自最新公开理由。只能由作弊局的引擎调用（见 MainEngine.cheat_notes_payload）。"""
        reasons = reasons or {}
        rows = []
        for owner_id in self.owners:
            owner = self._player(owner_id)
            rows.append({
                "player_id": owner_id,
                "seat": owner_id + 1,
                "name": getattr(owner, "name", ""),
                "frozen": owner_id in self._frozen,
                "reason": str(reasons.get(owner_id, ""))[:200],
                "notes": [
                    {"target_id": tid, "seat": tid + 1, **{k: entry[k] for k in ("guess", "conf", "why")},
                     "locked": bool(entry.get("locked"))}
                    for tid, entry in self.view(owner_id).items()
                ],
            })
        return {"round": int(getattr(self.engine.game_state, "round_number", 0) or 0), "players": rows}


__all__ = ["CognitiveNotes", "validate_entry", "clean_why", "GUESSES", "CONFS", "WHY_MAX"]
