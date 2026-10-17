"""2026-10-17 试玩反馈：摸牌动画事件、洛神逐张亮判定、作弊模式、阵亡暗置、对局日志。"""

import asyncio
import io
import json
import types

import game_server
from game_engine import MainEngine
from game_engine.game_history import GameHistoryStore
from game_engine.game_logs import GameLogStore, build_game_log
from game_engine.state_manager import Card, Phase


def run(coro):
    return asyncio.run(coro)


def game(**extra):
    cfg = {"mode": "5人身份局", "player_name": "P0",
           "ais": [{"name": f"P{i}"} for i in range(1, 5)], "deck_id": "standard"}
    cfg.update(extra)
    engine = MainEngine(MainEngine.normalize_config(cfg))
    for p in engine.game_state.players:
        p.hand.clear()
        p.equipment.clear()
        p.judge_area.clear()
    engine.game_state.current_player = engine.game_state.players[0]
    engine.game_state.current_player_index = 0
    engine.game_state.current_phase = Phase.PLAY
    return engine


def capture(engine, event):
    seen = []

    async def handler(**data):
        seen.append(data)

    engine.on(event, handler)
    return seen


# ---------- 摸牌：统一入口 + 动画事件 ----------

def test_draw_cards_moves_through_move_card_and_announces_once():
    engine = game()
    me, ai = engine.game_state.players[0], engine.game_state.players[1]
    moves = capture(engine, "card_move")
    anims = capture(engine, "card_animation")
    top = list(engine.game_state.deck[:2])
    drawn = run(engine.draw_cards(me, 2, "摸牌阶段"))
    assert drawn == top and me.hand == top
    assert len(moves) == 2 and all(m["move"]["from_zone"] == "deck" for m in moves)
    draw_events = [a for a in anims if a.get("event_kind") == "draw"]
    assert len(draw_events) == 1 and draw_events[0]["count"] == 2
    assert [c["id"] for c in draw_events[0]["cards"]] == [c.id for c in top]

    run(engine.draw_cards(ai, 1, "无中生有"))
    ai_event = [a for a in anims if a.get("event_kind") == "draw"][-1]
    assert ai_event["cards"] is None, "别人摸的牌只显示张数，不能下发牌面"


def test_draw_cards_reshuffles_discard_pile_when_deck_is_empty():
    engine = game()
    state = engine.game_state
    me = state.players[0]
    state.discard_pile = list(state.deck)
    state.deck = []
    drawn = run(engine.draw_cards(me, 2))
    assert len(drawn) == 2 and len(me.hand) == 2


def test_wuzhong_and_draw_phase_use_the_unified_draw():
    engine = game()
    me = engine.game_state.players[0]
    anims = capture(engine, "card_animation")
    run(engine.card_system.use_wuzhongshengyou(me, Card("wz", "无中生有", "heart", 7, "trick")))
    run(engine.phase_controller.draw_phase())
    draws = [a for a in anims if a.get("event_kind") == "draw"]
    assert [d["reason"] for d in draws][:2] == ["无中生有", "摸牌阶段"]
    assert len(me.hand) == 4


# ---------- 洛神：每次判定都亮出 ----------

def test_luoshen_announces_each_judgment_with_result():
    engine = game()
    state = engine.game_state
    zhenji = state.players[0]
    state.deck[:3] = [Card("b1", "杀", "spade", 3, "basic"), Card("b2", "闪", "club", 4, "basic"),
                      Card("r1", "桃", "heart", 5, "basic")]
    judged = capture(engine, "card_animation")
    handler = next(h for h in engine.skill_manager.handlers if hasattr(h, "_luoshen"))
    run(handler._luoshen(zhenji))
    shown = [a for a in judged if a.get("event_kind") == "judge"]
    assert [a["card"]["id"] for a in shown] == ["b1", "b2", "r1"]
    assert [a["effective"] for a in shown] == [True, True, False]
    assert {c.id for c in zhenji.hand} == {"b1", "b2"}


# ---------- 作弊模式 ----------

def _trace(engine, ai, reason):
    engine.ai_decision.last_meta[ai.id] = {"model": "m-1"}
    engine.ai_decision.last_reasoning[ai.id] = reason
    engine.ai_decision.last_failure[ai.id] = None
    traces = capture(engine, "decision_trace")
    run(engine._emit_decision_trace(ai, "play", 3, {"type": "end_phase"}, "accepted"))
    return traces[-1]


def test_cheat_mode_reveals_ai_reasoning_only_when_locked_on():
    normal = game()
    t = _trace(normal, normal.game_state.players[1], "我怀疑3号是反贼")
    assert t["reason"] != "我怀疑3号是反贼" and t["cheat"] is False

    cheat = game(cheat_mode=True)
    t = _trace(cheat, cheat.game_state.players[1], "我怀疑3号是反贼")
    assert t["reason"] == "我怀疑3号是反贼" and t["cheat"] is True
    assert cheat.serialize()["cheat_mode"] is True


def test_cheat_flag_only_accepts_true_and_reasons_always_reach_the_log():
    engine = game(cheat_mode="yes")
    assert engine.cheat_mode is False
    _trace(engine, engine.game_state.players[2], "留着桃救主公")
    assert engine.decision_log[-1]["reason"] == "留着桃救主公"


