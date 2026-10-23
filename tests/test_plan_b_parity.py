"""First five Stage 8 Python/DSL behavior parity scenes (B2)."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

from game_engine import MainEngine
from game_engine.skills_wei import WeiSkillHandler
from game_engine.state_manager import Card


def game():
    engine = MainEngine({
        "mode": "5人身份局", "player_name": "P0",
        "ais": [{"name": f"P{i}"} for i in range(1, 5)],
    })
    for player in engine.game_state.players:
        player.hand.clear()
        player.equipment.clear()
        player.shown.clear()
    engine.game_state.deck.clear()
    return engine


def skill_program(name):
    manifest = Path(__file__).resolve().parents[1] / "data" / "skill_dsl_coverage.json"
    definitions = json.loads(manifest.read_text(encoding="utf-8"))["definitions"]
    return next(item["dsl"] for item in definitions if item["skill"] == name)


def install_dsl(engine, owner, name):
    owner.hero = {
        "id": f"plan_b_{name}", "name": f"{name}对照场景", "faction": "魏",
        "max_hp": owner.max_hp,
        "skills": [{"name": f"{name}测试技", "description": "", "implementation_status": "active",
                    "dsl": skill_program(name)}],
    }
    engine.skill_manager.bind_engine(engine)


def zones(engine):
    return {
        "hands": [[card.id for card in p.hand] for p in engine.game_state.players],
        "equipment": [[(slot, card.id) for slot, card in p.equipment.items()]
                      for p in engine.game_state.players],
        "shown": [[card.id for card in p.shown] for p in engine.game_state.players],
        "discard": [card.id for card in engine.game_state.discard_pile],
        "deck": [card.id for card in engine.game_state.deck],
        "hp": [p.hp for p in engine.game_state.players],
        "moves": [(m.card_id, m.from_zone, m.to_zone, m.from_owner, m.to_owner, m.reason)
                  for m in engine.game_state.card_move_events],
    }


def test_tiandu_dsl_matches_native_claim_of_judgment_card():
    outcomes = []
    for use_dsl in (False, True):
        engine = game()
        owner = engine.game_state.players[0]
        judged = Card("b_tiandu_judged", "闪", "heart", 8, "basic")
        owner.shown.append(judged)
        if use_dsl:
            install_dsl(engine, owner, "天妒")
            engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
            claimed = asyncio.run(engine.skill_manager.after_judge(owner, judged, {"reason": "parity"}))
        else:
            native = WeiSkillHandler(engine.skill_manager)
            native.has = lambda player, skill: skill == "天妒"
            native.manager.ask_confirm = AsyncMock(return_value=True)
            claimed = asyncio.run(native.after_judge(owner, judged, {"reason": "parity"}))
        assert claimed is True
        outcomes.append(zones(engine))
    assert outcomes[0] == outcomes[1]


def test_guicai_dsl_matches_native_judgment_replacement_and_discard():
    outcomes = []
    for use_dsl in (False, True):
        engine = game()
        judged_player, owner = engine.game_state.players[:2]
        old = Card("b_guicai_old", "杀", "spade", 2, "basic")
        replacement = Card("b_guicai_new", "桃", "heart", 4, "basic")
        judged_player.shown.append(old)
        owner.hand.append(replacement)
        if use_dsl:
            install_dsl(engine, owner, "鬼才")
            engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
            engine.skill_manager.ask_choose_cards = AsyncMock(return_value=[replacement])
            result = asyncio.run(engine.skill_manager.before_judge(judged_player, old, {"reason": "parity"}))
        else:
            native = WeiSkillHandler(engine.skill_manager)
            native.has = lambda player, skill: player is owner and skill == "鬼才"
            native.manager.ask_confirm = AsyncMock(return_value=True)
            native.manager.ask_choose_cards_result = AsyncMock(return_value={
                "status": "resolved", "cards": [replacement],
            })
            result = asyncio.run(native.before_judge(judged_player, old, {"reason": "parity"}))
        assert result is replacement
        outcomes.append(zones(engine))
    assert outcomes[0] == outcomes[1]


def test_guidao_dsl_matches_native_black_replacement_claim_and_spade_draw():
    outcomes = []
    for use_dsl in (False, True):
        engine = game()
        judged_player, owner = engine.game_state.players[:2]
        old = Card("b_guidao_old", "杀", "heart", 2, "basic")
        replacement = Card("b_guidao_new", "杀", "spade", 7, "basic")
        draw = Card("b_guidao_draw", "桃", "heart", 3, "basic")
        judged_player.shown.append(old)
        owner.hand.append(replacement)
        engine.game_state.deck[:] = [draw]
        if use_dsl:
            install_dsl(engine, owner, "鬼道")
            engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
            engine.skill_manager.ask_choose_cards = AsyncMock(return_value=[replacement])
            result = asyncio.run(engine.skill_manager.before_judge(judged_player, old, {"reason": "parity"}))
        else:
            from game_engine.skills_qun import QunSkillHandler
            native = QunSkillHandler(engine.skill_manager)
            native.has = lambda player, skill: player is owner and skill == "鬼道"
            native.manager.ask_confirm = AsyncMock(return_value=True)
            native.manager.ask_choose_cards_result = AsyncMock(return_value={
                "status": "resolved", "cards": [replacement],
            })
            result = asyncio.run(native.before_judge(judged_player, old, {"reason": "parity"}))
        assert result is replacement
        outcomes.append(zones(engine))
    assert outcomes[0] == outcomes[1]


def test_jianxiong_dsl_matches_native_gain_damage_card_and_draw():
    outcomes = []
    for use_dsl in (False, True):
        engine = game()
        source, owner = engine.game_state.players[:2]
        damage_card = Card("b_jianxiong_damage", "杀", "spade", 7, "basic")
        draw = Card("b_jianxiong_draw", "桃", "heart", 3, "basic")
        engine.game_state.discard_pile.append(damage_card)
        engine.game_state.deck[:] = [draw]
        if use_dsl:
            install_dsl(engine, owner, "奸雄")
            engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
            asyncio.run(engine.skill_manager.after_damage(source, owner, 1, damage_card, {}))
        else:
            native = WeiSkillHandler(engine.skill_manager)
            native.has = lambda player, skill: player is owner and skill == "奸雄"
            native.manager.ask_confirm = AsyncMock(return_value=True)
            asyncio.run(native.after_damage(source, owner, 1, damage_card, {}))
        outcomes.append(zones(engine))
    assert outcomes[0] == outcomes[1]


def test_fankui_dsl_matches_native_card_transfer_per_damage_point_and_decline():
    outcomes = []
    for use_dsl in (False, True):
        engine = game()
        source, owner = engine.game_state.players[:2]
        stolen = Card("b_fankui_source", "闪", "club", 4, "basic")
        source.hand.append(stolen)
        if use_dsl:
            install_dsl(engine, owner, "反馈")
            engine.skill_manager.ask_confirm = AsyncMock(side_effect=[True, False])
            engine.skill_manager.ask_choose_cards = AsyncMock(return_value=[stolen])
            asyncio.run(engine.skill_manager.after_damage(source, owner, 2, None, {}))
        else:
            native = WeiSkillHandler(engine.skill_manager)
            native.has = lambda player, skill: player is owner and skill == "反馈"
            native.manager.ask_confirm = AsyncMock(side_effect=[True, False])
            native.manager.ask_choose_cards = AsyncMock(return_value=[stolen])
            asyncio.run(native.after_damage(source, owner, 2, None, {}))
        outcomes.append(zones(engine))
    assert outcomes[0] == outcomes[1]
