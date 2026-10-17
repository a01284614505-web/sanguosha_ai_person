"""A turn-limit draw must stay distinct from a victory in persisted history."""

import asyncio

from game_engine import MainEngine
from game_engine.game_history import GameHistoryStore


def test_turn_limit_draw_emits_once_and_breaks_streak(tmp_path):
    config = MainEngine.normalize_config({
        "mode": "5人身份局", "selected_hero": {"id": "liubei"},
        "ais": [{"name": f"AI{i}", "api_key": ""} for i in range(4)],
        "max_turns": 0, "phase_delay": 0, "turn_delay": 0,
    })
    engine = MainEngine(config)
    game_ends = []

    async def capture(**data):
        game_ends.append(data)

    engine.on("game_end", capture)
    assert asyncio.run(engine.run()) == "draw"
    assert len(game_ends) == 1
    assert game_ends[0]["winner"] == "draw"
    store = GameHistoryStore(tmp_path / "history.json")
    receipt = store.record_result("draw_profile", engine.game_id, game_ends[0])
    assert receipt["player_won"] is None
    assert receipt["reward"] is None
    assert receipt["profile"]["history"][0]["winner"] == "draw"
    assert receipt["profile"]["win_streak"] == 0
