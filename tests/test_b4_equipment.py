"""B4 装备批：装备实体、武器修正与防具交叉场景。"""

import asyncio
from unittest.mock import AsyncMock

from game_engine import MainEngine
from game_engine.state_manager import Card, Phase


def run(coro):
    return asyncio.run(coro)


def game():
    engine = MainEngine({"mode": "5人身份局", "player_name": "P0",
                         "ais": [{"name": f"P{i}"} for i in range(1, 5)],
                         "deck_id": "standard"})
    for p in engine.game_state.players:
        p.hand.clear()
        p.equipment.clear()
        p.judge_area.clear()
    engine.game_state.current_player = engine.game_state.players[0]
    engine.game_state.current_player_index = 0
    engine.game_state.current_phase = Phase.PLAY
    return engine


def card(tag, name, suit="spade", card_type="equipment", nature=None):
    return Card(tag, name, suit, 5, card_type, nature=nature)


def test_equip_action_moves_one_entity_from_hand_through_discard_to_slot():
    engine = game()
    player = engine.game_state.players[0]
    weapon = card("b4_qinggang", "青釭剑")
    player.hand.append(weapon)
    assert run(engine.execute_action(player, {"type": "play_card", "card_index": 0})) is True
    assert player.equipment["weapon"] is weapon
    assert weapon not in engine.game_state.discard_pile
    moves = [m for m in engine.game_state.card_move_events if m.card_id == weapon.id]
    assert [(m.from_zone, m.to_zone) for m in moves] == [
        ("hand", "discard"), ("discard", "equipment")]


def test_qinggang_ignores_renwang_and_tengjia_fire_is_amplified():
    engine = game()
    source, target = engine.game_state.players[:2]
    source.equipment["weapon"] = card("b4_qg", "青釭剑")
    target.equipment["armor"] = card("b4_renwang", "仁王盾")
    sha = card("b4_sha", "杀", "spade", "basic")
    assert run(engine.card_system.use_sha(source, sha, target)) is True
    assert target.hp == 3

    source.sha_count = 0
    source.equipment.pop("weapon")
    target.hp = 4
    assert run(engine.card_system.use_sha(source, sha, target)) is True
    assert target.hp == 4

    source.sha_count = 0
    target.equipment["armor"] = card("b4_tengjia", "藤甲")
    fire_sha = card("b4_fire", "杀", "heart", "basic", "fire")
    assert run(engine.card_system.use_sha(source, fire_sha, target)) is True
    assert target.hp == 2


def test_bagua_red_judgment_is_virtual_shan_without_hand_loss():
    engine = game()
    source, target = engine.game_state.players[:2]
    target.equipment["armor"] = card("b4_bagua", "八卦阵")
    red = card("b4_red", "桃", "heart", "basic")
    engine.game_state.deck.insert(0, red)
    sha = card("b4_attack", "杀", "spade", "basic")
    assert run(engine.card_system.use_sha(source, sha, target)) is True
    assert target.hp == 4
    assert not target.hand
    assert red in engine.game_state.discard_pile


def test_silver_lion_caps_damage_and_recovers_on_loss():
    engine = game()
    source, target = engine.game_state.players[:2]
    lion = card("b4_lion", "白银狮子")
    target.equipment["armor"] = lion
    run(engine.card_system.damage(source, target, 3))
    assert target.hp == 3
    moved = run(engine.move_card(lion, "equipment", "discard", from_owner=target,
                                 reason="test_loss", actor_id=source.id))
    assert moved is not None
    assert target.hp == 4
    assert engine.stats.row(target)["healing"] == 1


def test_crossbow_limit_and_guding_empty_hand_damage():
    engine = game()
    source, target = engine.game_state.players[:2]
    sha = card("b4_sha_limit", "杀", "spade", "basic")
    source.hand.append(sha)
    source.sha_count = 1
    assert engine.rules.can_play_card(source, sha, [target])[0] is False
    source.equipment["weapon"] = card("b4_zhuge", "诸葛连弩")
    assert engine.rules.can_play_card(source, sha, [target])[0] is True
    source.equipment["weapon"] = card("b4_guding", "古锭刀")
    source.sha_count = 0
    assert run(engine.card_system.use_sha(source, sha, target)) is True
    assert target.hp == 2


