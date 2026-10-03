#!/usr/bin/env python3
"""6A-7 四交互原语单元测试。"""

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


def make_card(tag, name="闪"):
    return Card(f"test_{tag}", name, "heart", 2, "basic")


class AskConfirmTest(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()
        self.human = self.engine.game_state.players[0]

    def test_confirm_true(self):
        async def scenario():
            task = asyncio.create_task(
                self.engine.ask_confirm(self.human, "是否发动？", default=False)
            )
            await asyncio.sleep(0)
            emitted = None
            async def capture(**data):
                nonlocal emitted
                emitted = data
            self.engine.on("require_response", capture)
            task2 = asyncio.create_task(
                self.engine.ask_confirm(self.human, "是否发动？", default=False)
            )
            await asyncio.sleep(0)
            req_id = emitted["request_id"]
            self.engine.submit_response(req_id, [0])
            result = await task2
            self.assertTrue(result)
            task.cancel()
        asyncio.run(scenario())

    def test_confirm_false(self):
        async def scenario():
            emitted = []
            async def capture(**data):
                emitted.append(data)
            self.engine.on("require_response", capture)
            task = asyncio.create_task(
                self.engine.ask_confirm(self.human, "是否发动？", default=True)
            )
            await asyncio.sleep(0)
            req_id = emitted[-1]["request_id"]
            self.engine.submit_response(req_id, [1])
            result = await task
            self.assertFalse(result)
        asyncio.run(scenario())

    def test_confirm_timeout_falls_back_to_default(self):
        async def scenario():
            self.engine.response_timeout = 0.1
            result = await self.engine.ask_confirm(self.human, "超时测试", default=True)
            self.assertTrue(result)
        asyncio.run(scenario())


class AskChoosePlayersTest(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()
        self.human = self.engine.game_state.players[0]
        self.candidates = [p for p in self.engine.game_state.players if p is not self.human]

    def test_out_of_range_rejected(self):
        request = {
            "kind": "choose_players",
            "context": {"all_players": list(self.engine.game_state.players)},
            "candidate_ids": [p.id for p in self.candidates],
            "min_n": 1, "max_n": 1, "cancelable": True,
        }
        result = self.engine._resolve_choice(self.human, request, [999])
        self.assertFalse(result["bool"])
        self.assertEqual(result["players"], [])

    def test_dead_player_rejected(self):
        target = self.candidates[0]
        target.alive = False
        request = {
            "kind": "choose_players",
            "context": {"all_players": list(self.engine.game_state.players)},
            "candidate_ids": [target.id],
            "min_n": 1, "max_n": 1, "cancelable": True,
        }
        result = self.engine._resolve_choice(self.human, request, [0])
        self.assertFalse(result["bool"])


class AskChooseCardsTest(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()
        self.human = self.engine.game_state.players[0]

    def test_card_left_zone_rejected(self):
        card = make_card("x")
        self.human.hand.append(card)
        request = {
            "kind": "choose_cards",
            "zone": "hand",
            "candidate_cards": [card],
            "card_owner": self.human,
            "min_n": 1, "max_n": 1, "cancelable": True,
        }
        self.human.hand.remove(card)
        result = self.engine._resolve_choice(self.human, request, [0])
        self.assertFalse(result["bool"])

    def test_multi_select_correct(self):
        c1 = make_card("c1", "闪")
        c2 = make_card("c2", "桃")
        self.human.hand.extend([c1, c2])
        request = {
            "kind": "choose_cards",
            "zone": "hand",
            "candidate_cards": [c1, c2],
            "card_owner": self.human,
            "min_n": 2, "max_n": 2, "cancelable": False,
        }
        result = self.engine._resolve_choice(self.human, request, [0, 1])
        self.assertTrue(result["bool"])
        self.assertIn(c1, result["cards"])
        self.assertIn(c2, result["cards"])


class AskChooseOptionTest(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()
        self.human = self.engine.game_state.players[0]

    def test_invalid_index_rejected(self):
        request = {
            "kind": "choose_option",
            "choices": [{"key": "a", "label": "选A"}, {"key": "b", "label": "选B"}],
            "min_n": 1, "max_n": 1, "cancelable": True,
        }
        result = self.engine._resolve_choice(self.human, request, [99])
        self.assertFalse(result["bool"])
        self.assertIsNone(result["choice"])


class AIRuleFallbackTest(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()
        self.ai = self.engine.game_state.players[1]
        self.ai.is_ai = True
        self.human = self.engine.game_state.players[0]
        self.candidates = [p for p in self.engine.game_state.players if p is not self.human]

    def test_ai_confirm(self):
        request = {"kind": "confirm", "default": False}
        result = self.engine.ai_decision.simple_choice_decision(self.ai, request)
        self.assertIsInstance(result, list)
        self.assertIn(result[0], (0, 1))

    def test_ai_choose_players(self):
        request = {
            "kind": "choose_players",
            "context": {"all_players": list(self.engine.game_state.players)},
            "candidate_ids": [p.id for p in self.candidates],
            "min_n": 1, "max_n": 1,
        }
        result = self.engine.ai_decision.simple_choice_decision(self.ai, request)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)

    def test_ai_choose_cards(self):
        c1 = make_card("ai1", "闪")
        c2 = make_card("ai2", "桃")
        self.ai.hand.extend([c1, c2])
        request = {
            "kind": "choose_cards",
            "candidate_cards": [c1, c2],
            "card_owner": self.ai,
            "zone": "hand",
            "min_n": 1, "max_n": 1,
        }
        result = self.engine.ai_decision.simple_choice_decision(self.ai, request)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertIn(result[0], (0, 1))

    def test_ai_choose_option(self):
        request = {
            "kind": "choose_option",
            "choices": [{"key": "fire", "label": "火"}, {"key": "thunder", "label": "雷"}],
        }
        result = self.engine.ai_decision.simple_choice_decision(self.ai, request)
        self.assertIsInstance(result, list)
        self.assertEqual(result, [0])


if __name__ == "__main__":
    unittest.main()
