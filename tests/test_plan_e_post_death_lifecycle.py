"""真人阵亡后三种生命周期由服务器管理，对局规则仍留在引擎。"""

import asyncio
import json

from game_engine import MainEngine
from game_engine.game_logs import build_game_log
from game_engine.protocol import ENGINE_EVENT, ENGINE_EVENTS
from game_server import GameServer


CONFIG = {
    "mode": "5人身份局", "player_name": "玩家", "profile_id": "post_death_p1",
    "ais": [{"name": f"AI{i}"} for i in range(4)], "deck_id": "standard",
}


class Socket:
    def __init__(self):
        self.messages = []

    async def send(self, raw):
        self.messages.append(json.loads(raw))


def attach(server, engine, gid, ws):
    engine.game_id = gid
    server.engines[gid] = engine
    server.ws_map[ws] = gid
    server.viewers[gid] = ws
    server.viewer_modes[gid] = "player"
    for event in ENGINE_EVENTS:
        engine.on(event, server._forward(gid, event))
    engine.on(ENGINE_EVENT.CARD_ANIMATION, server._animation_handler(gid))


def setup_dead_human(tmp_path, gid="dead-1"):
    server = GameServer(history_path=tmp_path / "history.json")
    engine = MainEngine(dict(CONFIG))
    human = engine.human_player()
    human.alive = False
    human.hp = 0
    ws = Socket()
    attach(server, engine, gid, ws)
    server.tasks[gid] = asyncio.create_task(asyncio.sleep(30))
    return server, engine, ws


def test_live_human_cannot_enter_post_death_lifecycle(tmp_path):
    async def scenario():
        server = GameServer(history_path=tmp_path / "history.json")
        engine = MainEngine(dict(CONFIG))
        ws = Socket()
        attach(server, engine, "live", ws)
        await server.do_post_death_action(ws, {"action": "background"})
        assert ws.messages[-1]["type"] == "error"
        assert server.viewers["live"] is ws

    asyncio.run(scenario())


def test_dead_human_can_stay_as_public_spectator(tmp_path):
    async def scenario():
        server, _engine, ws = setup_dead_human(tmp_path)
        try:
            await server.do_post_death_action(ws, {"action": "spectate"})
            assert server.viewer_modes["dead-1"] == "spectator"
            assert ws.messages[-2] == {
                "type": "post_death_action_result", "game_id": "dead-1",
                "action": "spectate", "status": "accepted",
            }
            state = ws.messages[-1]["state"]
            assert state["post_death"] == {
                "available": True, "mode": "spectator",
                "actions": ["spectate", "background", "end"],
            }
            assert all("hand" not in row for row in state["players"])
            await server.do_action(ws, {"action": {"type": "end_phase"}, "target_ids": []})
            assert ws.messages[-1]["type"] == "error"
            assert "没有可操作" in ws.messages[-1]["message"]
        finally:
            server.tasks["dead-1"].cancel()

    asyncio.run(scenario())


def test_background_choice_detaches_without_grace_abort_and_allows_new_game(tmp_path):
    async def scenario():
        server, engine, ws = setup_dead_human(tmp_path)
        server.DISCONNECT_GRACE = 0.01
        try:
            await server.do_post_death_action(ws, {"action": "background"})
            assert ws.messages[-1]["type"] == "post_death_action_result"
            assert "dead-1" in server.background_games
            assert ws not in server.ws_map and "dead-1" not in server.viewers
            assert "dead-1" not in server.grace_tasks
            await server._end_orphaned_games("post_death_p1")
            await asyncio.sleep(0.03)
            assert not engine.game_aborted
        finally:
            server.tasks["dead-1"].cancel()

    asyncio.run(scenario())


def test_background_game_can_resume_and_end_action_is_idempotent(tmp_path):
    async def scenario():
        server, engine, first = setup_dead_human(tmp_path)
        try:
            await server.do_post_death_action(first, {"action": "background"})
            resumed = Socket()
            await server.do_resume(resumed, {"game_id": "dead-1", "profile_id": "post_death_p1"})
            assert "dead-1" not in server.background_games
            assert server.viewer_modes["dead-1"] == "spectator"
            assert resumed.messages[1]["state"]["post_death"]["mode"] == "spectator"
            await server.do_post_death_action(resumed, {"action": "end"})
            assert engine.game_aborted
            assert resumed.messages[-1]["type"] == "post_death_action_result"
            await server.do_post_death_action(resumed, {"action": "end"})
            assert resumed.messages[-1]["status"] == "already_finished"
            assert server.history.profile("post_death_p1")["total_games"] == 1
        finally:
            server.tasks["dead-1"].cancel()

    asyncio.run(scenario())


def test_animation_ack_metrics_measure_success_timeout_and_no_viewer(tmp_path):
    async def scenario():
        server = GameServer(history_path=tmp_path / "history.json")
        server.ANIMATION_ACK_TIMEOUT = 0.01
        engine = MainEngine(dict(CONFIG))
        ws = Socket()
        attach(server, engine, "anim", ws)
        handler = server._animation_handler("anim")

        acknowledged = asyncio.create_task(handler(await_ui=True, card_name="杀"))
        await asyncio.sleep(0)
        animation_id = next(iter(server.animation_waiters))
        await server.do_animation_done({"animation_id": animation_id})
        await acknowledged
        await handler(await_ui=True, card_name="闪")
        server.viewers.pop("anim")
        await handler(await_ui=True, card_name="桃")

        metrics = engine.animation_metrics
        assert metrics["awaited"] == 2
        assert metrics["acked"] == 1
        assert metrics["timed_out"] == 1
        assert metrics["no_viewer"] == 1
        summary = build_game_log(engine, {"state": engine.serialize()},
                                 include_thinking=False)["animation_diagnostics"]
        assert summary["ack_rate"] == 0.5
        assert summary["mean_ack_ms"] is not None
        assert summary["max_ack_ms"] is not None

    asyncio.run(scenario())
