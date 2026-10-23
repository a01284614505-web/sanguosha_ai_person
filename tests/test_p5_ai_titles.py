from game_engine.game_history import GameHistoryStore
from game_engine.ai_titles import NO_TITLE, title_view, update_player_stats
from game_engine.cognitive_notes import CognitiveNotes
from game_engine.main_engine import MainEngine
from game_server import GameServer
from types import SimpleNamespace


def result_payload(*, winner="lord", ai_identity="loyalist", cheat=False, mvp_id=1, hidden=None):
    players = [
        {"id": 0, "is_ai": False, "identity": "lord", "alive": True, "hero_name": "真人武将", "stats": {}},
        {"id": 1, "is_ai": True, "ai_id": "ai_1", "name": "诸葛村夫", "identity": ai_identity,
         "alive": True, "hero_name": "AI武将", "stats": {}},
        {"id": 2, "is_ai": True, "ai_id": "ai_2", "name": "曹操的粉丝", "identity": "rebel",
         "alive": True, "hero_name": "AI武将2", "stats": {}},
        {"id": 3, "is_ai": True, "ai_id": "ai_3", "name": "小乔我老婆", "identity": "rebel",
         "alive": True, "hero_name": "AI武将3", "stats": {}},
        {"id": 4, "is_ai": True, "ai_id": "ai_4", "name": "酒馆常客", "identity": "spy",
         "alive": True, "hero_name": "AI武将4", "stats": {}},
    ]
    return {"winner": winner, "cheat": cheat, "state": {"round": 5, "players": players},
            "mvp": {"player_id": mvp_id}, "_title_hidden_players": hidden if hidden is not None else [],
            "spy_duel_lord": winner == "spy"}


def test_ai_title_award_and_result_are_idempotent(tmp_path):
    store = GameHistoryStore(tmp_path / "history.json")
    store.update_ai_player("profile", "ai_1", name="持久选手")
    first_payload = result_payload()
    first_payload["state"]["players"][1]["name"] = "持久选手"
    first = store.record_result("profile", "game-1", first_payload)
    assert store.ai_players("profile")[0]["name"] == "持久选手"
    second = store.record_result("profile", "game-2", result_payload())
    assert any(a["ai_id"] == "ai_1" and a["title"]["id"] == "streak_2" for a in second["ai_title_awards"])
    repeated = store.record_result("profile", "game-2", result_payload())
    assert repeated == second
    profile = store.ai_players("profile")[0]
    assert profile["stats"]["win_streak"] == 2
    assert profile["stats"]["wins"] == 2
    assert profile["titles"]["equipped"]["id"] == "streak_2"
    assert first["ai_title_awards"] == []


def test_cheat_games_do_not_change_title_stats_or_ai_history(tmp_path):
    store = GameHistoryStore(tmp_path / "history.json")
    store.record_result("profile", "cheat", result_payload(cheat=True))
    assert store.ai_players("profile")[0]["stats"] == {}
    assert store.ai_players("profile")[0]["history"] == []
    assert "title_stats" not in store.profile("profile")


def test_high_confidence_identity_guess_blocks_deep_cover(tmp_path):
    store = GameHistoryStore(tmp_path / "history.json")
    payload = result_payload(winner="lord", ai_identity="loyalist", hidden=[0, 2, 3, 4])
    store.record_result("profile", "game", payload)
    assert store.ai_players("profile")[0]["stats"].get("deep_cover_wins", 0) == 0


def test_ai_title_equipping_requires_earned_title(tmp_path):
    store = GameHistoryStore(tmp_path / "history.json")
    try:
        store.update_ai_player("profile", "ai_1", equipped_title="streak_2")
    except ValueError as exc:
        assert "已获得" in str(exc)
    else:
        raise AssertionError("uneared title should be rejected")


def test_no_title_is_distinct_from_auto_highest():
    stats = {"win_streak": 2}
    assert title_view(stats)["equipped"]["id"] == "streak_2"
    assert title_view(stats, NO_TITLE)["equipped"] is None


def test_ai_rosters_are_scoped_to_browser_profile(tmp_path):
    store = GameHistoryStore(tmp_path / "history.json")
    store.update_ai_player("profile-a", "ai_1", name="甲")
    assert store.ai_players("profile-a")[0]["name"] == "甲"
    assert store.ai_players("profile-b")[0]["name"] == "诸葛村夫"


def test_old_profiles_without_ai_roster_are_upgraded_on_read(tmp_path):
    path = tmp_path / "history.json"
    path.write_text('{"schema_version":1,"profiles":{"old":{"win_streak":2,"total_games":3,"identity_cards":0,"history":[]}},"games":{},"card_uses":{}}', encoding="utf-8")
    store = GameHistoryStore(path)
    assert store.ai_players("old")[0]["id"] == "ai_1"
    assert store.profile("old")["total_games"] == 3


