"""Behavioral contracts for the isolated Stage 8 skill-trial engine."""

import json
import random
import shutil
import threading
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory
from http.server import ThreadingHTTPServer

from game_engine.hero_trial import _TrialHarness, _public_state, _validate_request, run_hero_trial
from game_engine.state_manager import Card, PlayerStatus


def payload():
    return {
        "package": {"id": "trial-isolation-package", "name": "隔离试验包", "version": "1.0"},
        "hero": {
            "id": "trial_isolation_hero", "name": "隔离试验将", "faction": "魏", "max_hp": 4,
            "skills": [{
                "name": "隔离摸牌技", "implementation_status": "active",
                "dsl": {"version": 1, "trigger": "phase_start",
                        "condition": {"op": "eq", "path": "event.phase", "value": "draw"},
                        "effects": [{"type": "draw_cards", "target": "owner", "count": 1,
                                     "reason": "试验隔离"}]},
            }],
        },
        "scenario_id": "phase_draw",
        "seed": 20261019,
    }


def test_full_trial_payload_is_deterministic_for_the_same_seed():
    request = payload()
    first = run_hero_trial(request)
    second = run_hero_trial(request)
    assert first == second
    assert first["scenario_id"] == "phase_draw"
    assert first["seed"] == request["seed"]
    assert first["outcome"] == "success"


def test_trial_uses_isolated_rng_and_does_not_advance_module_global_random():
    random.seed(8675309)
    before = random.getstate()

    result = run_hero_trial(payload())

    assert result["outcome"] == "success"
    assert random.getstate() == before


def test_trial_opponents_have_no_native_or_imported_skills():
    package, hero, scenario_id, seed = _validate_request(payload(), Path.cwd())
    harness = _TrialHarness(hero, scenario_id, seed)
    opponents = harness.engine.game_state.players[1:]

    assert len(opponents) == 4
    assert [player.hero["id"] for player in opponents] == [
        "trial_dummy_1", "trial_dummy_2", "trial_dummy_3", "trial_dummy_4",
    ]
    assert all(player.hero.get("skills", []) == [] for player in opponents)
    assert all(harness.engine.skill_manager.player_skills(player) == [] for player in opponents)
    assert package["id"] == "trial-isolation-package"


def test_trial_state_explains_public_zones_status_marks_and_skill_usage_without_hidden_cards():
    _package, hero, scenario_id, seed = _validate_request(payload(), Path.cwd())
    harness = _TrialHarness(hero, scenario_id, seed)
    owner = harness.owner
    owner.status = PlayerStatus.TURNED
    owner.chained = True
    owner.sha_count = 1
    owner.flags["skill_used"] = {"隔离摸牌技": True}
    owner.equipment["weapon"] = Card("public_weapon", "青龙偃月刀", "spade", 5, "equipment")
    owner.judge_area.append(Card("public_judge", "乐不思蜀", "heart", 6, "trick"))
    owner.shown.append(Card("public_shown", "桃", "heart", 3, "basic"))
    owner.treasure_cards.append(Card("hidden_ox", "杀", "spade", 7, "basic"))
    hidden_hand_ids = {card.id for player in harness.engine.game_state.players for card in player.hand}

    state = _public_state(harness.engine)
    owner_state = state["players"][0]
    encoded = json.dumps(state, ensure_ascii=False)

    assert owner_state["status"] == "turned"
    assert owner_state["chained"] is True
    assert owner_state["sha_count"] == 1
    assert owner_state["equipment"]["weapon"]["name"] == "青龙偃月刀"
    assert owner_state["judge_area"][0]["name"] == "乐不思蜀"
    assert owner_state["shown"][0]["name"] == "桃"
    assert owner_state["treasure_count"] == 1
    assert owner_state["marks"]["skill_used"]["隔离摸牌技"] is True
    assert owner_state["skill_state"][0]["skill_id"].endswith("隔离摸牌技")
    assert all(card_id not in encoded for card_id in hidden_hand_ids | {"hidden_ox"})


def test_http_trial_reports_real_runtime_budget_exhaustion_without_persisting_package(monkeypatch):
    import game_server

    root = Path(__file__).resolve().parents[1]
    with TemporaryDirectory(prefix="plan-b-trial-http-") as temp:
        base_dir = Path(temp)
        data_dir = base_dir / "data"
        data_dir.mkdir()
        shutil.copy2(root / "data" / "heroes.json", data_dir / "heroes.json")
        heroes_before = (data_dir / "heroes.json").read_bytes()
        monkeypatch.setattr(game_server, "BASE_DIR", base_dir)
        server = ThreadingHTTPServer(("127.0.0.1", 0), game_server.CustomHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        request_body = payload()
        request_body["hero"]["skills"][0]["dsl"] = {
            "version": 1, "trigger": "phase_start",
            "condition": {"op": "eq", "path": "event.phase", "value": "draw"},
            "effects": [{"type": "repeat", "count": 52, "effects": [
                {"type": "set_state", "key": "budget_counter", "op": "add", "value": 1},
            ]}],
        }
        wire_request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/heroes/trial",
            data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(wire_request, timeout=10) as response:
                payload_out = json.loads(response.read().decode("utf-8"))
                assert response.status == 200
                assert payload_out["success"] is True
                assert payload_out["trial"]["outcome"] == "budget_exhausted"
                assert any(item["code"] == "budget_exhausted"
                           for item in payload_out["trial"]["diagnostics"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        assert (data_dir / "heroes.json").read_bytes() == heroes_before
        assert not (data_dir / "hero_packages.json").exists()
