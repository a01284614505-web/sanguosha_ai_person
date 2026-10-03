#!/usr/bin/env python3
"""六阶段控制器：负责非交互阶段的确定性结算。"""

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
            await self.execute_judge(player, delayed_card)

    async def execute_judge(self, player: "Player", delayed_card):

        if not self.game_state.deck:
            self.game_state.draw_card(player, 0)
        if not self.game_state.deck:
            return

        result = self.game_state.deck.pop(0)
        if self.skill_manager:
            result = await self.skill_manager.before_judge(player, result, {"delayed_card": delayed_card})
        logger.info(f"  判定【{delayed_card.name}】: {result.suit}{result.rank}")
        claimed = bool(self.skill_manager and await self.skill_manager.after_judge(player, result, {"delayed_card": delayed_card}))
        if not claimed:
            self.game_state.discard_pile.append(result)
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
                        player, player, 3, card=delayed_card, context={"reason": "闪电"}
                    )
                else:
                    player.hp -= 3
                logger.info(f"  {player.name}的【闪电】命中，受到3点雷电伤害，体力：{player.hp}/{player.max_hp}")
            else:
                players = self.game_state.players
                if player in players:
                    start = players.index(player)
                    next_player = next(
                        (players[(start + offset) % len(players)]
                         for offset in range(1, len(players) + 1)
                         if players[(start + offset) % len(players)].alive),
                        None,
                    )
                    if next_player and not any(c.name == "闪电" for c in next_player.judge_area):
                        next_player.judge_area.append(delayed_card)
                        logger.info(f"  【闪电】判定未命中，传给{next_player.name}")
                        if delayed_card in player.judge_area:
                            player.judge_area.remove(delayed_card)
                        return

        if delayed_card in player.judge_area:
            player.judge_area.remove(delayed_card)
            self.game_state.discard_pile.append(delayed_card)

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
                chosen = await self.engine.ask_choose_cards(
                    player,
                    f"弃牌阶段：请弃置 {discard_count} 张手牌",
                    list(player.hand),
                    min_n=discard_count,
                    max_n=discard_count,
                    zone="hand",
                    cancelable=False,
                )
                if len(chosen) == discard_count:
                    discarded = chosen
                else:
                    discarded = ordered[:discard_count]
            except Exception:
                discarded = ordered[:discard_count]
        else:
            discarded = ordered[:discard_count]
        for card in discarded:
            self.game_state.discard_card(player, card)
            if self.skill_manager:
                await self.skill_manager.on_cards_lost(player, [card], "hand_limit")
                await self.skill_manager.on_card_discarded(player, card, "hand_limit")
        logger.info(f"  自动弃置 {len(discarded)} 张牌")

    async def end_phase(self):
        logger.info(f"[结束阶段] {self.game_state.current_player.name}")


if __name__ == "__main__":
    logger.info("阶段控制器模块加载成功")
