"""Server-owned history survives restarts and never awards a game twice."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from game_engine.game_history import WELCOME_CARDS, GameHistoryStore, HistoryCorruptError
from game_engine.protocol import ENGINE_EVENT
from game_server import GameServer


def result(winner="lord", identity="loyalist"):
    return {
        "winner": winner, "duration": 42,
        "state": {"players": [
            {"id": 0, "is_ai": False, "identity": identity, "hero_name": "界曹操",
             "stats": {"damage_dealt": 2}},
            {"id": 1, "is_ai": True, "identity": "rebel"},
        ]},
    }


def test_history_atomic_restart_rewards_and_duplicate_end(tmp_path):
    path = tmp_path / "history.json"
    store = GameHistoryStore(path)
    first = store.record_result("local_1", "game_1", result())
    assert first["player_won"] is True
    assert first["profile"]["win_streak"] == 1
    assert first["reward"] is None

    restarted = GameHistoryStore(path)
    second = restarted.record_result("local_1", "game_2", result())
    assert second["profile"]["win_streak"] == 2
    # 见面礼 1 张 + 连胜两局奖励 1 张
    assert second["profile"]["identity_cards"] == WELCOME_CARDS + 1
    assert second["reward"] == "identity_card"
    assert restarted.record_result("local_1", "game_2", result()) == second
    assert restarted.profile("local_1")["total_games"] == 2

    assert restarted.reserve_identity_card("local_1", "game_3") is True
    assert restarted.reserve_identity_card("local_1", "game_3") is True
    assert restarted.profile("local_1")["identity_cards"] == WELCOME_CARDS
    assert restarted.reserve_identity_card("local_1", "game_4") is True
    assert restarted.profile("local_1")["identity_cards"] == 0
    with pytest.raises(ValueError, match="身份卡不足"):
        restarted.reserve_identity_card("local_1", "game_5")

    interrupted = restarted.record_result("local_1", "game_3", result("aborted"))
    assert interrupted["profile"]["win_streak"] == 2
    assert interrupted["profile"]["history"][0]["status"] == "interrupted"
    drawn = restarted.record_result("local_1", "game_5", result("draw"))
    assert drawn["profile"]["win_streak"] == 0
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1


def test_identity_card_reservation_refunds_failed_start_once(tmp_path):
    store = GameHistoryStore(tmp_path / "history.json")
    store.record_result("local_1", "win_1", result())
    store.record_result("local_1", "win_2", result())
    assert store.profile("local_1")["identity_cards"] == WELCOME_CARDS + 1
    store.reserve_identity_card("local_1", "failed_start")
    assert store.refund_identity_card("local_1", "failed_start") is True
    assert store.refund_identity_card("local_1", "failed_start") is False
    assert store.profile("local_1")["identity_cards"] == WELCOME_CARDS + 1
    store.reserve_identity_card("local_1", "played")
    store.record_result("local_1", "played", result("aborted"))
    assert store.refund_identity_card("local_1", "played") is False


def test_corrupt_history_is_preserved_and_not_reset(tmp_path):
    path = tmp_path / "history.json"
    path.write_text("{broken", encoding="utf-8")
    store = GameHistoryStore(path)
    with pytest.raises(HistoryCorruptError):
        store.record_result("local_1", "game_1", result())
    assert path.read_text(encoding="utf-8") == "{broken"
    assert list(tmp_path.glob("history.json.corrupt.*"))


def test_server_game_end_forwards_persisted_receipt(tmp_path):
    server = GameServer(history_path=tmp_path / "history.json")

    class Socket:
        def __init__(self):
            self.messages = []

        async def send(self, text):
            self.messages.append(json.loads(text))

    ws = Socket()
    server.ws_map[ws] = "game_1"
    server.viewers["game_1"] = ws
    server.engines["game_1"] = SimpleNamespace(
        game_id="game_1", game_config={"profile_id": "local_1"}
    )
    asyncio.run(server._forward("game_1", ENGINE_EVENT.GAME_END)(**result()))
    message = ws.messages[-1]
    assert message["type"] == "game_end"
    assert message["profile"]["total_games"] == 1
    assert message["player_won"] is True
    assert GameHistoryStore(tmp_path / "history.json").profile("local_1")["total_games"] == 1


def aborted(rounds, human_alive):
    data = result("aborted")
    data["state"]["round"] = rounds
    data["state"]["players"][0]["alive"] = human_alive
    return data


def _streak_of(store, game_id, payload):
    return store.record_result("local_9", game_id, payload)["profile"]["win_streak"]


def test_abort_clears_streak_only_when_human_alive_after_grace(tmp_path):
    store = GameHistoryStore(tmp_path / "h.json")
    store.record_result("local_9", "w1", result())
    assert _streak_of(store, "a1", aborted(3, True)) == 0  # 存活中止 + 第 3 轮 → 清零


def test_abort_after_human_died_keeps_streak(tmp_path):
    store = GameHistoryStore(tmp_path / "h.json")
    store.record_result("local_9", "w1", result())
    receipt = store.record_result("local_9", "a1", aborted(3, False))
    assert receipt["profile"]["win_streak"] == 1
    assert receipt["player_won"] is None
    assert receipt["profile"]["history"][0]["status"] == "interrupted"


def test_abort_after_human_died_in_first_rounds_keeps_streak(tmp_path):
    store = GameHistoryStore(tmp_path / "h.json")
    store.record_result("local_9", "w1", result())
    assert _streak_of(store, "a1", aborted(1, False)) == 1


def test_every_profile_gets_one_welcome_card_exactly_once(tmp_path):
    path = tmp_path / "history.json"
    store = GameHistoryStore(path)
    assert store.profile("fresh")["identity_cards"] == WELCOME_CARDS  # 未落盘的新档案也显示见面礼
    store.reserve_identity_card("fresh", "g1")                       # 第一次写入时真正发放并立即使用
    assert store.profile("fresh")["identity_cards"] == WELCOME_CARDS - 1
    # 老档案（没有 welcome_card 标记）在下次读取时补发一次，之后不再重复
    data = json.loads(path.read_text(encoding="utf-8"))
    data["profiles"]["old"] = {"win_streak": 3, "total_games": 9, "identity_cards": 0, "history": []}
    path.write_text(json.dumps(data), encoding="utf-8")
    assert GameHistoryStore(path).profile("old")["identity_cards"] == WELCOME_CARDS
    assert GameHistoryStore(path).profile("old")["identity_cards"] == WELCOME_CARDS
