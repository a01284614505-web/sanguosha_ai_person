#!/usr/bin/env python3
"""真实对局统计（ROADMAP 7B-1/7B-2）：七项指标、击杀归属与结算 payload。"""

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

STAT_KEYS = (
    "damage_dealt", "damage_taken", "healing", "kills",
    "cards_played", "cards_lost", "skill_activations",
)


def make_engine():
    engine = MainEngine(dict(BASE_CONFIG))
    engine.response_timeout = 1
    for player in engine.game_state.players:
        player.hand.clear()
        player.equipment.clear()
        player.judge_area.clear()
    return engine


def stats_of(engine, player):
    return engine.stats.by_player[player.id]


def make_card(tag, name, suit="spade", rank=5, card_type="basic"):
    return Card(f"test_{tag}", name, suit, rank, card_type)


class DamageStatsTest(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()
        self.players = self.engine.game_state.players

    def test_damage_stats_and_kill_credit(self):
        src, tgt = self.players[1], self.players[2]
        tgt.hp = 2
        asyncio.run(self.engine.card_system.damage(src, tgt, 2))
        self.assertFalse(tgt.alive)
        self.assertEqual(stats_of(self.engine, src)["damage_dealt"], 2)
        self.assertEqual(stats_of(self.engine, src)["kills"], 1)
        self.assertEqual(stats_of(self.engine, tgt)["damage_taken"], 2)
        self.assertEqual(stats_of(self.engine, tgt)["kills"], 0)

    def test_overkill_counts_full_damage(self):
        src, tgt = self.players[1], self.players[2]
        tgt.hp = 1
        asyncio.run(self.engine.card_system.damage(src, tgt, 3))
        self.assertEqual(stats_of(self.engine, tgt)["damage_taken"], 3)
        self.assertEqual(stats_of(self.engine, src)["damage_dealt"], 3)

    def test_lightning_self_damage_has_no_kill(self):
        victim = self.players[3]
        victim.hp = 3
        asyncio.run(self.engine.card_system.damage(victim, victim, 3))
        self.assertFalse(victim.alive)
        self.assertEqual(stats_of(self.engine, victim)["damage_taken"], 3)
        self.assertEqual(stats_of(self.engine, victim)["damage_dealt"], 0)
        for player in self.players:
            self.assertEqual(stats_of(self.engine, player)["kills"], 0)

    def test_hp_loss_death_has_no_kill_credit(self):
        src, tgt = self.players[1], self.players[2]
        asyncio.run(self.engine.card_system.damage(src, tgt, 1))
        self.assertEqual(stats_of(self.engine, src)["kills"], 0)
        asyncio.run(self.engine.skill_manager.lose_hp(tgt, 5, "测试"))
        self.assertFalse(tgt.alive)
        self.assertEqual(stats_of(self.engine, src)["kills"], 0,
                         "失去体力死亡不得回溯到早前伤害来源")


class HealingStatsTest(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()
        self.players = self.engine.game_state.players
        self.human = self.players[0]

    def test_tao_healing_is_capped_by_max_hp(self):
        self.human.hp = self.human.max_hp - 1
        tao = make_card("tao", "桃", "heart", 3)
        asyncio.run(self.engine.card_system.use_tao(self.human, tao))
        self.assertEqual(stats_of(self.engine, self.human)["healing"], 1)
        asyncio.run(self.engine.card_system.use_tao(self.human, tao))
        self.assertEqual(stats_of(self.engine, self.human)["healing"], 1,
                         "满血使用桃不得计数")

    def test_skill_recover_attributed_to_source(self):
        src, tgt = self.players[1], self.players[2]
        tgt.hp = tgt.max_hp - 2
        healed = asyncio.run(self.engine.skill_manager.recover(tgt, 3, src, "测试"))
        self.assertEqual(healed, 2, "只统计实际恢复量")
        self.assertEqual(stats_of(self.engine, src)["healing"], 2)
        self.assertEqual(stats_of(self.engine, tgt)["healing"], 0)


class CardStatsTest(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()
        self.players = self.engine.game_state.players

    def test_discard_phase_counts_cards_lost(self):
        ai = self.players[1]
        ai.hp = 2
        ai.max_hp = 4
        ai.hand.extend([
            make_card("e1", "杀"), make_card("e2", "闪"),
            make_card("e3", "桃"), make_card("e4", "无懈可击", "club", 2, "trick"),
        ])
        self.engine.game_state.current_player = ai
        asyncio.run(self.engine.phase_controller.discard_phase())
        self.assertEqual(stats_of(self.engine, ai)["cards_lost"], 2)
        self.assertEqual(stats_of(self.engine, ai)["cards_played"], 0)

    def test_use_card_counts_played_and_lost(self):
        human, target = self.players[0], self.players[1]
        human.hand.append(make_card("sha", "杀"))
        self.engine.game_state.current_phase = Phase.PLAY
        self.engine.game_state.current_player = human
        ok = asyncio.run(self.engine.execute_action(
            human, {"type": "play_card", "card_index": 0}, [target.id]
        ))
        self.assertTrue(ok)
        self.assertEqual(stats_of(self.engine, human)["cards_played"], 1)
        self.assertEqual(stats_of(self.engine, human)["cards_lost"], 1)
        self.assertEqual(stats_of(self.engine, target)["damage_taken"], 1)

    def test_response_card_counts_played(self):
        src, target = self.players[1], self.players[2]
        shan = make_card("shan", "闪", "diamond", 2)
        target.hand.append(shan)
        event = {
            "name": "useCard", "card": make_card("sha_src", "杀"),
            "player": src, "target": target, "baseDamage": 1,
            "shanRequired": 1, "nature": None,
        }
        asyncio.run(self.engine.card_system._sha_effect(event))
        self.assertEqual(stats_of(self.engine, target)["cards_played"], 1)
        self.assertEqual(stats_of(self.engine, target)["cards_lost"], 1)
        self.assertEqual(stats_of(self.engine, target)["damage_taken"], 0)
        self.assertIn(shan, self.engine.game_state.discard_pile)


class SkillStatsTest(unittest.TestCase):
    def test_skill_activation_counted(self):
        engine = make_engine()
        human = engine.game_state.players[0]
        asyncio.run(engine.skill_manager.announce(human, "测试技", "测试发动"))
        self.assertEqual(stats_of(engine, human)["skill_activations"], 1)
        self.assertEqual(engine.skill_manager.activation_log[-1]["event"], "activate")


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class SettlementPayloadTest(unittest.TestCase):
    def test_serialize_exposes_stats_for_every_player(self):
        engine = make_engine()
        state = engine.serialize()
        for player in state["players"]:
            self.assertIn("stats", player)
            for key in STAT_KEYS:
                self.assertEqual(player["stats"][key], 0)

    def test_game_end_payload_carries_stats_mvp_duration(self):
        engine = make_engine()
        clock = FakeClock()
        engine.time_source = clock
        engine._started_at = clock.now
        clock.advance(42)
        human = engine.game_state.players[0]
        engine.stats.add(human, "kills", 1)
        engine.stats.add(human, "damage_dealt", 2)

        captured = []

        async def capture(**data):
            captured.append(data)

        engine.on("game_end", capture)
        asyncio.run(engine._emit_game_end_once())
        self.assertTrue(captured)
        payload = captured[0]
        self.assertEqual(payload["duration"], 42)
        self.assertIn("stats", payload)
        self.assertEqual(payload["stats"][human.id]["kills"], 1)
        mvp = payload["mvp"]
        self.assertEqual(mvp["player_id"], human.id)
        self.assertEqual(mvp["kills"], 1)
        for key in STAT_KEYS:
            self.assertIn(key, mvp)
        self.assertTrue(engine._game_end_emitted)


class SkillStatsEdgeTest(unittest.TestCase):
    """审查修复回归：救援冲销行、谦逊暂存、手牌损失统一事件。"""

    def setUp(self):
        self.engine = make_engine()
        self.players = self.engine.game_state.players

    def _handler(self, cls):
        return next(h for h in self.engine.skill_manager.handlers if isinstance(h, cls))

    def test_rescue_reversal_lands_on_crediting_row(self):
        """救援把回复改给主公时，冲销必须落在正向治疗所记的行（提供者）。"""
        from game_engine.skills_wu import WuSkillHandler

        wu = self._handler(WuSkillHandler)
        rescuer, target = self.players[1], self.players[2]
        lord = self.players[3]
        lord.identity = "lord"
        lord.hp = 1
        lord.max_hp = 4
        target.identity = "rebel"
        target.hero = {"faction": "wu"}
        target.hp = 1  # 濒死救援后回到1点；主公更濒危（1点）时才会触发救援转移
        self.engine.game_state.current_player = target
        wu.has = lambda p, name: name == "救援" and p is lord
        self.engine.stats.add(rescuer, "healing", 1)  # 模拟濒死救援记给提供者
        asyncio.run(wu.on_recover(target, 1, rescuer, "dying_rescue"))
        self.assertEqual(stats_of(self.engine, rescuer)["healing"], 0,
                         "被改走的治疗不得留在提供者账上")
        self.assertEqual(stats_of(self.engine, target)["healing"], 0)
        self.assertEqual(stats_of(self.engine, lord)["healing"], 1)
        self.assertEqual(target.hp, 0)
        self.assertEqual(lord.hp, 2)

    def test_qianxun_parking_not_counted_nor_triggers_lianying(self):
        """谦逊暂存不是失去：不计失牌、不触发连营；回合结束原样归还。"""
        from game_engine.skills_wu import WuSkillHandler

        wu = self._handler(WuSkillHandler)
        target = self.players[2]
        trick = make_card("jx", "乐不思蜀", "spade", 6)
        stored = make_card("qc", "桃", "heart", 3)
        target.judge_area.append(trick)
        target.hand.append(stored)
        wu.has = lambda p, name: name == "谦逊" and p is target
        deck_before = len(self.engine.game_state.deck)
        asyncio.run(wu.before_phase(target, Phase.JUDGE))
        self.assertEqual(target.hand, [])
        self.assertEqual(target.flags.get("qianxun_cards"), [stored])
        self.assertEqual(stats_of(self.engine, target)["cards_lost"], 0, "暂存不得计失牌")
        self.assertEqual(len(self.engine.game_state.deck), deck_before,
                         "连营等失去牌监听不得因暂存触发")
        asyncio.run(wu.after_phase(target, Phase.END))
        self.assertIn(stored, target.hand, "暂存牌应在回合结束归还")
        self.assertEqual(stats_of(self.engine, target)["cards_lost"], 0)

    def test_hand_card_loss_routes_through_unified_event(self):
        """武圣转化等手牌损失统一走 on_cards_lost：统计与监听器看到同一事件。"""
        from game_engine.skills_shu import ShuSkillHandler
        from game_engine.skills_wu import WuSkillHandler

        shu = self._handler(ShuSkillHandler)
        wu = self._handler(WuSkillHandler)
        player = self.players[1]
        card = make_card("ws", "桃", "heart", 8)
        player.hand.append(card)
        shu.has = lambda p, name: name == "武圣"
        wu.has = lambda p, name: name == "连营" and p is player
        deck_before = len(self.engine.game_state.deck)
        asyncio.run(shu._consume_conversion(player, card, "武圣", "杀"))
        self.assertEqual(stats_of(self.engine, player)["cards_lost"], 1)
        self.assertEqual(stats_of(self.engine, player)["cards_played"], 1)
        self.assertLess(len(self.engine.game_state.deck), deck_before,
                        "失去最后一张手牌应经统一事件触发连营摸牌")
        self.assertEqual(len(player.hand), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