def test_muniu_store_once_and_play_from_distinct_treasure_zone():
    engine = game()
    owner = engine.game_state.players[0]
    owner.equipment["treasure"] = card("b4_muniu", "木牛流马")
    wine = card("b4_stored_wine", "酒", "diamond", "basic")
    owner.hand.append(wine)
    engine.ask_choose_players = AsyncMock(return_value=[])
    action = next(a for a in engine.get_available_actions(owner)
                  if a.get("skill_name") == "木牛流马")
    assert run(engine.execute_action(owner, action)) is True
    assert not owner.hand and owner.treasure_cards == [wine]
    assert owner.flags["muniu_stored_this_turn"] is True
    assert engine.get_player_hand(owner)[0]["zone"] == "treasure"
    assert not any(a.get("skill_name") == "木牛流马"
                   for a in engine.get_available_actions(owner))
    play = next(a for a in engine.get_available_actions(owner)
                if a.get("type") == "play_card" and a.get("card_index") == 0)
    assert run(engine.execute_action(owner, play)) is True
    assert wine not in owner.treasure_cards and wine in engine.game_state.discard_pile
    assert [(e.from_zone, e.to_zone) for e in engine.game_state.card_move_events
            if e.card_id == wine.id] == [("hand", "treasure"), ("treasure", "discard")]


def test_muniu_transfer_keeps_attached_cards_and_loss_discards_them():
    engine = game()
    owner, recipient = engine.game_state.players[:2]
    treasure = card("b4_muniu_transfer", "木牛流马")
    stored = card("b4_muniu_attached", "闪", "heart", "basic")
    owner.equipment["treasure"] = treasure
    owner.treasure_cards.append(stored)
    moved = run(engine.move_card(
        treasure, "equipment", "equipment", from_owner=owner,
        to_owner=recipient, to_slot="treasure", reason="muniu_give", actor_id=owner.id,
    ))
    assert moved is not None
    assert not owner.treasure_cards and recipient.treasure_cards == [stored]
    options = engine.card_system.build_response_options(
        recipient, lambda c: c.name == "闪", "闪")
    assert options[0]["source_zone"] == "treasure"
    response = engine._resolve_option(recipient, {"options": options, "requested_name": "闪"}, 0)
    assert response["bool"] and response["source_zone"] == "treasure"
    assert run(engine.card_system._consume_response(recipient, response, "杀", {})) is True
    assert stored in engine.game_state.discard_pile

    another = card("b4_muniu_attached_2", "桃", "heart", "basic")
    recipient.treasure_cards.append(another)
    run(engine.move_card(treasure, "equipment", "discard", from_owner=recipient,
                         reason="muniu_removed", actor_id=owner.id))
    assert not recipient.treasure_cards and another in engine.game_state.discard_pile


def test_hanbing_prevents_damage_and_discards_two_cards():
    engine = game()
    source, target = engine.game_state.players[1:3]
    source.equipment["weapon"] = card("b4_hanbing", "寒冰剑")
    first = card("b4_hanbing_first", "杀", "spade", "basic")
    second = card("b4_hanbing_second", "闪", "heart", "basic")
    target.hand.extend((first, second))
    engine.ask_choose_cards = AsyncMock(side_effect=lambda *args, **kwargs: [args[2][0]])
    run(engine.card_system.damage(source, target, 1,
                                  card=card("b4_hanbing_sha", "杀", "heart", "basic")))
    assert target.hp == 4
    assert not target.hand
    assert first in engine.game_state.discard_pile and second in engine.game_state.discard_pile
    assert engine.stats.row(source)["damage_dealt"] == 0


def test_qilin_discards_mount_after_damage():
    engine = game()
    source, target = engine.game_state.players[1:3]
    source.equipment["weapon"] = card("b4_qilin", "麒麟弓")
    horse = card("b4_horse", "绝影")
    target.equipment["plus_horse"] = horse
    run(engine.card_system.damage(source, target, 1,
                                  card=card("b4_qilin_sha", "杀", "heart", "basic")))
    assert target.hp == 3
    assert "plus_horse" not in target.equipment
    assert horse in engine.game_state.discard_pile


