"""批次 4 服务器端：暂停 / 继续、离开牌桌（托管或暂停）、进行中对局列表。"""

import asyncio
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import game_server
from game_engine import MainEngine
from game_engine.chat_director import ChatTask
from game_engine.protocol import ENGINE_EVENT, ENGINE_EVENTS
from game_engine.recovery import RecoveryStore, dump_engine
from game_server import CustomHandler, GameServer


def make_config(profile="srv_p1", **extra):
    config = {
        "mode": "5人身份局", "player_name": "玩家", "profile_id": profile,
        "ais": [{"name": f"AI{i}"} for i in range(4)], "deck_id": "standard",
        "turn_delay": 0, "phase_delay": 0,
    }
    config.update(extra)
    return config


class Socket:
    def __init__(self):
        self.messages = []
        self.remote_address = ("test", 0)

    async def send(self, raw):
        self.messages.append(json.loads(raw))

    def types(self):
        return [m["type"] for m in self.messages]

    def last(self, kind):
        return next(m for m in reversed(self.messages) if m["type"] == kind)


def attach(server, engine, gid, ws, *, started=True, run=False):
    engine.game_id = gid
    server.engines[gid] = engine
    server.ws_map[ws] = gid
    server.viewers[gid] = ws
    server.viewer_modes[gid] = "player"
    for event in ENGINE_EVENTS:
        engine.on(event, server._forward(gid, event))
    engine.on(ENGINE_EVENT.CARD_ANIMATION, server._animation_handler(gid))
    if started and not run:
        engine._started_at = engine.time_source()
    if run:
        server.tasks[gid] = asyncio.create_task(server._run_engine(gid, engine))
    else:
        server.tasks[gid] = asyncio.create_task(asyncio.sleep(30))


async def settle(seconds=0.05):
    await asyncio.sleep(seconds)


def new_server(tmp_path):
    return GameServer(history_path=tmp_path / "history.json", recovery_path=tmp_path / "recovery")


@pytest.fixture(autouse=True)
def isolate_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(game_server, "GAME_LOG_DIR", tmp_path / "logs")


# ---------------------------------------------------------------- 引擎：暂停闸门

def test_pause_stops_turn_progress_and_resume_continues():
    async def scenario():
        engine = MainEngine(make_config(turn_delay=0.05, phase_delay=0.01))
        engine.set_trustee(True, source="rules")       # 真人托管，整桌自己跑
        task = asyncio.create_task(engine.run())
        await settle(0.15)
        assert engine.pause()
        await settle(0.05)                              # 让已在途的同步片段走完
        frozen = (engine.completed_turns, engine._log_seq, engine.game_state.current_phase)
        await settle(0.4)
        assert (engine.completed_turns, engine._log_seq, engine.game_state.current_phase) == frozen
        assert engine.resume()
        await settle(0.3)
        assert (engine.completed_turns, engine._log_seq) != frozen[:2] or task.done()
        await engine.request_end_game("测试结束")
        await asyncio.wait_for(task, 5)

    asyncio.run(scenario())


def test_pause_refused_before_start_or_after_end():
    engine = MainEngine(make_config())
    assert engine.pause() is False              # 还没 run()
    engine._started_at = engine.time_source()
    assert engine.pause() is True
    assert engine.pause() is False              # 已经暂停

    async def end():
        await engine.request_end_game("结束")

    asyncio.run(end())
    assert engine.paused is False               # 结束会放开闸门
    assert engine.pause() is False


def test_pause_holds_in_flight_model_result_until_resume():
    async def scenario():
        engine = MainEngine(make_config(ais=[{"name": f"AI{i}", "api_key": "k" * 12} for i in range(4)]))
        engine._started_at = engine.time_source()
        ai = engine.game_state.players[1]
        release = asyncio.Event()
        calls = []

        async def fake_call_ai(**kwargs):
            calls.append(1)
            await release.wait()
            return '{"reasoning":"x","action_index":0}', {}

        engine.ai_decision.gateway.call_ai = fake_call_ai
        task = asyncio.create_task(engine.ai_decision._call_with_session(ai, "decision", "你好"))
        await settle()
        assert calls == [1]
        engine.pause()
        release.set()                                # 模型请求在暂停期间返回
        await settle(0.1)
        assert not task.done()                       # 结果被扣住，没有写回会话
        before = len(engine.ai_decision.get_session(ai)["messages"])
        engine.resume()
        reply = await asyncio.wait_for(task, 2)
        assert "action_index" in reply
        assert len(engine.ai_decision.get_session(ai)["messages"]) == before + 1

    asyncio.run(scenario())


