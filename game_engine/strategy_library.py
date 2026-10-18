"""按公开局势筛选、抽样的可编辑经验库；建议不是规则或身份结论。"""
import json
import logging
from pathlib import Path

from .seats import seat_of

ROOT = Path(__file__).with_name("strategy_examples")
logger = logging.getLogger(__name__)
ROLES = {"lord", "loyalist", "rebel", "spy"}


def load_examples(role):
    if role not in ROLES | {"common"}:
        return []
    try:
        raw = json.loads((ROOT / f"{role}.json").read_text(encoding="utf-8"))
        return [row for row in raw["examples"] if isinstance(row, dict)
                and isinstance(row.get("when"), list) and all(isinstance(k, str) for k in row["when"])
                and all(isinstance(row.get(k), str) for k in ("id", "condition", "option", "say"))]
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning("策略示例库不可用：%s；跳过示例，不影响合法决策", role)
        return []


def select_examples(engine, player, rng):
    if player.identity not in ROLES:
        return []
    state = engine.game_state
    flags = set()
    if state.round_number <= 2:
        flags.add("opening")
    if seat_of(state, player.id) == 2:
        flags.add("seat2")
    if sum(p.alive for p in state.players) == 2:
        flags.add("duel")
    if any(p.identity_revealed and p.identity == "lord" and p.hp <= 2 and p.alive for p in state.players):
        flags.add("lord_low")
    ledger = getattr(engine, "ledger", None)
    if ledger and any(e.target_id == player.id and e.kind == "hostile" and e.round >= state.round_number - 1
                      for e in ledger.entries):
        flags.add("threatened")
    eligible = [row for row in load_examples(player.identity) if set(row["when"]) <= flags]
    count = min(len(eligible), rng.randint(3, 4))
    return rng.sample(eligible, count) if count else []


def examples_prompt(examples):
    common = load_examples("common")
    # 小段拆谎提醒不使用对手真实身份；按本批示例 ID 确定一条，避免额外随机调用。
    deception = common[sum(len(row["id"]) for row in examples) % len(common)] if common else None
    lines = ["【老玩家经验示例】你已经先写了自己的判断。下面是参考，不是规则或限制；"
             "你完全可以想出别的打法，局势不符时不要硬套。"]
    for row in examples:
        text = f"- 条件：{row['condition']} → 可选做法：{row['option']}"
        if row["say"]:
            text += f"；台词示例（可说也可不说）：「{row['say']}」"
        lines.append(text)
    if deception:
        lines.append("【别人通常怎么骗人】" + deception["condition"] + "：" + deception["option"])
    lines.append("请比较自己原先的打算与这些建议：有没有更好的做法？保留或改写都可以，说明理由后再选操作。")
    return "\n".join(lines)
