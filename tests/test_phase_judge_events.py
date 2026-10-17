#!/usr/bin/env python3
"""阶段栏与判定框的引擎事件，以及乐不思蜀“跳过出牌阶段”修复。"""

import asyncio
import unittest

from game_engine import MainEngine
from game_engine.state_manager import Card, Phase


BASE_CONFIG = {
    "mode": "5人身份局",
    "player_name": "测试玩家",
    "ais": [{"name": f"AI{i}"} for i in range(1, 5)],
    "deck_id": "standard",
}


def make_engine():
    engine = MainEngine(dict(BASE_CONFIG))
    engine.response_timeout = 1
    for player in engine.game_state.players:
        player.hand.clear()
        player.equipment.clear()
        player.judge_area.clear()
    return engine


def record_events(engine):
    """收集引擎发出的全部事件：[(事件名, 数据)]。"""
    events = []
    for name in ("event_notification", "card_animation", "your_turn", "state_changed"):
        async def handler(_name=name, **data):
            events.append((_name, data))
        engine.on(name, handler)
    return events


def phase_events(events):
    return [d for n, d in events if n == "event_notification" and d.get("event_kind") == "phase"]


def judge_events(events):
    return [d for n, d in events if n == "card_animation" and d.get("event_kind") == "judge"]


def put_on_deck_top(engine, card):
    engine.game_state.deck.insert(0, card)


class LebuSkipTest(unittest.TestCase):
    def test_human_play_phase_skipped_when_lebu_hits(self):
        engine = make_engine()
        human = engine.human_player()
        engine.game_state.current_player = human
        human.judge_area.append(Card("t_lebu", "乐不思蜀", "spade", 6, "trick"))
        put_on_deck_top(engine, Card("t_judge", "杀", "spade", 7, "basic"))  # 非红桃 → 生效
        events = record_events(engine)

        asyncio.run(engine._human_turn(human))

        self.assertFalse([d for n, d in events if n == "your_turn"], "乐不思蜀生效后不应再进入出牌")
        phases = [(d["phase"], d["skipped"]) for d in phase_events(events)]
        self.assertEqual([p for p, _ in phases], ["prepare", "judge", "draw", "play", "discard", "end"])
        self.assertIn(("play", True), phases)
        self.assertNotIn(Phase.PLAY, engine.phase_controller.skip_phases, "跳过标记必须被消费，不能残留到之后的回合")

        judges = judge_events(events)
        self.assertEqual(len(judges), 1)
        self.assertEqual(judges[0]["judge_for"], "乐不思蜀")
        self.assertIs(judges[0]["effective"], True)
        self.assertEqual(judges[0]["card"]["id"], "t_judge")
        self.assertTrue(judges[0]["await_ui"])

    def test_ai_play_phase_skipped_when_lebu_hits(self):
        engine = make_engine()
        ai = engine.game_state.players[1]
        engine.game_state.current_player = ai
        ai.judge_area.append(Card("t_lebu", "乐不思蜀", "spade", 6, "trick"))
        put_on_deck_top(engine, Card("t_judge", "闪", "diamond", 2, "basic"))
        called = []

        async def fake_auto_play(player):
            called.append(player.id)
        engine._auto_play_phase = fake_auto_play
        asyncio.run(engine._run_phases(ai))
        self.assertEqual(called, [])
        self.assertNotIn(Phase.PLAY, engine.phase_controller.skip_phases)

    def test_ai_still_plays_when_lebu_misses(self):
        engine = make_engine()
        ai = engine.game_state.players[1]
        engine.game_state.current_player = ai
        ai.judge_area.append(Card("t_lebu", "乐不思蜀", "spade", 6, "trick"))
        put_on_deck_top(engine, Card("t_judge", "桃", "heart", 3, "basic"))  # 红桃 → 失效
        events = record_events(engine)
        called = []

        async def fake_auto_play(player):
            called.append(player.id)
        engine._auto_play_phase = fake_auto_play
        asyncio.run(engine._run_phases(ai))
        self.assertEqual(called, [ai.id])
        judges = judge_events(events)
        self.assertIs(judges[0]["effective"], False)
        self.assertIn(("play", False), [(d["phase"], d["skipped"]) for d in phase_events(events)])


class PhaseEventTest(unittest.TestCase):
    def test_ai_turn_emits_all_six_phases_in_order(self):
        engine = make_engine()
        ai = engine.game_state.players[2]
        engine.game_state.current_player = ai
        events = record_events(engine)

        async def fake_auto_play(player):
            return None
        engine._auto_play_phase = fake_auto_play
        asyncio.run(engine._run_phases(ai))
        phases = phase_events(events)
        self.assertEqual([d["phase"] for d in phases], ["prepare", "judge", "draw", "play", "discard", "end"])
        self.assertTrue(all(d["player_id"] == ai.id for d in phases))

    def test_bingliang_marks_draw_phase_skipped(self):
        engine = make_engine()
        ai = engine.game_state.players[3]
        engine.game_state.current_player = ai
        ai.judge_area.append(Card("t_bl", "兵粮寸断", "spade", 10, "trick"))
        put_on_deck_top(engine, Card("t_judge", "杀", "spade", 8, "basic"))  # 非梅花 → 生效
        events = record_events(engine)

        async def fake_auto_play(player):
            return None
        engine._auto_play_phase = fake_auto_play
        asyncio.run(engine._run_phases(ai))
        self.assertIn(("draw", True), [(d["phase"], d["skipped"]) for d in phase_events(events)])
        self.assertEqual(len(ai.hand), 0, "兵粮寸断生效时不应摸牌")


class SkillJudgeEventTest(unittest.TestCase):
    def test_skill_judge_is_announced_without_verdict(self):
        engine = make_engine()
        p = engine.game_state.players[1]
        put_on_deck_top(engine, Card("t_j", "闪", "heart", 9, "basic"))
        events = record_events(engine)
        card = asyncio.run(engine.skill_manager.judge(p, "刚烈"))
        self.assertEqual(card.id, "t_j")
        judges = judge_events(events)
        self.assertEqual(len(judges), 1)
        self.assertEqual(judges[0]["judge_for"], "刚烈")
        self.assertIsNone(judges[0]["effective"])


if __name__ == "__main__":
    unittest.main()