def test_paused_ai_makes_no_new_model_call():
    async def scenario():
        engine = MainEngine(make_config(ais=[{"name": f"AI{i}", "api_key": "k" * 12} for i in range(4)]))
        engine._started_at = engine.time_source()
        ai = engine.game_state.players[1]
        calls = []

        async def fake_call_ai(**kwargs):
            calls.append(1)
            return '{"reasoning":"x","action_index":0}', {}

        engine.ai_decision.gateway.call_ai = fake_call_ai
        engine.pause()
        task = asyncio.create_task(engine.ai_decision._call_with_session(ai, "decision", "你好"))
        await settle(0.2)
        assert calls == [] and not task.done()
        engine.resume()
        await asyncio.wait_for(task, 2)
        assert calls == [1]

    asyncio.run(scenario())


def test_human_countdown_freezes_while_paused_and_continues_with_remaining_time():
    async def scenario():
        engine = MainEngine(make_config())
        engine._started_at = engine.time_source()
        engine.human_action_timeout = 0.6
        engine._player_event = asyncio.Event()
        task = asyncio.create_task(engine._wait_player_input())
        await settle(0.3)                             # 用掉 0.3，剩 0.3
        engine.pause()
        await settle(1.0)                             # 暂停时间远超剩余时间
        assert not task.done() and not engine._trustee_active
        engine.resume()
        await settle(0.15)                            # 续上后过了 0.15，仍没到期
        assert not task.done()
        result = await asyncio.wait_for(task, 1.5)    # 约 0.15 后到期
        assert result["action"]["type"] == "trustee" and engine._trustee_active

    asyncio.run(scenario())


def test_response_countdown_freezes_and_input_during_pause_is_rejected():
    async def scenario():
        engine = MainEngine(make_config())
        engine._started_at = engine.time_source()
        engine.response_timeout = 0.5
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        task = asyncio.create_task(engine._wait_human(future, 0.5))
        await settle(0.25)
        engine.pause()
        await settle(0.8)
        assert not task.done()
        # 暂停中的操作被拒绝，不落地。
        assert engine.submit_action({"type": "end_phase"}, [])["status"] == "paused"
        assert engine.submit_response_status("nope", 0)["status"] == "paused"
        engine.resume()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(task, 1.5)

    asyncio.run(scenario())


def test_answer_arriving_while_paused_is_held_until_resume():
    async def scenario():
        engine = MainEngine(make_config())
        engine._started_at = engine.time_source()
        future = asyncio.get_running_loop().create_future()
        task = asyncio.create_task(engine._wait_human(future, 5))
        await settle()
        engine.pause()
        future.set_result({"trustee": True})          # 例如暂停中开了托管，唤醒了等待者
        await settle(0.1)
        assert not task.done()
        engine.resume()
        assert await asyncio.wait_for(task, 1) == {"trustee": True}

    asyncio.run(scenario())


# ---------------------------------------------------------------- 聊天

def test_human_chat_rejected_while_paused_and_ai_chat_scheduler_stops(tmp_path):
    async def scenario():
        server = new_server(tmp_path)
        engine = MainEngine(make_config(ais=[{"name": f"AI{i}", "api_key": "k" * 12} for i in range(4)]))
        ws = Socket()
        attach(server, engine, "chat1", ws)
        await server.do_set_pause(ws, {"paused": True})
        await server.do_chat(ws, {"message": "你好"})
        assert ws.messages[-1]["type"] == "error"
        assert ws.messages[-1]["message"] == "暂停中不能发言"
        assert len(engine.table_chat) == 0
        assert await engine.submit_chat(0, "绕过入口") is None     # 引擎里的第二道闸门

        # AI 发言调度器：暂停期间 tick / pump 都不会开新任务。
        director = engine.chat_director
        director._submit(ChatTask(1, "idle", "测试", engine.time_source(), 1, 60))
        started = []

        async def never(task):
            started.append(task)

        director._run_task = never
        director.tick()
        director._pump()
        await settle()
        assert started == [] and not director._inflight
        await server.do_set_pause(ws, {"paused": False})
        director._pump()
        await settle()
        assert len(started) == 1
        await server.do_chat(ws, {"message": "继续后可以发言"})
        assert engine.table_chat[-1]["text"] == "继续后可以发言"
        server.tasks["chat1"].cancel()

    asyncio.run(scenario())


