"""按 AI 座位与调用类型统计 token（Stage T · W1b）。

假网关沿用 test_chat_model_config.py 的写法：call_ai 在 return_usage=True 时返回 (文本, usage)。
"""

import asyncio
import json

import httpx
import pytest

from game_engine import MainEngine
from game_engine.game_logs import build_game_log
from game_engine.token_usage import USAGE_KINDS

RELAY = "https://relay.example.test/v1"
KEY = "sk-relay-token-usage-0123456789"


def run(coro):
    return asyncio.run(coro)


def engine_with_relay_seat():
    engine = MainEngine({"mode": "5人身份局", "player_name": "P0",
                         "ais": [{"name": f"P{i}"} for i in range(1, 5)],
                         "deck_id": "standard"})
    ai = engine.game_state.players[1]
    ai.ai_config = {"provider": "openai", "model": "relay-model",
                    "api_key": KEY, "api_url": RELAY}
    return engine, ai


class UsageGateway:
    """按调用顺序返回预设的 usage；error 非空时抛异常（模拟网络或 HTTP 失败）。"""

    def __init__(self, usages=None, reply="来战！", error=None):
        self.usages = list(usages or [])
        self.reply = reply
        self.error = error
        self.calls = []

    async def call_ai(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        usage = self.usages.pop(0) if self.usages else {}
        if kwargs.get("return_usage"):
            return self.reply, usage
        return self.reply


def http_error(status):
    request = httpx.Request("POST", RELAY + "/chat/completions")
    return httpx.HTTPStatusError("err", request=request,
                                 response=httpx.Response(status, request=request))


def bucket(engine, ai, kind):
    return engine.usage_stats[ai.id][kind]


# ---------- 累计 ----------

def test_usage_accumulates_per_seat_and_kind():
    engine, ai = engine_with_relay_seat()
    engine.record_usage(ai.id, "decision", {"prompt_tokens": 100, "cached_tokens": 64, "completion_tokens": 20})
    engine.record_usage(ai.id, "decision", {"prompt_tokens": 50, "cached_tokens": 0, "completion_tokens": 5})
    engine.record_usage(ai.id, "response", {"prompt_tokens": 7, "cached_tokens": None, "completion_tokens": 3})

    decision = bucket(engine, ai, "decision")
    assert decision == {"calls": 2, "failures": 0, "prompt_tokens": 150, "cached_tokens": 64,
                        "completion_tokens": 25, "unknown_usage_calls": 0}
    response = bucket(engine, ai, "response")
    assert response["calls"] == 1 and response["prompt_tokens"] == 7
    assert response["cached_tokens"] == 0, "cached 为 None 只是没报告，不累计也不算未知"
    assert response["unknown_usage_calls"] == 0
    assert "choice" not in engine.usage_stats[ai.id]


def test_unknown_kind_is_rejected():
    engine, ai = engine_with_relay_seat()
    with pytest.raises(ValueError):
        engine.record_usage(ai.id, "thinking", {}, False)


# ---------- 缺字段 ----------

def test_missing_fields_count_as_unknown_not_zero():
    engine, ai = engine_with_relay_seat()
    engine.record_usage(ai.id, "decision", {"prompt_tokens": 40}, False)        # 缺 completion
    engine.record_usage(ai.id, "decision", {"completion_tokens": 9}, False)     # 缺 prompt
    engine.record_usage(ai.id, "decision", None, False)                          # 整个 usage 为空
    engine.record_usage(ai.id, "decision", {}, False)

    b = bucket(engine, ai, "decision")
    assert b["calls"] == 4
    assert b["unknown_usage_calls"] == 4
    assert b["prompt_tokens"] == 40, "已有的字段照加"
    assert b["completion_tokens"] == 9
    assert b["failures"] == 0


def test_non_numeric_usage_values_are_treated_as_missing():
    engine, ai = engine_with_relay_seat()
    engine.record_usage(ai.id, "choice", {"prompt_tokens": "12", "completion_tokens": True}, False)
    b = bucket(engine, ai, "choice")
    assert b["prompt_tokens"] == 0 and b["completion_tokens"] == 0
    assert b["unknown_usage_calls"] == 1


# ---------- 失败 ----------

def test_failed_call_counts_calls_and_failures_but_not_unknown():
    engine, ai = engine_with_relay_seat()
    engine.record_usage(ai.id, "decision", None, True)
    engine.record_usage(ai.id, "decision", None, True)
    b = bucket(engine, ai, "decision")
    assert b["calls"] == 2 and b["failures"] == 2
    assert b["unknown_usage_calls"] == 0
    assert b["prompt_tokens"] == 0


def test_gateway_exception_on_decision_path_is_counted_as_failure():
    engine, ai = engine_with_relay_seat()
    engine.ai_decision.gateway = UsageGateway(error=http_error(429))

    with pytest.raises(httpx.HTTPStatusError):
        run(engine.ai_decision._call_with_session(ai, "decision", "局势"))

    b = bucket(engine, ai, "decision")
    assert b["calls"] == 1 and b["failures"] == 1


def test_successful_decision_call_is_counted_with_its_kind():
    engine, ai = engine_with_relay_seat()
    usage = {"prompt_tokens": 300, "cached_tokens": 128, "completion_tokens": 30}
    engine.ai_decision.gateway = UsageGateway(usages=[usage], reply='{"action_index": 0}')

    run(engine.ai_decision._call_with_session(ai, "response", "是否响应？"))

    b = bucket(engine, ai, "response")
    assert b["calls"] == 1 and b["prompt_tokens"] == 300
    assert b["cached_tokens"] == 128 and b["completion_tokens"] == 30
    assert "decision" not in engine.usage_stats[ai.id]


# ---------- 聊天 ----------

def test_chat_call_is_counted_as_chat():
    engine, ai = engine_with_relay_seat()
    engine.chat_engine.gateway = UsageGateway(
        usages=[{"prompt_tokens": 55, "cached_tokens": 0, "completion_tokens": 6}])

    msg = run(engine.chat_engine.trigger_event_chat("turn_start", ai, {}))

    assert msg == "来战！"
    b = bucket(engine, ai, "chat")
    assert b["calls"] == 1 and b["prompt_tokens"] == 55 and b["completion_tokens"] == 6


def test_chat_failure_is_counted_and_does_not_break_the_call():
    engine, ai = engine_with_relay_seat()
    engine.chat_engine.gateway = UsageGateway(error=http_error(429))
    engine.chat_engine.chat_cooldown = 0

    assert run(engine.chat_engine.trigger_event_chat("turn_start", ai, {})) is None
    b = bucket(engine, ai, "chat")
    assert b["calls"] == 1 and b["failures"] == 1


def test_chat_without_usage_is_counted_as_unknown():
    engine, ai = engine_with_relay_seat()
    engine.chat_engine.gateway = UsageGateway(usages=[None])

    assert run(engine.chat_engine.trigger_event_chat("turn_start", ai, {})) == "来战！"
    b = bucket(engine, ai, "chat")
    assert b["calls"] == 1 and b["unknown_usage_calls"] == 1


# ---------- 局后日志 ----------

def test_game_log_carries_token_usage_per_ai_without_the_key():
    engine, ai = engine_with_relay_seat()
    engine.chat_engine.gateway = UsageGateway(
        usages=[{"prompt_tokens": 10, "cached_tokens": 0, "completion_tokens": 2}])
    run(engine.chat_engine.trigger_event_chat("turn_start", ai, {}))
    engine.record_usage(ai.id, "decision", {"prompt_tokens": 99, "cached_tokens": 0, "completion_tokens": 9}, False)

    record = build_game_log(engine, {"winner": "lord", "message": "测试", "state": {}, "stats": {}},
                            include_thinking=False)

    rows = {row["id"]: row for row in record["token_usage"]}
    assert set(rows) == {p.id for p in engine.game_state.players if p.is_ai}
    row = rows[ai.id]
    assert row["name"] == ai.name and row["model"] == "relay-model" and row["provider"] == "openai"
    assert set(row["kinds"]) == set(USAGE_KINDS)
    assert row["kinds"]["chat"]["calls"] == 1 and row["kinds"]["chat"]["prompt_tokens"] == 10
    assert row["kinds"]["decision"]["prompt_tokens"] == 99
    assert row["kinds"]["response"]["calls"] == 0

    dumped = json.dumps(record, ensure_ascii=False)
    assert KEY not in dumped
    assert RELAY not in dumped


def test_game_log_token_usage_is_empty_zeroes_when_nothing_was_called():
    engine, ai = engine_with_relay_seat()
    record = build_game_log(engine, {"winner": None, "state": {}, "stats": {}}, include_thinking=True)
    row = next(r for r in record["token_usage"] if r["id"] == ai.id)
    assert all(row["kinds"][k]["calls"] == 0 for k in USAGE_KINDS)
    assert KEY not in json.dumps(record, ensure_ascii=False)
