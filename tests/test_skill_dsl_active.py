import asyncio
from unittest.mock import AsyncMock

import pytest

from game_engine import MainEngine
from game_engine.state_manager import Card, Phase


def test_active_dsl_action_with_chosen_players_appears_and_executes():
    engine = MainEngine({"mode": "5人身份局", "player_name": "P0", "ais": [{"name": f"P{i}"} for i in range(1, 5)]})
    owner, target = engine.game_state.players[:2]
    owner.hero = {"id": "custom_active", "name": "主动技能测试", "faction": "吴", "max_hp": owner.max_hp,
                  "skills": [{"name": "群体摸牌", "implementation_status": "active", "dsl": {
                      "version": 1, "trigger": "play_action", "condition": {"op": "gt", "path": "owner.hp", "value": 0},
                      "targets": {"selector": "chosen_players", "candidates": "all_alive", "min": 1, "max": 1},
                      "effects": [{"type": "draw_cards", "target": "targets", "count": 1, "reason": "测试"}],
                  }}]}
    engine.skill_manager.bind_engine(engine)
    engine.game_state.current_player = owner
    engine.game_state.current_phase = Phase.PLAY
    engine.game_state.deck.clear()
    engine.game_state.deck[:] = [Card("top", "桃", "heart", 1, "basic")]
    engine.ask_choose_players = AsyncMock(return_value=[target])
    before_count = len(target.hand)

    actions = engine.skill_manager.get_actions(owner)
    action = next(a for a in actions if a.get("skill_name") == "群体摸牌")
    assert action["requires_target"] is False
    assert asyncio.run(engine.skill_manager.execute(owner, action, [])) is True
    assert len(target.hand) == before_count + 1


def test_active_dsl_action_condition_and_usage_hide_unavailable_action():
    engine = MainEngine({"mode": "5人身份局", "player_name": "P0", "ais": [{"name": f"P{i}"} for i in range(1, 5)]})
    owner = engine.game_state.players[0]
    owner.hero = {"id": "custom_gate", "name": "主动技能测试", "faction": "吴", "max_hp": owner.max_hp,
                  "skills": [{"name": "限次技能", "implementation_status": "active", "dsl": {
                      "version": 1, "trigger": "play_action", "condition": {"op": "lt", "path": "owner.hp", "value": 0},
                      "usage": {"scope": "game", "limit": 1},
                      "effects": [{"type": "announce"}],
                  }}]}
    engine.skill_manager.bind_engine(engine)
    engine.game_state.current_player = owner
    engine.game_state.current_phase = Phase.PLAY
    assert all(a.get("skill_name") != "限次技能" for a in engine.skill_manager.get_actions(owner))
    owner.hp = -1
    assert any(a.get("skill_name") == "限次技能" for a in engine.skill_manager.get_actions(owner))


def test_huangtian_delegated_action_requires_lord_and_moves_donor_card():
    from pathlib import Path
    import json

    engine = MainEngine({"mode": "5人身份局", "player_name": "P0", "ais": [{"name": f"P{i}"} for i in range(1, 5)]})
    lord, donor = engine.game_state.players[:2]
    lord.identity = "lord"
    lord.hero = {"id": "custom_huangtian_lord", "name": "黄天主", "faction": "群", "max_hp": lord.max_hp,
                 "skills": [{"name": "黄天", "implementation_status": "active",
                             "dsl": next(item["dsl"] for item in json.loads((Path(__file__).resolve().parents[1] / "data" / "skill_dsl_coverage.json").read_text(encoding="utf-8"))["definitions"] if item["skill"] == "黄天")}]} 
    donor.hero = {"id": "custom_huangtian_donor", "name": "群捐赠者", "faction": "群", "max_hp": donor.max_hp, "skills": []}
    engine.skill_manager.bind_engine(engine)
    engine.game_state.current_player = donor
    engine.game_state.current_phase = Phase.PLAY
    card = Card("tribute", "杀", "spade", 7, "basic")
    donor.hand.append(card)
    engine.skill_manager.ask_choose_cards = AsyncMock(return_value=[card])

    action = next(a for a in engine.skill_manager.get_actions(donor) if a.get("skill_name") == "黄天")
    assert action["dsl_owner_id"] == lord.id
    assert asyncio.run(engine.skill_manager.execute(donor, action, [])) is True
    assert card not in donor.hand and card in lord.hand

    lord.identity = "rebel"
    assert all(a.get("skill_name") != "黄天" for a in engine.skill_manager.get_actions(donor))