# ---------------------------------------------------------------- 离席监控

def test_idle_watchdog_does_not_count_paused_time():
    clock = {"now": 1000.0}
    engine = MainEngine(make_config())
    engine._started_at = 1000.0
    engine.time_source = lambda: clock["now"]
    engine.idle_abort_seconds = 300
    engine._human_idle_since = clock["now"]

    async def scenario():
        clock["now"] += 200
        assert not await engine._check_idle_timeout()
        engine.pause()
        clock["now"] += 3600                            # 暂停了一个小时
        assert engine.idle_seconds() == pytest.approx(200)
        assert not await engine._check_idle_timeout()
        engine.resume()
        assert engine.idle_seconds() == pytest.approx(200)   # 暂停时长被顺延，不算离席
        clock["now"] += 99
        assert not await engine._check_idle_timeout()
        clock["now"] += 2
        assert await engine._check_idle_timeout()            # 规则本身不变：累计 300 秒仍然中止
        assert engine._abort_reason == "idle_timeout"

    asyncio.run(scenario())


def test_disconnect_during_pause_schedules_no_five_minute_abort(tmp_path):
    async def scenario():
        server = new_server(tmp_path)
        server.DISCONNECT_GRACE = 0.05
        engine = MainEngine(make_config())
        ws = Socket()
        attach(server, engine, "d1", ws)
        await server.do_set_pause(ws, {"paused": True})
        await server._detach(ws)
        assert "d1" not in server.grace_tasks
        await settle(0.2)
        assert not engine.game_aborted                  # 由暂停期限负责，宽限不触发
        # 继续后重新断线，离席宽限照常生效。
        again = Socket()
        await server.do_resume(again, {"game_id": "d1", "profile_id": "srv_p1"})
        await server.do_set_pause(again, {"paused": False})
        await server._detach(again)
        assert "d1" in server.grace_tasks
        await settle(0.2)
        assert engine.game_aborted
        server.tasks["d1"].cancel()

    asyncio.run(scenario())


# ---------------------------------------------------------------- 服务器：set_pause

def test_set_pause_broadcasts_status_and_state_and_expires(tmp_path):
    async def scenario():
        server = new_server(tmp_path)
        server.PAUSE_LIMIT_SECONDS = 0.2
        engine = MainEngine(make_config())
        ws = Socket()
        attach(server, engine, "p1", ws)
        before = time.time()
        await server.do_set_pause(ws, {"paused": True})
        status = ws.last("pause_status")
        assert status["paused"] is True and status["remaining_seconds"] == 1
        assert before + 0.1 < status["deadline_ts"] < before + 1
        assert ws.last("game_state")["state"]["paused"] is True
        assert engine.paused
        await settle(0.4)                               # 到期：按中断结束
        assert engine.game_aborted and engine.game_state.winner == "aborted"
        assert "暂停超过" in engine.game_state.end_message
        assert "p1" not in server.pause_tasks
        server.tasks["p1"].cancel()

    asyncio.run(scenario())


def test_pause_expiry_message_uses_fifteen_minutes_by_default(tmp_path):
    server = new_server(tmp_path)
    assert server.PAUSE_LIMIT_SECONDS == 900
    assert GameServer.pause_end_message(900) == "暂停超过 15 分钟，对局结束"


def test_resume_cancels_expiry_and_game_continues(tmp_path):
    async def scenario():
        server = new_server(tmp_path)
        server.PAUSE_LIMIT_SECONDS = 0.2
        engine = MainEngine(make_config())
        ws = Socket()
        attach(server, engine, "p2", ws)
        await server.do_set_pause(ws, {"paused": True})
        await server.do_set_pause(ws, {"paused": False})
        status = ws.last("pause_status")
        assert status["paused"] is False and status["remaining_seconds"] == 0
        assert ws.last("game_state")["state"]["paused"] is False
        await settle(0.4)
        assert not engine.game_aborted and "p2" not in server.pause_tasks
        server.tasks["p2"].cancel()

    asyncio.run(scenario())


