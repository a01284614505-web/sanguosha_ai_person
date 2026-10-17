"""B5 scene coverage for optional 群雄 triggers and card choices."""

import asyncio
from unittest.mock import AsyncMock

from game_engine import MainEngine
from game_engine.state_manager import Card
from game_engine.skills_qun import QunSkillHandler


def run(coro):
    return asyncio.run(coro)


def game():
    engine = MainEngine({"mode": "5人身份局", "player_name": "P0",
                         "ais": [{"name": f"P{i}"} for i in range(1, 5)],
                         "deck_id": "standard"})
    for player in engine.game_state.players:
        player.hand.clear()
        player.equipment.clear()
    return engine


def handler_for(engine):
    return next(h for h in engine.skill_manager.handlers if isinstance(h, QunSkillHandler))


def card(tag, name, suit="spade", card_type="basic"):
    return Card(tag, name, suit, 7, card_type)


def test_liyu_decline_does_not_take_a_card():
    engine = game()
    handler = handler_for(engine)
    source, target = engine.game_state.players[:2]
    target.hand.append(card("b5_liyu_hold", "闪", "heart"))
    handler.has = lambda p, skill: p is source and skill == "利驭"
    engine.skill_manager.ask_confirm = AsyncMock(return_value=False)

    run(handler.after_damage(source, target, 1, card("b5_liyu_sha", "杀")))

    assert len(target.hand) == 1
    assert source.hand == []
    engine.skill_manager.ask_confirm.assert_awaited_once()


def test_liyu_takes_the_chosen_equipment_and_requests_duel_target():
    engine = game()
    handler = handler_for(engine)
    source, target, duel_target = engine.game_state.players[:3]
    weapon = card("b5_liyu_weapon", "青釭剑", card_type="equipment")
    target.equipment["weapon"] = weapon
    handler.has = lambda p, skill: p is source and skill == "利驭"
    engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
    engine.skill_manager.ask_choose_cards_result = AsyncMock(return_value={"status": "resolved", "cards": [weapon]})
    engine.skill_manager.ask_choose_players = AsyncMock(return_value=[duel_target])
    engine.skill_manager.duel = AsyncMock(return_value=True)

    run(handler.after_damage(source, target, 1, card("b5_liyu_sha2", "杀")))

    assert target.equipment == {}
    assert source.hand == [weapon]
    engine.skill_manager.ask_choose_cards_result.assert_awaited_once()
    engine.skill_manager.ask_choose_players.assert_awaited_once()
    assert engine.skill_manager.ask_confirm.await_args.args[0] is target
    assert engine.skill_manager.ask_choose_players.await_args.args[0] is target
    engine.skill_manager.duel.assert_awaited_once_with(source, duel_target, "利驭")


def test_guidao_decline_preserves_the_original_judgment_card():
    engine = game()
    handler = handler_for(engine)
    owner, judged = engine.game_state.players[:2]
    black = card("b5_guidao_black", "闪", "spade")
    original = card("b5_guidao_original", "桃", "heart")
    owner.hand.append(black)
    handler.has = lambda p, skill: p is owner and skill == "鬼道"
    engine.skill_manager.ask_confirm = AsyncMock(return_value=False)

    result = run(handler.before_judge(judged, original))

    assert result is original
    assert owner.hand == [black]
    assert original not in engine.game_state.discard_pile


def test_guidao_discards_selected_equipment_and_takes_original_judgment():
    engine = game()
    handler = handler_for(engine)
    owner, judged = engine.game_state.players[:2]
    black = card("b5_guidao_equipment", "八卦阵", "club", "equipment")
    original = card("b5_guidao_displaced", "闪", "heart")
    owner.equipment["armor"] = black
    handler.has = lambda p, skill: p is owner and skill == "鬼道"
    engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
    engine.skill_manager.ask_choose_cards_result = AsyncMock(return_value={"status": "resolved", "cards": [black]})

    result = run(handler.before_judge(judged, original))

    assert result is black
    assert owner.equipment == {}
    assert owner.hand == [original]
    # The chosen replacement is in flight until the judgment resolves; it is
    # not prematurely copied into the discard pile here.
    assert black not in engine.game_state.discard_pile
    assert engine.skill_manager.ask_choose_cards_result.await_count == 1


