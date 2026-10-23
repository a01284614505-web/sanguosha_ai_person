"""The four C-batch ablation controls all use the production choice entrypoint."""

import pytest

from game_engine import MainEngine


@pytest.fixture
def engine():
    return MainEngine({
        "mode": "5人身份局", "player_name": "P0",
        "ais": [{"name": f"AI{i}"} for i in range(1, 5)],
    })


@pytest.mark.parametrize(
    "knobs,expected_confirm,expected_target",
    [
        ({"skill_strategy": False, "target_strategy": False}, [1], [0]),
        ({"skill_strategy": True, "target_strategy": False}, [0], [0]),
        ({"skill_strategy": False, "target_strategy": True}, [1], [1]),
        ({"skill_strategy": True, "target_strategy": True}, [0], [1]),
    ],
)
def test_four_ablation_modes_toggle_skill_cost_and_public_target_strategy(
        engine, knobs, expected_confirm, expected_target):
    player = engine.game_state.players[0]
    player.identity = "lord"
    engine.game_config["ai_ablation"] = dict(knobs)
    confirm = {"kind": "confirm", "skill_name": "天妒", "default": False}
    target = {
        "kind": "choose_players", "candidate_ids": [1, 2],
        "min_n": 1, "max_n": 1, "context": {"intent": "harm", "all_players": [
            {"id": 1, "name": "忠臣", "identity": "loyalist", "alive": True, "hp": 3},
            {"id": 2, "name": "反贼", "identity": "rebel", "alive": True, "hp": 3},
        ]},
    }

    assert engine.ai_decision.simple_choice_decision(player, confirm) == expected_confirm
    assert engine.ai_decision.simple_choice_decision(player, target) == expected_target


def test_missing_ablation_fields_keep_formal_enhanced_strategy_enabled(engine):
    player = engine.game_state.players[0]
    player.identity = "lord"
    engine.game_config.pop("ai_ablation", None)
    confirm = {"kind": "confirm", "skill_name": "天妒", "default": False}
    target = {
        "kind": "choose_players", "candidate_ids": [1, 2],
        "min_n": 1, "max_n": 1, "context": {"intent": "harm", "all_players": [
            {"id": 1, "identity": "loyalist", "alive": True, "hp": 3},
            {"id": 2, "identity": "rebel", "alive": True, "hp": 3},
        ]},
    }
    assert engine.ai_decision.simple_choice_decision(player, confirm) == [0]
    assert engine.ai_decision.simple_choice_decision(player, target) == [1]
