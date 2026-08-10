import asyncio
import unittest

from game_engine.card_system import CardSystem
from game_engine import MainEngine
from game_engine.state_manager import Card


class WuxieChainTest(unittest.TestCase):
    def setUp(self):
        config = {
            'mode': '5人身份局', 'player_name': '测试玩家',
            'ais': [{'name': f'AI{i}'} for i in range(1, 5)],
            'deck_id': 'standard',
        }
        self.engine = MainEngine(config)
        self.system = self.engine.card_system
        self.players = self.engine.game_state.players
        for player in self.players:
            player.hand.clear()
        self.card = Card('test_guohe', '过河拆桥', 'heart', 3, 'trick')
        self.source = self.players[0]

    def run_async(self, coro):
        return asyncio.run(coro)

    def test_four_layers_consume_four_wuxie_cards(self):
        for i in range(1, 5):
            self.players[i].hand.append(Card(f'wuxie_{i}', '无懈可击', 'club', i, 'trick'))
        result = self.run_async(self.system.ask_wuxie(self.card, self.source, self.players[1:]))
        self.assertFalse(result, '偶数层无懈后原锦囊最终生效')
        self.assertEqual(sum(c.name == '无懈可击' for c in self.engine.game_state.discard_pile), 4)
        for player in self.players[1:]:
            self.assertFalse(any(c.name == '无懈可击' for c in player.hand))

    def test_no_artificial_depth_limit(self):
        for i in range(1, 5):
            self.players[i].hand.append(Card(f'wuxie_long_{i}', '无懈可击', 'spade', i, 'trick'))
        # 1号位多一张：链长会超过玩家数，验证深度只由牌数决定而非人数或固定上限。
        self.players[1].hand.append(Card('wuxie_extra', '无懈可击', 'diamond', 9, 'trick'))
        result = self.run_async(self.system.ask_wuxie(self.card, self.source, self.players[1:]))
        self.assertTrue(result, '奇数层无懈后原锦囊被抵消')
        self.assertEqual(sum(c.name == '无懈可击' for c in self.engine.game_state.discard_pile), 5)
        for player in self.players:
            self.assertFalse(any(c.name == '无懈可击' for c in player.hand), '全场无懈应当耗尽，链自然终止')

    def test_card_system_fallback_without_responder(self):
        original = self.system.responder
        self.system.responder = None
        try:
            self.players[1].hand.append(Card('wuxie_none', '无懈可击', 'spade', 1, 'trick'))
            result = self.run_async(self.system.ask_wuxie(self.card, self.source, []))
            self.assertFalse(result)
            self.assertEqual(len(self.players[1].hand), 1)
        finally:
            self.system.responder = original


if __name__ == '__main__':
    unittest.main(verbosity=2)
