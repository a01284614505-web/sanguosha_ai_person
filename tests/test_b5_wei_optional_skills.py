"""B5 场景：魏国受伤触发技由技能持有者决定是否发动和选择牌。"""

import asyncio
from unittest.mock import AsyncMock

from game_engine import MainEngine
from game_engine.state_manager import Card, Phase
from game_engine.skills_wei import WeiSkillHandler


def run(coro):
    return asyncio.run(coro)


def game():
    engine = MainEngine({
        "mode": "5人身份局", "player_name": "P0",
        "ais": [{"name": f"P{i}"} for i in range(1, 5)],
        "deck_id": "standard",
    })
    for player in engine.game_state.players:
        player.hand.clear()
        player.equipment.clear()
    return engine


def get_wei(engine):
    return next(handler for handler in engine.skill_manager.handlers
                if isinstance(handler, WeiSkillHandler))


def card(tag, name, suit="spade", card_type="basic"):
    return Card(tag, name, suit, 7, card_type)


def test_jianxiong_decline_leaves_damage_card_and_deck_untouched():
    engine = game()
    handler = get_wei(engine)
    target, source = engine.game_state.players[:2]
    handler.has = lambda player, name: name == "奸雄"
    damage_card = card("b5_jianxiong_damage", "杀")
    top = card("b5_jianxiong_top", "闪")
    engine.game_state.discard_pile.append(damage_card)
    engine.game_state.deck[:] = [top]
    engine.skill_manager.ask_confirm = AsyncMock(return_value=False)

    run(handler.after_damage(source, target, 1, damage_card))

    assert damage_card in engine.game_state.discard_pile
    assert target.hand == []
    assert engine.game_state.deck == [top]
    engine.skill_manager.ask_confirm.assert_awaited_once()


def test_jianxiong_accept_moves_damage_card_then_draws_once():
    engine = game()
    handler = get_wei(engine)
    target, source = engine.game_state.players[:2]
    handler.has = lambda player, name: name == "奸雄"
    damage_card = card("b5_jianxiong_gain", "决斗", card_type="trick")
    top = card("b5_jianxiong_draw", "桃", "heart")
    engine.game_state.discard_pile.append(damage_card)
    engine.game_state.deck[:] = [top]
    engine.skill_manager.ask_confirm = AsyncMock(return_value=True)

    run(handler.after_damage(source, target, 1, damage_card))

    assert damage_card not in engine.game_state.discard_pile
    assert target.hand == [damage_card, top]
    moves = [m for m in engine.game_state.card_move_events if m.card_id == damage_card.id]
    assert [(m.from_zone, m.to_zone, m.to_owner) for m in moves] == [
        ("discard", "hand", target.id)]


def test_fankui_prompts_and_takes_the_selected_equipment():
    engine = game()
    handler = get_wei(engine)
    target, source = engine.game_state.players[:2]
    handler.has = lambda player, name: name == "反馈"
    weapon = card("b5_fankui_weapon", "青釭剑", card_type="equipment")
    source.equipment["weapon"] = weapon
    engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
    engine.skill_manager.ask_choose_cards_result = AsyncMock(return_value={
        "status": "resolved", "cards": [weapon],
    })

    run(handler.after_damage(source, target, 1, card("b5_fankui_damage", "杀")))

    assert source.equipment == {}
    assert target.hand == [weapon]
    move = next(m for m in engine.game_state.card_move_events if m.card_id == weapon.id)
    assert (move.from_zone, move.to_zone, move.from_owner, move.to_owner) == (
        "equipment", "hand", source.id, target.id)
    engine.skill_manager.ask_choose_cards_result.assert_awaited_once()


