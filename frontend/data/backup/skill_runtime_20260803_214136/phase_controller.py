#!/usr/bin/env python3
"""六阶段控制器：负责非交互阶段的确定性结算。"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from state_manager import GameState, Phase, Player
    from event_bus import EventBus


class PhaseController:
    def __init__(self, game_state: "GameState", event_bus: "EventBus"):
        self.game_state = game_state
        self.event_bus = event_bus
        self.skip_phases = set()

    def execute_phase(self, phase: "Phase"):
        from event_bus import EventType

        if phase in self.skip_phases:
            self.skip_phases.remove(phase)
            print(f"跳过阶段: {phase.value}")
            return

        player = self.game_state.current_player
        self.event_bus.trigger(EventType.PHASE_BEGIN, player=player, data={"phase": phase})

        handler = {
            "prepare": self.prepare_phase,
            "judge": self.judge_phase,
            "draw": self.draw_phase,
            "play": self.play_phase,
            "discard": self.discard_phase,
            "end": self.end_phase,
        }.get(phase.value)
        if handler:
            handler()

        self.event_bus.trigger(EventType.PHASE_END, player=player, data={"phase": phase})

    def prepare_phase(self):
        from state_manager import Phase, PlayerStatus

        player = self.game_state.current_player
        print(f"[准备阶段] {player.name}")
        if player.status == PlayerStatus.TURNED:
            player.status = PlayerStatus.NORMAL
            self.skip_phases.update({Phase.JUDGE, Phase.DRAW, Phase.PLAY, Phase.DISCARD})
            print(f"  {player.name} 翻回正面并跳过本回合后续主要阶段")

    def judge_phase(self):
        player = self.game_state.current_player
        print(f"[判定阶段] {player.name}")
        for delayed_card in list(player.judge_area):
            self.execute_judge(player, delayed_card)

    def execute_judge(self, player: "Player", delayed_card):
        from event_bus import EventType

        if not self.game_state.deck:
            self.game_state.draw_card(player, 0)
        if not self.game_state.deck:
            return

        result = self.game_state.deck.pop(0)
        event = self.event_bus.trigger(
            EventType.JUDGE,
            player=player,
            card=result,
            data={"delayed_card": delayed_card},
        )
        result = event.get("card", result)
        print(f"  判定【{delayed_card.name}】: {result.suit}{result.rank}")
        # 延时锦囊具体效果在卡牌补全阶段实现；P0保证判定牌流转正确。
        self.game_state.discard_pile.append(result)
        self.event_bus.trigger(EventType.JUDGE_END, player=player, card=result)

    def draw_phase(self):
        from event_bus import EventType

        player = self.game_state.current_player
        print(f"[摸牌阶段] {player.name}")
        cards = self.game_state.draw_card(player, 2)
        print(f"  摸了 {len(cards)} 张牌")
        self.event_bus.trigger(
            EventType.CARD_GAIN,
            player=player,
            data={"cards": cards, "reason": "draw"},
        )

    def play_phase(self):
        player = self.game_state.current_player
        player.sha_count = 0
        print(f"[出牌阶段] {player.name}，手牌数: {player.get_hand_count()}")

    def discard_phase(self):
        from event_bus import EventType

        player = self.game_state.current_player
        print(f"[弃牌阶段] {player.name}")
        max_hand = max(0, player.hp)
        discard_count = max(0, player.get_hand_count() - max_hand)
        if not discard_count:
            return

        # P0托管策略：优先保留桃、闪，再保留其他牌。后续接入玩家选牌交互。
        keep_score = {"桃": 100, "闪": 80, "杀": 50, "无懈可击": 70}
        ordered = sorted(
            list(player.hand),
            key=lambda c: (keep_score.get(c.name, 20), c.rank),
        )
        discarded = ordered[:discard_count]
        for card in discarded:
            self.game_state.discard_card(player, card)
        print(f"  自动弃置 {len(discarded)} 张牌")
        self.event_bus.trigger(
            EventType.CARD_DISCARD,
            player=player,
            data={"cards": discarded, "reason": "hand_limit"},
        )

    def end_phase(self):
        print(f"[结束阶段] {self.game_state.current_player.name}")


if __name__ == "__main__":
    print("阶段控制器模块加载成功")
