#!/usr/bin/env python3
"""AI会话窗口与前缀缓存分层回归测试（S4）。

验证目标全部来自计划书第7节：
- L0 全局层在所有玩家之间**逐字节相同**（跨玩家命中缓存的前提）
- 同一玩家连续调用时消息列表满足「前缀单调不变」（自动前缀缓存命中的前提）
- 超限时一次性压缩重建，而非逐条滑窗删除
- 改配置后窗口整体重建
"""

import asyncio
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path


from game_engine.ai_decision import AIGateway
from game_engine import MainEngine


BASE_CONFIG = {
    "mode": "5人身份局",
    "player_name": "测试玩家",
    "ais": [{"name": f"AI{i}"} for i in range(1, 5)],
    "deck_id": "standard",
}


class FakeGateway:
    """记录每次调用收到的完整消息列表，便于断言前缀不变性。"""

    def __init__(self, reply='{"action_index": 0, "reasoning": "测试"}'):
        self.reply = reply
        self.calls = []

    async def call_ai(self, **kwargs):
        self.calls.append([dict(m) for m in kwargs["messages"]])
        if kwargs.get("return_usage"):
            return self.reply, {"prompt_tokens": 100, "cached_tokens": 64, "completion_tokens": 20}
        return self.reply


def make_engine(stats_dir=None):
    engine = MainEngine(dict(BASE_CONFIG))
    engine.ai_decision.gateway = FakeGateway()
    for player in engine.game_state.players:
        if player.is_ai:
            player.ai_config["api_key"] = "sk-fake-for-test"
    if stats_dir is not None:
        engine.ai_decision.cache_stats_path = str(Path(stats_dir) / "ai_cache_stats.jsonl")
    return engine


def quiet(coro):
    """引擎会 print 大量对局信息，测试里吞掉以免刷屏。"""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = asyncio.run(coro)
    return result, buffer.getvalue()


class GlobalLayerTest(unittest.TestCase):
    """L0：与玩家无关，所有人逐字节相同。"""

    def setUp(self):
        self.engine = make_engine()
        self.ai = self.engine.ai_decision

    def test_l0_identical_across_all_players(self):
        texts = [
            self.ai.get_session(p)["messages"][0]["content"]
            for p in self.engine.game_state.players if p.is_ai
        ]
        self.assertEqual(len(texts), 4)
        for text in texts[1:]:
            self.assertEqual(text, texts[0], "L0全局层必须逐字节相同，否则跨玩家缓存不可能命中")
        print(f"S4: L0跨4个AI逐字节相同，长度={len(texts[0])} OK")

    def test_l0_contains_no_player_specific_content(self):
        text = self.ai.worldbook_manager.build_global_rules()
        for player in self.engine.game_state.players:
            self.assertNotIn(player.name, text, f"L0里混进了玩家名 {player.name}")
            if player.identity:
                self.assertNotIn(f"身份：{player.identity}", text)
        print("S4: L0不含任何玩家专属内容 OK")

    def test_l0_card_table_is_deduped_by_name(self):
        text = self.ai.worldbook_manager.build_global_rules()
        self.assertEqual(text.count("- 【杀】"), 1, "同名牌有多条数据，卡牌效果表必须按名字去重")
        print("S4: L0卡牌效果表按名字去重 OK")

    def test_l1_is_player_specific(self):
        ai_players = [p for p in self.engine.game_state.players if p.is_ai]
        layers = [self.ai.get_session(p)["messages"][1]["content"] for p in ai_players]
        self.assertEqual(len(set(layers)), len(layers), "L1角色层应当各不相同")
        for player, layer in zip(ai_players, layers):
            self.assertIn(player.name, layer)
        print("S4: L1角色层含各自玩家信息且互不相同 OK")


