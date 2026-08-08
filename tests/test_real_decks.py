#!/usr/bin/env python3
"""真实牌堆数据与 GameState 接入回归测试。"""

import sys
import unittest
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "game_engine"))

from deck_manager import DeckManager  # noqa: E402
from rules_engine import RulesEngine  # noqa: E402
from state_manager import Card, GameState, Phase, Player  # noqa: E402


class RealDeckTest(unittest.TestCase):
    def setUp(self):
        self.base_config = {
            "mode": "5人身份局",
            "player_name": "测试玩家",
            "ais": [{"name": f"AI{i}"} for i in range(1, 5)],
        }

    def all_cards(self, game):
        return game.deck + [card for player in game.players for card in player.hand]

    def test_all_deck_modes_initialize(self):
        for deck_id, expected in (("standard", 108), ("extra", 53), ("combined", 161)):
            with self.subTest(deck_id=deck_id):
                game = GameState()
                game.init_game({**self.base_config, "deck_id": deck_id})
                cards = self.all_cards(game)
                self.assertEqual(game.deck_id, deck_id)
                self.assertEqual(game.initial_deck_count, expected)
                self.assertEqual(len(game.deck), expected - 20)
                self.assertEqual(sum(len(player.hand) for player in game.players), 20)
                self.assertEqual(len(cards), expected)
                self.assertEqual(len({card.id for card in cards}), expected)
                self.assertFalse(any(card.id.startswith("filler_") for card in cards))
                print(
                    f"{deck_id}: initial={expected} remaining={len(game.deck)} "
                    f"hands=20 filler=0 unique={expected}"
                )

    def test_standard_key_cards_and_counts(self):
        manager = DeckManager(PROJECT_ROOT)
        cards = manager.load_deck_cards("standard")
        counts = Counter(card["name"] for card in cards)
        self.assertEqual(counts["杀"], 30)
        self.assertEqual(counts["闪"], 15)
        self.assertEqual(counts["桃"], 8)
        self.assertEqual(counts["闪电"], 2)
        self.assertTrue(any(card["name"] == "杀" and card["suit"] == "spade" and card["rank"] == 7 for card in cards))
        self.assertTrue(any(card["name"] == "桃园结义" and card["suit"] == "heart" and card["rank"] == 1 for card in cards))
        self.assertTrue(any(card["name"] == "闪电" and card["suit"] == "spade" and card["rank"] == 1 for card in cards))

    def test_extra_natures_survive_card_conversion(self):
        game = GameState()
        game.init_game({**self.base_config, "deck_id": "extra"})
        cards = self.all_cards(game)
        self.assertEqual(sum(card.nature == "fire" for card in cards), 5)
        self.assertEqual(sum(card.nature == "thunder" for card in cards), 9)
        self.assertEqual(sum(card.name == "酒" for card in cards), 5)

    def test_legacy_ids_resolve_to_standard(self):
        manager = DeckManager(PROJECT_ROOT)
        self.assertEqual(manager.normalize_deck_id("test_deck"), "standard")
        self.assertEqual(manager.normalize_deck_id("complete_deck"), "standard")

    def test_equipment_is_not_exposed_as_playable(self):
        game = GameState()
        player = Player(id=0, name="测试玩家")
        equipment = Card("standard_zhuge_club_1_1", "诸葛连弩", "club", 1, "equipment")
        player.hand.append(equipment)
        game.players = [player]
        game.current_player = player
        game.current_phase = Phase.PLAY
        allowed, reason = RulesEngine(game).can_play_card(player, equipment, [])
        self.assertFalse(allowed)
        self.assertIn("仅支持摸取和弃置", reason)


if __name__ == "__main__":
    unittest.main(verbosity=2)
