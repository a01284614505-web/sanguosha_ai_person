"""B7 batch regressions: a legal failed fire attack stays spent; treasure Wuxie responds."""

import asyncio
from unittest.mock import AsyncMock

from game_engine import MainEngine
from game_engine.state_manager import Card, Phase


def make_engine():
    config = MainEngine.normalize_config({
        "mode": "5人身份局", "selected_hero": {"id": "liubei"},
        "ais": [{"name": f"AI{i}", "api_key": ""} for i in range(4)],
        "deck_id": "extra", "phase_delay": 0, "turn_delay": 0,
    })
    engine = MainEngine(config)
    for player in engine.game_state.players:
        player.hand.clear()
        player.equipment.clear()
        player.treasure_cards.clear()
    engine.game_state.current_player = engine.game_state.players[0]
    engine.game_state.current_phase = Phase.PLAY
    return engine


def test_fire_attack_target_selects_shown_card_and_no_match_spends_attack():
    engine = make_engine()
    source, target = engine.game_state.players[:2]
    attack = Card("fire_attack", "火攻", "heart", 2, "trick")
    black = Card("fire_black", "杀", "spade", 7, "basic")
    red = Card("fire_red", "闪", "diamond", 9, "basic")
    source.hand.append(attack)
    target.hand.extend([black, red])
    engine.ask_choose_cards = AsyncMock(return_value=[red])
    action = next(item for item in engine.get_available_actions(source)
                  if item.get("type") == "play_card" and item.get("card_index") == 0)
    assert asyncio.run(engine.execute_action(source, action, [target.id])) is True
    assert engine.ask_choose_cards.await_args.args[0] is target
    assert attack in engine.game_state.discard_pile
    assert attack not in source.hand
    assert target.hp == target.max_hp


def test_wuxie_in_muniu_treasure_zone_is_consumed_once():
    engine = make_engine()
    source, responder = engine.game_state.players[:2]
    responder.equipment["treasure"] = Card("wood", "木牛流马", "diamond", 5, "equipment")
    wuxie = Card("wood_wuxie", "无懈可击", "spade", 10, "trick")
    responder.treasure_cards.append(wuxie)
    engine.card_system.responder = AsyncMock(return_value={
        "bool": True, "card": wuxie, "owner": responder,
        "source_zone": "treasure", "as_name": "无懈可击",
    })
    cancelled = asyncio.run(engine.card_system.ask_wuxie(
        Card("test_trick", "无中生有", "heart", 7, "trick"), source, [source],
    ))
    assert cancelled is True
    assert wuxie not in responder.treasure_cards
    assert wuxie in engine.game_state.discard_pile
    assert sum(card is wuxie for card in engine.game_state.discard_pile) == 1
