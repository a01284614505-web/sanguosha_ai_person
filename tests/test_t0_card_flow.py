#!/usr/bin/env python3
"""Stage T · T0-7：判定 / 五谷丰登 / 裸衣 / 鬼才 / 鬼道的牌都走 move_card。"""

import asyncio
import unittest

from game_engine import MainEngine
from game_engine.state_manager import Card

CONFIG = {
    "mode": "5人身份局", "player_name": "测试玩家",
    "ais": [{"name": f"AI{i}"} for i in range(1, 5)], "deck_id": "standard",
}


def make_engine():
    engine = MainEngine(dict(CONFIG))
    engine.response_timeout = 1
    for p in engine.game_state.players:
        p.hand.clear()
        p.equipment.clear()
        p.judge_area.clear()
        p.shown.clear()
    return engine


def record_moves(engine):
    moves = []

    async def handler(move=None, **_):
        moves.append(move)
    engine.on("card_move", handler)
    return moves


def zone_count(state, card):
    n = sum(1 for c in state.deck if c is card) + sum(1 for c in state.discard_pile if c is card)
    for p in state.players:
        n += sum(1 for c in p.hand if c is card) + sum(1 for c in p.shown if c is card)
        n += sum(1 for c in p.equipment.values() if c is card)
        n += sum(1 for c in p.judge_area if c is card)
    return n


class JudgeFlowTest(unittest.TestCase):
    def test_judge_card_moves_deck_shown_discard_publicly(self):
        engine = make_engine()
        player = engine.game_state.players[1]
        top = Card("t_top", "杀", "spade", 7, "basic")
        engine.game_state.deck.insert(0, top)
        moves = record_moves(engine)

        judged = asyncio.run(engine.skill_manager.judge(player, "测试"))

        self.assertIs(judged, top)
        self.assertEqual(zone_count(engine.game_state, top), 1)
        self.assertIn(top, engine.game_state.discard_pile)
        pairs = [(m["from_zone"], m["to_zone"]) for m in moves if m["card_id"] == "t_top"]
        self.assertEqual(pairs, [("deck", "shown"), ("shown", "discard")])
        self.assertTrue(all(m["visibility"] == "public" for m in moves if m["card_id"] == "t_top"))

    def test_judge_reshuffles_before_reveal_when_deck_empty(self):
        engine = make_engine()
        state = engine.game_state
        player = state.players[0]
        state.deck.clear()
        card = Card("t_disc", "闪", "heart", 2, "basic")
        state.discard_pile[:] = [card]

        judged = asyncio.run(engine.skill_manager.judge(player, "测试"))

        self.assertIs(judged, card)
        self.assertEqual(zone_count(state, card), 1)


class WuguFlowTest(unittest.TestCase):
    def test_wugu_cards_are_shown_then_taken_or_discarded(self):
        engine = make_engine()
        state = engine.game_state
        user = state.players[1]
        pool = [Card(f"w{i}", "杀", "spade", i + 2, "basic") for i in range(5)]
        state.deck[:0] = pool
        moves = record_moves(engine)
        card = Card("t_wugu", "五谷丰登", "heart", 3, "trick")

        asyncio.run(engine.card_system.use_wugu(user, card))

        for c in pool:
            self.assertEqual(zone_count(state, c), 1, c.id)
        got = sum(len(p.hand) for p in state.players)
        self.assertEqual(got, 5)
        self.assertTrue(all(not p.shown for p in state.players))
        reveal = [m for m in moves if m["to_zone"] == "shown"]
        self.assertEqual(len(reveal), 5)
        self.assertTrue(all(m["visibility"] == "public" for m in reveal))

    def test_wugu_leftover_discarded_when_a_player_is_dead(self):
        engine = make_engine()
        state = engine.game_state
        user = state.players[1]
        # 一个角色死亡 → 只亮 4 张
        dead = state.players[3]
        dead.alive = False
        pool = [Card(f"x{i}", "闪", "heart", i + 2, "basic") for i in range(6)]
        state.deck[:0] = pool
        card = Card("t_wugu2", "五谷丰登", "heart", 3, "trick")

        asyncio.run(engine.card_system.use_wugu(user, card))

        for c in pool:
            self.assertEqual(zone_count(state, c), 1, c.id)
        self.assertEqual(sum(1 for c in pool if c in state.deck), 2)
        self.assertEqual(sum(len(p.hand) for p in state.players), 4)


class ReplacementFlowTest(unittest.TestCase):
    def test_take_replacement_from_hand_then_original_discarded(self):
        from game_engine import card_flow
        engine = make_engine()
        state = engine.game_state
        owner, judged = state.players[0], state.players[1]
        repl = Card("t_repl", "杀", "club", 5, "basic")
        orig = Card("t_orig", "闪", "heart", 2, "basic")
        owner.hand.append(repl)
        state.deck.insert(0, orig)

        async def run():
            revealed = await card_flow.reveal_top(engine, state, judged, 1, reason="判定")
            taken = await card_flow.take_judge_replacement(
                engine, state, owner, judged, repl, "hand", reason="鬼才")
            await card_flow.release_shown(engine, state, orig, "discard", reason="判定替换")
            await card_flow.release_shown(engine, state, repl, "discard", reason="判定结算")
            return revealed, taken

        revealed, taken = asyncio.run(run())
        self.assertEqual(taken, "engine")
        self.assertEqual(zone_count(state, repl), 1)
        self.assertEqual(zone_count(state, orig), 1)
        self.assertNotIn(repl, owner.hand)
        self.assertIn(orig, state.discard_pile)
        self.assertIn(repl, state.discard_pile)


if __name__ == "__main__":
    unittest.main()
