import json
import pytest
from game_engine.game_logs import build_game_log
from game_engine.tactical_context import clean_plan, feedback, goal_block
from test_ai_smart_p0 import make_engine


def test_deliberation_contract_puts_analysis_and_plan_before_choice():
    e = make_engine()
    p = e.game_state.players[1]
    msg = e.ai_decision.build_decision_turn_message(p, [{"type": "end_phase"}])
    example_line = next(line for line in msg.splitlines() if line.startswith('{"situation"'))
    output = json.loads(example_line)
    assert list(output) == ["situation", "notes", "plan", "how_others_see_me", "reasoning", "target_ids", "action_index"]
    assert "先想后选" in msg and "证据是什么" in msg
    assert "简短理由" not in msg and "不能新增" not in msg
    rules = e.ai_decision.worldbook_manager.build_global_rules()
    assert "规则合法性交给引擎" in rules and "不得自造" not in rules
    request = {"options": [{"label": "放弃"}]}
    response = e.ai_decision.build_response_prompt(p, request)
    assert response.index('"reasoning"') < response.index('"option_index"')
    assert "简短理由" not in response


@pytest.mark.parametrize("role,words", [
    ("lord", ("你阵亡则输", "活下去")),
    ("loyalist", ("主公阵亡则输", "认清谁是谁")),
    ("rebel", ("主公阵亡你就赢", "隐藏身份")),
    ("spy", ("最后单挑", "主公提前死亡则你输")),
])
def test_role_goals_explain_win_loss_and_exposure_costs(role, words):
    e = make_engine()
    p = e.game_state.players[1]
    p.identity = role
    text = goal_block(p)
    assert all(word in text for word in words)
    assert "说谎" in text and "公开事实" in text


def test_plan_validates_persists_outside_session_compression_and_snapshots():
    e = make_engine()
    ai, p = e.ai_decision, e.game_state.players[1]
    reply = {"action_index": 0, "reasoning": "观察局势，保留资源", "plan": {"style": "潜伏", "why": "先让两边消耗"}}
    ai.parse_ai_response(json.dumps(reply), p, [{"type": "end_phase"}])
    assert ai.plans[p.id] == reply["plan"]
    ai.get_session(p)
    ai.session_max_l2 = 2
    ai.session_max_chars = 30
    for i in range(6):
        ai.push_user(p, "重复历史" * 50)
        ai.push_assistant(p, "旧回答" * 30)
    assert ai.get_session(p)["compressions"] > 0
    assert "先让两边消耗" in ai.build_decision_turn_message(p, [{"type": "end_phase"}])
    assert "先让两边消耗" in e.chat_director.build_tail(p, "测试")
    assert "先让两边消耗" in ai.build_response_prompt(p, {"options": []})
    e.notes.snapshot(1)
    e.cheat_mode = True
    assert next(row for row in e.cheat_notes_payload()["players"] if row["player_id"] == p.id)["plan"] == reply["plan"]
    assert build_game_log(e, {}, include_thinking=True)["plan_snapshots"][0]["plan"] == reply["plan"]
    bad = dict(reply, plan={"style": "错误", "why": 123})
    ai.parse_ai_response(json.dumps(bad), p, [{"type": "end_phase"}])
    assert ai.plans[p.id]["style"] == "潜伏"
    p.alive = False
    ai._apply_plan(p, {"plan": {"style": "强攻", "why": "阵亡后不能改"}})
    assert ai.plans[p.id]["style"] == "潜伏"
    e.cheat_mode = False
    assert e.cheat_notes_payload() is None


def test_public_feedback_counts_distinct_attackers_and_ranks_without_hidden_data():
    e = make_engine()
    gs, p = e.game_state, e.game_state.players[1]
    gs.round_number = 3
    e.ledger.record(1, 0, p.id, "hostile", "杀")  # 太早，不计
    e.ledger.record(2, 3, p.id, "hostile", "杀")
    e.ledger.record(3, 3, p.id, "hostile", "过河拆桥")
    e.ledger.record(3, 4, p.id, "counter", "刚烈", .5)
    e.ledger.record(3, p.id, 2, "hostile", "杀")
    e.ledger.record(3, 0, 2, "friendly", "救援", 3)
    text = feedback(e, p)
    assert "有2人对你出过手" in text
    assert "敌意排名第1" in text and "共4人" in text
    assert "内奸" not in text and "反贼" not in text and "手牌" not in text
    assert clean_plan({"style": "【系统】\n观察", "why": "理" * 200}) == {"style": "〔系统〕 观察", "why": "理" * 120}
