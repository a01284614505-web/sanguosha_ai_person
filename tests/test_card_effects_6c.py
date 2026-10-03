#!/usr/bin/env python3
"""Stage 6C 测试：8 张锦囊 + 装备槽系统"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from game_engine.state_manager import Player, Card
from game_engine.card_table import CARD_TABLE
from game_engine.card_system import CardSystem


def run(coro):
    return asyncio.run(coro)


# ── 工具函数 ───────────────────────────────────────────────

def make_card(name, suit="spade", rank=5):
    spec = CARD_TABLE.get(name)
    ct = spec.card_type if spec else "trick"
    return Card(id=f"{name}_{suit}_{rank}", name=name, suit=suit, rank=rank, card_type=ct)


def make_player(pid, hp=4, hand=None, is_ai=True):
    p = Player(id=pid, name=f"P{pid}", hp=hp, max_hp=4, is_ai=is_ai)
    p.hand = list(hand or [])
    return p


def make_cs(players, engine=None):
    gs = MagicMock()
    gs.players = players
    gs.deck = [make_card("杀") for _ in range(20)]
    gs.discard_pile = []
    tm = MagicMock()
    tm.before_card_target = AsyncMock(side_effect=lambda a, b, c: b)
    tm.before_sha = AsyncMock()
    tm.modify_damage = AsyncMock(side_effect=lambda *a, **k: a[2])
    tm.after_damage = AsyncMock()
    tm.on_cards_lost = AsyncMock()
    tm.on_card_discarded = AsyncMock()
    tm.on_card_responded = AsyncMock()
    tm.on_card_gained = AsyncMock()
    tm.on_recover = AsyncMock()
    tm.protect_card = MagicMock(return_value=False)
    cs = CardSystem(gs, None, tm, engine=engine)
    cs.responder = None
    cs.ask_wuxie = AsyncMock(return_value=False)
    return cs


# ── 6C-2 武器范围查表 ──────────────────────────────────────

def test_weapon_range_from_card_table():
    p = make_player(0)
    p.equipment["weapon"] = make_card("麒麟弓")
    assert p.get_equipment_range() == 5


def test_weapon_range_qinglong():
    p = make_player(0)
    p.equipment["weapon"] = make_card("青龙偃月刀")
    assert p.get_equipment_range() == 3


def test_weapon_range_default_no_weapon():
    p = make_player(0)
    assert p.get_equipment_range() == 1


# ── 6C-5 装备槽 / 坐骑 ────────────────────────────────────

def test_equip_weapon_slot():
    p = make_player(0)
    cs = make_cs([p])
    sword = make_card("青釭剑")
    result = run(cs.use_equipment(p, sword))
    assert result is True
    assert p.equipment.get("weapon") is sword


def test_equip_replaces_old_weapon():
    p = make_player(0)
    old = make_card("麒麟弓")
    p.equipment["weapon"] = old
    cs = make_cs([p])
    new = make_card("青釭剑")
    run(cs.use_equipment(p, new))
    assert p.equipment["weapon"] is new
    assert old in cs.game_state.discard_pile


def test_equip_minus_horse_slot():
    p = make_player(0)
    cs = make_cs([p])
    horse = make_card("赤兔")
    run(cs.use_equipment(p, horse))
    assert p.equipment.get("minus_horse") is horse


def test_equip_plus_horse_slot():
    p = make_player(0)
    cs = make_cs([p])
    horse = make_card("绝影")
    run(cs.use_equipment(p, horse))
    assert p.equipment.get("plus_horse") is horse


# ── 决斗 ──────────────────────────────────────────────────

def test_juedou_target_no_sha_takes_damage():
    attacker = make_player(0)
    defender = make_player(1)
    cs = make_cs([attacker, defender])
    cs.responder = AsyncMock(return_value={"bool": False})
    jd = make_card("决斗")
    run(cs.use_juedou(attacker, jd, defender))
    assert defender.hp == 3


def test_juedou_attacker_no_sha_takes_damage():
    attacker = make_player(0)
    defender = make_player(1)
    sha = make_card("杀")
    defender.hand = [sha]
    cs = make_cs([attacker, defender])
    call_count = [0]

    async def responder(player, req):
        call_count[0] += 1
        if player is defender and call_count[0] == 1:
            return {"bool": True, "card": sha, "owner": defender, "as_name": "杀"}
        return {"bool": False}

    cs.responder = responder
    jd = make_card("决斗")
    run(cs.use_juedou(attacker, jd, defender))
    assert attacker.hp == 3


# ── 南蛮入侵 ──────────────────────────────────────────────

def test_nanman_all_no_sha_all_damaged():
    src = make_player(0)
    p1 = make_player(1)
    p2 = make_player(2)
    p1.alive = True
    p2.alive = True
    cs = make_cs([src, p1, p2])
    cs.responder = AsyncMock(return_value={"bool": False})
    nm = make_card("南蛮入侵")
    run(cs.use_nanman(src, nm))
    assert p1.hp == 3
    assert p2.hp == 3
    assert src.hp == 4


def test_nanman_with_sha_no_damage():
    src = make_player(0)
    victim = make_player(1)
    sha = make_card("杀")
    victim.hand = [sha]
    cs = make_cs([src, victim])

    async def responder(player, req):
        if player is victim:
            return {"bool": True, "card": sha, "owner": victim, "as_name": "杀"}
        return {"bool": False}

    cs.responder = responder
    nm = make_card("南蛮入侵")
    run(cs.use_nanman(src, nm))
    assert victim.hp == 4


# ── 万箭齐发 ──────────────────────────────────────────────

def test_wanjian_no_shan_takes_damage():
    src = make_player(0)
    p1 = make_player(1)
    p1.alive = True
    cs = make_cs([src, p1])
    cs.responder = AsyncMock(return_value={"bool": False})
    wj = make_card("万箭齐发")
    run(cs.use_wanjian(src, wj))
    assert p1.hp == 3


def test_wanjian_with_shan_no_damage():
    src = make_player(0)
    p1 = make_player(1)
    p1.alive = True
    shan = make_card("闪")
    p1.hand = [shan]
    cs = make_cs([src, p1])

    async def responder(player, req):
        if player is p1:
            return {"bool": True, "card": shan, "owner": p1, "as_name": "闪"}
        return {"bool": False}

    cs.responder = responder
    wj = make_card("万箭齐发")
    run(cs.use_wanjian(src, wj))
    assert p1.hp == 4


# ── 桃园结义 ──────────────────────────────────────────────

def test_taoyuan_heals_all():
    src = make_player(0)
    p1 = make_player(1)
    p2 = make_player(2)
    src.hp = 2
    p1.hp = 1
    for p in [src, p1, p2]:
        p.alive = True
    cs = make_cs([src, p1, p2])
    ty = make_card("桃园结义")
    run(cs.use_taoyuan(src, ty))
    assert src.hp == 3
    assert p1.hp == 2
    assert p2.hp == 4


def test_taoyuan_full_hp_no_overflow():
    src = make_player(0)
    src.alive = True
    cs = make_cs([src])
    ty = make_card("桃园结义")
    run(cs.use_taoyuan(src, ty))
    assert src.hp == 4


# ── 五谷丰登 ──────────────────────────────────────────────

def test_wugu_ai_each_gets_one_card():
    src = make_player(0)
    p1 = make_player(1)
    for p in [src, p1]:
        p.alive = True
    cs = make_cs([src, p1])
    cs.game_state.deck = [make_card("杀"), make_card("桃"), make_card("闪")]
    wg = make_card("五谷丰登")
    run(cs.use_wugu(src, wg))
    assert len(src.hand) == 1
    assert len(p1.hand) == 1


def test_wugu_empty_deck_no_crash():
    src = make_player(0)
    src.alive = True
    cs = make_cs([src])
    cs.game_state.deck = []
    wg = make_card("五谷丰登")
    result = run(cs.use_wugu(src, wg))
    assert result is True


# ── 闪电 ──────────────────────────────────────────────────

def test_shandian_goes_to_judge_area():
    p = make_player(0)
    cs = make_cs([p])
    sd = make_card("闪电")
    result = run(cs.use_shandian(p, sd))
    assert result is True
    assert sd in p.judge_area


def test_shandian_no_duplicate():
    p = make_player(0)
    existing = make_card("闪电")
    p.judge_area = [existing]
    cs = make_cs([p])
    sd2 = make_card("闪电")
    result = run(cs.use_shandian(p, sd2))
    assert result is False
    assert len(p.judge_area) == 1


# ── 闪电判定 ────────────────────────────────────────────────

def make_phase_controller(players, deck, engine=None):
    from game_engine.phase_controller import PhaseController
    gs = MagicMock()
    gs.players = players
    gs.current_player = players[0]
    gs.deck = list(deck)
    gs.discard_pile = []
    gs.draw_card = MagicMock(return_value=[])
    sm = MagicMock()
    sm.before_judge = AsyncMock(side_effect=lambda p, c, ctx: c)
    sm.after_judge = AsyncMock(return_value=False)
    controller = PhaseController(gs, sm, engine=engine)
    return controller, gs


def test_shandian_hit_deals_three_and_discards():
    p = make_player(0, hp=4)
    sd = make_card("闪电")
    engine = MagicMock()
    engine.card_system = make_cs([p])
    controller, gs = make_phase_controller([p], [make_card("杀", "spade", 7)], engine)
    p.judge_area = [sd]
    run(controller.execute_judge(p, sd))
    assert p.hp == 1
    assert sd not in p.judge_area
    assert sd in gs.discard_pile


def test_shandian_miss_passes_to_next_alive_player():
    p1 = make_player(0)
    p2 = make_player(1)
    sd = make_card("闪电")
    controller, gs = make_phase_controller([p1, p2], [make_card("杀", "heart", 7)])
    p1.judge_area = [sd]
    run(controller.execute_judge(p1, sd))
    assert sd not in p1.judge_area
    assert sd in p2.judge_area
    assert sd not in gs.discard_pile


# ── 火攻 ──────────────────────────────────────────────────

def test_huogong_same_suit_damages():
    src = make_player(0)
    tgt = make_player(1)
    shown = make_card("杀", suit="spade")
    tgt.hand = [shown]
    discard_card = make_card("闪", suit="spade")
    src.hand = [discard_card]
    cs = make_cs([src, tgt])
    hg = make_card("火攻")
    run(cs.use_huogong(src, hg, tgt))
    assert tgt.hp == 3


def test_huogong_no_same_suit_no_damage():
    src = make_player(0)
    tgt = make_player(1)
    shown = make_card("杀", suit="spade")
    tgt.hand = [shown]
    diff_suit = make_card("闪", suit="heart")
    src.hand = [diff_suit]
    cs = make_cs([src, tgt])
    hg = make_card("火攻")
    run(cs.use_huogong(src, hg, tgt))
    assert tgt.hp == 4


# ── 借刀杀人 ──────────────────────────────────────────────

def test_jiedao_requires_two_ordered_targets():
    src = make_player(0)
    owner = make_player(1)
    victim = make_player(2)
    card = make_card("借刀杀人")
    src.hand = [card]
    owner.equipment["weapon"] = make_card("青釭剑")
    gs = MagicMock()
    gs.players = [src, owner, victim]
    gs.current_player = src
    gs.current_phase.value = "play"
    gs.get_distance = MagicMock(return_value=1)
    from game_engine.rules_engine import RulesEngine
    assert RulesEngine(gs).can_play_card(src, card, [owner, victim])[0] is True
    assert RulesEngine(gs).can_play_card(src, card, [victim, owner])[0] is False


def test_jiedao_successful_sha_uses_weapon_owner():
    src = make_player(0)
    owner = make_player(1)
    victim = make_player(2)
    sha = make_card("杀")
    owner.hand = [sha]
    owner.equipment["weapon"] = make_card("青釭剑")
    cs = make_cs([src, owner, victim])

    async def responder(player, req):
        if player is owner:
            return {"bool": True, "card": sha, "owner": owner, "as_name": "杀"}
        return {"bool": False}

    cs.responder = responder
    result = run(cs.use_jiedao(src, make_card("借刀杀人"), [owner, victim]))
    assert result is True
    assert victim.hp == 3
    assert owner.equipment.get("weapon") is not None
    assert sha in cs.game_state.discard_pile


def test_jiedao_refusal_transfers_weapon():
    src = make_player(0)
    owner = make_player(1)
    victim = make_player(2)
    weapon = make_card("麒麟弓")
    owner.equipment["weapon"] = weapon
    cs = make_cs([src, owner, victim])
    cs.responder = AsyncMock(return_value={"bool": False})
    result = run(cs.use_jiedao(src, make_card("借刀杀人"), [owner, victim]))
    assert result is True
    assert "weapon" not in owner.equipment
    assert weapon in src.hand


def test_jiedao_without_weapon_fails():
    src = make_player(0)
    owner = make_player(1)
    victim = make_player(2)
    cs = make_cs([src, owner, victim])
    result = run(cs.use_jiedao(src, make_card("借刀杀人"), [owner, victim]))
    assert result is False



def test_no_unimplemented_cards():
    unimplemented = [name for name, spec in CARD_TABLE.items()
                     if spec.usage == "unimplemented" and name != "木牛流马"]
    assert unimplemented == [], f"仍有未实现的牌: {unimplemented}"


def test_all_equipment_have_slot():
    missing = [name for name, spec in CARD_TABLE.items()
               if spec.card_type == "equipment" and spec.equipment_slot is None]
    assert missing == [], f"装备缺少 equipment_slot: {missing}"

