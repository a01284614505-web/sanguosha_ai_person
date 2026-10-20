"""All model decision entrances consume the same authoritative situation schema."""

import asyncio
import json
import re

from game_engine import MainEngine
from game_engine.game_logs import build_game_log
from game_engine.public_situation import build_public_situation
from game_engine.state_manager import Card


def make_engine():
    engine = MainEngine({
        "player_name": "真人",
        "ais": [{"name": f"AI{i}", "api_key": "offline-test"} for i in range(1, 5)],
    })
    viewer = engine.game_state.players[1]
    viewer.hand[:] = [Card("viewer-card", "闪", "heart", 2, "basic")]
    engine.game_state.players[2].hand[:] = [Card("other-secret", "桃", "heart", 3, "basic")]
    return engine, viewer


def versions(text):
    return re.findall(r'"state_version":"([0-9a-f]{16})"', text)


def test_play_and_response_prompts_share_versioned_current_state_and_private_view():
    engine, viewer = make_engine()
    action = {"type": "end_phase"}
    play = engine.ai_decision.build_decision_turn_message(viewer, [action])
    response = engine.ai_decision.build_response_prompt(viewer, {
        "prompt": "是否响应", "requested_name": "闪",
        "options": [{"card": viewer.hand[0], "owner": viewer, "as_name": "闪"}],
    })
    expected = build_public_situation(engine)["state_version"]

    assert versions(play) == [expected]
    assert versions(response) == [expected]
    assert "viewer-card" in play and "viewer-card" in response
    assert "other-secret" not in play and "other-secret" not in response
    assert "若历史摘要与这里冲突，以本区块为准" in play


def test_choice_model_call_uses_same_state_version_and_records_it_in_meta():
    engine, viewer = make_engine()
    captured = []

    async def fake_call(player, kind, content):
        captured.append((kind, content))
        return json.dumps({"reasoning": "测试", "option_indices": [0]}, ensure_ascii=False)

    engine.ai_decision._call_with_session = fake_call
    request = {
        "kind": "choose_option", "prompt": "选择", "options": [{"label": "甲"}],
        "min_n": 1, "max_n": 1, "cancelable": False,
    }
    result = asyncio.run(engine.ai_decision.make_choice_decision(viewer, request))
    expected = build_public_situation(engine)["state_version"]

    assert result == [0]
    assert captured[0][0] == "choice"
    assert versions(captured[0][1]) == [expected]
    assert engine.ai_decision.last_situation_versions[viewer.id] == expected
    assert "other-secret" not in captured[0][1]


def test_game_log_keeps_final_public_snapshot_and_structured_decision_diagnostics():
    engine, viewer = make_engine()

    async def emit_trace():
        await engine._emit_decision_trace(viewer, "choice", 2, {"type": "end_phase"}, "resolved")

    asyncio.run(emit_trace())
    row = engine.decision_log[-1]
    assert row["selection_kind"] == "choice"
    assert row["validation_status"] == "resolved"
    assert row["candidates_summary"] == "choice：2 个引擎候选"
    assert row["fallback_reason"] == "rules_no_provider"
    assert len(row["situation_version"]) == 16

    record = build_game_log(engine, {"state": engine.serialize()}, include_thinking=False)
    assert record["public_situation"] == build_public_situation(engine)
    encoded = json.dumps(record["public_situation"], ensure_ascii=False)
    assert "viewer-card" not in encoded and "other-secret" not in encoded


def test_variable_history_budget_compresses_without_counting_stable_prefix():
    engine, viewer = make_engine()
    ai = engine.ai_decision
    ai.session_max_l2 = 10_000
    ai.session_max_chars = 10_000_000
    ai.session_variable_max_chars = 24

    ai.push_user(viewer, "甲" * 20)
    ai.push_user(viewer, "乙" * 20)
    ai.push_user(viewer, "丙" * 20)

    session = ai.get_session(viewer)
    assert session["compressions"] == 1
    assert session["messages"][:session["prefix_len"]][0]["role"] == "system"
    assert any(message["content"].startswith(ai.SUMMARY_MARK)
               for message in session["messages"][session["prefix_len"]:])
