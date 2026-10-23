"""F3 second mode: four-seat alternating-team 2v2 backend contract."""

import asyncio
import logging
import random

import pytest

from game_engine import MainEngine
from game_engine.config_validator import normalize_config
from game_engine.identity_system import IdentitySystem
from game_engine.mode_registry import get_mode, supported_modes


def config(**overrides):
    raw = {
        "mode": "2v2", "player": {"name": "A1"},
        "ais": [{"name": name, "api_key": ""} for name in ("B1", "A2", "B2")],
        "deck_id": "standard", "max_turns": 120, "phase_delay": 0, "turn_delay": 0,
    }
    raw.update(overrides)
    return raw


def all_cards(state):
    cards = list(state.deck) + list(state.discard_pile)
    for player in state.players:
        cards.extend(player.hand)
        cards.extend(player.equipment.values())
        cards.extend(player.judge_area)
        cards.extend(player.shown)
        cards.extend(player.temporary)
        cards.extend(player.treasure_cards)
    return cards


def test_two_v_two_metadata_config_fixed_seats_and_open_teams():
    spec = get_mode("2v2")
    assert spec.identities == ("team_a", "team_b", "team_a", "team_b")
    assert spec.player_count == 4 and spec.ai_count == 3
    assert spec.initial_hand == 4 and spec.lord_hp_bonus == 0
    assert spec.rebel_kill_draw == 0 and spec.lord_kills_loyalist_discards is False
    assert supported_modes()[2] == {
        "id": "2v2", "player_count": 4, "ai_count": 3,
        "identity_pool": ["team_a", "team_b", "team_a", "team_b"],
        "initial_hand": 4, "first_player_identity": "team_a", "lord_hp_bonus": 0,
        "turn_order": "seat_clockwise", "identities_public": True,
        "victory": "team_elimination",
        "draw_bonus_identity": None, "draw_bonus_per_phase": 0,
    }
    engine = MainEngine(normalize_config(config()))
    assigned = IdentitySystem.assign_identities(engine.game_state.players, "2v2")
    assert [player.identity for player in engine.game_state.players] == list(spec.identities)
    assert all(player.identity_revealed for player in engine.game_state.players)
    assert assigned["first_player"] is engine.game_state.players[0]
    assert all(len(player.hand) == 4 for player in engine.game_state.players)


def test_two_v_two_rejects_wrong_player_count_and_identity_card():
    with pytest.raises(ValueError, match="需要3个AI"):
        normalize_config(config(ais=[]))
    engine = MainEngine(normalize_config(config()))
    with pytest.raises(ValueError, match="不支持身份卡"):
        IdentitySystem.assign_identities(
            engine.game_state.players, "2v2", {"use": True, "identity": "lord"})


def test_two_v_two_team_elimination_and_no_identity_kill_rewards():
    async def scenario():
        engine = MainEngine(normalize_config(config()))
        players = engine.game_state.players
        IdentitySystem.assign_identities(players, "2v2")
        a1, b1, a2, b2 = players
        b1.alive = b2.alive = False
        assert IdentitySystem.check_victory(players, "2v2") == {
            "game_over": True, "winner": "team_a", "message": "A队获胜！"}
        b1.alive = b2.alive = True; a1.alive = a2.alive = False
        assert IdentitySystem.check_victory(players, "2v2")["winner"] == "team_b"
        a1.alive = a2.alive = b1.alive = True
        assert IdentitySystem.check_victory(players, "2v2") == {"game_over": False}

        # Death settlement has neither rebel draw nor lord/loyalist discard in this mode.
        before_hand = list(a1.hand)
        b1.alive = False
        await engine.card_system._settle_identity_death(b1, a1)
        assert a1.hand == before_hand

    asyncio.run(scenario())


def test_two_v_two_round_anchor_moves_when_a_first_seat_dies():
    engine = MainEngine(normalize_config(config()))
    players = engine.game_state.players
    IdentitySystem.assign_identities(players, "2v2")
    engine.game_state.current_player = players[0]
    engine.game_state.current_player_index = 0
    engine.game_state.round_anchor_index = 0
    players[0].alive = False
    engine.on_player_death(players[0])
    assert engine.game_state.round_anchor_index == 1
    before = engine.game_state.round_number
    engine.game_state.next_turn()
    assert engine.game_state.current_player is players[1]
    assert engine.game_state.round_number == before + 1


@pytest.mark.parametrize("game_index", range(10))
def test_ten_complete_two_v_two_rule_ai_games_preserve_cards_and_actions(game_index):
    async def scenario():
        random.seed(20262020 + game_index * 89)
        engine = MainEngine(normalize_config(config()))
        for player in engine.game_state.players:
            player.is_ai = True
        game_ends = []
        invalid_actions = []
        declined_skills = []
        engine.on("game_end", lambda **data: game_ends.append(data))
        original_execute = engine.execute_action

        async def checked_execute(player, action, target_ids=None):
            accepted = await original_execute(player, action, target_ids)
            if not accepted:
                detail = {"actor": player.id, "action": action, "targets": target_ids}
                if action.get("skill_name") == "激将" and action.get("variant") == "borrow_sha":
                    declined_skills.append(detail)
                else:
                    invalid_actions.append(detail)
            return accepted

        engine.execute_action = checked_execute
        winner = await engine.run()
        physical = all_cards(engine.game_state)
        ids = [card.id for card in physical]
        assert winner in {"team_a", "team_b", "draw"}
        assert len(game_ends) == 1
        assert not invalid_actions
        assert len(ids) == engine.game_state.initial_deck_count == 108
        assert len(ids) == len(set(ids))
        assert engine.game_state.current_player_index in range(4)
        return winner, engine.completed_turns

    logging.disable(logging.CRITICAL)
    try:
        winner, turns = asyncio.run(scenario())
    finally:
        logging.disable(logging.NOTSET)
    assert turns <= 120
