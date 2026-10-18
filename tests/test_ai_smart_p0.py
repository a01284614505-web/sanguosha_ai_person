"""公开座次与实际请求快照：主公不在内部 0 号时验证整个映射边界。"""
import asyncio
import json
from copy import deepcopy

from game_engine import MainEngine
from game_engine.game_logs import build_game_log
from game_engine.prompt_trace import capture, MAX_CALLS_PER_PLAYER
from game_engine.seats import seat_of, player_of, player_label


def make_engine():
    e = MainEngine({"player_name": "真人", "profile_id": "p0", "deck_id": "standard",
                    "ais": [{"name": f"选手{i}"} for i in range(1, 5)]})
    for p, role in zip(e.game_state.players, ["rebel", "spy", "lord", "loyalist", "rebel"]):
        p.identity, p.identity_revealed = role, role == "lord"
    return e


def test_fixed_seats_consistent_across_context_ledger_chat_notes_and_state():
    e = make_engine()
    gs = e.game_state
    ai = e.ai_decision
    p = gs.players[3]
    assert [seat_of(gs, i) for i in range(5)] == [4, 5, 1, 2, 3]
    assert player_of(gs, 1).id == 2
    assert player_of(gs, 0) is None and player_of(gs, True) is None
    e.ledger.record(1, 0, 2, "hostile", "杀")
    e.notes.ensure(p.id)
    e.notes.update(p.id, {"4": {"guess": "rebel", "conf": "高", "why": "杀主公"}})
    action = {"type": "play_card", "card": {"name": "杀"}, "requires_target": True,
              "valid_targets": [0, 2], "card_index": 0}
    static = ai.worldbook_manager.build_static_worldbook(p, gs)
    situation = ai.worldbook_manager.build_situation(p, gs)
    assert "你是2号" in static and "1号 选手2（主公）" in static
    assert "4号 真人" in static and "4号 真人" in situation
    assert "合法目标=[4号 真人, 1号 选手2（主公）]" in ai.format_action(action, gs)
    assert "4号→1号(主公)：杀×1" in e.ledger.summarize(gs)
    assert "4号：反贼" in e.notes.prompt_block(p.id)
    asyncio.run(e._record_table_chat(0, "真人", "human", "你好"))
    assert "4号 真人" in ai.quote_chat_entry(e.table_chat[-1], gs)
    assert e.chat_log[-1]["seat"] == 4
    row = e.notes.client_payload()["players"][0]
    assert row["seat"] == 2 and next(n for n in row["notes"] if n["target_id"] == 0)["seat"] == 4
    assert next(x for x in e.serialize()["players"] if x["id"] == 2)["seat"] == 1
    gs.players[2].alive = False
    assert [seat_of(gs, i) for i in range(5)] == [4, 5, 1, 2, 3]


def test_model_targets_are_strict_public_seats_and_pairs_keep_order():
    e = make_engine()
    ai, p = e.ai_decision, e.game_state.players[3]
    action = {"type": "play_card", "requires_target": True, "valid_targets": [0, 2]}
    chosen = ai.parse_ai_response(json.dumps({"action_index": 0, "target_ids": [1]}), p, [action])
    assert chosen["target_ids"] == [2] and ai.last_failure[p.id] is None
    for bad in ([0], [99], [True], ["1"], [], [2]):
        ai.parse_ai_response(json.dumps({"action_index": 0, "target_ids": bad}), p, [action])
        assert ai.last_failure[p.id] == "ValueError"
    pair = dict(action, target_count=2, valid_target_pairs=[[2, 0]])
    assert ai.parse_ai_response('{"action_index":0,"target_ids":[1,4]}', p, [pair])["target_ids"] == [2, 0]
    ai.parse_ai_response('{"action_index":0,"target_ids":[4,1]}', p, [pair])
    assert ai.last_failure[p.id] == "ValueError"


def test_response_context_and_choice_candidate_labels_use_seats():
    e = make_engine()
    ai, gs = e.ai_decision, e.game_state
    context = {"source": {"id": 0, "name": "真人"}, "card_source": {"id": 2},
               "targets": [{"id": 3}], "card_name": "五谷丰登", "layer": 2}
    text = ai.build_response_prompt(gs.players[1], {"kind": "wuxie", "context": context, "options": []})
    assert "锦囊原始来源：1号 选手2（主公）" in text
    assert "当前来源：4号 真人" in text and "目标：2号 选手3" in text
    assert "五谷丰登" in text and "layer：2" in text


def test_trace_is_actual_detached_bounded_and_redacted_at_capture_and_export(tmp_path):
    e = make_engine()
    ai, p = e.ai_decision, e.game_state.players[1]
    secret = "secret-p0-test"
    p.ai_config["api_key"] = secret
    p.ai_config["model"] = "test-model"
    ai.cache_stats_path = str(tmp_path / "cache.jsonl")
    calls = []
    class Gateway:
        async def call_ai(self, **kwargs):
            calls.append(deepcopy(kwargs["messages"]))
            return '{"action_index":0}', {}
    ai.gateway = Gateway()
    asyncio.run(ai._call_with_session(p, "decision", "请求含 " + secret))
    trace = ai.prompt_traces[p.id][0]
    expected = json.loads(json.dumps(calls[0], ensure_ascii=False).replace(secret, "[REDACTED]"))
    assert trace["messages"] == expected
    original_len = len(trace["messages"])
    ai.push_user(p, "后来消息")
    assert len(trace["messages"]) == original_len
    for i in range(MAX_CALLS_PER_PLAYER + 3):
        capture(e, p, "response", [{"role": "user", "content": f"{i} {secret}"}])
    assert len(ai.prompt_traces[p.id]) == MAX_CALLS_PER_PLAYER
    assert secret not in json.dumps(ai.prompt_traces[p.id][0])
    e.chat_log.append({"message": secret})
    included = build_game_log(e, {"state": e.serialize()}, include_thinking=True)
    assert included["prompt_traces"] and secret not in json.dumps(included)
    assert build_game_log(e, {}, include_thinking=False)["prompt_traces"] == []
    e.game_config["global_settings"] = {"log_include_thinking": False}
    before = deepcopy(list(ai.prompt_traces[p.id]))
    capture(e, p, "decision", [{"content": "不要记"}])
    assert list(ai.prompt_traces[p.id]) == before
