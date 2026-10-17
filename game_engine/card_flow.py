#!/usr/bin/env python3
"""牌堆亮牌与展示区出口（Stage T · T0-7）。

判定牌、五谷丰登亮出的牌、裸衣亮出的牌，过去都是 ``deck.pop(0)`` 之后在「不属于任何牌区」的
空档里处理，牌移动事件、行为账本、局后日志都看不到它们，实体牌在这段时间里也没有位置。

现在它们先从牌堆顶移到某个角色的展示区（``shown``），结算时再从展示区移到弃牌堆或某人手牌；
每一步都是公开的 ``engine.move_card``，实体牌任何时刻都恰好在一个牌区里。

没有真引擎（规则单测桩、MagicMock 引擎）时退回原来的直接改牌区，行为不变。
牌堆为空时先洗弃牌堆再亮牌，与摸牌共用 ``GameState.refill_deck_if_empty``。
"""

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


def engine_moves(engine, state) -> bool:
    """engine 是否是管着这份牌局状态的真引擎（只有它能提交牌移动事件）。"""
    return (
        engine is not None
        and getattr(engine, "game_state", None) is state
        and callable(getattr(engine, "move_card", None))
        and isinstance(getattr(state, "deck", None), list)
    )


def shown_holder(state, card):
    """这张牌此刻在谁的展示区里；不在任何展示区返回 None（旧路径 / 单测桩）。"""
    return next(
        (p for p in state.players if any(c is card for c in p.shown)),
        None,
    )


async def reveal_top(engine, state, holder, count: int, *, reason: str,
                     refill: bool = True) -> List:
    """从牌堆顶亮出 count 张到 holder 的展示区，返回实际亮出的牌（可能不足 count）。

    refill=True 时牌堆空了先洗弃牌堆（判定、摸牌的规则）；五谷丰登、裸衣按原规则不洗牌，传 False。
    对局已收摊或牌移动被拒时停止，不再继续亮牌。
    """
    revealed: List = []
    for _ in range(max(0, int(count))):
        has_card = state.refill_deck_if_empty() if refill else bool(state.deck)
        if not has_card:
            break
        card = state.deck[0]
        if engine_moves(engine, state):
            if engine.game_aborted:
                break
            moved = await engine.move_card(
                card, "deck", "shown", to_owner=holder, reason=reason,
                actor_id=holder.id, visibility="public",
            )
            if moved is None:
                # 牌移动被引擎拒绝（数据异常）：退回直接取牌，保证对局还能往下走。
                logger.warning("  ⚠️ 亮牌移动被拒绝（%s），改为直接取牌", reason)
                state.deck.pop(0)
        else:
            state.deck.pop(0)
        revealed.append(card)
    return revealed


async def release_shown(engine, state, card, to_zone: str, *, to_owner=None,
                        reason: str, actor_id: Optional[int] = None) -> None:
    """让一张牌离开展示区：to_zone 为 ``discard`` 或 ``hand``（此时必须给 to_owner）。

    牌不在任何展示区（旧路径、单测桩里直接构造的牌）时，按原先的直接改牌区处理。
    """
    holder = shown_holder(state, card)
    if holder is not None and engine_moves(engine, state):
        moved = await engine.move_card(
            card, "shown", to_zone, from_owner=holder, to_owner=to_owner,
            reason=reason, actor_id=actor_id, visibility="public",
        )
        if moved is not None:
            return
        # 被拒绝（对局已收摊等）：落到下面的直接处理，避免牌永远卡在展示区。
    if holder is not None:
        holder.shown[:] = [c for c in holder.shown if c is not card]
    if to_zone == "discard":
        state.discard_pile.append(card)
    elif to_zone == "hand" and to_owner is not None:
        to_owner.hand.append(card)


async def take_judge_replacement(engine, state, owner, judged, replacement,
                                 from_zone: str, *, reason: str) -> Optional[str]:
    """鬼才 / 鬼道：把 owner 打出的替换牌从手牌或装备区放到被判定者的展示区，成为新的判定牌。

    返回 ``"engine"``（已走 move_card，失去牌的技能钩子已由移动事件触发）、
    ``"legacy"``（直接改了牌区，调用方需要自己触发失去牌钩子）、``None``（没能取出，判定不变）。
    """
    if from_zone == "hand":
        if not any(c is replacement for c in owner.hand):
            return None
    elif from_zone == "equipment":
        if not any(c is replacement for c in owner.equipment.values()):
            return None
    else:
        return None
    if engine_moves(engine, state):
        moved = await engine.move_card(
            replacement, from_zone, "shown", from_owner=owner, to_owner=judged,
            reason=reason, actor_id=owner.id, visibility="public",
        )
        if moved is not None:
            return "engine"
        if getattr(engine, "game_aborted", False):
            return None
    if from_zone == "hand":
        owner.hand[:] = [c for c in owner.hand if c is not replacement]
    else:
        slot = next((k for k, v in owner.equipment.items() if v is replacement), None)
        if slot is None:
            return None
        owner.equipment.pop(slot)
    return "legacy"
