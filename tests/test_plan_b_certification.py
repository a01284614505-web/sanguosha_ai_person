"""Additional B2 branch evidence and report invalidation contract."""

import asyncio
import copy
import json
import shutil
from pathlib import Path
from unittest.mock import AsyncMock

from game_engine import MainEngine
from game_engine.skill_parity_certification import (
    ENGINE_INPUTS, DSL_SOURCE, REPORT_PATH, build_report, report_is_current, write_report,
)
from game_engine.skills_wei import WeiSkillHandler
from game_engine.state_manager import Card


ROOT = Path(__file__).resolve().parents[1]


def game():
    engine = MainEngine({"mode": "5人身份局", "player_name": "P0", "ais": [{"name": f"P{i}"} for i in range(1, 5)]})
    for player in engine.game_state.players:
        player.hand.clear(); player.equipment.clear(); player.shown.clear()
    engine.game_state.deck.clear()
    return engine


def programs(*names):
    definitions = json.loads((ROOT / "data/skill_dsl_coverage.json").read_text(encoding="utf-8"))["definitions"]
    return {name: copy.deepcopy(next(item["dsl"] for item in definitions if item["skill"] == name)) for name in names}


def install(engine, owner, skill_programs):
    owner.hero = {"id": "b2_cert", "name": "认证场景", "faction": "魏", "max_hp": owner.max_hp,
                  "skills": [{"name": name, "implementation_status": "active", "dsl": program}
                             for name, program in skill_programs.items()]}
    engine.skill_manager.bind_engine(engine)


def state(engine):
    return {
        "hands": [[card.id for card in player.hand] for player in engine.game_state.players],
        "discard": [card.id for card in engine.game_state.discard_pile],
        "deck": [card.id for card in engine.game_state.deck],
        "shown": [[card.id for card in player.shown] for player in engine.game_state.players],
        "hp": [player.hp for player in engine.game_state.players],
        "moves": [(m.card_id, m.from_zone, m.to_zone, m.from_owner, m.to_owner, m.reason)
                  for m in engine.game_state.card_move_events],
    }


def test_decline_unmet_and_cancelled_selection_match_native_and_dsl():
    # Decline, unmet condition (no source card), and a cancelled card choice
    # are compared through the native handler and the real DSL runtime.
    for branch in ("decline", "unmet", "cancelled"):
        outcomes = []
        for use_dsl in (False, True):
            engine = game(); source, owner = engine.game_state.players[:2]
            owner_card = Card("cert_jianxiong_damage", "杀", "spade", 7, "basic")
            source_card = Card("cert_fankui_source", "闪", "club", 4, "basic")
            if branch != "unmet":
                source.hand.append(source_card)
            engine.game_state.discard_pile.append(owner_card)
            if use_dsl:
                install(engine, owner, programs("反馈"))
                if branch == "decline":
                    engine.skill_manager.ask_confirm = AsyncMock(return_value=False)
                elif branch == "cancelled":
                    engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
                    engine.skill_manager.ask_choose_cards_result = AsyncMock(return_value={"status": "cancelled", "cards": []})
                asyncio.run(engine.skill_manager.after_damage(source, owner, 1, None, {}))
            else:
                native = WeiSkillHandler(engine.skill_manager)
                native.has = lambda player, name: player is owner and name == "反馈"
                native.manager.ask_confirm = AsyncMock(return_value=branch != "decline")
                if branch == "cancelled":
                    native.manager.ask_choose_cards_result = AsyncMock(return_value={"status": "cancelled", "cards": []})
                asyncio.run(native.after_damage(source, owner, 1, None, {}))
            outcomes.append(state(engine))
        assert outcomes[0] == outcomes[1], branch


def test_abort_during_optional_prompt_matches_native_and_dsl():
    outcomes = []
    for use_dsl in (False, True):
        engine = game(); owner = engine.game_state.players[1]
        judged = Card("cert_tiandu", "桃", "heart", 3, "basic")
        owner.shown.append(judged)
        if use_dsl:
            install(engine, owner, programs("天妒"))
            async def abort_dsl(*_args, **_kwargs):
                engine.game_state.game_over = True
                return True
            engine.skill_manager.ask_confirm = AsyncMock(side_effect=abort_dsl)
            result = asyncio.run(engine.skill_manager.after_judge(owner, judged, {"reason": "cert"}))
        else:
            native = WeiSkillHandler(engine.skill_manager)
            native.has = lambda player, name: player is owner and name == "天妒"
            async def abort_native(*_args, **_kwargs):
                engine.game_state.game_over = True
                return True
            native.manager.ask_confirm = AsyncMock(side_effect=abort_native)
            result = asyncio.run(native.after_judge(owner, judged, {"reason": "cert"}))
        outcomes.append((result, state(engine)))
    assert outcomes[0] == outcomes[1]
    assert outcomes[0][0] is False
    assert outcomes[0][1]["shown"][1] == ["cert_tiandu"]


