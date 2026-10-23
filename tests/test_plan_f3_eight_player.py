"""F3 first mode: eight-player identity game backend contract."""

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
        "mode": "8人身份局", "player": {"name": "P0"},
        "ais": [{"name": f"P{i}", "api_key": ""} for i in range(1, 8)],
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


def test_eight_player_mode_metadata_config_and_identity_pool():
    spec = get_mode("8人身份局")
    assert spec.player_count == 8 and spec.ai_count == 7
    assert spec.identities.count("lord") == 1
    assert spec.identities.count("loyalist") == 2
    assert spec.identities.count("rebel") == 4
    assert spec.identities.count("spy") == 1
    assert supported_modes()[1] == {
        "id": "8人身份局", "player_count": 8, "ai_count": 7,
        "identity_pool": list(spec.identities), "initial_hand": 4,
        "first_player_identity": "lord", "lord_hp_bonus": 1,
        "turn_order": "seat_clockwise",
        "identities_public": False, "victory": "identity",
        "draw_bonus_identity": None, "draw_bonus_per_phase": 0,
    }
    normalized = normalize_config(config())
    engine = MainEngine(normalized)
    assert len(engine.game_state.players) == 8
    assert all(len(player.hand) == 4 for player in engine.game_state.players)
    assert len({player.hero["id"] for player in engine.game_state.players}) == 8


@pytest.mark.parametrize("requested", ["lord", "loyalist", "rebel", "spy"])
def test_eight_player_identity_card_preserves_exact_pool_and_public_lord(requested):
    random.seed(80300 + len(requested))
    engine = MainEngine(normalize_config(config()))
    assigned = IdentitySystem.assign_identities(
        engine.game_state.players, "8人身份局", {"use": True, "identity": requested})
    identities = [player.identity for player in engine.game_state.players]
    assert identities[0] == requested
    assert sorted(identities) == sorted(get_mode("8人身份局").identities)
    assert len(assigned["loyalist"]) == 2 and len(assigned["rebel"]) == 4
    assert len(assigned["spy"]) == 1
    assert [player.identity_revealed for player in engine.game_state.players].count(True) == 1
    assert assigned["lord"].identity_revealed is True


def test_eight_player_victory_contract_is_same_identity_ruleset():
    engine = MainEngine(normalize_config(config()))
    players = engine.game_state.players
    for player, identity in zip(players, get_mode("8人身份局").identities):
        player.identity = identity
    lord = players[0]
    for player in players:
        player.alive = player.identity in {"lord", "loyalist"}
    assert IdentitySystem.check_victory(players, "8人身份局")["winner"] == "lord"

    for player in players:
        player.alive = player.identity == "spy"
    assert IdentitySystem.check_victory(players, "8人身份局")["winner"] == "spy"

    lord.alive = False
    players[3].alive = True
    assert IdentitySystem.check_victory(players, "8人身份局")["winner"] == "rebel"


def test_eight_player_rebel_reward_and_lord_loyalist_penalty_use_mode_rules():
    async def scenario():
        engine = MainEngine(normalize_config(config()))
        players = engine.game_state.players
        lord, loyalist, _loyalist2, rebel, *_ = players
        for player, identity in zip(players, get_mode("8人身份局").identities):
            player.identity = identity
            player.is_ai = True
        # Remove rescue uncertainty while keeping every physical card in a managed zone.
        for player in players:
            if player is lord:
                continue
            engine.game_state.deck.extend(player.hand)
            player.hand.clear()
        lord_count = len(lord.hand)
        rebel.hp = 1
        await engine.card_system.damage(lord, rebel, 1)
        assert not rebel.alive
        assert len(lord.hand) == lord_count + 3

        # A fresh table isolates the loyalist penalty from the previous reward.
        engine = MainEngine(normalize_config(config()))
        players = engine.game_state.players
        lord, loyalist = players[:2]
        for player, identity in zip(players, get_mode("8人身份局").identities):
            player.identity = identity
            player.is_ai = True
        for player in players:
            if player is lord:
                continue
            engine.game_state.deck.extend(player.hand)
            player.hand.clear()
        assert lord.hand
        loyalist.hp = 1
        await engine.card_system.damage(lord, loyalist, 1)
        assert not loyalist.alive
        assert lord.hand == [] and lord.equipment == {}

    asyncio.run(scenario())


@pytest.mark.parametrize("game_index", range(10))
def test_ten_complete_eight_player_rule_ai_games_preserve_cards_and_actions(game_index):
    async def scenario():
        random.seed(20261020 + game_index * 97)
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
        cards = all_cards(engine.game_state)
        ids = [card.id for card in cards]
        assert winner in {"lord", "rebel", "spy", "draw"}
        assert len(game_ends) == 1
        assert not invalid_actions
        assert len(ids) == engine.game_state.initial_deck_count == 108
        assert len(ids) == len(set(ids))
        return winner, engine.completed_turns

    logging.disable(logging.CRITICAL)
    try:
        winner, turns = asyncio.run(scenario())
    finally:
        logging.disable(logging.NOTSET)
    assert turns <= 120