class PrefixStabilityTest(unittest.TestCase):
    """L2 只追加，不改动已有消息 —— 前缀单调不变。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.engine = make_engine(self.tmp.name)
        self.ai = self.engine.ai_decision
        self.player = next(p for p in self.engine.game_state.players if p.is_ai)

    def _decide_once(self):
        actions = self.engine.get_available_actions(self.player)
        return quiet(self.ai.make_decision(self.player, actions))[0]

    def test_prefix_grows_monotonically_over_ten_calls(self):
        for _ in range(10):
            self._decide_once()
        calls = self.ai.gateway.calls
        self.assertEqual(len(calls), 10)
        for i in range(1, len(calls)):
            previous, current = calls[i - 1], calls[i]
            self.assertGreater(len(current), len(previous), "每次调用应当只增不减")
            self.assertEqual(
                current[: len(previous)], previous,
                f"第{i}次调用的前{len(previous)}条与上一次不一致，前缀缓存会全部失效",
            )
        print(f"S4: 连续10次调用前缀单调不变，消息数 {len(calls[0])}→{len(calls[-1])} OK")

    def test_first_two_messages_are_the_stable_prefix(self):
        self._decide_once()
        messages = self.ai.gateway.calls[0]
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "system")
        self.assertEqual(messages[0]["content"], self.ai.worldbook_manager.build_global_rules())
        print("S4: 消息列表前两条恒为 L0/L1 system 层 OK")

    def test_response_decision_shares_the_same_window(self):
        self._decide_once()
        after_decision = len(self.ai.get_session(self.player)["messages"])
        request = {
            "kind": "respond", "prompt": "请打出闪", "requested_name": "闪",
            "options": [{"card": None, "label": "不响应"}], "context": {},
        }
        self.ai.gateway.reply = '{"option_index": 0, "reasoning": "测试"}'
        quiet(self.ai.make_response_decision(self.player, request))
        messages = self.ai.gateway.calls[-1]
        self.assertGreater(len(messages), after_decision, "响应决策应追加进同一窗口而不是新开会话")
        self.assertEqual(messages[0]["content"], self.ai.worldbook_manager.build_global_rules())
        print("S4: 出牌决策与响应决策共用同一会话窗口 OK")

    def test_record_outcome_enters_the_window(self):
        self._decide_once()
        before = len(self.ai.get_session(self.player)["messages"])
        self.ai.record_outcome(self.player, "【引擎执行结果】测试回灌")
        session = self.ai.get_session(self.player)
        self.assertEqual(len(session["messages"]), before + 1)
        self.assertIn("测试回灌", session["messages"][-1]["content"])
        print("S4: 引擎执行结果被回灌进会话窗口 OK")

    def test_cache_stats_are_written_with_real_usage(self):
        self._decide_once()
        lines = Path(self.ai.cache_stats_path).read_text(encoding="utf-8").strip().splitlines()
        record = json.loads(lines[-1])
        self.assertEqual(record["player_id"], self.player.id)
        self.assertEqual(record["kind"], "decision")
        self.assertEqual(record["cached_tokens"], 64)
        print(f"S4: 缓存统计落盘 cached_tokens={record['cached_tokens']} OK")

    def test_missing_usage_is_recorded_as_null_not_guessed(self):
        self.ai._log_cache_stats(self.player, "decision", {})
        record = json.loads(Path(self.ai.cache_stats_path).read_text(encoding="utf-8").strip().splitlines()[-1])
        self.assertIsNone(record["cached_tokens"], "取不到就必须写 null，绝不能用估算值冒充实测值")
        self.assertIsNone(record["prompt_tokens"])
        print("S4: usage缺失时写 null 而非估算值 OK")


class CompressionTest(unittest.TestCase):
    """超限时一次性压缩，压缩后前缀重新稳定。"""

    def setUp(self):
        self.engine = make_engine()
        self.ai = self.engine.ai_decision
        self.player = next(p for p in self.engine.game_state.players if p.is_ai)

    def _decide_once(self):
        actions = self.engine.get_available_actions(self.player)
        quiet(self.ai.make_decision(self.player, actions))

    def test_compression_triggers_and_prefix_restabilises(self):
        self.ai.session_max_chars = 10 ** 9  # 只考察条数触发，排除字符数干扰
        for _ in range(25):
            self._decide_once()
        session = self.ai.get_session(self.player)
        self.assertGreaterEqual(session["compressions"], 1, "第25次应当已触发压缩")
        self.assertTrue(session["has_summary"])
        self.assertEqual(session["prefix_len"], 2, "L0/L1 才是缓存断点前缀；摘要会变，不算前缀")
        self.assertIn("前情概要", session["messages"][2]["content"])

        # 压缩后再跑几次，前缀必须重新稳定下来。
        mark = len(self.ai.gateway.calls)
        for _ in range(3):
            self._decide_once()
        after = self.ai.gateway.calls[mark:]
        for i in range(1, len(after)):
            self.assertEqual(after[i][: len(after[i - 1])], after[i - 1], "压缩后前缀应重新单调不变")
        print(f"S4: 25次调用触发{session['compressions']}次压缩，压缩后前缀重新稳定 OK")

    def test_compression_is_one_shot_not_sliding_window(self):
        self.ai.session_max_l2 = 6
        self.ai.session_max_chars = 10 ** 9
        for _ in range(12):
            self._decide_once()
        session = self.ai.get_session(self.player)
        self.assertGreaterEqual(session["compressions"], 1)
        summaries = [m for m in session["messages"] if "前情概要" in m.get("content", "")]
        self.assertEqual(len(summaries), 1, "压缩必须是一次性重建成一条摘要，不是逐条滑窗删除")
        print(f"S4: 窗口内摘要恰好1条（压缩{session['compressions']}次）OK")

    def test_char_budget_also_triggers_compression(self):
        self.ai.session_max_l2 = 10 ** 9
        self.ai.session_max_chars = 1
        self._decide_once()
        self._decide_once()
        self.assertGreaterEqual(self.ai.get_session(self.player)["compressions"], 1)
        print("S4: 字符数超限同样触发压缩 OK")


class SessionResetTest(unittest.TestCase):
    """签名变化 → 窗口整体重建（R13）。"""

    def setUp(self):
        self.engine = make_engine()
        self.ai = self.engine.ai_decision
        self.player = next(p for p in self.engine.game_state.players if p.is_ai)

    def test_update_ai_config_rebuilds_window(self):
        self.ai.get_session(self.player)["messages"].append({"role": "user", "content": "旧窗口痕迹"})
        self.engine.update_ai_config(self.player.id, {"provider": "openai", "model": "gpt-4o"})
        messages = self.ai.get_session(self.player)["messages"]
        self.assertEqual(len(messages), 2, "改配置后窗口应回到只有 L0/L1 的初始状态")
        self.assertNotIn("旧窗口痕迹", json.dumps(messages, ensure_ascii=False))
        print("S4: update_ai_config 后会话窗口被重建 OK")

    def test_signature_change_rebuilds_even_without_explicit_reset(self):
        self.ai.get_session(self.player)["messages"].append({"role": "user", "content": "旧窗口痕迹"})
        self.player.ai_config["model"] = "another-model"
        messages = self.ai.get_session(self.player)["messages"]
        self.assertEqual(len(messages), 2)
        print("S4: 签名变化时窗口自动重建 OK")

    def test_same_config_keeps_the_window(self):
        session_before = self.ai.get_session(self.player)
        session_before["messages"].append({"role": "user", "content": "保留我"})
        self.assertIs(self.ai.get_session(self.player), session_before)
        print("S4: 配置未变时窗口原样保留 OK")


class UsageExtractionTest(unittest.TestCase):
    """各家 cached tokens 字段名不同，必须都能取到。"""

    def test_deepseek_field(self):
        usage = AIGateway.extract_usage({"usage": {
            "prompt_tokens": 900, "prompt_cache_hit_tokens": 768, "completion_tokens": 30}})
        self.assertEqual(usage["cached_tokens"], 768)

    def test_openai_field(self):
        usage = AIGateway.extract_usage({"usage": {
            "prompt_tokens": 900, "prompt_tokens_details": {"cached_tokens": 512}, "completion_tokens": 30}})
        self.assertEqual(usage["cached_tokens"], 512)

    def test_anthropic_field(self):
        usage = AIGateway.extract_usage({"usage": {
            "input_tokens": 900, "cache_read_input_tokens": 640, "output_tokens": 30}})
        self.assertEqual(usage["cached_tokens"], 640)
        self.assertEqual(usage["prompt_tokens"], 900)

    def test_absent_usage_yields_none(self):
        usage = AIGateway.extract_usage({})
        self.assertEqual(usage, {"prompt_tokens": None, "cached_tokens": None, "completion_tokens": None})
        print("S4: 三家 cached tokens 字段均可提取，缺失时为 None OK")


class CacheBreakpointTest(unittest.TestCase):
    """Anthropic 显式断点：只打在稳定前缀上。"""

    MESSAGES = [
        {"role": "system", "content": "L0"},
        {"role": "system", "content": "L1"},
        {"role": "user", "content": "L2"},
    ]

    def test_openai_compatible_providers_are_untouched(self):
        for provider in ("deepseek", "openai", "qwen"):
            out = AIGateway.apply_cache_breakpoints(self.MESSAGES, provider, 2)
            self.assertIs(out, self.MESSAGES, f"{provider} 是自动前缀缓存，不应加断点")

    def test_anthropic_gets_two_breakpoints_on_the_prefix_only(self):
        out = AIGateway.apply_cache_breakpoints(self.MESSAGES, "claude", 2)
        marked = [i for i, m in enumerate(out) if "cache_control" in m]
        self.assertEqual(marked, [0, 1], "断点只打在 L0/L1 末尾，L2 每次都变不打")
        self.assertNotIn("cache_control", self.MESSAGES[0], "原列表不得被就地污染")
        print("S4: Anthropic 断点只落在稳定前缀（当前未接入原生协议，处于休眠）OK")


if __name__ == "__main__":
    unittest.main(verbosity=2)