def test_cixiong_opposite_gender_discards_and_same_gender_does_nothing():
    engine = game()
    source, target = engine.game_state.players[1:3]
    source.hero = {"sex": "male"}
    target.hero = {"sex": "female"}
    source.equipment["weapon"] = card("b4_cixiong", "雌雄双股剑")
    cost = card("b4_cixiong_cost", "桃", "heart", "basic")
    target.hand.append(cost)
    engine.ask_choose_cards = AsyncMock(return_value=[cost])
    run(engine.card_system.use_sha(source, card("b4_cixiong_sha", "杀", "heart", "basic"), target))
    assert cost in engine.game_state.discard_pile
    assert not target.hand

    source.sha_count = 0
    source.hero = {"sex": "female"}
    another = card("b4_cixiong_same", "桃", "heart", "basic")
    target.hand.append(another)
    run(engine.card_system.use_sha(source, card("b4_cixiong_sha2", "杀", "heart", "basic"), target))
    assert another in target.hand


def test_guanshi_pays_two_cards_after_shan_and_hits():
    engine = game()
    source, target = engine.game_state.players[1:3]
    source.equipment["weapon"] = card("b4_guanshi", "贯石斧")
    costs = [card(f"b4_axe_cost_{i}", "桃", "heart", "basic") for i in range(2)]
    source.hand.extend(costs)
    shan = card("b4_axe_shan", "闪", "heart", "basic")
    target.hand.append(shan)
    engine.ask_choose_cards = AsyncMock(side_effect=lambda *args, **kwargs: [args[2][0]])
    engine.card_system.responder = AsyncMock(return_value={
        "bool": True, "card": shan, "owner": target, "as_name": "闪"})
    run(engine.card_system.use_sha(source, card("b4_axe_sha", "杀", "spade", "basic"), target))
    assert target.hp == 3
    assert all(cost in engine.game_state.discard_pile for cost in costs)


def test_qinglong_uses_second_sha_after_first_is_dodged():
    engine = game()
    source, target = engine.game_state.players[1:3]
    source.equipment["weapon"] = card("b4_qinglong", "青龙偃月刀")
    follow = card("b4_qinglong_follow", "杀", "heart", "basic")
    shan = card("b4_qinglong_shan", "闪", "heart", "basic")
    source.hand.append(follow)
    target.hand.append(shan)

    async def respond(player, request):
        if player is target and shan in target.hand:
            return {"bool": True, "card": shan, "owner": target, "as_name": "闪"}
        if player is source and follow in source.hand:
            return {"bool": True, "card": follow, "owner": source, "as_name": "杀"}
        return {"bool": False}

    engine.card_system.responder = respond
    run(engine.card_system.use_sha(source, card("b4_first_sha", "杀", "spade", "basic"), target))
    assert target.hp == 3
    assert follow in engine.game_state.discard_pile
    assert shan in engine.game_state.discard_pile


def test_zhangba_two_hand_costs_resolve_as_one_sha():
    engine = game()
    source, target = engine.game_state.players[:2]
    source.equipment["weapon"] = card("b4_zhangba", "丈八蛇矛")
    first = card("b4_zhangba_cost1", "桃", "heart", "basic")
    second = card("b4_zhangba_cost2", "酒", "diamond", "basic")
    source.hand.extend((first, second))
    action = next(a for a in engine.get_available_actions(source)
                  if a.get("skill_name") == "丈八蛇矛")
    assert target.id in action["valid_targets"]
    assert run(engine.execute_action(source, action, [target.id])) is True
    assert target.hp == 3
    assert not source.hand
    assert first in engine.game_state.discard_pile and second in engine.game_state.discard_pile
    assert source.sha_count == 1
    assert engine.stats.row(source)["cards_played"] == 2


def test_fangtian_three_targets_share_one_card_and_one_use_count():
    engine = game()
    source, first, second, third = engine.game_state.players[:4]
    source.equipment["weapon"] = card("b4_fangtian", "方天画戟")
    sha = card("b4_fangtian_sha", "杀", "heart", "basic")
    source.hand.append(sha)
    action = next(a for a in engine.get_available_actions(source)
                  if a.get("type") == "play_card" and a.get("card_index") == 0)
    assert [first.id, second.id, third.id] in action["valid_target_groups"]
    assert run(engine.execute_action(source, action, [first.id, second.id, third.id])) is True
    assert [p.hp for p in (first, second, third)] == [3, 3, 3]
    assert source.sha_count == 1
    assert engine.stats.row(source)["cards_played"] == 1
    assert engine.game_state.discard_pile.count(sha) == 1


