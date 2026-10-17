#!/usr/bin/env python3
"""前端重构所需的状态字段：判定区公开、真人自己的手牌、席间聊天开关与聊天发言者。"""

import asyncio
import json
import unittest

from game_engine import MainEngine
from game_engine.state_manager import Card

import game_server


BASE_CONFIG = {
    "mode": "5人身份局",
    "player_name": "测试玩家",
    "ais": [{"name": f"AI{i}"} for i in range(1, 5)],
    "deck_id": "standard",
}


def make_engine(**extra):
    cfg = dict(BASE_CONFIG)
    cfg.update(extra)
    engine = MainEngine(cfg)
    for player in engine.game_state.players:
        player.hand.clear()
        player.equipment.clear()
        player.judge_area.clear()
    return engine


class SerializeForFrontendTest(unittest.TestCase):
    def test_judge_area_is_public_by_card_name(self):
        engine = make_engine()
        ai = engine.game_state.players[2]
        ai.judge_area.append(Card("t_lebu", "乐不思蜀", "heart", 6, "trick"))
        state = engine.serialize()
        by_id = {p["id"]: p for p in state["players"]}
        self.assertEqual(by_id[ai.id]["judge_area"], ["乐不思蜀"])
        self.assertEqual(by_id[0]["judge_area"], [])

    def test_self_hand_is_only_the_humans_hand(self):
        engine = make_engine()
        human = engine.human_player()
        self.assertIsNotNone(human)
        self.assertFalse(human.is_ai)
        human.hand.append(Card("t_sha", "杀", "spade", 7, "basic"))
        ai = engine.game_state.players[1]
        ai.hand.append(Card("t_secret", "桃", "heart", 3, "basic"))

        state = engine.serialize()
        self.assertEqual([c["id"] for c in state["self_hand"]], ["t_sha"])
        self.assertEqual(state["self_hand"][0]["index"], 0)
        # 他人手牌仍只有数量，任何位置都不出现其牌面
        dumped = json.dumps(state, ensure_ascii=False)
        self.assertNotIn("t_secret", dumped)
        self.assertEqual({p["id"]: p["hand_count"] for p in state["players"]}[ai.id], 1)


class ChatToggleTest(unittest.TestCase):
    def test_chat_enabled_by_default(self):
        self.assertTrue(make_engine().chat_enabled)

    def test_chat_disabled_from_lobby_switch(self):
        self.assertFalse(make_engine(chat={"enabled": False}).chat_enabled)

    def test_disabled_chat_suppresses_ai_chat_in_play_phase(self):
        engine = make_engine(chat={"enabled": False})
        sent = []

        async def on_chat(**data):
            sent.append(data)
        engine.on("chat", on_chat)

        ai = engine.game_state.players[1]

        async def fake_decision(player, actions):
            return {"action": {"type": "end_phase"}, "chat": "看招！"}
        engine.ai_decision.make_decision = fake_decision
        engine.get_available_actions = lambda player: [{"type": "play_card"}, {"type": "end_phase"}]
        asyncio.run(engine._auto_play_phase(ai))
        self.assertEqual(sent, [])

    def test_enabled_chat_carries_sender_id(self):
        engine = make_engine()
        sent = []

        async def on_chat(**data):
            sent.append(data)
        engine.on("chat", on_chat)
        ai = engine.game_state.players[1]

        async def fake_decision(player, actions):
            return {"action": {"type": "end_phase"}, "chat": "看招！"}
        engine.ai_decision.make_decision = fake_decision
        engine.get_available_actions = lambda player: [{"type": "play_card"}, {"type": "end_phase"}]
        asyncio.run(engine._auto_play_phase(ai))
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["from_"], ai.name)
        self.assertEqual(sent[0]["from_id"], ai.id)


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


class ServerChatEchoTest(unittest.TestCase):
    def test_player_chat_echo_names_the_human(self):
        server = game_server.GameServer()
        ws = _FakeWS()
        engine = make_engine()
        server.engines["1"] = engine
        server.ws_map[ws] = "1"
        asyncio.run(server.do_chat(ws, {"message": "  大家好  "}))
        self.assertEqual(ws.sent[-1]["type"], "chat")
        self.assertEqual(ws.sent[-1]["message"], "大家好")
        self.assertEqual(ws.sent[-1]["from"], "测试玩家")
        self.assertEqual(ws.sent[-1]["from_id"], engine.human_player().id)
        self.assertTrue(ws.sent[-1]["is_self"])

    def test_chat_without_game_still_echoes(self):
        server = game_server.GameServer()
        ws = _FakeWS()
        asyncio.run(server.do_chat(ws, {"message": "hi"}))
        self.assertEqual(ws.sent[-1]["from"], "玩家")

    def test_blank_chat_is_ignored(self):
        server = game_server.GameServer()
        ws = _FakeWS()
        asyncio.run(server.do_chat(ws, {"message": "   "}))
        self.assertEqual(ws.sent, [])


if __name__ == "__main__":
    unittest.main()