def test_ganglie_decline_does_not_judge_or_change_source():
    engine = game()
    handler = get_wei(engine)
    target, source = engine.game_state.players[:2]
    handler.has = lambda player, name: name == "刚烈"
    source.hand.append(card("b5_ganglie_hold", "闪"))
    engine.skill_manager.ask_confirm = AsyncMock(return_value=False)
    engine.skill_manager.judge = AsyncMock()

    run(handler.after_damage(source, target, 1, card("b5_ganglie_damage", "杀")))

    engine.skill_manager.judge.assert_not_awaited()
    assert len(source.hand) == 1
    engine.skill_manager.ask_confirm.assert_awaited_once()


def test_ganglie_black_judgment_asks_source_which_equipment_to_discard():
    engine = game()
    handler = get_wei(engine)
    target, source = engine.game_state.players[:2]
    handler.has = lambda player, name: name == "刚烈"
    armor = card("b5_ganglie_armor", "仁王盾", "club", "equipment")
    source.equipment["armor"] = armor
    engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
    engine.skill_manager.judge = AsyncMock(return_value=card("b5_ganglie_judge", "闪", "club"))
    engine.skill_manager.ask_choose_cards_result = AsyncMock(return_value={
        "status": "resolved", "cards": [armor],
    })
    engine.card_system.notify_card_to_discard = AsyncMock()

    run(handler.after_damage(source, target, 1, card("b5_ganglie_damage2", "杀")))

    assert source.equipment == {}
    assert armor in engine.game_state.discard_pile
    move = next(m for m in engine.game_state.card_move_events if m.card_id == armor.id)
    assert (move.from_zone, move.to_zone, move.from_owner) == ("equipment", "discard", source.id)
    request = engine.skill_manager.ask_choose_cards_result.await_args
    assert request.kwargs["places"] == [(source, "equipment")]
    assert request.kwargs["cancelable"] is False


def test_qingjian_decline_keeps_gained_cards_and_does_not_mark_use():
    engine = game()
    handler = get_wei(engine)
    player = engine.game_state.players[0]
    gained = card("b5_qingjian_decline", "桃", "heart")
    player.hand.append(gained)
    handler.has = lambda p, name: p is player and name == "清俭"
    engine.skill_manager.ask_confirm = AsyncMock(return_value=False)

    run(handler.on_card_gained(player, [gained], "技能获得"))

    assert player.hand == [gained]
    assert not player.flags.get("skill_used", {}).get("清俭")


def test_qingjian_uses_selected_gained_card_and_recipient():
    engine = game()
    handler = get_wei(engine)
    player, recipient = engine.game_state.players[:2]
    keep = card("b5_qingjian_keep", "闪", "club")
    gained = card("b5_qingjian_give", "八卦阵", "heart", "equipment")
    player.hand.extend([keep, gained])
    handler.has = lambda p, name: p is player and name == "清俭"
    engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
    engine.skill_manager.ask_choose_cards_result = AsyncMock(return_value={"status": "resolved", "cards": [keep, gained]})
    engine.skill_manager.ask_choose_players = AsyncMock(return_value=[recipient])
    engine.game_state.current_player = player

    run(handler.on_card_gained(player, [gained], "技能获得"))

    assert player.hand == []
    assert recipient.hand == [keep, gained]
    assert player.flags["skill_used"]["清俭"] is True
    assert player.flags["hand_limit_bonus"] == 2


def test_yiji_asks_owner_to_distribute_both_cards_before_moving_them():
    engine = game()
    handler = get_wei(engine)
    target, first, second = engine.game_state.players[:3]
    first_card = card("b5_yiji_first", "闪", "club")
    second_card = card("b5_yiji_second", "桃", "heart")
    handler.has = lambda p, name: p is target and name == "遗计"

    async def draw_two(player, count, reason):
        assert player is target and count == 2 and reason == "遗计"
        target.hand.extend([first_card, second_card])
        return [first_card, second_card]

    engine.skill_manager.draw_cards = AsyncMock(side_effect=draw_two)
    engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
    engine.skill_manager.ask_choose_players = AsyncMock(side_effect=[[first], [second]])
    engine.skill_manager.announce = AsyncMock()

    run(handler.after_damage(first, target, 1))

    assert target.hand == []
    assert first.hand == [first_card]
    assert second.hand == [second_card]
    assert engine.skill_manager.ask_choose_players.await_count == 2
    assert all(call.kwargs["cancelable"] is False for call in engine.skill_manager.ask_choose_players.await_args_list)


