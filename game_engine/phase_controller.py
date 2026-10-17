#!/usr/bin/env python3
"""六阶段控制器：负责非交互阶段的确定性结算。"""

import inspect
import logging
from typing import TYPE_CHECKING

from .card_table import CARD_TABLE
from .state_manager import Phase, PlayerStatus

if TYPE_CHECKING:
    from .state_manager import GameState, Player


logger = logging.getLogger(__name__)

# 弃牌托管保留分：从单一牌表 CARD_TABLE.discard_keep_score 派生，
# 保持原行为不变（桃100/闪80/杀50/无懈可击70，其余20）。
KEEP_SCORE = {name: spec.discard_keep_score for name, spec in CARD_TABLE.items()}


class PhaseController:
    def __init__(self, game_state: "GameState", skill_manager=None, engine=None):
        self.game_state = game_state
        self.skill_manager = skill_manager
        self.engine = engine
        self.skip_phases = set()

    async def execute_phase(self, phase: "Phase"):
        if getattr(self.engine, "game_aborted", False):
            return

        if phase in self.skip_phases:
            self.skip_phases.remove(phase)
            logger.info(f"跳过阶段: {phase.value}")
            return

        player = self.game_state.current_player

        handler = {
            "prepare": self.prepare_phase,
            "judge": self.judge_phase,
            "draw": self.draw_phase,
            "play": self.play_phase,
            "discard": self.discard_phase,
            "end": self.end_phase,
        }.get(phase.value)
        if handler:
            await handler()


    async def prepare_phase(self):

        player = self.game_state.current_player
        logger.info(f"[准备阶段] {player.name}")
        if player.status == PlayerStatus.TURNED:
            player.status = PlayerStatus.NORMAL
            self.skip_phases.update({Phase.JUDGE, Phase.DRAW, Phase.PLAY, Phase.DISCARD})
            logger.info(f"  {player.name} 翻回正面并跳过本回合后续主要阶段")

    async def judge_phase(self):
        player = self.game_state.current_player
        logger.info(f"[判定阶段] {player.name}")
        for delayed_card in list(player.judge_area):
            if not player.alive or (getattr(self.engine, "game_state", None) is self.game_state
                                    and getattr(self.engine, "game_aborted", False)):
                break
            await self.execute_judge(player, delayed_card)

    async def _move_delayed_card(self, owner, card, target=None, reason="judge_resolved"):
        """判定区实体移动；没有正式引擎时供规则单测使用。"""
        to_zone = "judge" if target is not None else "discard"
        if self.engine is not None and getattr(self.engine, "game_state", None) is self.game_state:
            return await self.engine.move_card(
                card, "judge", to_zone, from_owner=owner, to_owner=target,
                reason=reason, actor_id=owner.id,
            ) is not None
        if card not in owner.judge_area:
            return False
        owner.judge_area.remove(card)
        (target.judge_area if target is not None else self.game_state.discard_pile).append(card)
        return True

    def _next_lightning_target(self, owner):
        """闪电跳过死亡角色和已有闪电的判定区。"""
        players = self.game_state.players
        if owner not in players:
            return None
        start = players.index(owner)
        return next((candidate for offset in range(1, len(players))
                     if (candidate := players[(start + offset) % len(players)]).alive
                     and all(card.name != "闪电" for card in candidate.judge_area)), None)

    async def execute_judge(self, player: "Player", delayed_card):
        if delayed_card not in player.judge_area or not player.alive:
            return

        # 延时锦囊在此时询问无懈，成功抵消后不翻判定牌；闪电继续传递。
        card_system = getattr(self.engine, "card_system", None)
        if card_system is not None and await card_system.ask_wuxie(delayed_card, player, [player]):
            if delayed_card.name == "闪电":
                next_player = self._next_lightning_target(player)
                if next_player is not None:
                    await self._move_delayed_card(player, delayed_card, next_player, "lightning_countered")
                    return
            await self._move_delayed_card(player, delayed_card, reason="delayed_countered")
            return
        if (getattr(self.engine, "game_state", None) is self.game_state
                and getattr(self.engine, "game_aborted", False)):
            return

        if not self.game_state.refill_deck_if_empty():
            return

        result = self.game_state.deck.pop(0)
        if self.skill_manager:
            result = await self.skill_manager.before_judge(player, result, {"delayed_card": delayed_card})
        logger.info(f"  判定【{delayed_card.name}】: {result.suit}{result.rank}")
        claimed = bool(self.skill_manager and await self.skill_manager.after_judge(player, result, {"delayed_card": delayed_card}))
        if not claimed:
            self.game_state.discard_pile.append(result)

        # 判定结果先通知前端（判定框），再落地效果。
        effective, text = None, ""
        if delayed_card.name == "兵粮寸断":
            effective = result.suit != "club"
            text = "跳过摸牌阶段" if effective else "梅花，不受影响"
        elif delayed_card.name == "乐不思蜀":
            effective = result.suit != "heart"
            text = "跳过出牌阶段" if effective else "红桃，不受影响"
        elif delayed_card.name == "闪电":
            effective = result.suit == "spade" and 2 <= result.rank <= 9
            text = "受到3点雷电伤害" if effective else "移给下家"
        announce = getattr(self.engine, "announce_judge", None) if self.engine is not None else None
        if announce is not None:
            pending = announce(player, result, delayed_card.name, effective, text)
            if inspect.isawaitable(pending):  # 测试里的 MagicMock 引擎返回非协程，直接忽略
                await pending

        if delayed_card.name == "兵粮寸断" and result.suit != "club":
            self.skip_phases.add(Phase.DRAW)
            logger.info(f"  {player.name}的【兵粮寸断】生效：跳过摸牌阶段")
        if delayed_card.name == "乐不思蜀" and result.suit != "heart":
            self.skip_phases.add(Phase.PLAY)
            logger.info(f"  {player.name}的【乐不思蜀】生效：跳过出牌阶段")

        if delayed_card.name == "闪电":
            hit = result.suit == "spade" and 2 <= result.rank <= 9
            if hit:
                if self.engine and getattr(self.engine, "card_system", None):
                    await self.engine.card_system.damage(
                        None, player, 3, card=delayed_card,
                        context={"reason": "闪电", "nature": "thunder"},
                    )
                else:
                    player.hp -= 3
                logger.info(f"  {player.name}的【闪电】命中，受到3点雷电伤害，体力：{player.hp}/{player.max_hp}")
            else:
                next_player = self._next_lightning_target(player)
                if next_player and await self._move_delayed_card(
                    player, delayed_card, next_player, "lightning_passed",
                ):
                    logger.info(f"  【闪电】判定未命中，传给{next_player.name}")
                    return

        if delayed_card in player.judge_area:
            await self._move_delayed_card(player, delayed_card)

    async def draw_phase(self):

        player = self.game_state.current_player
        logger.info(f"[摸牌阶段] {player.name}")
        cards = self.game_state.draw_card(player, 2)
        if self.skill_manager:
            await self.skill_manager.on_card_gained(player, cards, "draw")
        logger.info(f"  摸了 {len(cards)} 张牌")

    async def play_phase(self):
        player = self.game_state.current_player
        player.sha_count = 0
        logger.info(f"[出牌阶段] {player.name}，手牌数: {player.get_hand_count()}")

    async def discard_phase(self):

        player = self.game_state.current_player
        logger.info(f"[弃牌阶段] {player.name}")
        max_hand = max(0, player.hp)
        if self.skill_manager:
            max_hand = self.skill_manager.hand_limit(player, max_hand)
        discard_count = max(0, player.get_hand_count() - max_hand)
        if not discard_count:
            return
        if getattr(self.engine, "game_aborted", False):
            # 对局已收摊（离席/主动结束）：不再新落地弃牌与动画事件。
            return

        ordered = sorted(
            list(player.hand),
            key=lambda c: (KEEP_SCORE.get(c.name, 20), c.rank),
        )
        trustee = getattr(self.engine, "_trustee_active", False) if self.engine else False
        if self.engine and not player.is_ai and not trustee:
            try:
                choice = await self.engine.ask_choose_cards_result(
                    player,
                    f"弃牌阶段：请弃置 {discard_count} 张手牌",
                    list(player.hand),
                    min_n=discard_count,
                    max_n=discard_count,
                    zone="hand",
                    cancelable=False,
                )
                chosen = choice.get("cards", [])
                if choice.get("status") == "game_ended":
                    return
                if choice.get("status") in ("resolved", "timeout") and len(chosen) == discard_count:
                    discarded = chosen
                else:
                    discarded = ordered[:discard_count]
            except Exception:
                discarded = ordered[:discard_count]
        else:
            discarded = ordered[:discard_count]
        # 等待真人选牌期间可能主动结束或被离席看门狗结束。
        if getattr(self.engine, "game_aborted", False):
            return
        if self.skill_manager and self.engine is not None:
            self.skill_manager.begin_loss_batch(player, "hand_limit")
        try:
            for card in discarded:
                if getattr(self.engine, "game_aborted", False):
                    return
                if self.engine is not None:
                    move = await self.engine.move_card(
                        card, "hand", "discard", from_owner=player,
                        reason="hand_limit", actor_id=player.id,
                    )
                    if move is None:
                        continue
                else:
                    self.game_state.discard_card(player, card)
                if self.skill_manager:
                    await self.skill_manager.on_card_discarded(player, card, "hand_limit")
        finally:
            if self.skill_manager and self.engine is not None:
                await self.skill_manager.finish_loss_batch(player)
        logger.info(f"  自动弃置 {len(discarded)} 张牌")

    async def end_phase(self):
        # 酒的“下一张杀”仅限本回合，跳过出牌阶段也不能留到下回合。
        self.game_state.current_player.jiu_buff = False
        logger.info(f"[结束阶段] {self.game_state.current_player.name}")


if __name__ == "__main__":
    logger.info("阶段控制器模块加载成功")
