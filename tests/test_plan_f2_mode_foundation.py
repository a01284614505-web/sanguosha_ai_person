"""F2 keeps the current mode behavior while making its rules declarative."""

import pytest

from game_engine import MainEngine
from game_engine.config_validator import normalize_config, sanitize_client_config
from game_engine.identity_system import IdentitySystem
from game_engine.mode_registry import get_mode, supported_modes


def config(ai_count=4, mode="5人身份局"):
    return {"mode": mode, "player_name": "P0",
            "ais": [{"name": f"P{i}"} for i in range(1, ai_count + 1)]}


def test_only_fully_implemented_mode_is_advertised_with_rule_metadata():
    rows = supported_modes()
    assert rows == [{
        "id": "5人身份局", "player_count": 5, "ai_count": 4,
        "identity_pool": ["lord", "loyalist", "rebel", "rebel", "spy"],
        "initial_hand": 4, "first_player_identity": "lord",
        "lord_hp_bonus": 1, "turn_order": "seat_clockwise",
    }]
    info = MainEngine.server_info()
    assert info["supported_modes"] == ["5人身份局"]
    assert info["modes"] == rows


def test_config_player_count_comes_from_mode_and_client_cannot_override_budgets():
    assert len(normalize_config(config())["ais"]) == get_mode("5人身份局").ai_count
    with pytest.raises(ValueError, match="需要4个AI"):
        normalize_config(config(ai_count=3))
    with pytest.raises(ValueError, match="暂不支持模式"):
        normalize_config(config(mode="8人身份局"))
    cleaned = sanitize_client_config({**config(), "session_variable_max_chars": 999999})
    assert "session_variable_max_chars" not in cleaned


def test_setup_identity_opening_and_victory_keep_current_five_player_contract():
    normalized = normalize_config(config())
    engine = MainEngine(normalized)
    spec = get_mode(engine.game_state.mode)
    assert len(engine.game_state.players) == spec.player_count
    assert all(len(player.hand) == spec.initial_hand for player in engine.game_state.players)
    assigned = IdentitySystem.assign_identities(engine.game_state.players, engine.game_state.mode)
    assert sorted(player.identity for player in engine.game_state.players) == sorted(spec.identities)
    lord = assigned[spec.first_player_identity]
    for player in engine.game_state.players:
        player.alive = player is lord
    assert IdentitySystem.check_victory(engine.game_state.players, engine.game_state.mode) == {
        "game_over": True, "winner": "lord", "message": "主公和忠臣获胜！",
    }