def test_deep_cover_needs_complete_public_round_coverage_and_ignores_lord():
    target = SimpleNamespace(id=1, seat=4, identity="loyalist")
    engine = SimpleNamespace(
        game_state=SimpleNamespace(players=[target], round_number=2, _public_seats={1: 4}),
        notes=SimpleNamespace(snapshots=[
                {"round": 1, "player_id": 9, "seat": 2, "judged_seats": [4], "notes": {"4": {"guess": "unknown", "conf": "低", "locked": False}}},
                {"round": 2, "player_id": 9, "seat": 2, "judged_seats": [4], "notes": {"4": {"guess": "rebel", "conf": "中", "locked": False}}},
        ], owners=[9], _death_round={}),
    )
    assert GameServer._title_hidden_players(engine) == [1]
    engine.notes.owners.append(10)
    engine.notes.snapshots.extend([
        {"round": 1, "player_id": 10, "seat": 3, "judged_seats": [4], "notes": {"4": {"guess": "unknown", "conf": "低", "locked": False}}},
        {"round": 2, "player_id": 10, "seat": 3, "judged_seats": [4], "notes": {"4": {"guess": "unknown", "conf": "低", "locked": False}}},
    ])
    assert GameServer._title_hidden_players(engine) == [1]
    engine.notes.snapshots.pop()
    assert GameServer._title_hidden_players(engine) == []
    engine.notes.owners.remove(10)
    engine.notes.snapshots = [row for row in engine.notes.snapshots if row["player_id"] == 9]
    assert GameServer._title_hidden_players(engine) == [1]
    engine.notes.snapshots[1].pop("judged_seats")
    assert GameServer._title_hidden_players(engine) == []  # 视图沿用旧笔记不等于本轮有判断
    engine.notes.snapshots[1]["judged_seats"] = [4]
    engine.notes.snapshots[1]["notes"]["4"] = {"guess": "loyalist", "conf": "高", "locked": False}
    assert GameServer._title_hidden_players(engine) == []
    target.identity = "lord"
    assert GameServer._title_hidden_players(engine) == []


def test_cognitive_snapshot_marks_only_current_round_valid_judgments():
    owner = SimpleNamespace(id=0, is_ai=True, alive=True, identity_revealed=False)
    target = SimpleNamespace(id=1, is_ai=True, alive=True, identity_revealed=False)
    state = SimpleNamespace(players=[owner, target], round_number=3, seat_of=lambda player_id: player_id + 1)
    notes = CognitiveNotes(SimpleNamespace(game_state=state))
    notes.ensure(owner.id)
    notes.update(owner.id, {"2": {"guess": "unknown", "conf": "低", "why": "证据不足"}})
    notes.snapshot(3)
    assert notes.snapshots[0]["judged_seats"] == [2]
    notes.snapshot(4)
    assert notes.snapshots[1]["judged_seats"] == []


def test_spy_single_duel_title_requires_engine_evidence():
    spy = {"id": 4, "identity": "spy", "alive": True}
    stats = update_player_stats({}, spy, {"winner": "spy", "spy_duel_lord": False}, True)
    assert stats.get("spy_lord_wins", 0) == 0
    stats = update_player_stats({}, spy, {"winner": "spy", "spy_duel_lord": True}, True)
    assert stats["spy_lord_wins"] == 1


def test_spy_duel_evidence_is_captured_at_lord_death():
    lord = SimpleNamespace(identity="lord", alive=False, flags={})
    spy = SimpleNamespace(identity="spy", alive=True)
    engine = SimpleNamespace(game_state=SimpleNamespace(players=[lord, spy], round_number=1), spy_duel_lord=False,
                             _spy_duel_lord_ready=False,
                             notes=SimpleNamespace(on_death=lambda player: None),
                             chat_director=SimpleNamespace(on_death=lambda player: None))
    lord.alive = True
    MainEngine._observe_spy_duel_lord_state(engine)
    lord.alive = False
    MainEngine.on_player_death(engine, lord)
    assert engine.spy_duel_lord is True
    assert lord.flags["death_round"] == 1
    engine.game_state.players.append(SimpleNamespace(identity="rebel", alive=True))
    lord.alive = True
    MainEngine._observe_spy_duel_lord_state(engine)
    lord.alive = False
    engine.spy_duel_lord = False
    MainEngine.on_player_death(engine, lord)
    assert engine.spy_duel_lord is False


def test_deep_cover_requires_positive_engine_coverage_evidence():
    winner = {"id": 1, "identity": "rebel", "alive": True}
    assert update_player_stats({}, winner, {"winner": "rebel"}, True).get("deep_cover_wins", 0) == 0
    assert update_player_stats({}, winner, {"winner": "rebel", "_title_hidden_players": []}, True).get("deep_cover_wins", 0) == 0
    assert update_player_stats({}, winner, {"winner": "rebel", "_title_hidden_players": [1]}, True)["deep_cover_wins"] == 1


def test_first_death_uses_actual_death_round_not_final_round():
    player = {"id": 1, "identity": "rebel", "alive": False, "death_round": 1}
    late_result = {"winner": "lord", "state": {"round": 5}}
    assert update_player_stats({}, player, late_result, False)["first_death"] == 1
    player["death_round"] = 2
    assert update_player_stats({}, player, late_result, False).get("first_death", 0) == 0


def test_aborted_streak_follows_existing_history_grace_policy(tmp_path):
    store = GameHistoryStore(tmp_path / "history.json")
    store.record_result("profile", "win", result_payload())
    early = result_payload(winner="aborted")
    early["state"]["round"] = 2
    store.record_result("profile", "early-abort", early)
    assert store.profile("profile")["title_stats"]["win_streak"] == 1
    late = result_payload(winner="aborted")
    late["state"]["round"] = 3
    store.record_result("profile", "late-abort", late)
    assert store.profile("profile")["title_stats"]["win_streak"] == 0
