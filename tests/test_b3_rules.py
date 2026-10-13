"""B3 公共规则的实体牌与时序场景。"""

import asyncio
from unittest.mock import AsyncMock

from game_engine import MainEngine
from game_engine.state_manager import Card, Phase, PlayerStatus


def run(coro):
    return asyncio.run(coro)


def game():
    engine = MainEngine({
        "mode": "5人身份局", "player_name": "真人",
        "ais": [{"name": f"AI{i}"} for i in range(1, 5)],
        "deck_id": "standard",
    })
    for player, identity in zip(engine.game_state.players,
                                ("lord", "loyalist", "rebel", "rebel", "spy")):
        player.identity = identity
        player.hand.clear()
        player.equipment.clear()
        player.judge_area.clear()
        player.shown.clear()
        player.temporary.clear()
    return engine


def card(tag, name, nature=None):
    return Card(tag, name, "spade", 5, "trick", nature=nature)


def test_delayed_wuxie_occurs_before_judgment_and_preserves_deck():
    engine = game()
    source, target = engine.game_state.players[:2]
    delayed = card("b3_lebu", "乐不思蜀")
    engine.game_state.discard_pile.append(delayed)
    engine.card_system.ask_wuxie = AsyncMock(return_value=True)

    assert run(engine.card_system.use_card(source, delayed, [target])) is True
    assert delayed in target.judge_area
    engine.card_system.ask_wuxie.assert_not_awaited()
    deck_top = engine.game_state.deck[0]
    run(engine.phase_controller.execute_judge(target, delayed))
    engine.card_system.ask_wuxie.assert_awaited_once()
    assert engine.game_state.deck[0] is deck_top
    assert delayed in engine.game_state.discard_pile
    assert delayed not in target.judge_area
    assert [move.to_zone for move in engine.game_state.card_move_events
            if move.card_id == delayed.id] == ["judge", "discard"]


def test_countered_lightning_passes_without_revealing_judge_card():
    engine = game()
    source, next_player = engine.game_state.players[:2]
    lightning = card("b3_lightning", "闪电")
    engine.game_state.discard_pile.append(lightning)
    engine.card_system.ask_wuxie = AsyncMock(return_value=True)
    assert run(engine.card_system.use_card(source, lightning)) is True
    deck_top = engine.game_state.deck[0]
    run(engine.phase_controller.execute_judge(source, lightning))
    assert lightning in next_player.judge_area
    assert lightning not in source.judge_area
    assert engine.game_state.deck[0] is deck_top
    assert [move.reason for move in engine.game_state.card_move_events
            if move.card_id == lightning.id] == ["place_lightning", "lightning_countered"]


def test_wine_is_scoped_to_turn_and_chain_coexists_with_turn_over():
    engine = game()
    first, second, third = engine.game_state.players[:3]
    engine.game_state.current_player = first
    engine.game_state.current_player_index = 0
    engine.game_state.current_phase = Phase.PLAY
    wine = Card("b3_wine", "酒", "diamond", 9, "basic")
    first.hand.append(wine)
    assert run(engine.card_system.use_jiu(first, wine)) is True
    assert engine.rules.can_play_card(first, wine, [])[0] is False
    first.status = PlayerStatus.TURNED
    first.chained = second.chained = third.chained = True
    fire = card("b3_fire", "杀", "fire")
    run(engine.card_system.damage(second, first, 1, card=fire))
    assert [p.hp for p in (first, second, third)] == [3, 3, 3]
    assert all(not p.chained for p in (first, second, third))
    assert first.status == PlayerStatus.TURNED
    assert first.jiu_buff is True
    engine.game_state.next_turn()
    assert first.jiu_buff is False
    assert first.jiu_used_this_turn is False


def test_death_cleans_zones_then_rewards_rebel_killer():
    engine = game()
    lord, _, rebel = engine.game_state.players[:3]
    held = Card("b3_death_hand", "杀", "spade", 3, "basic")
    equipped = Card("b3_death_armor", "八卦阵", "club", 2, "equipment")
    delayed = card("b3_death_judge", "乐不思蜀")
    rebel.hand.append(held)
    rebel.equipment["armor"] = equipped
    rebel.judge_area.append(delayed)
    rebel.hp = 1
    run(engine.card_system.damage(lord, rebel, 1))
    assert not rebel.alive
    assert not rebel.hand and not rebel.equipment and not rebel.judge_area
    assert len(lord.hand) == 3
    assert all(c in engine.game_state.discard_pile for c in (held, equipped, delayed))
    events = engine.game_state.card_move_events
    assert [e.to_zone for e in events[:3]] == ["discard"] * 3
    assert [e.reason for e in events[3:]] == ["kill_rebel_reward"] * 3
    assert engine.stats.row(lord)["kills"] == 1
    assert engine.game_state.game_over is False


def test_lord_killing_loyalist_discards_hand_and_equipment():
    engine = game()
    lord, loyalist = engine.game_state.players[:2]
    held = Card("b3_lord_hand", "杀", "spade", 3, "basic")
    equipped = Card("b3_lord_weapon", "青釭剑", "spade", 6, "equipment")
    lord.hand.append(held)
    lord.equipment["weapon"] = equipped
    loyalist.hp = 1
    run(engine.card_system.damage(lord, loyalist, 1))
    assert not lord.hand and not lord.equipment
    assert held in engine.game_state.discard_pile
    assert equipped in engine.game_state.discard_pile


def test_victory_is_set_at_death_before_turn_end():
    engine = game()
    lord, loyalist, first_rebel, second_rebel, spy = engine.game_state.players
    first_rebel.alive = second_rebel.alive = False
    spy.hp = 1
    run(engine.card_system.damage(loyalist, spy, 1))
    assert engine.game_state.game_over is True
    assert engine.game_state.winner == "lord"

    engine = game()
    lord, loyalist, first_rebel, second_rebel, spy = engine.game_state.players
    loyalist.alive = first_rebel.alive = second_rebel.alive = False
    lord.hp = 1
    run(engine.card_system.damage(spy, lord, 1))
    assert engine.game_state.game_over is True
    assert engine.game_state.winner == "spy"


def test_lethal_play_reports_success_and_counts_used_card():
    engine = game()
    lord, _, rebel = engine.game_state.players[:3]
    engine.game_state.current_player = rebel
    engine.game_state.current_player_index = 2
    engine.game_state.current_phase = Phase.PLAY
    rebel.equipment["weapon"] = Card("b3_lethal_weapon", "青釭剑", "spade", 6, "equipment")
    sha = Card("b3_lethal_sha", "杀", "heart", 7, "basic")
    rebel.hand.append(sha)
    lord.hp = 1
    assert run(engine.execute_action(rebel, {"type": "play_card", "card_index": 0}, [lord.id]))
    assert engine.game_state.winner == "rebel"
    assert engine.stats.row(rebel)["cards_played"] == 1
    assert sha in engine.game_state.discard_pile