def test_kurou_cost_discard_and_hp_loss_are_executable_without_python_escape():
    from game_engine.skills_wu import WuSkillHandler

    program = {"version": 1, "trigger": "play_action", "usage": {"scope": "current_turn", "limit": 1},
               "cost": [{"interaction": "ask_choose_cards", "min": 1, "max": 1, "zone": "hand"}],
               "effects": [{"type": "announce", "text": "发动【苦肉】"},
                           {"type": "discard_card", "reason": "苦肉"},
                           {"type": "lose_hp", "target": "owner", "amount": 1, "reason": "苦肉"}]}
    engine = MainEngine({"mode": "5人身份局", "player_name": "P0", "ais": [{"name": f"P{i}"} for i in range(1, 5)]})
    owner = engine.game_state.players[0]
    owner.hero = {"id": "custom_kurou", "name": "苦肉测试", "faction": "吴", "max_hp": owner.max_hp,
                  "skills": [{"name": "苦肉测试技", "implementation_status": "active", "dsl": program}]}
    engine.skill_manager.bind_engine(engine)
    engine.game_state.current_player = owner
    engine.game_state.current_phase = Phase.PLAY
    engine.game_state.deck.clear()
    card = owner.hand[0]
    engine.ask_choose_cards = AsyncMock(return_value=[card])
    actions = engine.skill_manager.get_actions(owner)
    action = next(a for a in actions if a.get("skill_name") == "苦肉测试技")
    hp_before = owner.hp
    assert asyncio.run(engine.skill_manager.execute(owner, action, [])) is True
    assert owner.hp == hp_before - 1
    assert card not in owner.hand
    assert any(m.card_id == card.id and m.to_zone == "discard" for m in engine.game_state.card_move_events)


def test_active_dsl_static_modifiers_apply_distance_sha_limit_and_response_count():
    engine = MainEngine({"mode": "5人身份局", "player_name": "P0", "ais": [{"name": f"P{i}"} for i in range(1, 5)]})
    owner, target = engine.game_state.players[:2]
    owner.hero = {"id": "custom_modifiers", "name": "修饰器测试", "faction": "吴", "max_hp": owner.max_hp,
                  "skills": [
                      {"name": "减距离", "implementation_status": "active", "dsl": {"version": 1, "trigger": "turn_start", "modifiers": [{"stat": "distance", "op": "subtract", "value": 1}]}},
                      {"name": "额外杀次数", "implementation_status": "active", "dsl": {"version": 1, "trigger": "turn_start", "modifiers": [{"stat": "max_sha", "op": "max", "value": 10}]}},
                      {"name": "双闪", "implementation_status": "active", "dsl": {"version": 1, "trigger": "turn_start", "modifiers": [{"stat": "response_count", "op": "max", "value": 2}]}},
                      {"name": "空城保护", "implementation_status": "active", "dsl": {"version": 1, "trigger": "turn_start", "modifiers": [{"stat": "target_protection", "op": "deny", "value": 0, "when": {"op": "all", "args": [{"op": "eq", "path": "owner.hand_count", "value": 0}, {"op": "in", "path": "event.card_name", "values": ["杀", "决斗"]}]}}]}},
                  ]}
    engine.skill_manager.bind_engine(engine)
    engine.game_state.current_player = owner
    asyncio.run(engine.skill_manager.on_turn_start(owner))
    assert owner.max_sha == 10
    assert engine.skill_manager.modify_distance(owner, target, 3) == 2
    event = {"shanRequired": 1}
    asyncio.run(engine.skill_manager.before_sha(owner, target, Card("sha", "杀", "spade", 7, "basic"), event))
    assert event["shanRequired"] == 2
    assert engine.skill_manager.required_response_count(owner, "杀") == 2
    owner.hand.clear()
    assert engine.skill_manager.target_error(target, owner, "杀") is not None
    assert engine.skill_manager.target_error(target, owner, "桃") is None


