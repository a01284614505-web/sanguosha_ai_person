import asyncio
import json
import random

from game_engine.strategy_library import load_examples, select_examples, examples_prompt
from test_ai_smart_p0 import make_engine


def test_editable_role_libraries_are_valid_and_sampled_in_small_varying_sets():
    e = make_engine()
    p = e.game_state.players[1]
    for role in ("lord", "loyalist", "rebel", "spy"):
        rows = load_examples(role)
        assert len(rows) >= 5 and len({row["id"] for row in rows}) == len(rows)
        p.identity = role
        observed = set()
        rng = random.Random(42)
        for _ in range(10):
            selected = select_examples(e, p, rng)
            assert 3 <= len(selected) <= 4
            assert all(row["id"].startswith(role + "_") for row in selected)
            assert len({row["id"] for row in selected}) == len(selected)
            observed.add(tuple(row["id"] for row in selected))
        assert len(observed) > 1
    assert load_examples("../api_key") == []


def test_public_conditions_exclude_inapplicable_advice_without_using_hidden_roles():
    e = make_engine()
    p = e.game_state.players[1]
    e.game_state.round_number = 4
    selected_sets = [select_examples(e, p, random.Random(i)) for i in range(10)]
    assert all(not row["when"] for selection in selected_sets for row in selection)
    # spy 的残血与单挑示例均不应在五人满血场合出现
    text = examples_prompt(selected_sets[0])
    assert "不是规则或限制" in text and "完全可以想出别的打法" in text
    assert "别人通常怎么骗人" in text and "有没有更好的做法" in text


def test_real_two_request_order_initial_thought_has_no_examples_and_only_final_choice_is_applied(tmp_path):
    e = make_engine()
    p = e.game_state.players[1]
    ai = e.ai_decision
    p.ai_config["api_key"] = "fake-p4-key"
    ai.cache_stats_path = str(tmp_path / "cache.jsonl")
    calls = []
    class Gateway:
        async def call_ai(self, **kwargs):
            calls.append(json.loads(json.dumps(kwargs["messages"])))
            if len(calls) == 1:
                assert not ai.plans
                return json.dumps({"situation": "先独立判断", "plan": {"style": "潜伏", "why": "自己的想法"},
                                   "action_index": 1}, ensure_ascii=False), {"prompt_tokens": 10}
            assert not ai.plans, "草稿尚未提交"  # 即使草稿擅自选操作也不能提前执行/落库
            return json.dumps({"plan": {"style": "平衡", "why": "比较建议后改进"}, "reasoning": "最终比较",
                               "target_ids": [], "action_index": 0}), {"prompt_tokens": 12}
    ai.gateway = Gateway()
    actions = [{"type": "end_phase"}, {"type": "play_card", "card": {"name": "杀"}, "requires_target": True,
                                         "valid_targets": [2]}]
    result = asyncio.run(ai.make_decision(p, actions))
    assert len(calls) == 2 and result["action"]["type"] == "end_phase"
    first, second = calls[0][-1]["content"], calls[1][-1]["content"]
    assert "独立判断阶段" in first and "老玩家经验示例】" not in first
    output = json.loads(next(line for line in first.splitlines() if line.startswith('{"situation"')))
    assert "action_index" not in output and "target_ids" not in output
    assert "老玩家经验示例】" in second and "有没有更好的做法" in second
    assert any("先独立判断" in message["content"] for message in calls[1] if message["role"] == "assistant")
    assert ai.plans[p.id]["style"] == "平衡"
    assert e.usage_stats[p.id]["decision"]["calls"] == 2
    assert len(ai.prompt_traces[p.id]) == 2
    assert not e.table_chat


def test_single_option_or_rule_ai_skips_extra_deliberation_and_failure_has_no_retry_loop(tmp_path):
    e = make_engine()
    p, ai = e.game_state.players[1], e.ai_decision
    p.ai_config["api_key"] = "fake-p4-key"
    ai.cache_stats_path = str(tmp_path / "cache.jsonl")
    calls = []
    class Gateway:
        async def call_ai(self, **kwargs):
            calls.append(kwargs)
            return '{"action_index":0}', {}
    ai.gateway = Gateway()
    asyncio.run(ai.make_decision(p, [{"type": "end_phase"}]))
    assert len(calls) == 1
    p.ai_config["api_key"] = ""
    asyncio.run(ai.make_decision(p, [{"type": "end_phase"}, {"type": "end_phase"}]))
    assert len(calls) == 1
    p.ai_config["api_key"] = "fake-p4-key"
    class Failing:
        async def call_ai(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 2:
                return '{"plan":{"style":"草稿","why":"不能提交"}}', {}
            raise TimeoutError()
    ai.gateway = Failing()
    result = asyncio.run(ai.make_decision(p, [{"type": "end_phase"}, {"type": "end_phase"}]))
    assert len(calls) == 3 and result["action"]["type"] == "end_phase"
    assert not ai.plans and ai.last_failure[p.id] == "TimeoutError"
