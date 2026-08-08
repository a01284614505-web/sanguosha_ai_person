#!/usr/bin/env python3
"""场外响应通道回归测试（S1-a：按 request_id 隔离的请求/应答通道）。"""

import asyncio
import contextlib
import io
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "game_engine"))

import httpx  # noqa: E402
from main_engine import MainEngine  # noqa: E402
from state_manager import Card  # noqa: E402


BASE_CONFIG = {
    "mode": "5人身份局",
    "player_name": "测试玩家",
    "ais": [{"name": f"AI{i}"} for i in range(1, 5)],
    "deck_id": "standard",
}


def make_engine():
    engine = MainEngine(dict(BASE_CONFIG))
    engine.response_timeout = 5
    return engine


def make_shan(tag: str) -> Card:
    return Card(f"test_shan_{tag}", "闪", "heart", 2, "basic")


def make_request(cards, requested_name="闪", owner=None):
    options = [
        {"card": card, "card_index": i, "owner": owner, "as_name": "闪", "skill_name": None}
        for i, card in enumerate(cards)
    ]
    options.append(MainEngine.make_pass_option())
    return {
        "kind": "respond",
        "prompt": "请打出闪响应【杀】",
        "requested_name": requested_name,
        "options": options,
        "context": {},
    }


class ResponseChannelTest(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()
        self.human = self.engine.game_state.players[0]
        self.assertFalse(self.human.is_ai, "0号位应当是真人")
        self.emitted = []
        self.engine.on("require_response", self._capture)

    async def _capture(self, **data):
        self.emitted.append(data)

    # ---------- 用例 ----------

    def test_normal_choice(self):
        async def scenario():
            shan = make_shan("a")
            self.human.hand.append(shan)
            request = make_request([shan], owner=self.human)
            task = asyncio.create_task(self.engine.request_response(self.human, request))
            await asyncio.sleep(0)
            self.assertEqual(len(self.emitted), 1)
            payload = self.emitted[0]
            self.assertEqual(payload["options"][-1]["is_pass"], True)
            self.assertEqual(payload["options"][0]["card"]["name"], "闪")
            self.assertTrue(self.engine.submit_response(payload["request_id"], 0))
            result = await task
            self.assertTrue(result["bool"])
            self.assertIs(result["card"], shan)
            self.assertIs(result["owner"], self.human)
            self.assertEqual(result["as_name"], "闪")
            print(f"normal_choice: request_id={payload['request_id']} -> {result['as_name']} OK")

        asyncio.run(scenario())

    def test_pass_option_returns_false(self):
        async def scenario():
            shan = make_shan("b")
            self.human.hand.append(shan)
            request = make_request([shan], owner=self.human)
            task = asyncio.create_task(self.engine.request_response(self.human, request))
            await asyncio.sleep(0)
            rid = self.emitted[0]["request_id"]
            self.assertTrue(self.engine.submit_response(rid, 1))  # 末项＝不响应
            result = await task
            self.assertFalse(result["bool"])
            print("pass_option: 选择不响应 -> bool=False OK")

        asyncio.run(scenario())

    def test_illegal_index_rejected(self):
        async def scenario():
            shan = make_shan("c")
            self.human.hand.append(shan)
            request = make_request([shan], owner=self.human)
            task = asyncio.create_task(self.engine.request_response(self.human, request))
            await asyncio.sleep(0)
            rid = self.emitted[0]["request_id"]
            self.assertTrue(self.engine.submit_response(rid, 99))
            result = await task
            self.assertFalse(result["bool"])
            print("illegal_index: 索引99 -> bool=False OK")

        asyncio.run(scenario())

    def test_card_no_longer_in_hand_rejected(self):
        async def scenario():
            shan = make_shan("d")
            self.human.hand.append(shan)
            request = make_request([shan], owner=self.human)
            task = asyncio.create_task(self.engine.request_response(self.human, request))
            await asyncio.sleep(0)
            rid = self.emitted[0]["request_id"]
            self.human.hand.remove(shan)  # 牌在应答之前已经离手
            self.assertTrue(self.engine.submit_response(rid, 0))
            result = await task
            self.assertFalse(result["bool"])
            print("card_gone: 牌已离手 -> 复核拦截 OK")

        asyncio.run(scenario())

    def test_wrong_as_name_rejected(self):
        async def scenario():
            shan = make_shan("e")
            self.human.hand.append(shan)
            request = make_request([shan], requested_name="桃", owner=self.human)
            task = asyncio.create_task(self.engine.request_response(self.human, request))
            await asyncio.sleep(0)
            rid = self.emitted[0]["request_id"]
            self.assertTrue(self.engine.submit_response(rid, 0))
            result = await task
            self.assertFalse(result["bool"])
            print("wrong_name: 要桃给闪 -> 复核拦截 OK")

        asyncio.run(scenario())

    def test_timeout_falls_back_to_trustee(self):
        async def scenario():
            self.engine.response_timeout = 0.05
            shan = make_shan("f")
            self.human.hand.append(shan)
            request = make_request([shan], owner=self.human)
            result = await self.engine.request_response(self.human, request)
            # 单次超时不再判「不响应」，而是交规则托管替他挡下
            self.assertTrue(result["bool"])
            self.assertIs(result["card"], shan)
            self.assertTrue(self.engine._trustee_active)
            self.assertEqual(self.engine._pending_requests, {})
            self.assertIsNotNone(self.engine._human_idle_since, "单次超时后不得清零离席计时")
            trustee_logs = [e for e in self.engine.game_log if e.get("trustee")]
            self.assertEqual(len(trustee_logs), 1)
            print(f"timeout->trustee: {trustee_logs[0]['message']} 且通道已清理 OK")

        asyncio.run(scenario())

    def test_concurrent_requests_do_not_cross(self):
        async def scenario():
            shan1, shan2 = make_shan("g1"), make_shan("g2")
            self.human.hand.extend([shan1, shan2])
            req1 = make_request([shan1], owner=self.human)
            req2 = make_request([shan2], owner=self.human)
            task1 = asyncio.create_task(self.engine.request_response(self.human, req1))
            task2 = asyncio.create_task(self.engine.request_response(self.human, req2))
            await asyncio.sleep(0)
            self.assertEqual(len(self.emitted), 2)
            rid1, rid2 = self.emitted[0]["request_id"], self.emitted[1]["request_id"]
            self.assertNotEqual(rid1, rid2)
            # 故意倒序应答，验证不会串号
            self.engine.submit_response(rid2, 0)
            self.engine.submit_response(rid1, 0)
            result1, result2 = await task1, await task2
            self.assertIs(result1["card"], shan1)
            self.assertIs(result2["card"], shan2)
            print(f"concurrent: {rid1}->{shan1.id} {rid2}->{shan2.id} 不串号 OK")

        asyncio.run(scenario())

    def test_stale_request_id_is_ignored(self):
        self.assertFalse(self.engine.submit_response("resp999", 0))
        self.assertFalse(self.engine.submit_response(None, 0))
        print("stale_id: 未知 request_id 被拒 OK")

    def test_submit_action_routes_response_type(self):
        async def scenario():
            shan = make_shan("h")
            self.human.hand.append(shan)
            request = make_request([shan], owner=self.human)
            task = asyncio.create_task(self.engine.request_response(self.human, request))
            await asyncio.sleep(0)
            rid = self.emitted[0]["request_id"]
            # 走前端真实路径：submit_action 识别 type=response 并转交
            self.engine._player_input = None
            self.engine.submit_action({"type": "response", "request_id": rid, "option_index": 0}, [])
            result = await task
            self.assertTrue(result["bool"])
            self.assertIsNone(self.engine._player_input, "响应不得污染出牌单槽位")
            print("submit_action路由: type=response 未碰 _player_event OK")

        asyncio.run(scenario())

    def test_options_without_card_short_circuit(self):
        async def scenario():
            request = {"kind": "respond", "requested_name": "闪",
                       "options": [MainEngine.make_pass_option()], "context": {}}
            result = await self.engine.request_response(self.human, request)
            self.assertFalse(result["bool"])
            self.assertEqual(self.emitted, [], "只有『不响应』时不应打扰玩家")
            print("short_circuit: 无可用候选时直接返回，不发请求 OK")

        asyncio.run(scenario())


class FakeClock:
    """假时钟：看门狗测试不真的睡 5 分钟。"""

    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float):
        self.now += seconds