def test_dynamic_faction_count_modifier_and_card_damage_color_event_execute():
    engine = MainEngine({"mode": "5人身份局", "player_name": "P0", "ais": [{"name": f"P{i}"} for i in range(1, 5)]})
    owner, ally, source = engine.game_state.players[:3]
    owner.identity = "lord"
    owner.hero = {"id": "custom_lord", "name": "血裔测试", "faction": "群", "max_hp": owner.max_hp,
                  "skills": [{"name": "血裔测试技", "implementation_status": "active", "dsl": {"version": 1, "trigger": "turn_start", "modifiers": [{"stat": "hand_limit", "op": "add", "value": {"op": "mul", "args": [2, {"path": "game.alive_other_faction_count"}]}, "when": {"op": "eq", "path": "owner.identity", "value": "lord"}}]}}]}
    ally.hero = {"id": "custom_ally", "name": "群友", "faction": "群", "max_hp": ally.max_hp, "skills": []}
    engine.skill_manager.bind_engine(engine)
    assert engine.skill_manager.hand_limit(owner, owner.hp) == owner.hp + 2

    owner.hero["skills"].append({"name": "耀武测试技", "implementation_status": "active", "dsl": {"version": 1, "trigger": "damage_received", "condition": {"op": "exists", "path": "event.card_name"}, "effects": [{"type": "draw_cards", "target": "source", "count": 1, "reason": "耀武", "when": {"op": "eq", "path": "event.card_color", "value": "red"}}, {"type": "draw_cards", "target": "owner", "count": 1, "reason": "耀武", "when": {"op": "ne", "path": "event.card_color", "value": "red"}}]}})
    engine.skill_manager.bind_engine(engine)
    owner.hand.clear(); source.hand.clear(); engine.game_state.deck.clear()
    engine.game_state.deck.append(Card("award", "桃", "heart", 3, "basic"))
    # Invoke the real post-damage hook to verify card color reaches the DSL event scope.
    red = Card("damage_red", "杀", "heart", 6, "basic")
    before = len(source.hand)
    asyncio.run(engine.skill_manager.after_damage(source, owner, 1, red))
    assert len(source.hand) == before + 1


def test_dsl_card_as_uses_engine_validation_and_virtual_card_resolution():
    engine = MainEngine({"mode": "5人身份局", "player_name": "P0", "ais": [{"name": f"P{i}"} for i in range(1, 5)]})
    owner = engine.game_state.players[0]
    owner.hero = {"id": "custom_card_as", "name": "转化测试", "faction": "蜀", "max_hp": owner.max_hp,
                  "skills": [{"name": "红牌救援", "implementation_status": "active", "dsl": {
                      "version": 1, "trigger": "play_action",
                      "cost": [{"interaction": "ask_choose_cards", "min": 1, "max": 1, "filter": {"color": "red"}}],
                      "effects": [{"type": "card_as", "card": "桃", "target": "owner", "reason": "测试转化"}],
                  }}]}
    engine.skill_manager.bind_engine(engine)
    engine.game_state.current_player = owner
    engine.game_state.current_phase = Phase.PLAY
    owner.hp = max(1, owner.max_hp - 1)
    card = Card("red_cost", "闪", "heart", 4, "basic")
    owner.hand.append(card)
    engine.skill_manager.ask_choose_cards = AsyncMock(return_value=[card])
    action = next(a for a in engine.skill_manager.get_actions(owner) if a.get("skill_name") == "红牌救援")
    assert asyncio.run(engine.skill_manager.execute(owner, action, [])) is True
    assert owner.hp == owner.max_hp
    assert card not in owner.hand
    assert any(m.card_id == card.id and m.to_zone == "discard" for m in engine.game_state.card_move_events)


