"""B5 场景：吴国触发技把牌与目标选择交给技能持有者。"""

import asyncio
from unittest.mock import AsyncMock

from game_engine import MainEngine
from game_engine.state_manager import Card
from game_engine.skill_runtime_core import once_per_turn
from game_engine.skills_wu import WuSkillHandler


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


def get_wu(engine):
    return next(handler for handler in engine.skill_manager.handlers
                if isinstance(handler, WuSkillHandler))


def card(tag, name, suit="spade", card_type="basic"):
    return Card(tag, name, suit, 7, card_type)


def test_fenwei_decline_does_not_consume_limited_skill():
    engine = game()
    handler = get_wu(engine)
    owner, *targets = engine.game_state.players
    handler.has = lambda player, name: name == "奋威"
    owner.flags["limited_skills"] = set()
    engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
    engine.skill_manager.ask_choose_players = AsyncMock(return_value=[])
    trick = card("b5_fenwei_trick", "万箭齐发", card_type="trick")

    result = run(handler.before_multi_target_trick(owner, trick, targets[:2]))

    assert result == targets[:2]
    assert "奋威" not in owner.flags["limited_skills"]
    engine.skill_manager.ask_confirm.assert_awaited_once()
    engine.skill_manager.ask_choose_players.assert_awaited_once()


def test_fenwei_selects_exact_targets_before_spending_limited_skill():
    engine = game()
    handler = get_wu(engine)
    owner, *targets = engine.game_state.players
    handler.has = lambda player, name: name == "奋威"
    owner.flags["limited_skills"] = set()
    engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
    engine.skill_manager.ask_choose_players = AsyncMock(return_value=[targets[1]])
    trick = card("b5_fenwei_trick2", "万箭齐发", card_type="trick")

    result = run(handler.before_multi_target_trick(owner, trick, targets[:3]))

    assert result == [targets[0], targets[2]]
    assert "奋威" in owner.flags["limited_skills"]
    request = engine.skill_manager.ask_choose_players.await_args
    assert request.args[2] == targets[:3]
    assert (request.kwargs["min_n"], request.kwargs["max_n"]) == (1, 3)


def test_liuli_requests_cost_and_target_then_discards_selected_equipment():
    engine = game()
    handler = get_wu(engine)
    source, target, alternative = engine.game_state.players[:3]
    handler.has = lambda player, name: name == "流离"
    armor = card("b5_liuli_armor", "仁王盾", "club", "equipment")
    target.equipment["armor"] = armor
    engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
    engine.skill_manager.ask_choose_cards_result = AsyncMock(return_value={
        "status": "resolved", "cards": [armor],
    })
    engine.skill_manager.ask_choose_players = AsyncMock(return_value=[alternative])
    engine.card_system.notify_card_to_discard = AsyncMock()
    sha = card("b5_liuli_sha", "杀")

    result = run(handler.before_card_target(source, target, sha))

    assert result is alternative
    assert target.equipment == {}
    assert armor in engine.game_state.discard_pile
    move = next(m for m in engine.game_state.card_move_events if m.card_id == armor.id)
    assert (move.from_zone, move.to_zone, move.from_owner) == (
        "equipment", "discard", target.id)
    assert engine.skill_manager.ask_choose_cards_result.await_count == 1
    assert engine.skill_manager.ask_choose_players.await_count == 1


def test_gongxin_lets_owner_pick_a_heart_and_cancel_uses_no_turn():
    engine = game()
    handler = get_wu(engine)
    player, target = engine.game_state.players[:2]
    handler.has = lambda owner, name: name == "攻心"
    first = card("b5_gongxin_heart1", "杀", "heart")
    chosen = card("b5_gongxin_heart2", "闪", "heart")
    target.hand.extend([first, chosen])
    engine.skill_manager.ask_choose_cards_result = AsyncMock(return_value={
        "status": "cancelled", "cards": [],
    })

    result = run(handler.execute(player, {"skill_name": "攻心"}, [target]))

    assert result is False
    assert target.hand == [first, chosen]
    assert player.hand == []
    assert not once_per_turn(player, "攻心")


def test_gongxin_moves_the_chosen_heart_and_only_then_marks_use():
    engine = game()
    handler = get_wu(engine)
    player, target = engine.game_state.players[:2]
    handler.has = lambda owner, name: name == "攻心"
    first = card("b5_gongxin_heart3", "杀", "heart")
    chosen = card("b5_gongxin_heart4", "闪", "heart")
    target.hand.extend([first, chosen])
    engine.skill_manager.ask_choose_cards_result = AsyncMock(return_value={
        "status": "resolved", "cards": [chosen],
    })

    result = run(handler.execute(player, {"skill_name": "攻心"}, [target]))

    assert result is True
    assert target.hand == [first]
    assert player.hand == [chosen]
    assert once_per_turn(player, "攻心")
    move = next(m for m in engine.game_state.card_move_events if m.card_id == chosen.id)
    assert (move.from_owner, move.to_owner, move.from_zone, move.to_zone) == (
        target.id, player.id, "hand", "hand")


def test_keji_can_decline_and_preserves_default_discard_phase():
    engine = game()
    handler = get_wu(engine)
    player = engine.game_state.players[0]
    handler.has = lambda p, name: name == "克己"
    player.flags["sha_used_this_turn"] = False
    engine.skill_manager.ask_confirm = AsyncMock(return_value=False)

    result = run(handler.before_phase(player, __import__("game_engine.state_manager", fromlist=["Phase"]).Phase.DISCARD))

    assert result is None
    engine.skill_manager.ask_confirm.assert_awaited_once()


def test_botu_decline_does_not_schedule_extra_turn():
    from game_engine.state_manager import Phase
    engine = game()
    handler = get_wu(engine)
    player = engine.game_state.players[0]
    handler.has = lambda p, name: name == "博图"
    player.flags["turn_discard_suits"] = {"spade", "club", "heart", "diamond"}
    engine.skill_manager.ask_confirm = AsyncMock(return_value=False)

    run(handler.after_phase(player, Phase.END))

    assert not player.flags.get("extra_turn")
    engine.skill_manager.ask_confirm.assert_awaited_once()


def test_lianying_decline_does_not_draw_for_anyone():
    engine = game()
    handler = get_wu(engine)
    player = engine.game_state.players[0]
    handler.has = lambda p, name: name == "连营"
    engine.skill_manager.ask_confirm = AsyncMock(return_value=False)
    engine.skill_manager.draw_cards = AsyncMock()

    run(handler.on_cards_lost(player, [card("b5_lianying", "闪")]))

    engine.skill_manager.draw_cards.assert_not_awaited()


def test_qinxue_choice_is_asked_after_forced_awakening():
    engine = game()
    handler = get_wu(engine)
    player = engine.game_state.players[0]
    handler.has = lambda p, name: name == "勤学"
    player.hand = [card(f"b5_qinxue_{i}", "杀") for i in range(6)]
    engine.skill_manager.ask_choose_option = AsyncMock(return_value={"key": "draw"})
    engine.skill_manager.draw_cards = AsyncMock(return_value=[])

    run(handler._try_qinxue(player))

    assert player.max_hp == 3
    engine.skill_manager.ask_choose_option.assert_awaited_once()
    engine.skill_manager.draw_cards.assert_awaited_once_with(player, 2, "勤学")