class IdleWatchdogTest(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()
        self.clock = FakeClock()
        self.engine.time_source = self.clock
        self.human = self.engine.game_state.players[0]
        self.ai = next(p for p in self.engine.game_state.players if p.is_ai)

    def test_not_triggered_before_five_minutes(self):
        async def scenario():
            self.engine._mark_waiting_for_human()
            self.clock.advance(299)
            self.assertFalse(await self.engine._check_idle_timeout())
            self.assertFalse(self.engine.game_state.game_over)
            print(f"watchdog: 离席{self.engine.idle_seconds():.0f}秒 -> 不触发 OK")

        asyncio.run(scenario())

    def test_triggered_after_five_minutes(self):
        async def scenario():
            self.engine._mark_waiting_for_human()
            self.clock.advance(301)
            self.assertTrue(await self.engine._check_idle_timeout())
            self.assertTrue(self.engine.game_state.game_over)
            self.assertEqual(self.engine.game_state.winner, "aborted")
            self.assertEqual(self.engine._abort_reason, "idle_timeout")
            self.assertFalse(self.engine._trustee_active, "收摊时必须停掉托管代打")
            self.assertIn("服务器仍在运行", self.engine.game_state.end_message)
            print(f"watchdog: 离席301秒 -> winner={self.engine.game_state.winner} 已收摊 OK")

        asyncio.run(scenario())

    def test_idle_accumulates_across_requests(self):
        """多次超时之间不清零，是累计而不是每次重置。"""

        async def scenario():
            self.engine._mark_waiting_for_human()
            self.clock.advance(200)
            self.engine._mark_waiting_for_human()  # 第二个请求发出
            self.clock.advance(120)
            self.assertAlmostEqual(self.engine.idle_seconds(), 320.0)
            self.assertTrue(await self.engine._check_idle_timeout())
            print("watchdog: 200+120秒跨请求累计 -> 触发 OK")

        asyncio.run(scenario())

    def test_human_input_resets_timer(self):
        self.engine._mark_waiting_for_human()
        self.clock.advance(280)
        self.engine.submit_action({"type": "end_phase"}, [])
        self.assertIsNone(self.engine._human_idle_since)
        self.assertEqual(self.engine.idle_seconds(), 0.0)
        print("watchdog: 真人一操作 -> 计时清零 OK")

    def test_ai_turn_never_counts_as_idle(self):
        """R11 防误杀：AI 回合期间绝不计时。"""

        async def scenario():
            shan = make_shan("ai")
            self.ai.hand.append(shan)
            request = make_request([shan], owner=self.ai)
            result = await self.engine.request_response(self.ai, request)
            self.assertTrue(result["bool"])
            self.assertIsNone(self.engine._human_idle_since, "AI 响应不得触发离席计时")
            self.assertEqual(self.engine.idle_seconds(), 0.0)
            print("watchdog: AI 连续响应 -> 离席计时恒为 0 OK")

        asyncio.run(scenario())

    def test_abort_wakes_pending_request(self):
        """收摊时必须唤醒挂起的响应，否则协程永久挂死。"""

        async def scenario():
            self.engine.response_timeout = 30
            shan = make_shan("z")
            self.human.hand.append(shan)
            request = make_request([shan], owner=self.human)
            task = asyncio.create_task(self.engine.request_response(self.human, request))
            await asyncio.sleep(0)
            self.assertEqual(len(self.engine._pending_requests), 1)
            self.clock.advance(400)
            self.assertTrue(await self.engine._check_idle_timeout())
            result = await asyncio.wait_for(task, timeout=1)
            self.assertFalse(result["bool"])
            self.assertEqual(self.engine._pending_requests, {})
            print("watchdog: 收摊唤醒挂起请求 -> 协程正常退出 OK")

        asyncio.run(scenario())

    def test_trustee_rules(self):
        """规则托管的取舍：自己濒死必救、替别人不花桃、无懈只护自己。"""
        ai_decision = self.engine.ai_decision
        tao = Card("test_tao_1", "桃", "heart", 3, "basic")
        self.human.hand.append(tao)
        options = [
            {"card": tao, "card_index": 0, "owner": self.human, "as_name": "桃", "skill_name": None},
            MainEngine.make_pass_option(),
        ]
        self_dying = {"kind": "dying", "options": options, "context": {"target": self.human}}
        other_dying = {"kind": "dying", "options": options, "context": {"target": self.ai}}
        self.assertEqual(ai_decision.simple_response_decision(self.human, self_dying), 0)
        self.assertIsNone(ai_decision.simple_response_decision(self.human, other_dying))

        wuxie = Card("test_wuxie_1", "无懈可击", "club", 12, "trick")
        wx_options = [
            {"card": wuxie, "card_index": 0, "owner": self.human, "as_name": "无懈可击", "skill_name": None},
            MainEngine.make_pass_option(),
        ]
        on_me = {"kind": "wuxie", "options": wx_options, "context": {"targets": [self.human]}}
        on_other = {"kind": "wuxie", "options": wx_options, "context": {"targets": [self.ai]}}
        self.assertEqual(ai_decision.simple_response_decision(self.human, on_me), 0)
        self.assertIsNone(ai_decision.simple_response_decision(self.human, on_other))
        print("trustee: 濒死/无懈的保守取舍 OK")

    def test_trustee_prefers_plain_card_over_skill(self):
        shan = make_shan("plain")
        black = Card("test_sha_black", "杀", "spade", 7, "basic")
        request = {
            "kind": "respond",
            "requested_name": "闪",
            "options": [
                {"card": black, "card_index": 1, "owner": self.human, "as_name": "闪", "skill_name": "倾国"},
                {"card": shan, "card_index": 0, "owner": self.human, "as_name": "闪", "skill_name": None},
                MainEngine.make_pass_option(),
            ],
            "context": {},
        }
        self.assertEqual(self.engine.ai_decision.simple_response_decision(self.human, request), 1)
        print("trustee: 有普通闪时不白发倾国 OK")


class ScriptedResponder:
    """假 responder：按 player_id 预设选择，仍走引擎真复核。"""

    def __init__(self, engine, script):
        self.engine = engine
        self.script = dict(script)          # player_id -> 'pass' | int
        self.asked = []                     # (player_id, kind, [labels])

    async def __call__(self, player, request):
        labels = [self.engine._option_label(o) for o in request["options"]]
        self.asked.append((player.id, request["kind"], labels))
        choice = self.script.get(player.id, "pass")
        index = len(request["options"]) - 1 if choice == "pass" else int(choice)
        return self.engine._resolve_option(player, request, index)


class DummyTrigger:
    """只提供 response_options 的技能触发器替身。"""

    def __init__(self, options=None):
        self._options = options or []

    def response_options(self, player, requested_name):
        return list(self._options)


class CardSystemResponderTest(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()
        self.cs = self.engine.card_system
        self.src = self.engine.game_state.players[1]
        self.tgt = self.engine.game_state.players[2]
        for p in self.engine.game_state.players:
            p.hand.clear()
            p.hp = p.max_hp

    def sha_event(self, sha):
        return {"name": "useCard", "card": sha, "player": self.src, "target": self.tgt,
                "baseDamage": 1, "shanRequired": 1, "nature": None}

    def test_refusing_shan_takes_damage(self):
        async def scenario():
            sha = Card("t_sha_1", "杀", "spade", 7, "basic")
            shan = make_shan("keep")
            self.tgt.hand.append(shan)
            self.cs.responder = ScriptedResponder(self.engine, {self.tgt.id: "pass"})
            before = self.tgt.hp
            await self.cs._sha_effect(self.sha_event(sha))
            self.assertEqual(self.tgt.hp, before - 1)
            self.assertIn(shan, self.tgt.hand, "拒绝出闪时不得偷偷把闪打出去")
            print(f"S2: 手上有闪但选择不响应 -> 掉血 {before}->{self.tgt.hp} OK")

        asyncio.run(scenario())

    def test_choosing_shan_dodges(self):
        async def scenario():
            sha = Card("t_sha_2", "杀", "spade", 8, "basic")
            shan = make_shan("use")
            self.tgt.hand.append(shan)
            self.cs.responder = ScriptedResponder(self.engine, {self.tgt.id: 0})
            before = self.tgt.hp
            await self.cs._sha_effect(self.sha_event(sha))
            self.assertEqual(self.tgt.hp, before)
            self.assertNotIn(shan, self.tgt.hand)
            self.assertIn(shan, self.engine.game_state.discard_pile)
            print("S2: 选择出闪 -> 闪避成功且闪进弃牌堆 OK")

        asyncio.run(scenario())

    def test_no_shan_never_asks(self):
        async def scenario():
            sha = Card("t_sha_3", "杀", "club", 9, "basic")
            responder = ScriptedResponder(self.engine, {})
            self.cs.responder = responder
            await self.cs._sha_effect(self.sha_event(sha))
            self.assertEqual(responder.asked, [], "没有闪时不应打扰玩家")
            print("S2: 无闪 -> 不发请求，直接结算 OK")

        asyncio.run(scenario())

    def test_dying_asks_each_rescuer_in_seat_order(self):
        async def scenario():
            dying = self.engine.game_state.players[1]
            refuser = self.engine.game_state.players[2]
            saver = self.engine.game_state.players[3]
            refuser.hand.append(Card("t_tao_r", "桃", "heart", 5, "basic"))
            saver_tao = Card("t_tao_s", "桃", "heart", 6, "basic")
            saver.hand.append(saver_tao)
            dying.hp = 0

            responder = ScriptedResponder(self.engine, {refuser.id: "pass", saver.id: 0})
            self.cs.responder = responder
            await self.cs.enter_dying(dying)

            asked_ids = [entry[0] for entry in responder.asked]
            self.assertEqual(asked_ids, [refuser.id, saver.id], "应按座次逐个询问，且只问持桃者")
            self.assertTrue(all(entry[1] == "dying" for entry in responder.asked))
            self.assertTrue(dying.alive)
            self.assertEqual(dying.hp, 1)
            self.assertNotIn(saver_tao, saver.hand)
            print(f"S2: 濒死链 询问顺序={asked_ids} 拒绝→施救 hp={dying.hp} OK")

        asyncio.run(scenario())

    def test_dying_all_refuse_dies(self):
        async def scenario():
            dying = self.engine.game_state.players[1]
            other = self.engine.game_state.players[3]
            other.hand.append(Card("t_tao_x", "桃", "heart", 7, "basic"))
            dying.hp = 0
            self.cs.responder = ScriptedResponder(self.engine, {other.id: "pass"})
            await self.cs.enter_dying(dying)
            self.assertFalse(dying.alive)
            self.assertTrue(dying.identity_revealed)
            print("S2: 濒死无人施救 -> 阵亡且身份揭示 OK")

        asyncio.run(scenario())

    def test_skill_conversion_appears_alongside_plain_card(self):
        """R5：黑桃闪既能直接打出也能被倾国转化，两项都要在，靠 skill_name 区分。"""
        from card_system import CardSystem

        player = self.engine.game_state.players[0]
        black_shan = Card("t_shan_black", "闪", "spade", 2, "basic")
        black_sha = Card("t_sha_black", "杀", "spade", 3, "basic")
        player.hand.extend([black_shan, black_sha])
        trigger = DummyTrigger([
            {"card": black_shan, "card_index": 0, "as_name": "闪", "skill_name": "倾国", "owner": player},
            {"card": black_sha, "card_index": 1, "as_name": "闪", "skill_name": "倾国", "owner": player},
        ])
        cs = CardSystem(self.engine.game_state, None, trigger)
        options = cs.build_response_options(player, lambda c: c.name == "闪", "闪")

        self.assertEqual(options[-1]["card"], None, "末项必须是不响应")
        real = options[:-1]
        self.assertEqual(len(real), 3)
        self.assertEqual([o["skill_name"] for o in real], [None, "倾国", "倾国"])
        self.assertIsNone(cs.responder, "未注入 responder 时不得报错")
        print(f"S2: 候选={[self.engine._option_label(o) for o in options]} OK")

    def test_no_responder_returns_false(self):
        async def scenario():
            from card_system import CardSystem
            player = self.engine.game_state.players[0]
            player.hand.append(make_shan("orphan"))
            cs = CardSystem(self.engine.game_state, None, DummyTrigger())
            result = await cs.choose_to_respond(player, "请出闪", lambda c: c.name == "闪", "闪")
            self.assertFalse(result["bool"])
            print("S2: 未注入 responder 的老调用点 -> 不响应，不崩 OK")

        asyncio.run(scenario())


class FakeGateway:
    """假网关：不发任何真实网络请求。"""

    def __init__(self, reply=None, error=None):
        self.reply = reply
        self.error = error
        self.calls = []

    async def call_ai(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        # S4 起决策路径走 return_usage=True，假网关必须跟上真网关的契约。
        if kwargs.get("return_usage"):
            return self.reply, {"prompt_tokens": None, "cached_tokens": None, "completion_tokens": None}
        return self.reply


class AIResponseDecisionTest(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()
        self.ai = next(p for p in self.engine.game_state.players if p.is_ai)
        self.ai.hand.clear()
        self.shan = make_shan("ai_real")
        self.ai.hand.append(self.shan)
        self.request = make_request([self.shan], owner=self.ai)

    def decide(self):
        return asyncio.run(self.engine.ai_decision.make_response_decision(self.ai, self.request))

    def test_without_key_uses_rule_ai_and_never_calls_api(self):
        gateway = FakeGateway(reply='{"option_index":1}')
        self.engine.ai_decision.gateway = gateway
        self.ai.ai_config["api_key"] = ""
        self.assertEqual(self.decide(), 0)
        self.assertEqual(gateway.calls, [], "无 key 时不得发起任何 API 调用")

        self.ai.ai_config["api_key"] = "test_key"
        self.assertEqual(self.decide(), 0)
        self.assertEqual(gateway.calls, [], "test_key 是占位符，同样不得调用")
        print("S3: 无 key / test_key -> 规则AI，零调用 OK")

    def test_valid_reply_is_honoured(self):
        gateway = FakeGateway(reply='好的。{"option_index": 1, "reasoning": "留着闪救急"}')
        self.engine.ai_decision.gateway = gateway
        self.ai.ai_config["api_key"] = "sk-fake-not-a-real-key"
        self.assertEqual(self.decide(), 1)
        self.assertEqual(len(gateway.calls), 1)
        prompt = gateway.calls[0]["messages"][-1]["content"]
        self.assertIn("候选列表", prompt)
        self.assertIn("不响应", prompt)
        print("S3: AI 选择索引1（放弃）被采纳 OK")

    def test_out_of_range_index_falls_back(self):
        gateway = FakeGateway(reply='{"option_index": 99, "reasoning": "乱选"}')
        self.engine.ai_decision.gateway = gateway
        self.ai.ai_config["api_key"] = "sk-fake-not-a-real-key"
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            index = self.decide()
        self.assertEqual(index, 0, "越界应回落规则AI")
        output = buffer.getvalue()
        self.assertIn("ValueError", output, "日志必须带异常类型名")
        print(f"S3: 越界索引 -> 回落，日志='{output.strip().splitlines()[0]}' OK")

    def test_api_exception_logs_type_name(self):
        gateway = FakeGateway(error=httpx.ReadTimeout(""))
        self.engine.ai_decision.gateway = gateway
        self.ai.ai_config["api_key"] = "sk-fake-not-a-real-key"
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            index = self.decide()
        self.assertEqual(index, 0)
        output = buffer.getvalue()
        self.assertIn("ReadTimeout", output, "空 str() 的异常也必须能在日志里认出来")
        print(f"S3: httpx.ReadTimeout('') -> 日志='{output.strip()}' OK")

    def test_malformed_json_falls_back(self):
        gateway = FakeGateway(reply="我选第一张闪吧")
        self.engine.ai_decision.gateway = gateway
        self.ai.ai_config["api_key"] = "sk-fake-not-a-real-key"
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            index = self.decide()
        self.assertEqual(index, 0)
        self.assertIn("响应解析失败", buffer.getvalue())
        print("S3: 非JSON回复 -> 回落规则AI OK")

    def test_engine_path_uses_real_decision(self):
        """引擎的 AI 分支确实走 make_response_decision，而不是绕过去。"""

        async def scenario():
            gateway = FakeGateway(reply='{"option_index": 0}')
            self.engine.ai_decision.gateway = gateway
            self.ai.ai_config["api_key"] = "sk-fake-not-a-real-key"
            result = await self.engine.request_response(self.ai, self.request)
            self.assertTrue(result["bool"])
            self.assertIs(result["card"], self.shan)
            self.assertEqual(len(gateway.calls), 1)
            self.assertIsNone(self.engine._human_idle_since)
            print("S3: 引擎AI分支 -> 真调用一次 OK")

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main(verbosity=2)