def test_dsl_response_conversion_uses_shared_hand_restriction_and_treasure_entries():
    engine = MainEngine({"mode": "5人身份局", "player_name": "P0", "ais": [{"name": f"P{i}"} for i in range(1, 5)]})
    owner = engine.game_state.players[0]
    owner.hero = {"id": "custom_response", "name": "转换响应", "faction": "群", "max_hp": owner.max_hp,
                  "skills": [{"name": "黑牌闪", "implementation_status": "active", "dsl": {"version": 1, "trigger": "card_responded", "conversions": [{"color": "black", "as": "闪"}]}}]}
    engine.skill_manager.bind_engine(engine)
    owner.flags["cannot_use_hand"] = True
    owner.hand.clear()
    owner.equipment["treasure"] = Card("wooden_ox", "木牛流马", "diamond", 5, "equipment", sub_type="treasure")
    stored = Card("stored_black", "杀", "spade", 9, "basic")
    owner.treasure_cards.append(stored)
    options = engine.skill_manager.response_options(owner, "闪")
    assert len(options) == 1
    assert options[0]["card"] is stored
    assert options[0]["source_zone"] == "treasure"


def test_illegal_card_as_does_not_consume_skill_charge_or_move_cost_card():
    engine = MainEngine({"mode": "5人身份局", "player_name": "P0", "ais": [{"name": f"P{i}"} for i in range(1, 5)]})
    owner = engine.game_state.players[0]
    owner.hero = {"id": "custom_illegal_card_as", "name": "非法转化测试", "faction": "蜀", "max_hp": owner.max_hp,
                  "skills": [{"name": "限次救援", "implementation_status": "active", "dsl": {
                      "version": 1, "trigger": "play_action", "usage": {"scope": "game", "charges": 1},
                      "cost": [{"interaction": "ask_choose_cards", "min": 1, "max": 1, "filter": {"color": "red"}}],
                      "effects": [{"type": "card_as", "card": "桃", "target": "owner"}],
                  }}]}
    engine.skill_manager.bind_engine(engine)
    engine.game_state.current_player = owner
    engine.game_state.current_phase = Phase.PLAY
    card = Card("red_cost", "闪", "heart", 4, "basic")
    owner.hand.append(card)
    engine.skill_manager.ask_choose_cards = AsyncMock(return_value=[card])
    action = next(a for a in engine.skill_manager.get_actions(owner) if a.get("skill_name") == "限次救援")
    assert asyncio.run(engine.skill_manager.execute(owner, action, [])) is False
    instance = engine.skill_manager._skill_instance(owner, "限次救援")
    assert instance.charges == 1
    assert card in owner.hand


def test_dsl_tiandu_claims_real_judged_card_through_after_judge_hook():
    engine = MainEngine({"mode": "5人身份局", "player_name": "P0", "ais": [{"name": f"P{i}"} for i in range(1, 5)]})
    owner = engine.game_state.players[0]
    owner.hero = {"id": "custom_tiandu", "name": "天妒测试", "faction": "魏", "max_hp": owner.max_hp,
                  "skills": [{"name": "天妒测试技", "implementation_status": "active", "dsl": {
                      "version": 1, "trigger": "judge_after",
                      "cost": [{"interaction": "ask_confirm", "prompt": "获得判定牌？"}],
                      "effects": [{"type": "gain_judged_card", "reason": "天妒"}],
                  }}]}
    engine.skill_manager.bind_engine(engine)
    judged = Card("judged", "闪", "heart", 8, "basic")
    owner.shown.append(judged)
    engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
    assert asyncio.run(engine.skill_manager.after_judge(owner, judged, {"reason": "test"})) is True
    assert judged in owner.hand and judged not in owner.shown


