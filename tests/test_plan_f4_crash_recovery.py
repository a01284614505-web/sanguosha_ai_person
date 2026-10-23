"""F4: versioned process restart recovery at safe engine boundaries."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from game_engine import MainEngine
from game_engine.recovery import RecoveryStore, dump_engine, restore_engine
from game_server import GameServer


CONFIG = {
    "mode": "5人身份局", "profile_id": "f4_profile", "deck_id": "standard",
    "player": {"name": "玩家"}, "ais": [{"name": f"AI{i}"} for i in range(4)],
    "human_action_timeout": 30,
}


class Socket:
    def __init__(self):
        self.messages = []

    async def send(self, raw):
        self.messages.append(json.loads(raw))


def ready_engine(game_id="f4abc"):
    engine = MainEngine(dict(CONFIG))
    engine.game_id = game_id
    assigned = engine.identity_system.assign_identities(
        engine.game_state.players, engine.game_state.mode, {})
    mode = __import__("game_engine.mode_registry", fromlist=["get_mode"]).get_mode(engine.game_state.mode)
    lord = assigned[mode.first_player_identity]
    lord.max_hp += mode.lord_hp_bonus; lord.hp += mode.lord_hp_bonus
    engine.game_state.current_player_index = engine.game_state.players.index(lord)
    engine.game_state.current_player = lord
    engine.game_state.round_anchor_index = engine.game_state.current_player_index
    return engine


def all_physical_ids(engine):
    state = engine.game_state
    ids = [card.id for card in state.deck + state.discard_pile]
    for player in state.players:
        ids.extend(card.id for card in player.hand + player.judge_area + player.shown
                   + player.temporary + player.treasure_cards)
        ids.extend(card.id for card in player.equipment.values())
    return ids


def test_snapshot_round_trip_has_version_no_runtime_futures_and_no_duplicate_cards():
    engine = ready_engine()
    engine._pending_requests["old-request"] = object()
    engine._open_prompts["old-request"] = {"event": "require_response", "payload": {}}
    payload = dump_engine(engine)
    encoded = json.dumps(payload, ensure_ascii=False)
    assert payload["version"] == 1
    assert "old-request" not in encoded
    assert "Future" not in encoded and "Socket" not in encoded

    restored = restore_engine(payload, MainEngine)
    ids = all_physical_ids(restored)
    assert len(ids) == restored.game_state.initial_deck_count == len(set(ids))
    assert restored._pending_requests == {}
    assert restored._open_prompts == {}


def test_snapshot_written_by_one_process_is_resumed_by_a_new_process(tmp_path):
    recovery_dir = tmp_path / "recovery"
    writer = """
from pathlib import Path
from tests.test_plan_f4_crash_recovery import ready_engine
from game_engine.recovery import RecoveryStore
engine = ready_engine('feed1234')
engine.completed_turns = 7
engine.game_state.players[0].hp = 2
RecoveryStore(Path(__import__('sys').argv[1])).save(engine)
"""
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
           "PYTHONDONTWRITEBYTECODE": "1"}
    made = subprocess.run([sys.executable, "-c", writer, str(recovery_dir)], env=env,
                          capture_output=True, text=True, timeout=20)
    assert made.returncode == 0, made.stderr

    reader = """
import asyncio, json
from pathlib import Path
from game_server import GameServer
class S:
 def __init__(self): self.messages=[]
 async def send(self, raw): self.messages.append(json.loads(raw))
async def go():
 s=S(); server=GameServer(history_path=Path(__import__('sys').argv[2]), recovery_path=Path(__import__('sys').argv[1]))
 await server.do_resume(s, {'game_id':'feed1234','profile_id':'f4_profile'})
 state=next(m['state'] for m in s.messages if m['type']=='game_state')
 print(json.dumps({'types':[m['type'] for m in s.messages], 'hp':state['players'][0]['hp'], 'turns':state['completed_turns']}))
 server.tasks['feed1234'].cancel()
asyncio.run(go())
"""
    read = subprocess.run([sys.executable, "-c", reader, str(recovery_dir), str(tmp_path / "history.json")],
                          env=env, capture_output=True, text=True, timeout=20)
    assert read.returncode == 0, read.stderr
    result = json.loads(read.stdout.strip().splitlines()[-1])
    assert result == {"types": ["game_resumed", "game_state", "trustee_status"],
                      "hp": 2, "turns": 7}


def test_old_request_is_stale_after_restart(tmp_path):
    async def scenario():
        engine = ready_engine("fade1234")
        engine._request_seq = 9
        old_request_id = engine._next_request_id()
        RecoveryStore(tmp_path / "recovery").save(engine)
        server = GameServer(history_path=tmp_path / "history.json", recovery_path=tmp_path / "recovery")
        ws = Socket()
        await server.do_resume(ws, {"game_id": "fade1234", "profile_id": "f4_profile"})
        await server.do_action(ws, {"action": {"type": "response",
                                                "request_id": old_request_id, "option_index": 0}})
        assert ws.messages[-1]["type"] == "action_result"
        assert ws.messages[-1]["status"] == "stale"
        assert server.engines["fade1234"]._request_epoch != engine._request_epoch
        server.tasks["fade1234"].cancel()
    asyncio.run(scenario())


def test_finished_snapshot_replay_records_history_once(tmp_path):
    async def resume_once(snapshot):
        store = RecoveryStore(tmp_path / "recovery")
        store.root.mkdir(parents=True, exist_ok=True)
        store.path("dead1234").write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        server = GameServer(history_path=tmp_path / "history.json", recovery_path=store.root)
        ws = Socket()
        await server.do_resume(ws, {"game_id": "dead1234", "profile_id": "f4_profile"})
        await asyncio.wait_for(server.tasks["dead1234"], timeout=5)
        return server.history.profile("f4_profile")["total_games"]

    engine = ready_engine("dead1234")
    engine.game_state.game_over = True; engine.game_state.winner = "lord"
    snapshot = dump_engine(engine)
    assert asyncio.run(resume_once(snapshot)) == 1
    assert asyncio.run(resume_once(snapshot)) == 1
