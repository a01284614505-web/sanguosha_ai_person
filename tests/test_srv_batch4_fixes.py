"""批次 4 顺手修的三处：局后日志阵亡时间线、提示词里的中文身份、选择决策的降级原因。"""

import asyncio
import json

from game_engine import MainEngine
from game_engine.game_logs import build_game_log
from game_engine.state_manager import Card


def make_engine(api_key="offline-test-key"):
    engine = MainEngine({
        "player_name": "真人", "mode": "5人身份局",
        "ais": [{"name": f"AI{i}", "api_key": api_key} for i in range(1, 5)],
    })
    for player in engine.game_state.players:
        player.hand[:] = []
    return engine


def assign_identities(engine, identities):
    for player, identity in zip(engine.game_state.players, identities):
        player.identity = identity
        player.identity_revealed = identity == "lord"


# ---------------------------------------------------------------- 1. 阵亡进时间线

def test_death_event_enters_game_log_timeline_with_identity_and_killer():
    engine = make_engine(api_key="")
    assign_identities(engine, ["lord", "loyalist", "rebel", "rebel", "spy"])
    killer, victim = engine.game_state.players[1], engine.game_state.players[2]
    victim.hp = 1

    async def scenario():
        await engine.card_system.damage(killer, victim, 1)

    asyncio.run(scenario())
    assert not victim.alive
    record = build_game_log(engine, {"state": engine.serialize()}, include_thinking=False)
    deaths = [row for row in record["timeline"] if row["kind"] == "death"]
    assert len(deaths) == 1
    row = deaths[0]
    assert victim.name in row["text"] and "反贼" in row["text"] and killer.name in row["text"]
    assert row["player_id"] == victim.id and row["killer_id"] == killer.id
    assert row["identity"] == "rebel"
    # 序号与回合齐全，能和聊天、决策按先后穿插。
    assert isinstance(row["seq"], int) and row["round"] is not None


def test_death_event_is_not_broadcast_live_so_hidden_identity_games_do_not_leak():
    engine = make_engine(api_key="")
    assign_identities(engine, ["lord", "loyalist", "rebel", "rebel", "spy"])
    engine.hide_dead_identity = True
    seen = []

    async def collect(**data):
        seen.append(data)

    engine.on("event_notification", collect)
    victim = engine.game_state.players[2]
    victim.hp = 1

    async def scenario():
        await engine.card_system.damage(engine.game_state.players[1], victim, 1)

    asyncio.run(scenario())
    assert not victim.alive
    assert not any("反贼" in str(item.get("message", "")) for item in seen)
    assert any(item.get("event_kind") == "death" for item in engine.game_log)


def test_death_without_killer_still_recorded():
    engine = make_engine(api_key="")
    assign_identities(engine, ["lord", "loyalist", "rebel", "rebel", "spy"])
    victim = engine.game_state.players[3]
    engine.record_death(victim, None)
    record = build_game_log(engine, {"state": engine.serialize()}, include_thinking=False)
    row = next(item for item in record["timeline"] if item["kind"] == "death")
    assert "击杀者" not in row["text"] and "killer_id" not in row


# ---------------------------------------------------------------- 2. 提示词里的身份是中文

ENGLISH_CODES = ("lord", "loyalist", "rebel", "spy")


def test_l1_prompt_uses_chinese_identity_name():
    engine = make_engine()
    assign_identities(engine, ["lord", "loyalist", "rebel", "rebel", "spy"])
    ai = engine.ai_decision
    for player, expected in zip(engine.game_state.players[1:], ["忠臣", "反贼", "反贼", "内奸"]):
        text = ai.worldbook_manager.build_static_worldbook(player, engine.game_state)
        assert f"身份：{expected}" in text
        first_line = text.splitlines()[0]
        assert not any(code in first_line for code in ENGLISH_CODES)


def test_l2_situation_and_authoritative_block_hide_english_identity_codes():
    engine = make_engine()
    assign_identities(engine, ["lord", "loyalist", "rebel", "rebel", "spy"])
    viewer = engine.game_state.players[1]
    # 主公公开；再让一名反贼阵亡亮明，并给 viewer 一条英文码的认知笔记。
    engine.game_state.players[2].identity_revealed = True
    engine.notes.ensure(viewer.id)
    engine.notes._notes[viewer.id][engine.game_state.players[3].id] = {
        "guess": "spy", "conf": "中", "why": "测试"}
    ai = engine.ai_decision
    situation = ai.worldbook_manager.build_situation(viewer, engine.game_state, [])
    assert "主公" in situation and "反贼" in situation
    block = ai._authoritative_situation_block(viewer)
    assert '"identity":"主公"' in block
    assert '"guess":"内奸"' in block
    for code in ENGLISH_CODES:
        assert f'"{code}"' not in block
    # 内部数据不受影响：状态快照与局后日志保留英文码。
    from game_engine.public_situation import build_public_situation
    assert build_public_situation(engine)["players"][0]["identity"] == "lord"


