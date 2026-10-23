"""Independent behavioral audit of F4 recovery and E1 background games.

This file intentionally does not patch production code. A failing assertion is
an audit finding to report, not a reason to weaken the expected contract.
"""

import asyncio
import json

import pytest

from game_engine import MainEngine
from game_engine.recovery import RecoveryStore, dump_engine, restore_engine
from game_engine.protocol import ENGINE_EVENT, ENGINE_EVENTS, OUTBOUND
from game_server import GameServer


CONFIG = {
    "mode": "5人身份局", "profile_id": "f4_audit_profile", "deck_id": "standard",
    "player": {"name": "审查玩家"}, "ais": [{"name": f"AuditAI{i}"} for i in range(4)],
    "human_action_timeout": 30,
}


class Socket:
    def __init__(self):
        self.messages = []

    async def send(self, raw):
        self.messages.append(json.loads(raw))


def make_engine(game_id="audit1234", profile_id="f4_audit_profile"):
    config = dict(CONFIG)
    config["profile_id"] = profile_id
    engine = MainEngine(config)
    engine.game_id = game_id
    return engine


def physical_ids(engine):
    state = engine.game_state
    ids = [card.id for card in state.deck + state.discard_pile]
    for player in state.players:
        ids.extend(card.id for card in player.hand + player.judge_area + player.shown
                   + player.temporary + player.treasure_cards)
        ids.extend(card.id for card in player.equipment.values())
    return ids


def attach(server, engine, gid, ws):
    engine.game_id = gid
    server.engines[gid] = engine
    server.ws_map[ws] = gid
    server.viewers[gid] = ws
    server.viewer_modes[gid] = "player"
    for event in ENGINE_EVENTS:
        engine.on(event, server._forward(gid, event))
    engine.on(ENGINE_EVENT.CARD_ANIMATION, server._animation_handler(gid))


def test_recovery_rejects_malformed_and_old_version_snapshots(tmp_path):
    async def resume_case(game_id, content):
        recovery_dir = tmp_path / game_id
        recovery_dir.mkdir()
        (recovery_dir / f"{game_id}.json").write_text(content, encoding="utf-8")
        server = GameServer(history_path=tmp_path / f"{game_id}-history.json", recovery_path=recovery_dir)
        ws = Socket()
        await server.do_resume(ws, {"game_id": game_id, "profile_id": "f4_audit_profile"})
        return ws.messages

    async def scenario():
        invalid_json = await resume_case("bad00001", "{not-json")
        assert invalid_json[-1]["type"] == OUTBOUND.RESUME_FAILED
        assert invalid_json[-1]["reason"] == "not_found"

        old = dump_engine(make_engine("01d0e001"))
        old["version"] = 0
        old_version = await resume_case("01d0e001", json.dumps(old))
        assert old_version[-1]["type"] == OUTBOUND.RESUME_FAILED
        assert old_version[-1]["reason"] == "not_found"

    asyncio.run(scenario())


def test_resume_rejects_other_profile_before_restoring_engine(tmp_path):
    recovery = RecoveryStore(tmp_path / "recovery")
    recovery.save(make_engine("face0001"))
    server = GameServer(history_path=tmp_path / "history.json", recovery_path=recovery.root)
    ws = Socket()
    asyncio.run(server.do_resume(ws, {"game_id": "face0001", "profile_id": "other_profile"}))
    assert ws.messages[-1]["type"] == OUTBOUND.RESUME_FAILED
    assert ws.messages[-1]["reason"] == "forbidden"
    assert "face0001" not in server.engines


def test_restarted_process_rejects_old_request_epoch(tmp_path):
    async def scenario():
        engine = make_engine("57a1e234")
        engine._request_seq = 5
        old_id = engine._next_request_id()
        RecoveryStore(tmp_path / "recovery").save(engine)
        server = GameServer(history_path=tmp_path / "history.json", recovery_path=tmp_path / "recovery")
        ws = Socket()
        await server.do_resume(ws, {"game_id": "57a1e234", "profile_id": "f4_audit_profile"})
        restored = server.engines["57a1e234"]
        assert restored._request_epoch != engine._request_epoch
        await server.do_action(ws, {"action": {"type": "response", "request_id": old_id,
                                               "option_index": 0}})
        assert ws.messages[-1]["type"] == OUTBOUND.ACTION_RESULT
        assert ws.messages[-1]["status"] == "stale"
        server.tasks["57a1e234"].cancel()
        await asyncio.gather(server.tasks["57a1e234"], return_exceptions=True)

    asyncio.run(scenario())


def test_same_profile_new_game_does_not_abort_detached_background_game(tmp_path):
    async def scenario():
        server = GameServer(history_path=tmp_path / "history.json", recovery_path=tmp_path / "recovery")
        old = make_engine("bacc6001")
        old.game_state.players[0].alive = False
        old.game_state.players[0].hp = 0
        old_ws = Socket()
        attach(server, old, "bacc6001", old_ws)
        server.background_games["bacc6001"] = CONFIG["profile_id"]
        release = asyncio.Event()
        new_started = asyncio.Event()

        async def hold_run(gid, engine):
            if gid != "bacc6001":
                new_started.set()
            await release.wait()

        server._run_engine = hold_run
        new_ws = Socket()
        await server.do_create(new_ws, CONFIG)
        await asyncio.wait_for(new_started.wait(), timeout=5)
        new_gid = new_ws.messages[0]["game_id"]
        assert new_gid != "bacc6001"
        assert "bacc6001" in server.background_games
        assert not old.game_aborted
        assert server.engines[new_gid].game_config["profile_id"] == CONFIG["profile_id"]
        for task in server.tasks.values():
            task.cancel()
        release.set()
        await asyncio.gather(*server.tasks.values(), return_exceptions=True)

    asyncio.run(scenario())


def test_repeat_end_request_records_one_settlement(tmp_path):
    async def scenario():
        server = GameServer(history_path=tmp_path / "history.json", recovery_path=tmp_path / "recovery")
        engine = make_engine("5e771e23")
        engine.game_state.players[0].alive = False
        engine.game_state.players[0].hp = 0
        ws = Socket()
        attach(server, engine, "5e771e23", ws)
        server.tasks["5e771e23"] = asyncio.create_task(asyncio.sleep(30))
        await server.do_post_death_action(ws, {"action": "end"})
        first_total = server.history.profile(CONFIG["profile_id"])["total_games"]
        await server.do_post_death_action(ws, {"action": "end"})
        assert ws.messages[-1]["status"] == "already_finished"
        assert first_total == 1
        assert server.history.profile(CONFIG["profile_id"])["total_games"] == 1
        server.tasks["5e771e23"].cancel()

    asyncio.run(scenario())


def test_restore_rejects_duplicate_physical_card_zone_reference():
    engine = make_engine("a11ce123")
    payload = dump_engine(engine)
    hand_card_id = payload["state"]["players"][0]["hand"][0]
    payload["state"]["deck"].append(hand_card_id)
    with pytest.raises(ValueError, match="duplicate|exactly once|card"):
        restore_engine(payload, MainEngine)