def test_tuxi_decline_leaves_draw_phase_to_normal_flow():
    engine = game()
    handler = get_wei(engine)
    player, victim = engine.game_state.players[:2]
    victim.hand.append(card("b5_tuxi_decline", "闪"))
    handler.has = lambda p, name: p is player and name == "突袭"
    engine.skill_manager.ask_confirm = AsyncMock(return_value=False)
    engine.skill_manager.ask_choose_players = AsyncMock()

    result = run(handler.before_phase(player, Phase.DRAW))

    assert result is None
    engine.skill_manager.ask_choose_players.assert_not_awaited()
    assert victim.hand


def test_tuxi_takes_the_chosen_hidden_hand_card_and_compensates_one_draw():
    engine = game()
    handler = get_wei(engine)
    player, victim = engine.game_state.players[:2]
    stolen = card("b5_tuxi_stolen", "桃", "heart")
    victim.hand.append(stolen)
    handler.has = lambda p, name: p is player and name == "突袭"
    engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
    engine.skill_manager.ask_choose_players = AsyncMock(return_value=[victim])
    engine.skill_manager.ask_choose_cards_result = AsyncMock(return_value={"status": "resolved", "cards": [stolen]})
    engine.skill_manager.draw_cards = AsyncMock(return_value=[])
    engine.skill_manager.announce = AsyncMock()

    result = run(handler.before_phase(player, Phase.DRAW))

    assert result == {"skip_default": True}
    assert victim.hand == []
    assert player.hand == [stolen]
    engine.skill_manager.draw_cards.assert_awaited_once_with(player, 1, "突袭补摸")
    choice = engine.skill_manager.ask_choose_cards_result.await_args
    assert choice.kwargs["hidden_indices"] == [0]
    assert choice.kwargs["places"] == [(victim, "hand")]


def test_tuxi_canceled_player_selection_does_not_activate_skill():
    engine = game()
    handler = get_wei(engine)
    player, victim = engine.game_state.players[:2]
    victim.hand.append(card("b5_tuxi_cancel", "闪"))
    handler.has = lambda p, name: p is player and name == "突袭"
    engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
    engine.skill_manager.ask_choose_players = AsyncMock(return_value=[])
    engine.skill_manager.draw_cards = AsyncMock()

    result = run(handler.before_phase(player, Phase.DRAW))

    assert result is None
    engine.skill_manager.draw_cards.assert_not_awaited()


def test_guicai_decline_preserves_the_judgment_and_cost_card():
    engine = game()
    handler = get_wei(engine)
    owner, judged = engine.game_state.players[:2]
    cost = card("b5_guicai_decline", "闪", "club")
    original = card("b5_guicai_original", "桃", "heart")
    owner.hand.append(cost)
    handler.has = lambda p, name: p is owner and name == "鬼才"
    engine.skill_manager.ask_confirm = AsyncMock(return_value=False)
    engine.skill_manager.ask_choose_cards_result = AsyncMock()

    result = run(handler.before_judge(judged, original))

    assert result is original
    assert owner.hand == [cost]
    assert original not in engine.game_state.discard_pile
    engine.skill_manager.ask_choose_cards_result.assert_not_awaited()


def test_guicai_accepts_exact_equipment_replacement():
    engine = game()
    handler = get_wei(engine)
    owner, judged = engine.game_state.players[:2]
    cost = card("b5_guicai_armor", "八卦阵", "club", "equipment")
    original = card("b5_guicai_judgment", "闪", "heart")
    owner.equipment["armor"] = cost
    handler.has = lambda p, name: p is owner and name == "鬼才"
    engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
    engine.skill_manager.ask_choose_cards_result = AsyncMock(return_value={"status": "resolved", "cards": [cost]})

    result = run(handler.before_judge(judged, original))

    assert result is cost
    assert owner.equipment == {}
    assert original in engine.game_state.discard_pile


