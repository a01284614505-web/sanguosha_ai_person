"""Model decisions and the two selection paths degrade after bad provider output."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from game_engine import MainEngine
from game_engine.state_manager import Card


@pytest.mark.parametrize("kind,reply,expected", [
    ("play", '{"action_index":0,"reasoning":"公开理由"}', "end_phase"),
    ("response", '{"option_index":0,"reasoning":"可响应"}', 0),
    ("choice", '{"option_indices":[0],"reasoning":"同意"}', [0]),
])
def test_success_records_model_usage_and_public_reason(kind, reply, expected):
    engine, player = setup()
    engine.ai_decision.gateway.call_ai = AsyncMock(return_value=(
        reply, {"prompt_tokens": 12, "completion_tokens": 7},
    ))
    actual = asyncio.run(invoke(engine, player, kind))
    if kind == "play":
        actual = actual["action"]["type"]
    assert actual == expected
    assert engine.ai_decision.last_failure[player.id] is None
    assert engine.ai_decision.last_reasoning[player.id]
    assert engine.ai_decision.last_meta[player.id]["prompt_tokens"] == 12
    assert engine.ai_decision.last_meta[player.id]["completion_tokens"] == 7


@pytest.mark.parametrize("kind", ["play", "response", "choice"])
@pytest.mark.parametrize("failure", ["empty", "illegal", "error", "timeout"])
def test_bad_model_output_falls_back_once_without_exposing_secret(kind, failure):
    engine, player = setup()
    if failure == "error":
        engine.ai_decision.gateway.call_ai = AsyncMock(side_effect=RuntimeError("secret-key-value"))
    elif failure == "timeout":
        engine.ai_decision.gateway.call_ai = AsyncMock(side_effect=asyncio.TimeoutError())
    else:
        bad = "" if failure == "empty" else '{"action_index":999,"option_index":999,"option_indices":[999]}'
        engine.ai_decision.gateway.call_ai = AsyncMock(return_value=(bad, {}))
    actual = asyncio.run(invoke(engine, player, kind))
    if kind == "play":
        assert actual["action"]["type"] == "end_phase"
    elif kind == "response":
        assert actual == 0
    else:
        assert actual == [1]
    failure_text = engine.ai_decision.last_failure[player.id]
    assert failure_text
    assert "secret-key-value" not in failure_text
    assert engine.ai_decision.gateway.call_ai.await_count == 1


def setup():
    config = MainEngine.normalize_config({
        "mode": "5人身份局", "selected_hero": {"id": "caocao"},
        "ais": [{"name": f"AI{i}", "api_key": ""} for i in range(4)],
    })
    engine = MainEngine(config)
    player = engine.game_state.players[1]
    player.ai_config["api_key"] = "fake-key"
    return engine, player


async def invoke(engine, player, kind):
    decision = engine.ai_decision
    if kind == "play":
        return await decision.make_decision(player, [{"type": "end_phase"}])
    if kind == "response":
        return await decision.make_response_decision(player, {
            "kind": "respond", "prompt": "打出一张闪", "requested_name": "闪",
            "options": [{"card": Card("shan", "闪", "heart", 2, "basic")},
                        {"card": None}],
        })
    return await decision.make_choice_decision(player, {
        "kind": "confirm", "prompt": "是否发动", "default": False,
        "min_n": 1, "max_n": 1, "cancelable": False,
        "options": [{"key": "yes", "label": "是"}, {"key": "no", "label": "否"}],
    })
