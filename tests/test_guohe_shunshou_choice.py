#!/usr/bin/env python3
"""过河拆桥 / 顺手牵羊 / 五谷丰登：真人选牌流程回归测试。"""

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
    for player in engine.game_state.players:
        player.hand.clear()
        player.equipment.clear()
        player.judge_area.clear()
    return engine


def make_card(tag, name, suit="spade", rank=5):
    return Card(f"test_{tag}", name, suit, rank, "basic")


def stats_of(engine, player):
    return engine.stats.by_player[player.id]


class GuoheChoiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()
        self.human = self.engine.game_state.players[0]
        self.target = self.engine.game_state.players[1]
        self.emitted = []
        self.animations = []

        async def capture(**data):
            self.emitted.append(data)

        async def capture_anim(**data):
            self.animations.append(data)

        self.engine.on("require_response", capture)
        self.engine.on("card_animation", capture_anim)

    def _play_guohe(self, choose):
        async def scenario():
            task = asyncio.create_task(
                self.engine.card_system.use_guohe(
                    self.human, make_card("guohe", "过河拆桥", "spade", 3), self.target
                )
            )
            await asyncio.sleep(0)
            request = self.emitted[-1]
            choose(request)
            return await task

        return asyncio.run(scenario())

    def test_hidden_hand_masked_and_equipment_visible(self):
        """手牌候选对选择者隐藏身份，装备/判定区明牌。"""
        hand_card = make_card("h1", "桃", "heart", 3)
        weapon = make_card("eq1", "青釭剑")
        judged = make_card("jd1", "乐不思蜀", "spade", 6)
        self.target.hand.append(hand_card)
        self.target.equipment["weapon"] = weapon
        self.target.judge_area.append(judged)
        seen = {}

        def choose(request):
            seen.update(request)
            self.engine.submit_response(request["request_id"], 1)

        self.assertTrue(self._play_guohe(choose))
        self.assertEqual(seen["kind"], "choose_cards")
        self.assertEqual(seen["selection"]["mode"], "single")
        labels = [option["label"] for option in seen["options"]]
        self.assertEqual(labels[0], "手牌")
        self.assertIsNone(seen["options"][0]["card"], "手牌身份不得下发给选择者")
        self.assertTrue(seen["options"][0]["hidden"])
        self.assertEqual(seen["options"][1]["card"]["name"], "青釭剑")
        self.assertEqual(seen["options"][2]["card"]["name"], "乐不思蜀")
        self.assertNotIn(weapon, self.target.equipment.values())
        self.assertIn(weapon, self.engine.game_state.discard_pile)

    def test_discarded_card_is_revealed(self):
        """被弃置的牌必须明牌展示（动画事件带真实牌面）。"""
        hand_card = make_card("h2", "桃", "heart", 4)
        self.target.hand.append(hand_card)

        def choose(request):
            self.engine.submit_response(request["request_id"], 0)

        self.assertTrue(self._play_guohe(choose))
        self.assertTrue(self.animations, "应发出卡牌动画事件")
        payload = self.animations[-1]
        self.assertEqual(payload["card"]["name"], "桃")
        self.assertEqual(payload["card"]["suit"], "heart")
        self.assertIn("过河拆桥", payload["message"])

    def test_invalid_index_falls_back_and_never_leaks(self):
        """非法索引不落地：非取消请求走规则兜底，弃置一张合法牌。"""
        c1 = make_card("i1", "闪", "diamond", 2)
        c2 = make_card("i2", "杀", "club", 7)
        self.target.hand.extend([c1, c2])

        def choose(request):
            self.engine.submit_response(request["request_id"], 99)

        self.assertTrue(self._play_guohe(choose))
        self.assertEqual(len(self.target.hand), 1)
        self.assertEqual(len(self.engine.game_state.discard_pile), 1)

    def test_stale_equipment_rejected(self):
        """应答前装备已离场：复核拒绝并换一张仍然存在的牌。"""
        hand_card = make_card("s1", "桃", "heart", 7)
        weapon = make_card("s2", "青釭剑")
        self.target.hand.append(hand_card)
        self.target.equipment["weapon"] = weapon

        def choose(request):
            self.target.equipment.pop("weapon")
            self.engine.submit_response(request["request_id"], 1)

        self.assertTrue(self._play_guohe(choose))
        self.assertNotIn(weapon, self.engine.game_state.discard_pile)
        self.assertNotIn(hand_card, self.target.hand)
        self.assertIn(hand_card, self.engine.game_state.discard_pile)

    def test_cards_lost_stat(self):
        """被拆牌按失去牌计入目标统计。"""
        self.target.hand.append(make_card("st1", "闪", "club", 3))

        def choose(request):
            self.engine.submit_response(request["request_id"], 0)

        self.assertTrue(self._play_guohe(choose))
        self.assertEqual(stats_of(self.engine, self.target)["cards_lost"], 1)

    def test_judge_zone_card_not_counted_as_lost(self):
        """判定区牌不是目标自己的资源：被拆只展示弃牌，不计失牌。"""
        judged = make_card("jd2", "乐不思蜀", "spade", 6)
        self.target.judge_area.append(judged)

        def choose(request):
            self.engine.submit_response(request["request_id"], 0)

        self.assertTrue(self._play_guohe(choose))
        self.assertIn(judged, self.engine.game_state.discard_pile)
        self.assertEqual(stats_of(self.engine, self.target)["cards_lost"], 0)

    def test_ai_chooser_needs_no_ws(self):
        """AI 使用过河拆桥走规则决策，无真人询问也不会卡住。"""
        ai_user = self.engine.game_state.players[3]
        ai_target = self.engine.game_state.players[4]
        ai_target.hand.extend([make_card("a1", "桃", "heart", 2), make_card("a2", "杀", "spade", 9)])

        async def scenario():
            return await self.engine.card_system.use_guohe(
                ai_user, make_card("ag", "过河拆桥"), ai_target
            )

        self.assertTrue(asyncio.run(scenario()))
        self.assertEqual(len(ai_target.hand), 1)
        self.assertEqual(len(self.emitted), 0, "AI 路径不得发真人询问")


class ShunshouChoiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()
        self.human = self.engine.game_state.players[0]
        self.target = self.engine.game_state.players[2]
        self.emitted = []

        async def capture(**data):
            self.emitted.append(data)

        self.engine.on("require_response", capture)

    def test_equipment_only_target_can_be_stolen(self):
        """目标只有装备时也可被顺手牵羊（与 can_play 规则一致）。"""
        weapon = make_card("eq", "麒麟弓")
        self.target.equipment["weapon"] = weapon

        async def scenario():
            task = asyncio.create_task(
                self.engine.card_system.use_shunshou(
                    self.human, make_card("ss", "顺手牵羊", "heart", 3), self.target
                )
            )
            await asyncio.sleep(0)
            request = self.emitted[-1]
            self.assertEqual(request["options"][0]["card"]["name"], "麒麟弓")
            self.engine.submit_response(request["request_id"], 0)
            return await task

        self.assertTrue(asyncio.run(scenario()))
        self.assertIn(weapon, self.human.hand)
        self.assertNotIn("weapon", self.target.equipment)
        self.assertEqual(stats_of(self.engine, self.target)["cards_lost"], 1)

    def test_hidden_hand_choice_moves_selected_card(self):
        """手牌候选隐藏身份，选中的实体牌实际转移给使用者。"""
        first = make_card("sh1", "杀", "spade", 4)
        second = make_card("sh2", "桃", "heart", 6)
        self.target.hand.extend([first, second])

        async def scenario():
            task = asyncio.create_task(
                self.engine.card_system.use_shunshou(
                    self.human, make_card("ss2", "顺手牵羊", "heart", 4), self.target
                )
            )
            await asyncio.sleep(0)
            request = self.emitted[-1]
            self.assertTrue(request["options"][0]["hidden"])
            self.engine.submit_response(request["request_id"], 1)
            return await task

        self.assertTrue(asyncio.run(scenario()))
        self.assertIn(second, self.human.hand)
        self.assertEqual(self.target.hand, [first])

    def test_judge_zone_steal_not_counted_as_lost(self):
        """顺手牵羊拿走判定区牌同样不计目标失牌。"""
        judged = make_card("jd3", "兵粮寸断", "club", 4)
        self.target.judge_area.append(judged)

        async def scenario():
            task = asyncio.create_task(
                self.engine.card_system.use_shunshou(
                    self.human, make_card("ss3", "顺手牵羊", "heart", 5), self.target
                )
            )
            await asyncio.sleep(0)
            request = self.emitted[-1]
            self.engine.submit_response(request["request_id"], 0)
            return await task

        self.assertTrue(asyncio.run(scenario()))
        self.assertIn(judged, self.human.hand)
        self.assertEqual(stats_of(self.engine, self.target)["cards_lost"], 0)


class WuguChoiceTest(unittest.TestCase):
    def test_human_wugu_choice_takes_effect(self):
        """五谷丰登：真人选中的那张牌必须真正到手（修复 shown 区复核）。"""
        engine = make_engine()
        human = engine.game_state.players[0]
        emitted = []

        async def capture(**data):
            emitted.append(data)

        engine.on("require_response", capture)
        tao = make_card("wg1", "桃", "heart", 3)
        sha = make_card("wg2", "杀", "spade", 8)
        shan = make_card("wg3", "闪", "diamond", 5)
        wine = make_card("wg4", "酒", "spade", 9)
        extra = make_card("wg5", "无中生有", "heart", 7)
        engine.game_state.deck = [tao, sha, shan, wine, extra]

        async def scenario():
            task = asyncio.create_task(
                engine.card_system.use_wugu(human, make_card("wugu", "五谷丰登", "heart", 4))
            )
            await asyncio.sleep(0)
            request = emitted[-1]
            self.assertEqual([option["card"]["name"] for option in request["options"]],
                             ["桃", "杀", "闪", "酒", "无中生有"])
            engine.submit_response(request["request_id"], 1)
            return await task

        self.assertTrue(asyncio.run(scenario()))
        self.assertIn(sha, human.hand, "真人选中的牌应到手，而不是被 AI 兜底替换")
        self.assertNotIn(tao, human.hand)


if __name__ == "__main__":
    unittest.main(verbosity=2)