def test_dsl_guicai_replaces_judgment_for_another_player_and_keeps_original_discarded():
    engine = MainEngine({"mode": "5人身份局", "player_name": "P0", "ais": [{"name": f"P{i}"} for i in range(1, 5)]})
    judged_player, owner = engine.game_state.players[:2]
    owner.hero = {"id": "custom_guicai", "name": "鬼才测试", "faction": "魏", "max_hp": owner.max_hp,
                  "skills": [{"name": "鬼才测试技", "implementation_status": "active", "dsl": {
                      "version": 1, "trigger": "judge_before",
                      "cost": [{"interaction": "ask_confirm", "prompt": "替换判定？"},
                               {"interaction": "ask_choose_cards", "min": 1, "max": 1, "zone": "hand"}],
                      "effects": [{"type": "replace_judgment", "reason": "鬼才"}],
                  }}]}
    engine.skill_manager.bind_engine(engine)
    engine.game_state.current_player = owner
    old = Card("old_judge", "杀", "spade", 2, "basic")
    replacement = Card("replacement", "桃", "heart", 4, "basic")
    judged_player.shown.append(old)
    owner.hand.append(replacement)
    engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
    engine.skill_manager.ask_choose_cards = AsyncMock(return_value=[replacement])
    result = asyncio.run(engine.skill_manager.before_judge(judged_player, old, {"reason": "test"}))
    assert result is replacement
    assert replacement in judged_player.shown and replacement not in owner.hand
    assert old in engine.game_state.discard_pile


def test_generic_locals_repeat_and_state_effects_execute_without_skill_specific_actions():
    engine = MainEngine({"mode": "5人身份局", "player_name": "P0", "ais": [{"name": f"P{i}"} for i in range(1, 5)]})
    owner = engine.game_state.players[0]
    owner.hero = {"id": "custom_generic", "name": "通用 DSL", "faction": "吴", "max_hp": owner.max_hp,
                  "skills": [{"name": "通用组合", "implementation_status": "active", "dsl": {
                      "version": 1, "trigger": "turn_start", "effects": [
                          {"type": "draw_cards", "target": "owner", "count": 1, "store_as": "drawn"},
                          {"type": "interact", "interaction": "ask_choose_cards", "store_as": "selected",
                           "zone": "local:drawn", "min": 1, "max": 1},
                          {"type": "discard_card", "cards_from": "locals.selected", "zone": "hand"},
                          {"type": "repeat", "count": 2, "effects": [
                              {"type": "set_state", "key": "counter", "op": "add", "value": 1}
                          ]}
                      ]
                  }}]}
    engine.skill_manager.bind_engine(engine)
    engine.game_state.deck.clear()
    drawn = Card("generic_draw", "桃", "heart", 5, "basic")
    engine.game_state.deck.append(drawn)
    engine.ask_choose_cards = AsyncMock(return_value=[drawn])
    compiled = engine.skill_manager.dsl_programs[(owner.id, "通用组合")]
    assert asyncio.run(engine.skill_manager.dsl_runtime.run(compiled, owner, {}, "通用组合")) is True
    assert drawn in engine.game_state.discard_pile
    assert engine.skill_manager.skill_state_value(owner, "通用组合", "counter") == 2


@pytest.mark.parametrize("status", ["partial", "data_only"])
def test_metadata_only_dsl_cannot_override_an_active_native_skill(status):
    engine = MainEngine({"mode": "5人身份局", "player_name": "P0", "ais": [{"name": f"P{i}"} for i in range(1, 5)]})
    owner = engine.game_state.players[0]
    owner.hero = {"id": "zhouyu", "name": "周瑜", "faction": "吴", "max_hp": owner.max_hp,
                  "skills": [{"name": "英姿", "implementation_status": status, "dsl": {
                      "version": 1, "trigger": "card_gained",
                      "effects": [{"type": "draw_cards", "count": 1}],
                  }}]}
    engine.skill_manager.bind_engine(engine)
    card = Card(f"metadata_gate_{status}", "桃", "heart", 1, "basic")
    engine.game_state.deck[:] = [card]
    before = (len(owner.hand), len(engine.game_state.deck))

    asyncio.run(engine.skill_manager._run_dsl("card_gained", [owner], {"count": 1}))

    assert (len(owner.hand), len(engine.game_state.deck)) == before