def test_fangtian_stops_remaining_targets_after_identity_victory():
    engine = game()
    source, loyalist, rebel, other_rebel, spy = engine.game_state.players
    for player, identity in zip(engine.game_state.players,
                                ("lord", "loyalist", "rebel", "rebel", "spy")):
        player.identity = identity
    other_rebel.alive = spy.alive = False
    rebel.hp = 1
    source.equipment["weapon"] = card("b4_fangtian_end", "方天画戟")
    source.hand.append(card("b4_fangtian_lethal", "杀", "heart", "basic"))
    action = next(a for a in engine.get_available_actions(source)
                  if a.get("type") == "play_card" and a.get("card_index") == 0)
    # 反贼先结算并触发主忠胜利，忠臣不能再承受这张杀的后续伤害。
    assert run(engine.execute_action(source, action, [rebel.id, loyalist.id])) is True
    assert engine.game_state.winner == "lord"
    assert loyalist.hp == loyalist.max_hp


def test_zhuque_fire_sha_interacts_with_tengjia_and_chain():
    engine = game()
    source, target, chained = engine.game_state.players[:3]
    source.equipment["weapon"] = card("b4_zhuque", "朱雀羽扇")
    target.equipment["armor"] = card("b4_zhuque_tengjia", "藤甲")
    target.chained = chained.chained = True
    sha = card("b4_zhuque_sha", "杀", "heart", "basic")
    assert run(engine.card_system.use_sha(source, sha, target)) is True
    assert target.hp == 2
    assert chained.hp == 2
    assert not target.chained and not chained.chained


def test_guohe_discards_wood_and_its_attached_card():
    engine = game()
    source, target = engine.game_state.players[:2]
    wood = card("b4_wood_discard", "木牛流马")
    attached = card("b4_wood_attached", "桃", "heart", "basic")
    target.equipment["treasure"] = wood
    target.treasure_cards.append(attached)
    engine.ask_choose_cards = AsyncMock(return_value=[wood])
    assert run(engine.card_system.use_guohe(source, card("b4_guohe", "过河拆桥"), target))
    assert wood in engine.game_state.discard_pile
    assert attached in engine.game_state.discard_pile
    assert not target.treasure_cards


def test_shunshou_takes_wood_but_discards_attached_card():
    engine = game()
    source, target = engine.game_state.players[:2]
    wood = card("b4_wood_stolen", "木牛流马")
    attached = card("b4_wood_stolen_attached", "闪", "heart", "basic")
    target.equipment["treasure"] = wood
    target.treasure_cards.append(attached)
    engine.ask_choose_cards = AsyncMock(return_value=[wood])
    assert run(engine.card_system.use_shunshou(source, card("b4_shunshou", "顺手牵羊"), target))
    assert wood in source.hand
    assert attached in engine.game_state.discard_pile
    assert not target.treasure_cards


def test_guohe_loses_silver_lion_and_triggers_recovery():
    engine = game()
    source, target = engine.game_state.players[:2]
    lion = card("b4_lion_discard", "白银狮子")
    target.equipment["armor"] = lion
    target.hp = 2
    engine.ask_choose_cards = AsyncMock(return_value=[lion])
    assert run(engine.card_system.use_guohe(source, card("b4_guohe_lion", "过河拆桥"), target))
    assert target.hp == 3
    assert lion in engine.game_state.discard_pile


def test_bagua_black_judgment_falls_back_to_hand_shan():
    engine = game()
    source, target = engine.game_state.players[1:3]
    target.equipment["armor"] = card("b4_bagua_black", "八卦阵")
    black = card("b4_bagua_judge", "杀", "spade", "basic")
    shan = card("b4_bagua_hand", "闪", "heart", "basic")
    engine.game_state.deck.insert(0, black)
    target.hand.append(shan)
    engine.card_system.responder = AsyncMock(return_value={
        "bool": True, "card": shan, "owner": target, "as_name": "闪"})
    run(engine.card_system.use_sha(source, card("b4_bagua_attack", "杀", "heart", "basic"), target))
    assert target.hp == 4
    assert black in engine.game_state.discard_pile and shan in engine.game_state.discard_pile


