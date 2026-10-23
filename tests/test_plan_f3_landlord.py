"""F3 third mode: three-player landlord backend contract."""

import asyncio
import logging
import random

import pytest

from game_engine import MainEngine
from game_engine.config_validator import normalize_config
from game_engine.identity_system import IdentitySystem
from game_engine.mode_registry import get_mode, supported_modes
from game_engine.state_manager import Phase


def config(**overrides):
    raw = {
        "mode": "斗地主", "player": {"name": "地主"},
        "ais": [{"name": "农民1", "api_key": ""}, {"name": "农民2", "api_key": ""}],
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


def test_landlord_metadata_fixed_open_roles_and_opening():
    spec = get_mode("斗地主")
    assert spec.identities == ("landlord", "farmer", "farmer")
    assert spec.player_count == 3 and spec.ai_count == 2
    assert spec.lord_hp_bonus == 1 and spec.draw_bonus_per_phase == 1
    assert spec.rebel_kill_draw == 0 and spec.lord_kills_loyalist_discards is False
    assert supported_modes()[3] == {
        "id": "斗地主", "player_count": 3, "ai_count": 2,
        "identity_pool": ["landlord", "farmer", "farmer"], "initial_hand": 4,
        "first_player_identity": "landlord", "lord_hp_bonus": 1,
        "turn_order": "seat_clockwise", "identities_public": True,
        "victory": "landlord", "draw_bonus_identity": "landlord",
        "draw_bonus_per_phase": 1,
    }
    engine = MainEngine(normalize_config(config()))
    assigned = IdentitySystem.assign_identities(engine.game_state.players, "斗地主")
    assert [player.identity for player in engine.game_state.players] == ["landlord", "farmer", "farmer"]
    assert all(player.identity_revealed for player in engine.game_state.players)
    assert assigned["first_player"] is engine.game_state.players[0]
    assert all(len(player.hand) == 4 for player in engine.game_state.players)


def test_landlord_rejects_wrong_count_and_identity_card():
    with pytest.raises(ValueError, match="需要2个AI"):
        normalize_config(config(ais=[]))
    engine = MainEngine(normalize_config(config()))
    with pytest.raises(ValueError, match="不支持身份卡"):
        IdentitySystem.assign_identities(
            engine.game_state.players, "斗地主", {"use": True, "identity": "lord"})


def test_landlord_victory_hp_bonus_draw_bonus_and_no_identity_rewards():
    async def scenario():
        engine = MainEngine(normalize_config(config()))
        players = engine.game_state.players
        assigned = IdentitySystem.assign_identities(players, "斗地主")
        landlord, farmer1, farmer2 = players
        original_max = landlord.max_hp
        # The run setup applies this declarative bonus to the explicit first player.
        first = assigned["first_player"]
        first.max_hp += get_mode("斗地主").lord_hp_bonus
        first.hp += get_mode("斗地主").lord_hp_bonus
        assert landlord.max_hp == original_max + 1 and landlord.hp == landlord.max_hp
        assert engine.phase_draw_count(landlord) == 3
        assert engine.phase_draw_count(farmer1) == 2

        before = len(landlord.hand)
        engine.game_state.current_player = landlord
        engine.game_state.current_phase = Phase.DRAW
        await engine.phase_controller.draw_phase()
        assert len(landlord.hand) == before + 3

        landlord.alive = False
        assert IdentitySystem.check_victory(players, "斗地主")["winner"] == "farmer"
        landlord.alive = True; farmer1.alive = farmer2.alive = False
        assert IdentitySystem.check_victory(players, "斗地主")["winner"] == "landlord"
        farmer1.alive = True
        assert IdentitySystem.check_victory(players, "斗地主") == {"game_over": False}

        before_hand = list(landlord.hand)
        farmer1.alive = False
        await engine.card_system._settle_identity_death(farmer1, landlord)
        assert landlord.hand == before_hand

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("hero_id", "expected_hand_gain", "expected_deck_loss"),
    [("zhouyu", 4, 4), ("zhangliao", 3, 1)],
)
def test_landlord_draw_bonus_composes_with_yingzi_and_tuxi(
        hero_id, expected_hand_gain, expected_deck_loss):
    async def scenario():
        random.seed(20263099)
        engine = MainEngine(normalize_config(config(selected_hero={"id": hero_id})))
        IdentitySystem.assign_identities(engine.game_state.players, "斗地主")
        landlord = engine.game_state.players[0]
        landlord.is_ai = True
        engine.game_state.current_player = landlord
        engine.game_state.current_phase = Phase.DRAW
        before_hand = len(landlord.hand)
        before_deck = len(engine.game_state.deck)
        await engine._execute_phase_with_ui(Phase.DRAW)
        assert len(landlord.hand) == before_hand + expected_hand_gain
        assert len(engine.game_state.deck) == before_deck - expected_deck_loss

    asyncio.run(scenario())


def test_landlord_draw_bonus_composes_with_luoyi_replacement():
    async def scenario():
        engine = MainEngine(normalize_config(config(selected_hero={"id": "xuchu"})))
        IdentitySystem.assign_identities(engine.game_state.players, "斗地主")
        landlord = engine.game_state.players[0]
        landlord.is_ai = True
        engine.game_state.current_player = landlord
        engine.game_state.current_phase = Phase.DRAW
        before_deck = len(engine.game_state.deck)
        await engine._execute_phase_with_ui(Phase.DRAW)
        # 裸衣仍亮三张并按原规则取牌，地主模式另摸一张。
        assert len(engine.game_state.deck) == before_deck - 4
        assert landlord.flags.get("luoyi_active") is True

    asyncio.run(scenario())


@pytest.mark.parametrize("game_index", range(10))
def test_ten_complete_landlord_rule_ai_games_preserve_cards_and_actions(game_index):
    async def scenario():
        random.seed(20263020 + game_index * 83)
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
        assert winner in {"landlord", "farmer", "draw"}
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
