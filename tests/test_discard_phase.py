#!/usr/bin/env python3
"""6A-7 弃牌阶段手选回归测试。"""

import asyncio
import unittest

from game_engine import MainEngine
from game_engine.state_manager import Card


BASE_CONFIG = {
    "mode": "5人身份局",
    "player_name": "测试玩家",
    "ais": [{"name": f"AI{i}"} for i in range(1, 5)],
    "deck_id": "standard",
}


def make_engine():
    engine = MainEngine(dict(BASE_CONFIG))
    engine.response_timeout = 3
    return engine


def make_card(tag, name="闪", rank=5):
    return Card(f"test_{tag}", name, "heart", rank, "basic")


class HumanDiscardTest(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()
        self.human = self.engine.game_state.players[0]
        self.human.hp = 2
        self.human.max_hp = 4

    def _set_hand(self, cards):
        self.human.hand.clear()
        self.human.hand.extend(cards)

    def test_human_manual_select(self):
        """真人手选弃 2 张，弃的正是选中的那两张。"""
        c1 = make_card("h1", "桃", 3)
        c2 = make_card("h2", "闪", 5)
        c3 = make_card("h3", "杀", 7)
        c4 = make_card("h4", "无懈可击", 2)
        self._set_hand([c1, c2, c3, c4])

        emitted = []
        async def capture(**data):
            emitted.append(data)
        self.engine.on("require_response", capture)

        self.engine.game_state.current_player = self.human

        async def scenario():
            from game_engine.phase_controller import PhaseController
            pc = self.engine.phase_controller
            task = asyncio.create_task(pc.discard_phase())
            await asyncio.sleep(0)
            self.assertTrue(len(emitted) > 0, "应当发出 require_response 事件")
            req_id = emitted[-1]["request_id"]
            self.engine.submit_response(req_id, [1, 2])
            await task
            self.assertNotIn(c2, self.human.hand)
            self.assertNotIn(c3, self.human.hand)
            self.assertEqual(len(self.human.hand), 2)

        asyncio.run(scenario())

    def test_human_timeout_falls_back_to_strategy(self):
        """真人超时，引擎用 KEEP_SCORE 策略自动弃牌，弃掉低分牌。"""
        from game_engine.phase_controller import KEEP_SCORE
        self.engine.response_timeout = 0.05
        c_low = make_card("tl", "杀", 5)
        c_low2 = make_card("tl2", "杀", 6)
        c_high = make_card("th", "桃", 3)
        c_high2 = make_card("th2", "闪", 4)
        self._set_hand([c_low, c_low2, c_high, c_high2])
        self.engine.game_state.current_player = self.human

        async def scenario():
            await self.engine.phase_controller.discard_phase()
            self.assertEqual(len(self.human.hand), 2)
            for card in self.human.hand:
                self.assertGreaterEqual(
                    KEEP_SCORE.get(card.name, 20),
                    KEEP_SCORE.get(c_low.name, 20),
                )

        asyncio.run(scenario())

    def test_ai_discard_unchanged(self):
        """AI 弃牌走旧路径，行为与改造前逐张一致。"""
        ai = self.engine.game_state.players[1]
        ai.hp = 2
        ai.max_hp = 4
        c1 = make_card("a1", "杀", 5)
        c2 = make_card("a2", "闪", 6)
        c3 = make_card("a3", "桃", 3)
        c4 = make_card("a4", "无懈可击", 2)
        ai.hand.clear()
        ai.hand.extend([c1, c2, c3, c4])
        self.engine.game_state.current_player = ai

        from game_engine.phase_controller import KEEP_SCORE

        expected_kept = sorted(
            [c1, c2, c3, c4],
            key=lambda c: (KEEP_SCORE.get(c.name, 20), c.rank),
        )[2:]

        async def scenario():
            await self.engine.phase_controller.discard_phase()
            self.assertEqual(sorted([c.id for c in ai.hand]),
                             sorted([c.id for c in expected_kept]))

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
