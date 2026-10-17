"""断线重连：断线不再中止对局，重连后补发快照与仍在等待的提示。"""

import asyncio
import json

from game_engine import MainEngine
from game_engine.protocol import ENGINE_EVENT, ENGINE_EVENTS
from game_engine.state_manager import Card, Phase
from game_server import GameServer


CONFIG = {
    "mode": "5人身份局", "player_name": "玩家", "profile_id": "local_p1",
    "ais": [{"name": f"AI{i}"} for i in range(4)], "deck_id": "standard",
}


class Socket:
    def __init__(self):
        self.messages = []
        self.remote_address = ("test", 0)

    async def send(self, raw):
        self.messages.append(json.loads(raw))

    def types(self):
        return [m["type"] for m in self.messages]


def attach(server, engine, gid, ws):
    """与 do_create 相同的接线，只是用测试自建的引擎。"""
    engine.game_id = gid
    server.engines[gid] = engine
    server.ws_map[ws] = gid
    server.viewers[gid] = ws
    for event in ENGINE_EVENTS:
        engine.on(event, server._forward(gid, event))
    engine.on(ENGINE_EVENT.CARD_ANIMATION, server._animation_handler(gid))


def fresh_engine():
    engine = MainEngine(dict(CONFIG))
    engine.response_timeout = 5
    human = engine.game_state.players[0]
    engine.game_state.current_player = human
    engine.game_state.current_phase = Phase.PLAY
    for player in engine.game_state.players:
        player.hand.clear()
    return engine, human


def test_disconnect_keeps_game_and_resume_resends_pending_request(tmp_path):
    async def scenario():
        server = GameServer(history_path=tmp_path / "h.json")
        engine, human = fresh_engine()
        shan = Card("rc_shan", "闪", "spade", 5, "basic")
        human.hand.append(shan)
        first = Socket()
        attach(server, engine, "g1", first)
        # 让 tasks 里有一个“仍在运行”的任务代表对局。
        server.tasks["g1"] = asyncio.create_task(asyncio.sleep(30))
        pending = asyncio.create_task(engine.request_response(human, {
            "kind": "respond", "requested_name": "闪",
            "options": [{"card": shan, "owner": human, "as_name": "闪"}],
        }))
        await asyncio.sleep(0)
        assert "require_response" in first.types()
        rid = next(m for m in first.messages if m["type"] == "require_response")["request_id"]

        await server._detach(first)
        assert not engine.game_aborted, "断线不能再直接中止对局"
        assert "g1" in server.engines and server.viewers.get("g1") is None

        second = Socket()
        await server.do_resume(second, {"game_id": "g1", "profile_id": "local_p1"})
        types = second.types()
        assert types[0] == "game_resumed" and "game_state" in types
        resent = [m for m in second.messages if m["type"] == "require_response"]
        assert [m["request_id"] for m in resent] == [rid]
        assert 1 <= resent[0]["timeout"] <= 5

        # 旧连接已失效，新连接可以正常作答。
        await server.do_action(first, {"action": {"type": "response", "request_id": rid, "option_index": 0}})
        assert not any(m.get("type") == "action_result" for m in first.messages)
        await server.do_action(second, {"action": {"type": "response", "request_id": rid, "option_index": 0}})
        assert second.messages[-1]["status"] == "accepted"
        assert (await pending)["bool"] is True
        server.tasks["g1"].cancel()

    asyncio.run(scenario())


def test_resume_rejects_other_profile_and_unknown_game(tmp_path):
    async def scenario():
        server = GameServer(history_path=tmp_path / "h.json")
        engine, _ = fresh_engine()
        attach(server, engine, "g2", Socket())
        ws = Socket()
        await server.do_resume(ws, {"game_id": "g2", "profile_id": "someone_else"})
        assert ws.messages[-1]["type"] == "resume_failed" and ws.messages[-1]["reason"] == "forbidden"
        await server.do_resume(ws, {"game_id": "nope", "profile_id": "local_p1"})
        assert ws.messages[-1]["reason"] == "not_found"

    asyncio.run(scenario())


def test_game_ending_while_offline_is_recorded_and_returned_on_resume(tmp_path):
    async def scenario():
        server = GameServer(history_path=tmp_path / "h.json")
        engine, _ = fresh_engine()
        first = Socket()
        attach(server, engine, "g3", first)
        server.tasks["g3"] = asyncio.create_task(asyncio.sleep(30))
        await server._detach(first)
        await engine.request_end_game("测试结束")
        second = Socket()
        await server.do_resume(second, {"game_id": "g3", "profile_id": "local_p1"})
        assert second.types()[:2] == ["game_resumed", "game_end"]
        assert second.messages[0]["finished"] is True
        assert server.history.profile("local_p1")["total_games"] == 1
        server.tasks["g3"].cancel()

    asyncio.run(scenario())


def test_offline_longer_than_grace_ends_game_as_interrupted(tmp_path):
    async def scenario():
        server = GameServer(history_path=tmp_path / "h.json")
        server.DISCONNECT_GRACE = 0.05
        engine, _ = fresh_engine()
        first = Socket()
        attach(server, engine, "g4", first)
        server.tasks["g4"] = asyncio.create_task(asyncio.sleep(30))
        await server._detach(first)
        await asyncio.sleep(0.15)
        assert engine.game_aborted
        assert engine.game_state.winner == "aborted"
        server.tasks["g4"].cancel()

    asyncio.run(scenario())


def test_reconnect_within_grace_cancels_the_timer(tmp_path):
    async def scenario():
        server = GameServer(history_path=tmp_path / "h.json")
        server.DISCONNECT_GRACE = 0.05
        engine, _ = fresh_engine()
        first = Socket()
        attach(server, engine, "g5", first)
        server.tasks["g5"] = asyncio.create_task(asyncio.sleep(30))
        await server._detach(first)
        await server.do_resume(Socket(), {"game_id": "g5", "profile_id": "local_p1"})
        await asyncio.sleep(0.15)
        assert not engine.game_aborted
        server.tasks["g5"].cancel()

    asyncio.run(scenario())


def test_animation_does_not_wait_when_nobody_is_watching(tmp_path):
    async def scenario():
        server = GameServer(history_path=tmp_path / "h.json")
        handler = server._animation_handler("g6")
        loop = asyncio.get_running_loop()
        start = loop.time()
        await handler(await_ui=True, card_name="杀")
        assert loop.time() - start < 0.5

    asyncio.run(scenario())