def test_leiji_decline_does_not_perform_judgment():
    engine = game()
    handler = handler_for(engine)
    player = engine.game_state.players[0]
    handler.has = lambda p, skill: p is player and skill == "雷击"
    engine.skill_manager.ask_confirm = AsyncMock(return_value=False)
    engine.skill_manager.judge = AsyncMock()

    run(handler.on_card_responded(player, card("b5_leiji_shan", "闪"), "闪"))

    engine.skill_manager.ask_confirm.assert_awaited_once()
    engine.skill_manager.judge.assert_not_awaited()


def test_liyu_without_any_target_card_does_not_prompt():
    engine = game()
    handler = handler_for(engine)
    source, target = engine.game_state.players[:2]
    handler.has = lambda p, skill: p is source and skill == "利驭"
    engine.skill_manager.ask_confirm = AsyncMock()

    run(handler.after_damage(source, target, 1, card("b5_liyu_empty_sha", "杀")))

    engine.skill_manager.ask_confirm.assert_not_awaited()


def test_leiji_accepts_and_uses_the_selected_target_for_spade_result():
    engine = game()
    handler = handler_for(engine)
    player, chosen_target = engine.game_state.players[:2]
    handler.has = lambda p, skill: p is player and skill == "雷击"
    engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
    engine.skill_manager.judge = AsyncMock(return_value=card("b5_leiji_spade", "闪电", "spade", "trick"))
    engine.skill_manager.ask_choose_players = AsyncMock(return_value=[chosen_target])
    engine.card_system.damage = AsyncMock()

    run(handler.on_card_responded(player, card("b5_leiji_shan_yes", "闪"), "闪"))

    engine.skill_manager.ask_choose_players.assert_awaited_once()
    assert engine.skill_manager.ask_choose_players.await_args.args[0] is player
    engine.card_system.damage.assert_awaited_once_with(player, chosen_target, 2, context={"reason": "雷击"})


def test_leiji_also_prompts_when_lightning_is_used():
    engine = game()
    handler = handler_for(engine)
    player = engine.game_state.players[0]
    handler.has = lambda p, skill: p is player and skill == "雷击"
    engine.skill_manager.ask_confirm = AsyncMock(return_value=False)

    run(handler.after_card_used(player, card("b5_leiji_lightning", "闪电", "spade", "delayed_trick"), [], True))

    engine.skill_manager.ask_confirm.assert_awaited_once()
    assert engine.skill_manager.ask_confirm.await_args.args[0] is player


def test_biyue_decline_skips_optional_end_phase_draw():
    from game_engine.state_manager import Phase
    engine = game()
    handler = handler_for(engine)
    player = engine.game_state.players[0]
    handler.has = lambda p, skill: skill == "闭月"
    engine.skill_manager.ask_confirm = AsyncMock(return_value=False)
    engine.skill_manager.draw_cards = AsyncMock()

    run(handler.after_phase(player, Phase.END))

    engine.skill_manager.draw_cards.assert_not_awaited()
    engine.skill_manager.ask_confirm.assert_awaited_once()


def test_biyue_accepts_and_draws_two_when_hand_is_empty():
    from game_engine.state_manager import Phase
    engine = game()
    handler = handler_for(engine)
    player = engine.game_state.players[0]
    handler.has = lambda p, skill: skill == "闭月"
    engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
    engine.skill_manager.draw_cards = AsyncMock(return_value=[])

    run(handler.after_phase(player, Phase.END))

    engine.skill_manager.draw_cards.assert_awaited_once_with(player, 2, "闭月")


def test_biyue_draws_one_when_hand_is_not_empty():
    from game_engine.state_manager import Phase
    engine = game()
    handler = handler_for(engine)
    player = engine.game_state.players[0]
    player.hand.append(card("b5_biyue_hand", "闪"))
    handler.has = lambda p, skill: skill == "闭月"
    engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
    engine.skill_manager.draw_cards = AsyncMock(return_value=[])

    run(handler.after_phase(player, Phase.END))

    engine.skill_manager.draw_cards.assert_awaited_once_with(player, 1, "闭月")