def test_cheat_games_do_not_change_streak_or_identity_cards(tmp_path):
    store = GameHistoryStore(tmp_path / "h.json")
    state = {"round": 6, "players": [{"is_ai": False, "identity": "lord"}]}
    store.record_result("p1", "g1", {"winner": "lord", "state": state})
    receipt = store.record_result("p1", "g2", {"winner": "lord", "state": state, "cheat": True})
    assert receipt["cheat"] is True
    # 第二局若不是作弊局会连胜 2 并奖励一张；作弊局不变（只剩见面礼那一张）
    assert receipt["profile"]["win_streak"] == 1 and receipt["profile"]["identity_cards"] == 1
    assert store.profile("p1")["history"][0]["cheat"] is True


# ---------- 阵亡暗置（开局选项） ----------

def _kill(engine, victim):
    victim.hp = 0
    run(engine.card_system.enter_dying(victim))


def test_dead_identity_revealed_by_default_and_hidden_when_option_on():
    official = game()
    victim = official.game_state.players[2]
    _kill(official, victim)
    assert victim.alive is False and victim.identity_revealed is True

    hidden = game(hide_dead_identity=True)
    victim = hidden.game_state.players[2]
    _kill(hidden, victim)
    assert victim.alive is False and victim.identity_revealed is False
    seat = next(p for p in hidden.serialize()["players"] if p["id"] == victim.id)
    assert seat["identity"] is None


# ---------- 对局日志 ----------

def _finished_engine():
    engine = game()
    engine.game_config["profile_id"] = "prof_1"
    engine.game_log.append({"message": "P1使用【杀】", "event_kind": "card_to_discard", "round": 2})
    engine.game_log.append({"message": "", "event_kind": "phase", "round": 2})
    engine.chat_log.append({"round": 2, "from": "P1", "kind": "ai", "message": "你先别动"})
    engine.decision_log.append({"round": 2, "player_id": 1, "player_name": "P1", "kind": "play",
                                "model": "m", "reason": "先打主公", "choice": "杀", "validation": "accepted"})
    for p in engine.game_state.players:
        if p.is_ai:
            p.ai_config["api_key"] = "sk-secret-123"
    return engine


def test_build_game_log_never_contains_keys_and_respects_thinking_switch():
    engine = _finished_engine()
    end = {"winner": "rebel", "message": "反贼获胜！", "state": engine.serialize(), "stats": {}, "duration": 99}
    with_thinking = build_game_log(engine, end, include_thinking=True)
    without = build_game_log(engine, end, include_thinking=False)
    dumped = json.dumps(with_thinking, ensure_ascii=False)
    assert "sk-secret-123" not in dumped
    assert [t["text"] for t in with_thinking["timeline"]] == ["P1使用【杀】"]
    assert with_thinking["decisions"][0]["reason"] == "先打主公"
    assert "reason" not in without["decisions"][0]
    assert with_thinking["chat"][0]["message"] == "你先别动"


def test_log_store_list_get_delete_and_path_safety(tmp_path):
    store = GameLogStore(tmp_path)
    for gid in ("aaa1", "bbb2", "ccc3"):
        store.save({"game_id": gid, "profile_id": "prof_1", "ended_at": gid,
                    "players": [{"is_ai": False, "hero": "界关羽", "identity": "lord"}]})
    assert [l["game_id"] for l in store.list("prof_1")] == ["ccc3", "bbb2", "aaa1"]
    assert store.get("prof_1", "bbb2")["game_id"] == "bbb2"
    assert store.delete("prof_1", ["aaa1"]) == 1
    assert store.delete("prof_1", delete_all=True) == 2
    assert store.list("prof_1") == []
    for bad in ("../x", "a/b", ""):
        try:
            store.get("prof_1", bad)
        except ValueError:
            continue
        raise AssertionError(f"unsafe game id accepted: {bad!r}")


def test_server_saves_log_unless_incognito(tmp_path):
    server = game_server.GameServer(history_path=tmp_path / "h.json")
    server.game_logs = GameLogStore(tmp_path / "logs")
    engine = _finished_engine()
    end = {"winner": "rebel", "message": "x", "state": engine.serialize(), "stats": {}}
    assert server._save_game_log(engine, end) is True
    assert len(server.game_logs.list("prof_1")) == 1
    engine.game_config["global_settings"] = {"log_incognito": True}
    engine.game_id = "other"
    assert server._save_game_log(engine, end) is False
    assert len(server.game_logs.list("prof_1")) == 1


def _handler(path, body=None):
    raw = json.dumps(body or {}).encode()
    handler = game_server.CustomHandler.__new__(game_server.CustomHandler)
    handler.headers = {"Content-Length": str(len(raw))}
    handler.rfile = io.BytesIO(raw)
    handler.path = path
    sent = {}
    handler._send_json = lambda status, payload: sent.update(status=status, payload=payload)
    return handler, sent


def test_log_http_endpoints(tmp_path, monkeypatch):
    store = GameLogStore(tmp_path)
    store.save({"game_id": "g1", "profile_id": "prof_1", "players": []})
    monkeypatch.setattr(game_server, "ACTIVE_SERVER", types.SimpleNamespace(game_logs=store))
    h, sent = _handler("/api/logs")
    h._handle_logs_get("/api/logs", {"profile_id": ["prof_1"]})
    assert [l["game_id"] for l in sent["payload"]["logs"]] == ["g1"]
    h, sent = _handler("/api/logs/g1")
    h._handle_logs_get("/api/logs/g1", {"profile_id": ["prof_1"]})
    assert sent["payload"]["log"]["game_id"] == "g1"
    h, sent = _handler("/api/logs/g1")
    h._handle_logs_get("/api/logs/g1", {"profile_id": ["../etc"]})
    assert sent["status"] == 400
    h, sent = _handler("/api/logs/delete", {"profile_id": "prof_1", "all": True})
    h._handle_logs_delete()
    assert sent["payload"] == {"success": True, "removed": 1}