def test_set_pause_errors(tmp_path):
    async def scenario():
        server = new_server(tmp_path)
        engine = MainEngine(make_config())
        ws = Socket()
        attach(server, engine, "e1", ws, started=False)
        await server.do_set_pause(ws, {"paused": True})
        assert ws.last("error")["message"] == "对局尚未开始"
        engine._started_at = engine.time_source()
        await server.do_set_pause(ws, {"paused": "yes"})
        assert ws.last("error")
        stranger = Socket()
        await server.do_set_pause(stranger, {"paused": True})   # 没有观看这局的连接不能发
        assert stranger.last("error")
        assert not engine.paused
        await engine.request_end_game("结束")
        await server.do_set_pause(ws, {"paused": True})
        assert ws.last("error")["message"] == "对局已结束"
        server.tasks["e1"].cancel()

    asyncio.run(scenario())


def test_set_pause_is_idempotent_and_reconnect_gets_pause_status(tmp_path):
    async def scenario():
        server = new_server(tmp_path)
        engine = MainEngine(make_config())
        ws = Socket()
        attach(server, engine, "r1", ws)
        await server.do_set_pause(ws, {"paused": True})
        first_deadline = ws.last("pause_status")["deadline_ts"]
        await server.do_set_pause(ws, {"paused": True})
        assert ws.last("pause_status")["deadline_ts"] == first_deadline     # 不会重置期限
        await server._detach(ws)
        second = Socket()
        await server.do_resume(second, {"game_id": "r1", "profile_id": "srv_p1"})
        assert second.last("pause_status")["paused"] is True
        assert second.last("game_state")["state"]["paused"] is True
        wrong = Socket()
        await server.do_resume(wrong, {"game_id": "r1", "profile_id": "someone_else"})
        assert wrong.last("resume_failed")["reason"] == "forbidden"
        server.tasks["r1"].cancel()

    asyncio.run(scenario())


# ---------------------------------------------------------------- 服务器：leave_game

def test_leave_game_pause_acks_then_disconnect_waits_for_pause_deadline(tmp_path):
    async def scenario():
        server = new_server(tmp_path)
        server.PAUSE_LIMIT_SECONDS = 0.2
        server.DISCONNECT_GRACE = 0.05
        engine = MainEngine(make_config())
        ws = Socket()
        attach(server, engine, "l1", ws)
        await server.do_leave_game(ws, {"mode": "pause"})
        assert ws.last("leave_game_result") == {"type": "leave_game_result", "ok": True,
                                                "mode": "pause", "game_id": "l1"}
        assert ws.types().index("pause_status") < ws.types().index("leave_game_result")   # 先暂停，再回执
        assert engine.paused
        await server._detach(ws)
        assert "l1" not in server.grace_tasks
        await settle(0.4)
        assert engine.game_aborted and "暂停超过" in engine.game_state.end_message
        server.tasks["l1"].cancel()

    asyncio.run(scenario())


def test_leave_game_rejects_bad_mode_no_game_and_finished_game(tmp_path):
    async def scenario():
        server = new_server(tmp_path)
        nobody = Socket()
        await server.do_leave_game(nobody, {"mode": "trustee"})
        assert nobody.last("error")
        engine = MainEngine(make_config())
        ws = Socket()
        attach(server, engine, "l2", ws)
        await server.do_leave_game(ws, {"mode": "teleport"})
        assert ws.last("error")
        await engine.request_end_game("结束")
        await server.do_leave_game(ws, {"mode": "trustee"})
        assert ws.last("error")["message"] == "对局已结束"
        server.tasks["l2"].cancel()

    asyncio.run(scenario())


def test_leave_trustee_detaches_without_grace_abort_and_game_finishes_with_history(tmp_path):
    async def scenario():
        server = new_server(tmp_path)
        server.DISCONNECT_GRACE = 0.01               # 若误走离线宽限，局会被立刻中止
        engine = MainEngine(make_config(profile="srv_leave"))
        ws = Socket()
        attach(server, engine, "t1", ws, run=True)
        await settle(0.05)
        await server.do_leave_game(ws, {"mode": "trustee"})
        assert ws.last("leave_game_result")["ok"] is True
        assert ws.last("leave_game_result")["mode"] == "trustee"
        assert engine._trustee_active and "t1" in server.background_games
        assert ws not in server.ws_map and "t1" not in server.viewers
        assert "t1" not in server.grace_tasks
        await server._detach(ws)                     # 随后真的断线也不安排中止
        assert "t1" not in server.grace_tasks
        await asyncio.wait_for(server.tasks["t1"], 30)
        assert engine.game_state.winner != "aborted"
        profile = server.history.profile("srv_leave")
        assert profile["total_games"] == 1
        logs = server.game_logs.list("srv_leave")
        assert len(logs) == 1 and logs[0]["game_id"] == "t1"
        assert server.finished["t1"]["game_end"]["type"] == "game_end"
        assert "t1" not in server.engines                # 无人观看时结束，引擎被释放

    asyncio.run(scenario())


