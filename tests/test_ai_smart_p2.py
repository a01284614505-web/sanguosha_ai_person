import asyncio
import json
import logging
import pytest

from game_engine.card_table import CARD_TABLE
from game_engine.game_logs import build_game_log
from tests.test_t1_behavior_ledger import scripted_responder, card
from test_ai_smart_p0 import make_engine


def test_notes_required_complete_and_diagnostics_do_not_block_actions(caplog):
    e = make_engine()
    ai, p = e.ai_decision, e.game_state.players[1]
    prompt = ai.build_decision_turn_message(p, [{"type": "end_phase"}])
    assert "notes 必填" in prompt and "每轮重新看证据" in prompt
    assert "本次需要判断的座位号：4、2、3" in prompt
    assert "notes 可省略" not in prompt
    with caplog.at_level(logging.WARNING):
        result = ai.parse_ai_response('{"action_index":0}', p, [{"type": "end_phase"}])
    assert result["action"]["type"] == "end_phase" and ai.last_failure[p.id] is None
    assert ai.notes_diagnostics[-1]["missing"] is True
    assert set(ai.notes_diagnostics[-1]["missing_seats"]) == {2, 3, 4}
    assert "本次笔记缺失" in caplog.text
    payload = {"action_index": 0, "notes": {
        "4": {"guess": "rebel", "conf": "高", "why": "杀主公"},
        "2": {"guess": "invalid", "conf": "高", "why": "x"},
        "oops": {"guess": "spy", "conf": "高", "why": "x"}}}
    ai.parse_ai_response(json.dumps(payload), p, [{"type": "end_phase"}])
    diagnostic = ai.notes_diagnostics[-1]
    assert diagnostic["missing"] is False and diagnostic["rejected"] == 2
    assert set(diagnostic["missing_seats"]) == {2, 3}
    assert e.notes.view(p.id)[0]["why"] == "杀主公"
    log = build_game_log(e, {}, include_thinking=False)
    assert len(log["notes_diagnostics"]) == 2


def test_evidence_table_has_public_counts_and_no_secret_hands_or_identity_inference():
    e = make_engine()
    e.ledger.record(1, 0, 2, "hostile", "杀")
    e.ledger.record(2, 0, 2, "hostile", "杀")
    e.ledger.record(2, 3, 2, "friendly", "仁德")
    e.game_state.players[0].hand.append(card("secret", "诸葛连弩"))
    text = e.ai_decision._build_evidence_block()
    assert "4号：对1号 杀×2" in text and "2号：对1号 仁德×1" in text
    assert "诸葛连弩" not in text and "反贼" not in text and "内奸" not in text
    assert "5号：暂无定向公开行为" in text


def test_response_and_choice_receive_current_own_notes_without_consuming_play_review(tmp_path):
    e = make_engine()
    p, other = e.game_state.players[1], e.game_state.players[3]
    p.ai_config["api_key"] = "p2-fake-key"
    e.ai_decision.cache_stats_path = str(tmp_path / "cache.jsonl")
    e.notes.update(p.id, {"4": {"guess": "rebel", "conf": "高", "why": "自己理由"}})
    e.notes.update(other.id, {"4": {"guess": "spy", "conf": "低", "why": "别人理由"}})
    e.notes.mark_review_all()
    captured = []
    class Gateway:
        async def call_ai(self, **kwargs):
            captured.append(kwargs["messages"][-1]["content"])
            return '{"option_indices":[0],"option_index":0}', {}
    e.ai_decision.gateway = Gateway()
    request = {"options": [{"label": "甲"}], "context": {"source": {"id": 2}, "target": {"id": 0}}}
    asyncio.run(e.ai_decision.make_response_decision(p, request))
    asyncio.run(e.ai_decision.make_choice_decision(p, request))
    assert all("自己理由" in text and "别人理由" not in text for text in captured)
    assert all("1号 选手2（主公）" in text and "4号 真人" in text for text in captured)
    assert "局势有变" in e.ai_decision.build_decision_turn_message(p, [{"type": "end_phase"}])


@pytest.mark.parametrize("trick_name", ["五谷丰登", "桃园结义"])
@pytest.mark.parametrize("layers", [1, 2, 3])
def test_beneficial_group_wuxie_polarity_and_target_are_correct(trick_name, layers):
    e = make_engine()
    src, a, target, b, c = e.game_state.players
    for p in e.game_state.players:
        p.hand.clear()
    responders = [a, b, c][:layers]
    for i, p in enumerate(responders):
        p.hand.append(card(f"wx{i}", "无懈可击", "club"))
    e.card_system.responder = scripted_responder({p.id: {"无懈可击"} for p in responders})
    assert CARD_TABLE[trick_name].group_benefit is True
    canceled = asyncio.run(e.card_system.ask_wuxie(card("trick", trick_name), src, [target]))
    assert canceled is (layers % 2 == 1)
    entries = e.ledger.entries
    assert len(entries) == layers
    for i, entry in enumerate(entries):
        assert entry.target_id == target.id
        assert entry.kind == ("hostile" if i % 2 == 0 else "protect")
        assert entry.weight == (0.5 if i % 2 == 0 else 1)
    assert all(not any(c.name == "无懈可击" for c in p.hand) for p in responders)