def test_cost_player_selection_cannot_exclude_out_of_scope_targets():
    engine = MainEngine({"mode": "5人身份局", "player_name": "P0", "ais": [{"name": f"P{i}"} for i in range(1, 5)]})
    owner, target = engine.game_state.players[:2]
    owner.hero = {"id": "custom_exclude", "name": "排除校验", "faction": "吴", "max_hp": owner.max_hp,
                  "skills": [{"name": "限定选择", "implementation_status": "active", "dsl": {
                      "version": 1, "trigger": "multi_target_trick",
                      "cost": [{"interaction": "ask_choose_players", "candidates": "event.source",
                                "min": 1, "max": 1}],
                      "effects": [{"type": "exclude_targets"}],
                  }}]}
    engine.skill_manager.bind_engine(engine)
    engine.skill_manager.ask_choose_players = AsyncMock(return_value=[target])
    event = {"source": owner, "targets": [target], "target_count": 1}

    asyncio.run(engine.skill_manager._run_dsl("multi_target_trick", [owner], event))

    assert event.get("_targets") is None


def test_interact_player_count_is_rechecked_before_effects():
    engine = MainEngine({"mode": "5人身份局", "player_name": "P0", "ais": [{"name": f"P{i}"} for i in range(1, 5)]})
    owner, target, extra = engine.game_state.players[:3]
    owner.hero = {"id": "custom_interact_count", "name": "数量校验", "faction": "吴", "max_hp": owner.max_hp,
                  "skills": [{"name": "定量选择", "implementation_status": "active", "dsl": {
                      "version": 1, "trigger": "turn_start",
                      "effects": [
                          {"type": "interact", "interaction": "ask_choose_players", "store_as": "chosen",
                           "candidates": "all_alive", "min": 1, "max": 1},
                          {"type": "draw_cards", "target": "locals.chosen", "count": 1},
                      ],
                  }}]}
    engine.skill_manager.bind_engine(engine)
    engine.game_state.deck[:] = [Card("count_a", "桃", "heart", 1, "basic"),
                                 Card("count_b", "杀", "spade", 2, "basic")]
    engine.skill_manager.ask_choose_players = AsyncMock(return_value=[target, extra])
    before = (len(target.hand), len(extra.hand), len(engine.game_state.deck))

    asyncio.run(engine.skill_manager._run_dsl("turn_start", [owner], {"player": owner}))

    assert (len(target.hand), len(extra.hand), len(engine.game_state.deck)) == before


def test_unresolvable_dynamic_interaction_bounds_fail_without_exception():
    engine = MainEngine({"mode": "5人身份局", "player_name": "P0", "ais": [{"name": f"P{i}"} for i in range(1, 5)]})
    owner = engine.game_state.players[0]
    owner.hero = {"id": "custom_bad_bounds", "name": "边界校验", "faction": "吴", "max_hp": owner.max_hp,
                  "skills": [{"name": "动态边界", "implementation_status": "active", "dsl": {
                      "version": 1, "trigger": "play_action",
                      "cost": [{"interaction": "ask_choose_cards", "min": {"path": "event.absent"},
                                "max": 1}],
                      "effects": [{"type": "announce"}],
                  }}]}
    engine.skill_manager.bind_engine(engine)
    engine.game_state.current_player = owner
    engine.game_state.current_phase = Phase.PLAY
    engine.skill_manager.ask_choose_cards = AsyncMock(return_value=[owner.hand[0]])
    action = {"variant": "dsl", "skill_name": "动态边界"}

    assert asyncio.run(engine.skill_manager.execute(owner, action, [])) is False
    engine.skill_manager.ask_choose_cards.assert_not_awaited()