def test_leave_trustee_not_aborted_by_new_game_of_same_profile(tmp_path):
    async def scenario():
        server = new_server(tmp_path)
        engine = MainEngine(make_config())
        ws = Socket()
        attach(server, engine, "t2", ws)
        await server.do_leave_game(ws, {"mode": "trustee"})
        await server._end_orphaned_games("srv_p1")
        assert not engine.game_aborted
        server.tasks["t2"].cancel()

    asyncio.run(scenario())


def test_leave_trustee_while_paused_unpauses_and_cancels_deadline(tmp_path):
    async def scenario():
        server = new_server(tmp_path)
        server.PAUSE_LIMIT_SECONDS = 0.1
        engine = MainEngine(make_config())
        ws = Socket()
        attach(server, engine, "t3", ws)
        await server.do_set_pause(ws, {"paused": True})
        await server.do_leave_game(ws, {"mode": "trustee"})
        assert not engine.paused and "t3" not in server.pause_tasks
        await settle(0.3)
        assert not engine.game_aborted
        server.tasks["t3"].cancel()

    asyncio.run(scenario())


def test_leave_trustee_when_human_dead_is_background_settlement(tmp_path):
    async def scenario():
        server = new_server(tmp_path)
        engine = MainEngine(make_config())
        human = engine.human_player()
        human.alive = False
        human.hp = 0
        ws = Socket()
        attach(server, engine, "t4", ws)
        await server.do_leave_game(ws, {"mode": "trustee"})
        result = ws.last("leave_game_result")
        assert result["ok"] and result["human_alive"] is False
        assert not engine._trustee_active                # 真人已阵亡，不需要托管
        assert "t4" in server.background_games and "t4" not in server.viewers
        server.tasks["t4"].cancel()

    asyncio.run(scenario())


def test_leave_trustee_source_priority(tmp_path):
    # 1) 沿用本局已有的托管配置
    engine = MainEngine(make_config(ais=[{"name": f"AI{i}", "api_key": "ai-key-%d-xxxxxxxx" % i,
                                          "model": f"m{i}"} for i in range(4)]))
    engine._started_at = 1
    engine.set_trustee(True, source="custom", config={"provider": "qwen", "model": "mine", "api_key": "mine-key-1234"})
    engine.set_trustee(False)
    status = engine.start_leave_trustee()
    assert status["enabled"] and status["model"] == "mine" and engine._trustee_source == "custom"

    # 2) 没配过：复制第一个配了真模型的 AI
    engine = MainEngine(make_config(ais=[{"name": "规则AI"}] + [
        {"name": f"AI{i}", "api_key": "ai-key-%d-xxxxxxxx" % i, "model": f"m{i}"} for i in range(1, 4)]))
    status = engine.start_leave_trustee()
    assert status["enabled"] and engine._trustee_source == "copy_ai"
    assert engine._trustee_config.get("model") == "m1" and not status["degraded"]

    # 3) 谁都没有模型：规则 AI
    engine = MainEngine(make_config())
    status = engine.start_leave_trustee()
    assert status["enabled"] and engine._trustee_source == "rules" and status["model"] is None

    # 已在托管则保持原样
    assert engine.start_leave_trustee()["enabled"]


def test_reconnect_after_leave_trustee_can_cancel_trustee_and_take_back_seat(tmp_path):
    async def scenario():
        server = new_server(tmp_path)
        engine = MainEngine(make_config())
        first = Socket()
        attach(server, engine, "t5", first)
        await server.do_leave_game(first, {"mode": "trustee"})
        assert engine._trustee_active
        back = Socket()
        await server.do_resume(back, {"game_id": "t5", "profile_id": "srv_p1"})
        assert "t5" not in server.background_games and server.viewers["t5"] is back
        assert back.last("trustee_status")["enabled"] is True
        await server.do_set_trustee(back, {"enabled": False})
        assert not engine._trustee_active
        assert back.last("trustee_status")["enabled"] is False
        server.tasks["t5"].cancel()

    asyncio.run(scenario())


# ---------------------------------------------------------------- /api/active_games

