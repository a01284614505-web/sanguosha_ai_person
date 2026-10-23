"""Compare DSL executions with existing native handlers for complete, matching skills."""
import asyncio
from unittest.mock import AsyncMock

from game_engine import MainEngine
from game_engine.skill_dsl import compile_skill
from game_engine.skills_wu import WuSkillHandler
from game_engine.state_manager import Card, Phase


def game():
    return MainEngine({"mode": "5人身份局", "player_name": "P0", "ais": [{"name": f"P{i}"} for i in range(1, 5)]})


def blank(engine):
    for player in engine.game_state.players:
        player.hand.clear(); player.equipment.clear()
    engine.game_state.deck[:] = [Card(f"parity_{i}", "桃" if i % 2 else "杀", "heart", i + 1, "basic") for i in range(5)]


def install_dsl(engine, owner, name, program):
    owner.hero = {"id": "parity_custom", "name": "等价测试将", "faction": "吴", "max_hp": owner.max_hp,
                  "skills": [{"name": name, "description": "", "implementation_status": "active", "dsl": program}]}
    engine.skill_manager.bind_engine(engine)


def snapshot(engine, owner):
    return {"hand": [c.id for c in owner.hand], "deck": [c.id for c in engine.game_state.deck],
            "moves": [(m.card_id, m.from_zone, m.to_zone, m.to_owner) for m in engine.game_state.card_move_events],
            "activations": [(e["skill_name"], e["event"]) for e in engine.skill_manager.activation_log]}


def test_yingzi_dsl_matches_native_draw_and_skip_default_behavior():
    program = {"version": 1, "trigger": "phase_start", "condition": {"op": "eq", "path": "event.phase", "value": "draw"},
               "skip_default": True, "modifiers": [{"stat": "hand_limit", "op": "max", "value": {"path": "owner.max_hp"}}],
               "effects": [{"type": "draw_cards", "target": "owner", "count": 3, "reason": "英姿"}, {"type": "announce"}]}
    native = game(); blank(native); p0 = native.game_state.players[0]
    native.game_state.current_phase = Phase.DRAW
    handler = WuSkillHandler(native.skill_manager); handler.has = lambda p, skill: skill == "英姿"
    native_result = asyncio.run(handler.before_phase(p0, Phase.DRAW))

    dsl = game(); blank(dsl); p1 = dsl.game_state.players[0]
    dsl.game_state.current_phase = Phase.DRAW
    install_dsl(dsl, p1, "英姿", program)
    native.skill_manager.handlers[2].has = lambda p, skill: skill == "英姿"
    dsl_skipped = asyncio.run(dsl.skill_manager._run_dsl("phase_start", [p1], {"player": p1, "phase": "draw"}))
    assert native_result == {"skip_default": True}
    assert dsl_skipped is True
    assert snapshot(native, p0) == snapshot(dsl, p1)
    assert native.skill_manager.hand_limit(p0, p0.hp) == dsl.skill_manager.hand_limit(p1, p1.hp) == p0.max_hp


def test_biyue_dsl_matches_native_prompt_branch_draw_and_cost_decline():
    program = {"version": 1, "trigger": "phase_end", "condition": {"op": "eq", "path": "event.phase", "value": "end"},
               "cost": [{"interaction": "ask_confirm", "prompt": "是否发动【闭月】摸牌？"}],
               "effects": [
                   {"type": "draw_cards", "target": "owner", "count": 2, "reason": "闭月", "when": {"op": "eq", "path": "event.hand_count_before", "value": 0}},
                   {"type": "draw_cards", "target": "owner", "count": 1, "reason": "闭月", "when": {"op": "gt", "path": "event.hand_count_before", "value": 0}},
                   {"type": "announce"}]}
    for has_hand, accepted in ((False, True), (True, True), (True, False)):
        native = game(); blank(native); p0 = native.game_state.players[0]
        native.game_state.current_phase = Phase.END
        if has_hand: p0.hand.append(Card("parity_existing", "闪", "spade", 5, "basic"))
        # Native 闭月 lives in the Qun handler.
        from game_engine.skills_qun import QunSkillHandler
        reference = QunSkillHandler(native.skill_manager)
        reference.has = lambda p, skill: skill == "闭月"
        reference.manager.ask_confirm = AsyncMock(return_value=accepted)
        asyncio.run(reference.after_phase(p0, Phase.END))

        dsl = game(); blank(dsl); p1 = dsl.game_state.players[0]
        dsl.game_state.current_phase = Phase.END
        if has_hand: p1.hand.append(Card("parity_existing", "闪", "spade", 5, "basic"))
        install_dsl(dsl, p1, "闭月", program)
        dsl.skill_manager.ask_confirm = AsyncMock(return_value=accepted)
        asyncio.run(dsl.skill_manager._run_dsl("phase_end", [p1], {"player": p1, "phase": "end"}))
        assert snapshot(native, p0) == snapshot(dsl, p1)


