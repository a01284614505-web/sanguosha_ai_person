"""New mode outcomes and seven AI seats must survive the P5 profile store."""

import asyncio
import json

from game_engine.game_history import GameHistoryStore
from game_server import GameServer


def result(winner, identities):
    return {"winner": winner, "state": {"round": 3, "players": [
        {"id": i, "is_ai": i != 0, "identity": identity,
         "name": f"P{i}", "hero_name": f"H{i}", "ai_id": f"ai_{i}" if i else None,
         "stats": {}}
        for i, identity in enumerate(identities)
    ]}}


def test_team_and_landlord_results_update_human_and_ai_records(tmp_path):
    store = GameHistoryStore(tmp_path / "history.json")
    team = store.record_result("profile", "team-game", result(
        "team_a", ["team_a", "team_b", "team_a", "team_b"]))
    assert team["player_won"] is True
    assert team["profile"]["win_streak"] == 1
    accounts = {row["id"]: row for row in store.ai_players("profile")}
    assert accounts["ai_2"]["history"][0]["won"] is True
    assert accounts["ai_1"]["history"][0]["won"] is False

    farmers = store.record_result("profile", "farmer-game", result(
        "farmer", ["landlord", "farmer", "farmer"]))
    assert farmers["player_won"] is False
    assert farmers["profile"]["win_streak"] == 0
    assert store.ai_players("profile")[0]["history"][0]["won"] is True


def test_eight_player_server_can_create_and_keep_all_seven_ai_profiles(tmp_path):
    class Socket:
        def __init__(self):
            self.messages = []

        async def send(self, raw):
            self.messages.append(json.loads(raw))

    async def scenario():
        server = GameServer(history_path=tmp_path / "history.json",
                            recovery_path=tmp_path / "recovery")
        socket = Socket()
        await server.do_create(socket, {
            "mode": "8人身份局", "profile_id": "eight_profile",
            "player": {"name": "真人"},
            "ais": [{"name": f"P{i}", "api_key": ""} for i in range(1, 8)],
        })
        assert socket.messages[0]["type"] == "game_created"
        gid = socket.messages[0]["game_id"]
        engine = server.engines[gid]
        assert [player.ai_config["ai_id"] for player in engine.game_state.players[1:]] == [
            f"ai_{i}" for i in range(1, 8)]
        assert len(server.history.ai_players("eight_profile", count=7)) == 7
        server.tasks[gid].cancel()
        await asyncio.gather(server.tasks[gid], return_exceptions=True)

    asyncio.run(scenario())