def _fetch(base, path):
    try:
        with urllib.request.urlopen(base + path, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


class QuietHandler(CustomHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def http_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


def test_active_games_lists_memory_and_snapshot_games_for_profile_only(tmp_path, http_server, monkeypatch):
    server = new_server(tmp_path)
    monkeypatch.setattr(game_server, "ACTIVE_SERVER", server)

    async def build():
        # 内存里：暂停中、真人已离开托管的一局
        mine = MainEngine(make_config(profile="srv_list"))
        mine.set_trustee(True, source="rules")
        mine.game_state.round_number = 3
        ws = Socket()
        attach(server, mine, "aa11", ws)
        await server.do_set_pause(ws, {"paused": True})
        # 内存里：别人的局
        other = MainEngine(make_config(profile="srv_other"))
        attach(server, other, "bb22", Socket())
        # 内存里：已结束的局不出现
        done = MainEngine(make_config(profile="srv_list"))
        attach(server, done, "cc33", Socket())
        await done.request_end_game("结束")
        return mine

    mine = asyncio.run(build())
    # 快照：同档案的一份（只在磁盘），同一局内存里也有快照（不重复），别人的快照
    snap_engine = MainEngine(make_config(profile="srv_list"))
    snap_engine.game_id = "dd44"
    snap_engine.game_state.round_number = 5
    snap_engine.game_state.mode = "5人身份局"
    server.recovery.save_payload("dd44", dump_engine(snap_engine))
    mine.game_id = "aa11"
    server.recovery.save_payload("aa11", dump_engine(mine))
    foreign = MainEngine(make_config(profile="srv_other"))
    foreign.game_id = "ee55"
    server.recovery.save_payload("ee55", dump_engine(foreign))
    server.game_touched["aa11"] = time.time() + 10     # 内存局最近更新

    status, body = _fetch(http_server, "/api/active_games?profile_id=srv_list")
    assert status == 200 and body["success"] is True
    games = body["games"]
    assert [g["game_id"] for g in games] == ["aa11", "dd44"]
    live, snap = games
    assert live["paused"] is True and live["trustee"] is True and live["human_alive"] is True
    assert live["recoverable_only"] is False and live["round"] == 3
    assert live["mode"] == "5人身份局" and live["mode_name"] == "5人身份局"
    assert snap["recoverable_only"] is True and snap["round"] == 5 and snap["paused"] is False
    assert snap["updated_at"] > 0 and live["updated_at"] >= snap["updated_at"]
    for game in games:
        assert set(game) >= {"game_id", "mode", "mode_name", "round", "paused", "trustee",
                             "human_alive", "recoverable_only", "updated_at"}

    # 别人的档案看到的是他自己的，不会混入。
    _, other_body = _fetch(http_server, "/api/active_games?profile_id=srv_other")
    assert sorted(g["game_id"] for g in other_body["games"]) == ["bb22", "ee55"]


def test_active_games_rejects_invalid_profile_and_empty_profile_is_empty(tmp_path, http_server, monkeypatch):
    server = new_server(tmp_path)
    monkeypatch.setattr(game_server, "ACTIVE_SERVER", server)
    status, body = _fetch(http_server, "/api/active_games?profile_id=../etc")
    assert status == 400 and body["success"] is False
    status, body = _fetch(http_server, "/api/active_games")
    assert status == 400
    status, body = _fetch(http_server, "/api/active_games?profile_id=nobody_here")
    assert status == 200 and body["games"] == []


def test_active_game_from_list_is_resumable_for_memory_and_snapshot_games(tmp_path):
    """前端拿 game_id 写进 activeGame 再走 resume_game：内存对局与快照对局都要接得回。"""
    async def scenario():
        server = new_server(tmp_path)
        engine = MainEngine(make_config(profile="srv_res"))
        engine.game_id = "mem1"
        ws = Socket()
        attach(server, engine, "mem1", ws)
        await server._detach(ws)
        back = Socket()
        await server.do_resume(back, {"game_id": "mem1", "profile_id": "srv_res"})
        assert back.types()[:2] == ["game_resumed", "game_state"]

        snap = MainEngine(make_config(profile="srv_res"))
        snap.game_id = "abc1"
        server.recovery.save_payload("abc1", dump_engine(snap))
        restored = Socket()
        await server.do_resume(restored, {"game_id": "abc1", "profile_id": "srv_res"})
        assert restored.types()[:2] == ["game_resumed", "game_state"]
        assert "abc1" in server.engines and server.viewers["abc1"] is restored
        for task in list(server.tasks.values()):
            task.cancel()
        await settle()

    asyncio.run(scenario())
