"""B6 takeover uses the human perspective and rejects late model work."""

import asyncio

from game_engine import MainEngine


def engine():
    config = MainEngine.normalize_config({
        "mode": "5人身份局", "selected_hero": {"id": "caocao"},
        "ais": [{"name": f"AI{i}"} for i in range(4)], "deck_id": "standard",
    })
    return MainEngine(config)


def test_copy_ai_connection_keeps_human_perspective():
    game = engine()
    human, ai = game.game_state.players[:2]
    human.identity = "rebel"
    ai.identity = "lord"
    ai.ai_config.update({"provider": "openai", "model": "example-model", "api_key": "fake-key"})
    status = game.set_trustee(True, source="copy_ai", player_id=ai.id)
    assert status["model"] == "example-model"
    assert "api_key" not in status
    assert "identity" not in game._trustee_config
    assert "hand" not in game._trustee_config

    observed = {}

    class Decision:
        last_failure = {}

        async def make_decision(self, player, actions):
            observed.update(id=player.id, identity=player.identity, hand=player.hand,
                            model=player.ai_config["model"])
            return {"action": actions[0], "target_ids": []}

    game.ai_decision = Decision()
    asyncio.run(game._trustee_make_decision(human, [{"type": "end_phase"}]))
    assert observed == {"id": human.id, "identity": "rebel", "hand": human.hand,
                        "model": "example-model"}


def test_human_input_invalidates_late_takeover_decision():
    async def scenario():
        game = engine()
        human = game.game_state.players[0]
        game.set_trustee(True, source="custom", config={"provider": "openai", "model": "slow",
                                                        "api_key": "fake-key"})
        started = asyncio.Event()
        release = asyncio.Event()

        class Decision:
            last_failure = {}

            async def make_decision(self, _player, actions):
                started.set()
                await release.wait()
                return {"action": actions[0], "target_ids": []}

        game.ai_decision = Decision()
        task = asyncio.create_task(game._trustee_make_decision(human, [{"type": "end_phase"}]))
        await started.wait()
        game._note_human_input()
        release.set()
        assert await task is None
        assert game.trustee_status()["enabled"] is False

    asyncio.run(scenario())


def test_three_model_failures_degrade_to_rules():
    game = engine()
    human = game.game_state.players[0]
    game.set_trustee(True, source="custom", config={"provider": "openai", "model": "bad",
                                                    "api_key": "fake-key"})

    class Decision:
        def __init__(self):
            self.last_failure = {}
            self.model_calls = 0

        async def make_decision(self, player, actions):
            self.model_calls += 1
            self.last_failure[player.id] = "provider error"
            return self.simple_ai_decision(player, actions)

        def simple_ai_decision(self, _player, actions):
            return {"action": actions[0], "target_ids": []}

    decision = Decision()
    game.ai_decision = decision
    for _ in range(4):
        asyncio.run(game._trustee_make_decision(human, [{"type": "end_phase"}]))
    assert decision.model_calls == 3
    assert game.trustee_status()["degraded"] is True
    assert game.trustee_status()["failures"] == 3
    assert game.trustee_status()["degrade_reason"] == "three_failures"


def test_default_without_key_reports_rules_degrade_truthfully():
    game = engine()
    status = game.set_trustee(True, source="default")
    assert status["source"] == "default"
    assert status["model"] is None
    assert status["degraded"] is True
    assert status["degrade_reason"] == "missing_api_key"


def test_enabling_takeover_wakes_pending_confirmation_without_leaking_future():
    async def scenario():
        game = engine()
        human = game.game_state.players[0]
        started = asyncio.Event()

        async def on_request(**_payload):
            started.set()

        game.on("require_response", on_request)
        task = asyncio.create_task(game.ask_confirm(human, "是否发动技能？", default=False))
        await started.wait()
        game.set_trustee(True, source="rules")
        assert await task is False
        assert not game._pending_requests
        assert game.trustee_status()["enabled"] is True

    asyncio.run(scenario())


def test_public_trace_masks_other_ai_reason_and_private_choice():
    game = engine()
    human, ai = game.game_state.players[:2]
    captured = []

    async def on_trace(**data):
        captured.append(data)

    game.on("decision_trace", on_trace)
    game.ai_decision.last_meta[ai.id] = {"model": "example", "elapsed_ms": 12}
    game.ai_decision.last_reasoning[ai.id] = "我的隐藏身份是内奸，手里有桃"
    asyncio.run(game._emit_decision_trace(ai, "choose_cards", 3, [1], "accepted"))
    assert captured[-1]["model"] == "example"
    assert captured[-1]["candidate_count"] == 3
    assert captured[-1]["final_choice"] == "已选择"
    assert "内奸" not in captured[-1]["reason"]
    assert "桃" not in captured[-1]["reason"]

    game.set_trustee(True, source="custom", config={"model": "example", "api_key": "fake-key"})
    game.ai_decision.last_meta[human.id] = {"model": "example", "elapsed_ms": 9}
    game.ai_decision.last_reasoning[human.id] = "保留自己的桃"
    asyncio.run(game._emit_decision_trace(human, "choose_cards", 2, [0], "accepted"))
    assert captured[-1]["reason"] == "保留自己的桃"


def test_late_response_model_reprompts_and_uses_timeout_fallback():
    async def scenario():
        game = engine()
        human = game.game_state.players[0]
        game.set_trustee(True, source="custom", config={"model": "slow", "api_key": "fake-key"})
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_choice(_player, _request):
            started.set()
            await release.wait()
            return 1

        async def timed_out(_player, _request, _request_id):
            return None, "timeout"

        async def fallback(_player, _request):
            return 0

        game._ai_choose_option = slow_choice
        game._human_choose_option = timed_out
        game._trustee_choose = fallback
        request = {"kind": "respond", "options": [{"card": object()}, {"card": None}]}
        task = asyncio.create_task(game._ask_index(
            human, request, lambda _p, _r, index: {"bool": index == 0},
        ))
        await started.wait()
        game._note_human_input()
        release.set()
        assert (await task)["bool"] is True

    asyncio.run(scenario())
