"""席间聊天与出牌决策共用同一份模型连接配置；聊天失败或变慢不拖住对局。

背景：2026-10-17 真实运行日志里，决策请求走座位配置的中转地址（200），
聊天请求却落回 api.openai.com（401），并在每个 AI 回合结束后阻塞主循环约 1 秒。
"""

import asyncio
import logging

import httpx

from game_engine import MainEngine
from game_engine.ai_decision import model_call_kwargs

RELAY = "https://relay.example.test/v1"
KEY = "sk-relay-0123456789"


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


class RecordingGateway:
    def __init__(self, reply="来战！", error=None, delay=0.0):
        self.calls = []
        self.reply, self.error, self.delay = reply, error, delay

    async def call_ai(self, **kwargs):
        # 聊天走 call_ai(return_usage=True)，与真网关契约一致：返回 (文本, usage)。
        self.calls.append(kwargs)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.reply, {"prompt_tokens": 1, "cached_tokens": 0, "completion_tokens": 1}


def http_error(status):
    request = httpx.Request("POST", RELAY + "/chat/completions")
    return httpx.HTTPStatusError("err", request=request,
                                 response=httpx.Response(status, request=request))


def test_chat_uses_the_same_provider_model_key_and_url_as_decisions():
    engine, ai = engine_with_relay_seat()
    gateway = RecordingGateway()
    engine.chat_engine.gateway = gateway

    msg = run(engine.chat_engine.trigger_event_chat("turn_start", ai, {}))

    assert msg == "来战！"
    sent = gateway.calls[0]
    assert sent["base_url"] == RELAY
    for key, value in model_call_kwargs(ai).items():
        assert sent[key] == value


def test_base_url_alias_is_honoured_like_api_url():
    engine, ai = engine_with_relay_seat()
    ai.ai_config = {"provider": "openai", "model": "m", "api_key": KEY, "base_url": RELAY}
    assert model_call_kwargs(ai)["base_url"] == RELAY


def test_auth_failure_mutes_that_seat_for_the_game_without_traceback(caplog):
    engine, ai = engine_with_relay_seat()
    gateway = RecordingGateway(error=http_error(401))
    engine.chat_engine.gateway = gateway
    engine.chat_engine.chat_cooldown = 0

    with caplog.at_level(logging.WARNING, logger="game_engine.chat_engine"):
        assert run(engine.chat_engine.trigger_event_chat("turn_start", ai, {})) is None
        assert run(engine.chat_engine.trigger_event_chat("turn_start", ai, {})) is None

    assert len(gateway.calls) == 1, "401 之后同一座位本局不再发请求"
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert warnings[0].exc_info is None
    assert KEY not in caplog.text


def test_transient_failure_does_not_mute():
    engine, ai = engine_with_relay_seat()
    gateway = RecordingGateway(error=http_error(429))
    engine.chat_engine.gateway = gateway
    engine.chat_engine.chat_cooldown = 0

    run(engine.chat_engine.trigger_event_chat("turn_start", ai, {}))
    run(engine.chat_engine.trigger_event_chat("turn_start", ai, {}))

    assert len(gateway.calls) == 2


def test_turn_start_chat_runs_in_background_and_does_not_block_the_turn(monkeypatch):
    engine, ai = engine_with_relay_seat()
    engine.chat_engine.gateway = RecordingGateway(delay=5.0)
    monkeypatch.setattr("game_engine.main_engine.random.random", lambda: 0.0)
    phases_started = {}

    async def fake_phases(player):
        # 开场白已经发起，但回合不等它
        phases_started["pending_chats"] = len(engine._chat_tasks)

    engine._run_phases = fake_phases

    async def scenario():
        loop = asyncio.get_running_loop()
        started = loop.time()
        await engine._ai_turn(ai)
        elapsed = loop.time() - started
        pending = len(engine._chat_tasks)
        engine._cancel_chat_tasks()
        return elapsed, pending

    elapsed, pending = run(scenario())

    assert phases_started["pending_chats"] == 1, "开场白在回合阶段之前发起"
    assert elapsed < 1.0
    assert pending == 1


def test_background_chat_is_emitted_and_dropped_after_game_over():
    engine, ai = engine_with_relay_seat()
    engine.chat_engine.gateway = RecordingGateway(reply="看招", delay=0.01)
    seen = []

    async def on_chat(**data):
        seen.append(data["message"])

    engine.on("chat", on_chat)

    async def scenario():
        await engine._spawn_chat("turn_start", ai, {})
        engine.chat_engine.chat_cooldown = 0
        engine.game_state.game_over = True
        engine.game_state.winner = "lord"
        await engine._spawn_chat("turn_start", ai, {})

    run(scenario())

    assert seen == ["看招"]