def test_tiandu_can_decline_claiming_a_resolved_judgment():
    engine = game()
    handler = get_wei(engine)
    player = engine.game_state.players[0]
    judged = card("b5_tiandu_decline", "桃", "heart")
    handler.has = lambda p, name: p is player and name == "天妒"
    engine.skill_manager.ask_confirm = AsyncMock(return_value=False)

    claimed = run(handler.after_judge(player, judged))

    assert claimed is False
    assert player.hand == []


def test_yiji_decline_does_not_draw_or_ask_distribution_targets():
    engine = game()
    handler = get_wei(engine)
    target = engine.game_state.players[0]
    handler.has = lambda p, name: p is target and name == "遗计"
    engine.skill_manager.ask_confirm = AsyncMock(return_value=False)
    engine.skill_manager.draw_cards = AsyncMock()
    engine.skill_manager.ask_choose_players = AsyncMock()

    run(handler.after_damage(None, target, 1))

    engine.skill_manager.draw_cards.assert_not_awaited()
    engine.skill_manager.ask_choose_players.assert_not_awaited()


def test_fankui_can_decline_without_touching_sources_cards():
    engine = game()
    handler = get_wei(engine)
    source, target = engine.game_state.players[:2]
    source_card = card("b5_fankui_decline", "桃", "heart")
    source.hand.append(source_card)
    handler.has = lambda p, skill: p is target and skill == "反馈"
    engine.skill_manager.ask_confirm = AsyncMock(return_value=False)

    run(handler.after_damage(source, target, 1))

    assert source.hand == [source_card]
    assert target.hand == []


def test_tiandu_can_claim_the_resolved_judgment_card():
    engine = game()
    handler = get_wei(engine)
    player = engine.game_state.players[0]
    judged = card("b5_tiandu_claim", "闪", "heart")
    handler.has = lambda p, skill: p is player and skill == "天妒"
    engine.skill_manager.ask_confirm = AsyncMock(return_value=True)

    claimed = run(handler.after_judge(player, judged, {"reason": "test"}))

    assert claimed is True
    assert judged in player.hand


def test_luoshen_takes_consecutive_black_judgments_then_stops_on_red():
    from game_engine.state_manager import Phase
    engine = game()
    handler = get_wei(engine)
    player = engine.game_state.players[0]
    black1 = card("b5_luoshen_black1", "杀", "spade")
    black2 = card("b5_luoshen_black2", "闪", "club")
    red = card("b5_luoshen_red", "桃", "heart")
    following = card("b5_luoshen_following", "杀", "diamond")
    engine.game_state.deck = [black1, black2, red, following]
    handler.has = lambda p, skill: p is player and skill == "洛神"

    run(handler.before_phase(player, Phase.PREPARE))

    assert player.hand == [black1, black2]
    assert engine.game_state.discard_pile[-1] is red
    assert engine.game_state.deck == [following]
    assert player.flags["luoshen_exempt"] == 2


def test_luoshen_with_empty_deck_does_not_add_exemption():
    from game_engine.state_manager import Phase
    engine = game()
    handler = get_wei(engine)
    player = engine.game_state.players[0]
    engine.game_state.deck.clear()
    handler.has = lambda p, skill: p is player and skill == "洛神"

    run(handler.before_phase(player, Phase.PREPARE))

    assert player.hand == []
    assert "luoshen_exempt" not in player.flags


def test_fankui_with_source_without_cards_does_not_prompt():
    engine = game()
    handler = get_wei(engine)
    source, target = engine.game_state.players[:2]
    handler.has = lambda p, skill: p is target and skill == "反馈"
    engine.skill_manager.ask_confirm = AsyncMock(return_value=True)

    run(handler.after_damage(source, target, 1))

    engine.skill_manager.ask_confirm.assert_not_awaited()