def test_keji_dsl_matches_native_prompt_skip_and_sha_condition():
    program = {"version": 1, "trigger": "phase_start", "condition": {"op": "all", "args": [
        {"op": "eq", "path": "event.phase", "value": "discard"},
        {"op": "eq", "path": "event.sha_used_this_turn", "value": False},
    ]}, "cost": [{"interaction": "ask_confirm", "prompt": "是否发动【克己】跳过弃牌阶段？"}],
        "skip_default": True, "effects": [{"type": "announce", "text": "发动【克己】跳过弃牌阶段"}]}
    for used_sha, accepted in ((False, True), (False, False), (True, True)):
        native = game(); blank(native); p0 = native.game_state.players[0]
        p0.flags["sha_used_this_turn"] = used_sha
        reference = WuSkillHandler(native.skill_manager); reference.has = lambda p, s: s == "克己"
        reference.manager.ask_confirm = AsyncMock(return_value=accepted)
        native_result = asyncio.run(reference.before_phase(p0, Phase.DISCARD))

        dsl = game(); blank(dsl); p1 = dsl.game_state.players[0]
        p1.flags["sha_used_this_turn"] = used_sha
        install_dsl(dsl, p1, "克己", program)
        dsl.skill_manager.ask_confirm = AsyncMock(return_value=accepted)
        dsl_result = asyncio.run(dsl.skill_manager._run_dsl("phase_start", [p1], {"phase": "discard"}))
        assert bool(native_result and native_result.get("skip_default")) == dsl_result
        assert snapshot(native, p0) == snapshot(dsl, p1)


def test_tishen_dsl_matches_native_limited_recover_draw_and_decline():
    program = {"version": 1, "trigger": "phase_start", "condition": {"op": "all", "args": [
        {"op": "eq", "path": "event.phase", "value": "prepare"},
        {"op": "lt", "path": "owner.hp", "value": {"path": "owner.max_hp"}},
    ]}, "cost": [{"interaction": "ask_confirm", "prompt": "是否发动限定技【替身】？"}],
        "usage": {"scope": "game", "charges": 1},
        "effects": [{"type": "recover", "target": "owner", "amount": {"path": "event.missing_hp"}, "reason": "替身"},
                    {"type": "draw_cards", "target": "owner", "count": {"path": "event.missing_hp"}, "reason": "替身"},
                    {"type": "announce", "text": "发动【替身】"}]}
    for accepted in (True, False):
        native = game(); blank(native); p0 = native.game_state.players[0]
        p0.hp = max(1, p0.max_hp - 2)
        install_dsl(native, p0, "替身", program)
        reference = __import__("game_engine.skills_shu", fromlist=["ShuSkillHandler"]).ShuSkillHandler(native.skill_manager)
        reference.has = lambda p, s: s == "替身"
        reference.manager.ask_confirm = AsyncMock(return_value=accepted)
        asyncio.run(reference.before_phase(p0, Phase.PREPARE))

        dsl = game(); blank(dsl); p1 = dsl.game_state.players[0]
        p1.hp = max(1, p1.max_hp - 2)
        dsl.game_state.current_player = p1; dsl.game_state.current_phase = Phase.PREPARE
        install_dsl(dsl, p1, "替身", program)
        dsl.skill_manager.ask_confirm = AsyncMock(return_value=accepted)
        asyncio.run(dsl.skill_manager._run_dsl("phase_start", [p1], {"phase": "prepare"}))
        assert (p0.hp, snapshot(native, p0)) == (p1.hp, snapshot(dsl, p1))
        native_instance = native.skill_manager._skill_instance(p0, "替身")
        dsl_instance = dsl.skill_manager._skill_instance(p1, "替身")
        assert (native_instance.charges if native_instance else 1) == (dsl_instance.charges if dsl_instance else 1)
        if accepted:
            before = (p1.hp, len(p1.hand), dsl_instance.charges)
            asyncio.run(dsl.skill_manager._run_dsl("phase_start", [p1], {"phase": "prepare"}))
            assert (p1.hp, len(p1.hand), dsl_instance.charges) == before


def test_lianying_dsl_matches_native_empty_hand_selection_and_draws():
    program = {"version": 1, "trigger": "cards_lost", "condition": {"op": "eq", "path": "event.hand_empty", "value": True},
        "cost": [{"interaction": "ask_confirm", "prompt": "是否发动【连营】令角色摸牌？"}],
        "targets": {"selector": "chosen_players", "candidates": "all_alive", "min": 1,
                    "max": {"path": "event.count"}, "prompt": "选择因【连营】摸牌的角色"},
        "effects": [{"type": "draw_cards", "target": "targets", "count": 1, "reason": "连营"},
                    {"type": "announce", "text": "发动【连营】"}]}
    native = game(); blank(native); p0 = native.game_state.players[0]
    lost0 = Card("lost0", "闪", "heart", 3, "basic")
    p0.hand.append(lost0); p0.hand.remove(lost0)
    reference = WuSkillHandler(native.skill_manager); reference.has = lambda p, s: s == "连营"
    selected0 = [p0]
    reference.manager.ask_confirm = AsyncMock(return_value=True)
    reference.manager.ask_choose_players = AsyncMock(return_value=selected0)
    asyncio.run(reference.on_cards_lost(p0, [lost0]))

    dsl = game(); blank(dsl); p1 = dsl.game_state.players[0]
    lost1 = Card("lost0", "闪", "heart", 3, "basic")
    p1.hand.append(lost1); p1.hand.remove(lost1)
    install_dsl(dsl, p1, "连营", program)
    selected1 = [p1]
    dsl.skill_manager.ask_confirm = AsyncMock(return_value=True)
    dsl.skill_manager.ask_choose_players = AsyncMock(return_value=selected1)
    asyncio.run(dsl.skill_manager.on_cards_lost(p1, [lost1]))
    assert [([c.id for c in p.hand]) for p in native.game_state.players] == [([c.id for c in p.hand]) for p in dsl.game_state.players]
    assert [c.id for c in native.game_state.deck] == [c.id for c in dsl.game_state.deck]
