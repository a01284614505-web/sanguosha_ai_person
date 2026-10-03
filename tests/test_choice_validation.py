#!/usr/bin/env python3
"""交互原语引擎复核加固：重复/越界/跨牌区/临时池/不可取消兜底。"""

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


def make_card(tag, name, suit="heart", rank=5):
    return Card(f"test_{tag}", name, suit, rank, "basic")


class ChoiceCardValidationTest(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()
        self.human = self.engine.game_state.players[0]
        self.target = self.engine.game_state.players[1]

    def _cards_request(self, cards, *, min_n=1, max_n=1, cancelable=False,
                       places=None, owner=None, zone="hand"):
        return {
            "kind": "choose_cards",
            "candidate_cards": list(cards),
            "candidate_places": places,
            "card_owner": owner or self.human,
            "zone": zone,
            "min_n": min_n,
            "max_n": max_n,
            "cancelable": cancelable,
        }

    def test_duplicate_indices_deduped(self):
        c1 = make_card("d1", "杀")
        c2 = make_card("d2", "闪")
        c3 = make_card("d3", "桃")
        self.human.hand.extend([c1, c2, c3])
        request = self._cards_request([c1, c2, c3], min_n=2, max_n=2)
        result = self.engine._resolve_choice(self.human, request, [0, 0, 1])
        self.assertTrue(result["bool"])
        self.assertEqual(result["cards"], [c1, c2])

    def test_too_many_indices_falls_back(self):
        c1 = make_card("m1", "桃")
        c2 = make_card("m2", "杀")
        c3 = make_card("m3", "闪")
        self.human.hand.extend([c1, c2, c3])
        request = self._cards_request([c1, c2, c3], min_n=2, max_n=2)
        result = self.engine._resolve_choice(self.human, request, [0, 1, 2])
        self.assertTrue(result["bool"])
        self.assertEqual(len(result["cards"]), 2)
        self.assertEqual({card.name for card in result["cards"]}, {"杀", "闪"})

    def test_cross_zone_places_validated(self):
        hand_card = make_card("z1", "杀")
        weapon = make_card("z2", "青釭剑")
        self.target.hand.append(hand_card)
        self.target.equipment["weapon"] = weapon
        places = [(self.target, "hand"), (self.target, "equipment")]
        request = self._cards_request([hand_card, weapon], places=places, owner=self.target)

        result = self.engine._resolve_choice(self.human, request, [1])
        self.assertTrue(result["bool"])
        self.assertEqual(result["cards"], [weapon])

        self.target.equipment.pop("weapon")
        result = self.engine._resolve_choice(self.human, request, [1])
        self.assertTrue(result["bool"], "不可取消请求应兜底到仍合法的牌")
        self.assertEqual(result["cards"], [hand_card])

    def test_shown_pool_selection_accepted(self):
        first = make_card("p1", "桃")
        second = make_card("p2", "杀")
        request = self._cards_request([first, second], owner=self.human, zone="shown")
        result = self.engine._resolve_choice(self.human, request, [1])
        self.assertTrue(result["bool"])
        self.assertEqual(result["cards"], [second])

    def test_cancelable_invalid_returns_empty(self):
        card = make_card("c1", "杀")
        self.human.hand.append(card)
        request = self._cards_request([card], cancelable=True)
        result = self.engine._resolve_choice(self.human, request, [99])
        self.assertFalse(result["bool"])
        self.assertEqual(result["cards"], [])

    def test_garbage_input_never_lands(self):
        card = make_card("g1", "杀")
        self.human.hand.append(card)
        request = self._cards_request([card])
        result = self.engine._resolve_choice(self.human, request, "不是索引")
        self.assertTrue(result["bool"])
        self.assertEqual(result["cards"], [card])

    def test_empty_candidates_returns_empty(self):
        request = self._cards_request([])
        result = self.engine._resolve_choice(self.human, request, [0])
        self.assertFalse(result["bool"])
        self.assertEqual(result["cards"], [])

    def test_abort_blocks_all_choices(self):
        card = make_card("a1", "杀")
        self.human.hand.append(card)
        request = self._cards_request([card])
        self.engine._abort_reason = "idle_timeout"
        result = self.engine._resolve_choice(self.human, request, [0])
        self.assertFalse(result["bool"])
        self.assertEqual(result["cards"], [])


class ChoicePlayerValidationTest(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()
        self.human = self.engine.game_state.players[0]
        self.candidates = self.engine.game_state.players[1:3]

    def _players_request(self, min_n=1, max_n=1, cancelable=False):
        return {
            "kind": "choose_players",
            "context": {"all_players": list(self.engine.game_state.players)},
            "candidate_ids": [p.id for p in self.candidates],
            "min_n": min_n,
            "max_n": max_n,
            "cancelable": cancelable,
        }

    def test_duplicate_players_deduped(self):
        request = self._players_request(min_n=2, max_n=2)
        result = self.engine._resolve_choice(self.human, request, [0, 0, 1])
        self.assertTrue(result["bool"])
        self.assertEqual(result["players"], list(self.candidates))

    def test_dead_candidate_excluded_with_best_effort(self):
        self.candidates[0].alive = False
        request = self._players_request(min_n=2, max_n=2)
        result = self.engine._resolve_choice(self.human, request, [0, 1])
        self.assertEqual(result["players"], [self.candidates[1]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