def test_other_modes_have_chinese_identity_names():
    from game_engine.mode_registry import identity_name
    assert [identity_name(x) for x in ("team_a", "team_b", "landlord", "farmer")] == [
        "A队", "B队", "地主", "农民"]
    assert identity_name(None) == "未知"


# ---------------------------------------------------------------- 3. 降级原因

def hidden_choose_cards_request(victim):
    cards = [Card("h1", "杀", "spade", 7, "basic"), Card("h2", "闪", "heart", 2, "basic")]
    return {
        "kind": "choose_cards", "prompt": "【突袭】：选择一张手牌", "min_n": 1, "max_n": 1,
        "options": [{"label": "手牌"}, {"label": "手牌"}], "candidate_cards": cards,
        "hidden_indices": [0, 1], "cancelable": False, "context": {},
    }


def test_hidden_choose_cards_is_labelled_local_not_rules_no_provider():
    engine = make_engine()
    zhang = engine.game_state.players[1]
    calls = []

    async def fake_call(player, kind, content):
        calls.append(kind)
        return json.dumps({"reasoning": "x", "option_indices": [0]})

    engine.ai_decision._call_with_session = fake_call
    request = hidden_choose_cards_request(engine.game_state.players[2])

    async def scenario():
        indices = await engine._ai_choose_choice(zhang, request)
        await engine._emit_decision_trace(zhang, "choose_cards", 2, indices, "resolved")

    asyncio.run(scenario())
    assert calls == []          # 全暗置：问模型没有信息量，设计上本地随机
    row = engine.decision_log[-1]
    assert row["fallback_reason"] == "hidden_candidates_local_random"
    assert row["model"] is None


def test_visible_choose_cards_goes_through_model_and_has_no_fallback_reason():
    engine = make_engine()
    zhang = engine.game_state.players[1]
    calls = []

    async def fake_call(player, kind, content):
        calls.append(kind)
        engine.ai_decision.last_meta[player.id] = {"model": "test-model", "elapsed_ms": 1}
        return json.dumps({"reasoning": "x", "option_indices": [1]})

    engine.ai_decision._call_with_session = fake_call
    request = hidden_choose_cards_request(engine.game_state.players[2])
    request["hidden_indices"] = []

    async def scenario():
        indices = await engine._ai_choose_choice(zhang, request)
        await engine._emit_decision_trace(zhang, "choose_cards", 2, indices, "resolved")
        return indices

    assert asyncio.run(scenario()) == [1]
    assert calls == ["choice"]
    row = engine.decision_log[-1]
    assert row["fallback_reason"] is None and row["model"] == "test-model"


def test_stale_local_reason_does_not_leak_into_next_model_decision_and_no_key_stays_no_provider():
    engine = make_engine()
    zhang = engine.game_state.players[1]

    async def fake_call(player, kind, content):
        engine.ai_decision.last_meta[player.id] = {"model": "m"}
        return json.dumps({"reasoning": "x", "option_indices": [0]})

    engine.ai_decision._call_with_session = fake_call
    hidden = hidden_choose_cards_request(engine.game_state.players[2])
    visible = dict(hidden, hidden_indices=[])

    async def scenario():
        await engine._ai_choose_choice(zhang, hidden)
        await engine._ai_choose_choice(zhang, visible)
        await engine._emit_decision_trace(zhang, "choose_cards", 2, [0], "resolved")

    asyncio.run(scenario())
    assert engine.decision_log[-1]["fallback_reason"] is None

    keyless = make_engine(api_key="")
    player = keyless.game_state.players[1]

    async def keyless_scenario():
        await keyless._ai_choose_choice(player, hidden_choose_cards_request(None))
        await keyless._emit_decision_trace(player, "choose_cards", 2, [0], "resolved")

    asyncio.run(keyless_scenario())
    assert keyless.decision_log[-1]["fallback_reason"] == "rules_no_provider"


def test_choice_ai_disabled_setting_is_labelled_as_such():
    engine = make_engine()
    engine.game_config["global_settings"] = {"choice_ai_enabled": False}
    zhang = engine.game_state.players[1]
    request = hidden_choose_cards_request(None)
    request["hidden_indices"] = []

    async def scenario():
        await engine._ai_choose_choice(zhang, request)
        await engine._emit_decision_trace(zhang, "choose_cards", 2, [0], "resolved")

    asyncio.run(scenario())
    assert engine.decision_log[-1]["fallback_reason"] == "choice_ai_disabled"