def test_tengjia_ignores_aoe_without_requesting_response():
    engine = game()
    source, target = engine.game_state.players[:2]
    target.equipment["armor"] = card("b4_aoe_tengjia", "藤甲")
    responder = AsyncMock(return_value={"bool": False})
    engine.card_system.responder = responder
    engine.card_system.ask_wuxie = AsyncMock(return_value=False)
    run(engine.card_system.use_nanman(source, card("b4_aoe", "南蛮入侵")))
    assert target.hp == 4
    assert all(call.args[0] is not target for call in responder.await_args_list)


def test_muniu_stored_tao_can_rescue_dying_player():
    engine = game()
    dying, rescuer = engine.game_state.players[:2]
    rescuer.equipment["treasure"] = card("b4_rescue_muniu", "木牛流马")
    peach = card("b4_rescue_peach", "桃", "heart", "basic")
    rescuer.treasure_cards.append(peach)
    dying.hp = 0

    async def respond(player, request):
        if player is rescuer:
            option = request["options"][0]
            return {"bool": True, "card": option["card"], "owner": rescuer,
                    "source_zone": option["source_zone"], "as_name": "桃"}
        return {"bool": False}

    engine.card_system.responder = respond
    run(engine.card_system.enter_dying(dying))
    assert dying.alive and dying.hp == 1
    assert peach in engine.game_state.discard_pile
    assert not rescuer.treasure_cards


def test_muniu_stored_card_can_be_converted_for_response():
    engine = game()
    owner = engine.game_state.players[1]
    owner.equipment["treasure"] = card("b4_conversion_muniu", "木牛流马")
    stored = card("b4_conversion_sha", "杀", "spade", "basic")
    owner.treasure_cards.append(stored)
    engine.skill_manager.has_skill = lambda player, name, active_only=True: (
        player is owner and name == "龙胆")
    options = engine.card_system.build_response_options(
        owner, lambda candidate: candidate.name == "闪", "闪")
    converted = next(option for option in options if option.get("skill_name") == "龙胆")
    assert converted["source_zone"] == "treasure"
    response = engine._resolve_option(owner, {"options": options, "requested_name": "闪"},
                                      options.index(converted))
    assert response["bool"] and response["source_zone"] == "treasure"
    assert run(engine.card_system._consume_response(owner, response, "杀", {})) is True
    assert stored not in owner.treasure_cards and stored in engine.game_state.discard_pile


def test_muniu_stored_red_card_can_supply_urgent_peach():
    engine = game()
    owner = engine.game_state.players[1]
    owner.equipment["treasure"] = card("b4_urgent_muniu", "木牛流马")
    stored = card("b4_urgent_red", "杀", "heart", "basic")
    owner.treasure_cards.append(stored)
    engine.skill_manager.has_skill = lambda player, name, active_only=True: (
        player is owner and name == "急救")
    options = engine.card_system.build_response_options(
        owner, lambda candidate: candidate.name == "桃", "桃")
    assert any(option.get("skill_name") == "急救" and
               option.get("source_zone") == "treasure" for option in options)


def test_muniu_stored_red_card_can_be_played_through_wusheng():
    engine = game()
    owner, target = engine.game_state.players[:2]
    owner.equipment["treasure"] = card("b4_wusheng_muniu", "木牛流马")
    stored = card("b4_wusheng_red", "桃", "heart", "basic")
    owner.treasure_cards.append(stored)
    engine.skill_manager.has_skill = lambda player, name, active_only=True: (
        player is owner and name == "武圣")
    action = next(action for action in engine.get_available_actions(owner)
                  if action.get("skill_name") == "武圣")
    assert action["card_indices"] == [0] and target.id in action["valid_targets"]
    assert run(engine.execute_action(owner, action, [target.id])) is True
    assert stored in engine.game_state.discard_pile and not owner.treasure_cards
    assert target.hp == target.max_hp - 1
    assert [(event.from_zone, event.to_zone) for event in engine.game_state.card_move_events
            if event.card_id == stored.id] == [("treasure", "discard")]