def test_dead_owner_and_multi_skill_cross_trigger_match_native_and_dsl():
    # A terminal/dead state prevents both paths from committing. Then exercise
    # two skills on the same owner in one real damage trigger and compare zones.
    terminal = []
    for use_dsl in (False, True):
        engine = game(); source, owner = engine.game_state.players[:2]
        owner.alive = False
        owner.hp = 0
        engine.game_state.game_over = True
        damage_card = Card("cert_dead_damage", "杀", "spade", 8, "basic")
        engine.game_state.discard_pile.append(damage_card)
        if use_dsl:
            install(engine, owner, programs("奸雄"))
            engine.game_state.game_over = True
            result = asyncio.run(engine.skill_manager.after_damage(source, owner, 1, damage_card, {}))
        else:
            native = WeiSkillHandler(engine.skill_manager)
            native.has = lambda player, name: player is owner and name == "奸雄"
            engine.game_state.game_over = True
            result = asyncio.run(native.after_damage(source, owner, 1, damage_card, {}))
        terminal.append((result, state(engine)))
    assert terminal[0] == terminal[1]
    assert "cert_dead_damage" in terminal[0][1]["discard"]

    dead_owner = []
    for use_dsl in (False, True):
        engine = game(); source, owner = engine.game_state.players[:2]
        owner.alive = False; owner.hp = 0
        damage_card = Card("cert_dead_owner_damage", "杀", "spade", 8, "basic")
        engine.game_state.discard_pile.append(damage_card)
        if use_dsl:
            install(engine, owner, programs("奸雄"))
            engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
            next(item for item in engine.skill_manager.handlers if isinstance(item, WeiSkillHandler)).has = lambda *_args: False
            asyncio.run(engine.skill_manager.after_damage(source, owner, 1, damage_card, {}))
        else:
            native = WeiSkillHandler(engine.skill_manager)
            native.has = lambda player, name: player is owner and name == "奸雄"
            native.manager.ask_confirm = AsyncMock(return_value=True)
            asyncio.run(native.after_damage(source, owner, 1, damage_card, {}))
        dead_owner.append(state(engine))
    # Death during a continuing match must suppress both implementations and
    # leave the event card in discard without a transfer.
    assert dead_owner[0] == dead_owner[1]
    assert "cert_dead_owner_damage" not in dead_owner[0]["hands"][1]
    assert "cert_dead_owner_damage" in dead_owner[0]["discard"]
    assert dead_owner[0]["moves"] == []

    outcomes = []
    for use_dsl in (False, True):
        engine = game(); source, owner = engine.game_state.players[:2]
        damage_card = Card("cert_cross_damage", "杀", "spade", 8, "basic")
        stolen = Card("cert_cross_source", "闪", "club", 4, "basic")
        engine.game_state.discard_pile.append(damage_card)
        source.hand.append(stolen)
        engine.game_state.deck.append(Card("cert_cross_draw", "桃", "heart", 3, "basic"))
        if use_dsl:
            install(engine, owner, programs("奸雄", "反馈"))
            engine.skill_manager.ask_confirm = AsyncMock(side_effect=[True, True])
            engine.skill_manager.ask_choose_cards = AsyncMock(return_value=[stolen])
            # Avoid running the native counterparts after the DSL triggers.
            next(item for item in engine.skill_manager.handlers if isinstance(item, WeiSkillHandler)).has = lambda *_args: False
            asyncio.run(engine.skill_manager.after_damage(source, owner, 1, damage_card, {}))
        else:
            native = WeiSkillHandler(engine.skill_manager)
            native.has = lambda player, name: player is owner and name in {"奸雄", "反馈"}
            native.manager.ask_confirm = AsyncMock(side_effect=[True, True])
            native.manager.ask_choose_cards = AsyncMock(return_value=[stolen])
            asyncio.run(native.after_damage(source, owner, 1, damage_card, {}))
        outcomes.append(state(engine))
    assert outcomes[0] == outcomes[1]
    assert "cert_cross_damage" in outcomes[0]["hands"][1]
    assert "cert_cross_source" in outcomes[0]["hands"][1]


def test_machine_readable_report_is_content_and_engine_bound():
    report = write_report()
    assert report["rules_version_verified"] is False
    assert report["overall_status"] == "listed_scenarios_parity_with_branch_gaps"
    assert report["observed_divergences"] == []
    assert len(report["skills"]) == 10
    assert report_is_current(report)
    stale_dsl = copy.deepcopy(report)
    stale_dsl["dsl_sha256_by_skill"]["天妒"] = "changed"
    assert not report_is_current(stale_dsl)
    stale_engine = copy.deepcopy(report)
    stale_engine["engine_version"] = "changed"
    assert not report_is_current(stale_engine)
    assert json.loads(REPORT_PATH.read_text(encoding="utf-8")) == report


def test_report_becomes_stale_when_bound_engine_or_dsl_content_changes(tmp_path):
    for relative in (*ENGINE_INPUTS, DSL_SOURCE):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    report = build_report(tmp_path)
    assert report_is_current(report, tmp_path)
    engine_input = tmp_path / ENGINE_INPUTS[0]
    engine_input.write_bytes(engine_input.read_bytes() + b"\n# changed engine source\n")
    assert not report_is_current(report, tmp_path)
    report = build_report(tmp_path)
    dsl_input = tmp_path / DSL_SOURCE
    dsl_input.write_bytes(dsl_input.read_bytes() + b"\n")
    assert not report_is_current(report, tmp_path)

