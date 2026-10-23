"""Stage 8 integration review: persisted imports must execute through the real engine."""
import asyncio
import http.client
import json
from pathlib import Path
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import AsyncMock

import pytest

from game_engine import MainEngine
from game_engine.config_validator import normalize_config
from game_engine.hero_package_store import HeroPackageStore
from game_engine.hero_registry import HeroRegistry
from game_engine.state_manager import Phase


@pytest.fixture
def imported_game(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    root = Path(__file__).resolve().parents[1]
    (data / "heroes.json").write_bytes((root / "data/heroes.json").read_bytes())
    store = HeroPackageStore(tmp_path)

    def build(trigger="play_action", status="active", effects=None, cost=None):
        program = {"version": 1, "trigger": trigger,
                   "effects": effects or [{"type": "draw_cards", "count": 1}]}
        if cost is not None:
            program["cost"] = cost
        store.import_hero({"id": "review_pack", "name": "审查包"}, {
            "id": "review_hero", "name": "审查将", "faction": "群", "max_hp": 4,
            "skills": [{"name": "审查技能", "implementation_status": status, "dsl": program}],
        })
        store.set_enabled("review_pack", True)
        config = normalize_config({"selected_hero": {"id": "review_hero"},
                                   "ais": [{"name": str(i)} for i in range(4)]},
                                  hero_registry=HeroRegistry(tmp_path))
        engine = MainEngine(config)
        engine.game_state.current_phase = Phase.PLAY
        return engine, engine.game_state.players[0], store
    return build


def test_persisted_active_import_draws_real_card_and_pool_disable_preserves_game(imported_game):
    engine, owner, store = imported_game()
    manager = engine.skill_manager
    action = next(a for a in manager.get_actions(owner) if a.get("variant") == "dsl")
    before = len(owner.hand)
    assert asyncio.run(manager.execute(owner, action, []))
    assert len(owner.hand) == before + 1
    assert engine.game_state.card_move_events[-1].to_owner == owner.id
    store.set_enabled("review_pack", False)
    assert "review_hero" not in {h["id"] for h in HeroRegistry(store.project_root).all_heroes()}
    assert manager.has_skill(owner, "审查技能")


@pytest.mark.parametrize("status", ["partial", "data_only"])
def test_nonactive_import_never_offers_or_executes_action(imported_game, status):
    engine, owner, _ = imported_game(status=status)
    manager = engine.skill_manager
    assert not any(a.get("variant") == "dsl" for a in manager.get_actions(owner))
    before = len(owner.hand)
    assert not asyncio.run(manager.execute(owner, {"variant": "dsl", "skill_name": "审查技能"}, []))
    assert len(owner.hand) == before


def test_disabled_and_wrong_phase_actions_cannot_execute(imported_game):
    engine, owner, _ = imported_game()
    manager = engine.skill_manager
    action = next(a for a in manager.get_actions(owner) if a.get("variant") == "dsl")
    engine.game_state.current_phase = Phase.DRAW
    assert not asyncio.run(manager.execute(owner, action, []))
    engine.game_state.current_phase = Phase.PLAY
    manager.disable_skill(owner, manager.player_skills(owner)[0].skill_id)
    assert not any(a.get("variant") == "dsl" for a in manager.get_actions(owner))
    assert not asyncio.run(manager.execute(owner, action, []))


def test_card_gained_draw_trigger_terminates_and_respects_disable(imported_game):
    engine, owner, _ = imported_game(trigger="card_gained")
    manager = engine.skill_manager
    before = len(owner.hand)
    asyncio.run(manager.draw_cards(owner, 1))
    assert len(owner.hand) == before + 2
    manager.disable_skill(owner, manager.player_skills(owner)[0].skill_id)
    asyncio.run(manager.draw_cards(owner, 1))
    assert len(owner.hand) == before + 3


def test_cancelled_card_cost_does_not_apply_effect(imported_game):
    engine, owner, _ = imported_game(cost=[{"interaction": "ask_choose_cards", "min": 1, "max": 1}])
    manager = engine.skill_manager
    manager.ask_choose_cards = AsyncMock(return_value=[])
    before = len(owner.hand)
    assert not asyncio.run(manager.execute(owner, {"variant": "dsl", "skill_name": "审查技能"}, []))
    assert len(owner.hand) == before


@pytest.fixture
def hero_http(tmp_path, monkeypatch):
    import game_server
    monkeypatch.setattr(game_server, "BASE_DIR", tmp_path)
    (tmp_path / "data").mkdir()
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "data/heroes.json").write_bytes((root / "data/heroes.json").read_bytes())
    server = ThreadingHTTPServer(("127.0.0.1", 0), game_server.CustomHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(path, payload=None, method="POST"):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        body = json.dumps(payload).encode() if payload is not None else None
        try:
            conn.request(method, path, body, {"Content-Type": "application/json"})
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()
    yield request
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_http_import_enable_and_read_pool(hero_http):
    payload = {"package": {"id": "http_pack", "name": "HTTP包"},
               "hero": {"id": "http_hero", "name": "HTTP将", "faction": "蜀", "max_hp": 4}}
    assert hero_http("/api/heroes/import", payload)[0] == 200
    status, data = hero_http("/api/heroes", method="GET")
    assert status == 200
    assert "http_hero" not in {h["id"] for h in data["heroes"]}
    assert hero_http("/api/hero-packages/http_pack/enabled", {"enabled": True})[0] == 200
    assert "http_hero" in {h["id"] for h in hero_http("/api/heroes", method="GET")[1]["heroes"]}


@pytest.mark.parametrize("payload", [[], {"package": {}, "hero": {}},
    {"package": {"id": "bad", "name": "坏包"},
     "hero": {"id": "bad_hero", "name": "坏将", "faction": [], "max_hp": 4}}])
def test_invalid_http_import_returns_client_error(hero_http, payload):
    assert hero_http("/api/heroes/import", payload)[0] == 400


def test_corrupt_current_package_store_is_reported_as_server_error(hero_http, tmp_path):
    payload = {"package": {"id": "broken_pack", "name": "损坏包"},
               "hero": {"id": "broken_hero", "name": "损坏将", "faction": "蜀", "max_hp": 4}}
    assert hero_http("/api/heroes/import", payload)[0] == 200
    store_path = tmp_path / "data" / "hero_packages.json"
    current = json.loads(store_path.read_text(encoding="utf-8"))
    current["packages"][0]["heroes"][0] = None
    store_path.write_text(json.dumps(current), encoding="utf-8")

    status, data = hero_http("/api/hero-packages/broken_pack/enabled", {"enabled": True})
    assert status == 500
    assert not data["success"]


def test_ai_conversion_uses_mock_gateway_without_external_calls(hero_http, monkeypatch):
    import game_server
    gateway = AsyncMock(return_value=json.dumps({"id": "converted", "name": "转换将", "skills": []}))
    monkeypatch.setattr(game_server.AIGateway, "call_ai", gateway)
    status, data = hero_http("/api/heroes/convert", {
        "text": "转换将 蜀", "provider": "openai", "model": "mock", "api_key": "test-placeholder"})
    assert status == 200
    assert data["hero"]["id"] == "converted"
    gateway.assert_awaited_once()


def test_runtime_budget_disables_skill_without_interrupting_game(imported_game):
    engine, owner, _ = imported_game(effects=[{"type": "recover", "amount": 0}] * 30)
    owner.hero["skills"][0]["dsl"]["targets"] = {"selector": "alive_others", "min": 1, "max": 4}
    manager = engine.skill_manager
    manager.bind_engine(engine)
    assert not asyncio.run(manager.execute(owner, {"variant": "dsl", "skill_name": "审查技能"}, []))
    assert not manager.has_skill(owner, "审查技能")
    assert not engine.game_aborted


def test_game_end_during_confirmation_prevents_following_effect(imported_game):
    engine, owner, _ = imported_game(cost=[{"interaction": "ask_confirm"}])
    manager = engine.skill_manager

    async def abort(*args, **kwargs):
        engine.game_state.game_over = True
        return True

    manager.ask_confirm = abort
    before = len(owner.hand)
    assert not asyncio.run(manager.execute(owner, {"variant": "dsl", "skill_name": "审查技能"}, []))
    assert len(owner.hand) == before


def test_counter_damage_credits_skill_owner_as_declared_source(imported_game):
    engine, owner, _ = imported_game(trigger="damage_received", effects=[{
        "type": "damage", "source": "owner", "target": "source", "amount": 1,
    }])
    attacker = engine.game_state.players[1]
    engine.card_system.damage = AsyncMock()
    asyncio.run(engine.skill_manager.after_damage(attacker, owner, 1))
    call = engine.card_system.damage.await_args
    assert call.args[:3] == (owner, attacker, 1)
