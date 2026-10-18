"""Stage T · T1 行为账本：6.2 归属规则逐条单测、6.3 排除项反向测试、汇总格式、AI 注入、规则 AI 选目标、局后日志。"""

import asyncio
import json
import logging
from unittest.mock import AsyncMock

import pytest

from game_engine import MainEngine
from game_engine.behavior_ledger import (
    BehaviorLedger, SUMMARY_HEADER, WEIGHT_HIGH, WEIGHT_LOW, summary_limit,
)
from game_engine.card_table import CARD_TABLE
from game_engine.game_logs import build_game_log
from game_engine.skill_runtime_core import RuntimeSkill
from game_engine.skills_generated import get_all_skills
from game_engine.skills_wei import WeiSkillHandler
from game_engine.skills_wu import WuSkillHandler
from game_engine.state_manager import Card


def run(coro):
    return asyncio.run(coro)


def game(n_ai=4):
    engine = MainEngine({
        "mode": "5人身份局", "player_name": "P0",
        "ais": [{"name": f"P{i}"} for i in range(1, n_ai + 1)],
        "deck_id": "standard",
    })
    for player in engine.game_state.players:
        player.hand.clear()
        player.equipment.clear()
        player.judge_area.clear()
        player.is_ai = True      # 全员规则 AI：不会等待真人输入
    return engine


def card(tag, name, suit="spade", rank=7):
    spec = CARD_TABLE.get(name)
    return Card(tag, name, suit, rank, spec.card_type if spec else "basic")


def rows(engine, kinds=None):
    """账本流水 → (来源, 目标, 类型, 标签) 元组，便于断言。"""
    return [(e.source_id, e.target_id, e.kind, e.label) for e in engine.ledger.entries
            if kinds is None or e.kind in kinds]


def scripted_responder(allowed_names_by_player):
    """只让指定玩家打出指定牌名，其余一律不响应。allowed: {player_id: {牌名}}。"""
    async def responder(player, request):
        wanted = allowed_names_by_player.get(player.id, set())
        for option in request["options"]:
            if option.get("card") is not None and option.get("as_name") in wanted \
                    and option.get("owner") is player:
                return {"bool": True, "card": option["card"], "owner": option["owner"],
                        "as_name": option["as_name"], "source_zone": option.get("source_zone", "hand")}
        return {"bool": False}
    return responder


# ───────────────────────── T1-1 牌表 / 技能元数据 ─────────────────────────

def test_every_card_has_valid_ledger_kind():
    valid = {"none", "hostile", "friendly", "group", "borrow"}
    for name, spec in CARD_TABLE.items():
        assert spec.ledger_kind in valid, name


def test_card_table_ledger_kinds_match_rule_table_6_2():
    kinds = {name: spec.ledger_kind for name, spec in CARD_TABLE.items() if spec.ledger_kind != "none"}
    assert kinds == {
        "杀": "hostile", "决斗": "hostile", "火攻": "hostile", "过河拆桥": "hostile",
        "顺手牵羊": "hostile", "乐不思蜀": "hostile", "兵粮寸断": "hostile", "铁索连环": "hostile",
        "南蛮入侵": "group", "万箭齐发": "group", "桃园结义": "group", "五谷丰登": "group",
        "借刀杀人": "borrow",
    }
    assert CARD_TABLE["铁索连环"].ledger_weight == WEIGHT_LOW


def test_group_kind_cards_are_exactly_the_all_target_tricks():
    group = {n for n, s in CARD_TABLE.items() if s.ledger_kind == "group"}
    assert group == {n for n, s in CARD_TABLE.items()
                     if s.card_type == "trick" and s.target_rule.get("type") in ("all", "all_others")}


def test_ledger_never_applies_to_lightning_peach_or_wuxie_cards():
    for name in ("闪电", "桃", "闪", "酒", "无中生有", "无懈可击"):
        assert CARD_TABLE[name].ledger_kind == "none", name


def test_runtime_skill_default_is_none_and_only_table_skills_are_marked():
    assert RuntimeSkill("x", "x", "h", "t", "e").ledger_kind == "none"
    marked = {s.name: s.ledger_kind for s in get_all_skills() if s.ledger_kind != "none"}
    assert marked == {"仁德": "friendly", "遗计": "friendly", "流离": "transfer",
                      "刚烈": "counter", "反馈": "counter"}


# ───────────────────────── T1-2 归属规则（6.2 逐条）─────────────────────────

def test_sha_records_hostile_from_source_to_target():
    engine = game()
    p0, p1 = engine.game_state.players[:2]
    run(engine.card_system.use_card(p0, card("sha1", "杀"), [p1]))
    assert rows(engine) == [(0, 1, "hostile", "杀")]
    assert engine.ledger.entries[0].weight == 1.0


@pytest.mark.parametrize("name,resolver", [
    ("决斗", "use_juedou"), ("火攻", "use_huogong"), ("过河拆桥", "use_guohe"),
    ("顺手牵羊", "use_shunshou"), ("乐不思蜀", "use_lebu"), ("兵粮寸断", "use_bingliang"),
])
def test_single_target_tricks_record_hostile(name, resolver):
    engine = game()
    p0, p1 = engine.game_state.players[:2]
    setattr(engine.card_system, resolver, AsyncMock(return_value=True))
    run(engine.card_system.use_card(p0, card("t1", name), [p1]))
    assert rows(engine) == [(0, 1, "hostile", name)]


def test_tiesuo_records_low_weight_hostile_for_others_and_skips_self():
    engine = game()
    p0, p1, p2 = engine.game_state.players[:3]
    run(engine.card_system.use_card(p0, card("ts", "铁索连环"), [p0, p1, p2][:2]))
    assert rows(engine) == [(0, 1, "hostile", "铁索连环")]          # 对自己横置不算敌意
    assert engine.ledger.entries[0].weight == WEIGHT_LOW


@pytest.mark.parametrize("name", ["南蛮入侵", "万箭齐发", "桃园结义", "五谷丰登"])
def test_group_tricks_record_only_group_and_no_hostile_or_friendly(name):
    engine = game()
    p0 = engine.game_state.players[0]
    for p in engine.game_state.players[1:]:
        p.hand.clear()
    engine.card_system.responder = None
    run(engine.card_system.use_card(p0, card("g1", name), []))
    assert rows(engine) == [(0, None, "group", name)]
    # 群体牌没有任何「来源→目标」条目，汇总里不出现。
    assert engine.ledger.summarize(engine.game_state) == ""
    assert engine.ledger.stance_toward(0, 1) == 0


def test_lightning_and_chain_damage_are_not_attributed():
    engine = game()
    p0, p1, p2 = engine.game_state.players[:3]
    p1.chained = p2.chained = True
    # 闪电命中：无伤害来源；铁索传导：chain_transfer。两者都不归属任何人。
    run(engine.card_system.damage(None, p1, 1, context={"nature": "thunder", "reason": "闪电"}))
    assert engine.ledger.entries == []
    # 带来源的属性伤害经传导：传导目标不记任何敌意，而且伤害本身（非选择）也不入账。
    p3 = engine.game_state.players[3]
    p3.chained = p1.chained = True
    p1.hp = p3.hp = 4
    run(engine.card_system.damage(p0, p3, 1, context={"nature": "fire"}))
    assert engine.ledger.entries == []


def test_jiedao_attributes_to_instigator_and_not_to_the_forced_executor():
    engine = game()
    p0, p1, p2 = engine.game_state.players[:3]
    p1.equipment["weapon"] = card("w", "诸葛连弩", "club")
    p1.hand.append(card("sha_exec", "杀"))
    engine.card_system.responder = scripted_responder({1: {"杀"}})
    run(engine.card_system.use_card(p0, card("jd", "借刀杀人"), [p1, p2]))
    assert rows(engine) == [(0, 2, "hostile", "借刀"), (0, 1, "hostile", "借刀夺武器")]
    weights = {e.label: e.weight for e in engine.ledger.entries}
    assert weights == {"借刀": 1.0, "借刀夺武器": WEIGHT_LOW}
    # 被迫出杀的执行者(1号)对最终目标(2号)没有任何敌意记录。
    assert not any(e.source_id == 1 and e.target_id == 2 for e in engine.ledger.entries)


def test_jiedao_executor_declines_then_weapon_is_taken_still_no_executor_entry():
    engine = game()
    p0, p1, p2 = engine.game_state.players[:3]
    p1.equipment["weapon"] = card("w", "诸葛连弩", "club")
    engine.card_system.responder = None
    run(engine.card_system.use_card(p0, card("jd2", "借刀杀人"), [p1, p2]))
    assert [r[:2] for r in rows(engine)] == [(0, 2), (0, 1)]
    assert p0.hand and p0.hand[0].name == "诸葛连弩"


def test_failed_play_leaves_no_ledger_entry():
    """借刀杀人对没有武器的角色结算失败 → 牌会退回手牌，账本不能留下这次行为。"""
    engine = game()
    p0, p1, p2 = engine.game_state.players[:3]
    assert run(engine.card_system.use_card(p0, card("jd3", "借刀杀人"), [p1, p2])) is False
    assert engine.ledger.entries == []


def _wire_liuli(engine, daqiao, alternative):
    handler = next(h for h in engine.skill_manager.handlers if isinstance(h, WuSkillHandler))
    handler.has = lambda p, name: name == "流离" and p is daqiao
    engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
    cost = card("liuli_cost", "闪", "club")
    daqiao.hand.append(cost)
    engine.skill_manager.ask_choose_cards_result = AsyncMock(
        return_value={"status": "resolved", "cards": [cost]})
    engine.skill_manager.ask_choose_players = AsyncMock(return_value=[alternative])
    engine.card_system.notify_card_to_discard = AsyncMock()


def test_liuli_records_source_to_daqiao_hostile_and_daqiao_to_new_target_transfer():
    engine = game()
    source, daqiao, alternative = engine.game_state.players[:3]
    _wire_liuli(engine, daqiao, alternative)
    engine.card_system.responder = None
    run(engine.card_system.use_sha(source, card("sha_l", "杀"), daqiao))
    assert rows(engine) == [(source.id, daqiao.id, "hostile", "杀"),
                            (daqiao.id, alternative.id, "transfer", "流离")]
    # 原杀来源并没有选择新目标：不记 来源→新目标。
    assert not any(e.source_id == source.id and e.target_id == alternative.id
                   for e in engine.ledger.entries)


def test_liuli_transfer_is_not_counted_as_hostility_or_lord_stance():
    ledger = BehaviorLedger()
    ledger.record(1, 1, 0, "transfer", "流离")
    ledger.record(1, 1, 0, "counter", "刚烈")
    assert ledger.stance_toward(1, 0) == 0


def test_rescue_records_high_weight_friendly_from_rescuer_to_dying():
    engine = game()
    p0, p1 = engine.game_state.players[:2]
    p0.hp = 0
    p1.hand.append(card("peach", "桃", "heart"))
    engine.card_system.responder = scripted_responder({1: {"桃"}})
    run(engine.card_system.enter_dying(p0))
    assert rows(engine) == [(1, 0, "friendly", "救援")]
    assert engine.ledger.entries[0].weight == WEIGHT_HIGH
    assert p0.hp == 1


def test_self_rescue_is_not_recorded():
    engine = game()
    p0 = engine.game_state.players[0]
    p0.hp = 0
    p0.hand.append(card("peach", "桃", "heart"))
    engine.card_system.responder = scripted_responder({0: {"桃"}})
    run(engine.card_system.enter_dying(p0))
    assert p0.hp == 1 and engine.ledger.entries == []


def test_not_rescuing_is_never_recorded_even_when_holding_a_peach():
    """6.3：「该救没救」= 泄露别人有没有桃 → 不入账。"""
    engine = game()
    p0, p1, p2 = engine.game_state.players[:3]
    p0.hp = 0
    p1.hand.append(card("peach1", "桃", "heart"))
    p2.hand.append(card("peach2", "桃", "diamond"))
    engine.card_system.responder = scripted_responder({})        # 谁都不救
    run(engine.card_system.enter_dying(p0))
    assert not p0.alive
    assert engine.ledger.entries == []


def test_not_dodging_is_never_recorded_even_when_holding_a_dodge():
    """6.3：「该闪没闪」同理。"""
    engine = game()
    p0, p1 = engine.game_state.players[:2]
    p1.hand.append(card("shan", "闪", "heart"))
    engine.card_system.responder = scripted_responder({})        # 持闪不出
    run(engine.card_system.use_card(p0, card("sha_nd", "杀"), [p1]))
    assert rows(engine) == [(0, 1, "hostile", "杀")]            # 只有出杀本身


def test_wuxie_single_layer_protects_original_target():
    engine = game()
    p0, p1, p2 = engine.game_state.players[:3]
    p1.hand.append(card("wx1", "无懈可击", "club"))
    engine.card_system.responder = scripted_responder({1: {"无懈可击"}})
    result = run(engine.card_system.ask_wuxie(card("gh", "过河拆桥"), p0, [p2]))
    assert result is True
    assert rows(engine) == [(1, 2, "protect", "无懈保护")]


def test_wuxie_chain_records_the_beneficiary_of_each_layer():
    engine = game()
    p0, p1, p2, p3, p4 = engine.game_state.players
    p1.hand.append(card("wx1", "无懈可击", "club"))
    p3.hand.append(card("wx3", "无懈可击", "spade"))
    p4.hand.append(card("wx4", "无懈可击", "heart"))
    engine.card_system.responder = scripted_responder(
        {1: {"无懈可击"}, 3: {"无懈可击"}, 4: {"无懈可击"}})
    result = run(engine.card_system.ask_wuxie(card("gh2", "过河拆桥"), p0, [p2]))
    assert result is True                         # 三层：抵消 → 反抵消 → 再抵消
    assert rows(engine) == [
        (1, 2, "protect", "无懈保护"),            # 第 1 层：保护原目标 2 号
        (3, 0, "protect", "无懈保护"),            # 第 2 层：抵消无懈，等于帮锦囊使用者 0 号
        (4, 2, "protect", "无懈保护"),            # 第 3 层：再次保护原目标
    ]


def test_wuxie_on_trick_without_targets_records_nothing():
    engine = game()
    p0, p1 = engine.game_state.players[:2]
    p1.hand.append(card("wx1", "无懈可击", "club"))
    engine.card_system.responder = scripted_responder({1: {"无懈可击"}})
    assert run(engine.card_system.ask_wuxie(card("wz", "无中生有"), p0, [])) is True
    assert engine.ledger.entries == []


def test_wuxie_for_own_benefit_is_not_recorded():
    engine = game()
    p0, p1 = engine.game_state.players[:2]
    p1.hand.append(card("wx1", "无懈可击", "club"))
    engine.card_system.responder = scripted_responder({1: {"无懈可击"}})
    run(engine.card_system.ask_wuxie(card("gh3", "过河拆桥"), p0, [p1]))
    assert engine.ledger.entries == []


def _wei_handler(engine):
    return next(h for h in engine.skill_manager.handlers if isinstance(h, WeiSkillHandler))


def test_rende_give_cards_record_friendly_without_card_names():
    engine = game()
    p0, p1 = engine.game_state.players[:2]
    handler = next(h for h in engine.skill_manager.handlers if h.faction == "shu")
    handler.has = lambda p, name: name == "仁德" and p is p0
    secret = card("secret", "桃", "heart")
    p0.hand.append(secret)
    assert run(handler.execute(p0, {"skill_name": "仁德", "variant": "give", "card_indices": [0]}, [p1]))
    assert rows(engine) == [(0, 1, "friendly", "仁德")]
    assert "桃" not in json.dumps(engine.ledger.snapshot(), ensure_ascii=False)


def test_yiji_records_friendly_for_each_card_given_to_others_not_to_self():
    engine = game()
    guojia, p1 = engine.game_state.players[:2]
    source = engine.game_state.players[2]
    handler = _wei_handler(engine)
    handler.has = lambda p, name: name == "遗计" and p is guojia
    engine.game_state.deck.extend([card("d1", "杀"), card("d2", "闪", "heart")])
    engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
    engine.skill_manager.ask_choose_players = AsyncMock(side_effect=[[p1], [guojia]])
    engine.skill_manager.draw_cards = AsyncMock(
        side_effect=lambda p, n, r: p.hand.extend([card("y1", "杀"), card("y2", "闪")]) or list(p.hand))
    run(handler.after_damage(source, guojia, 1))
    assert rows(engine) == [(guojia.id, p1.id, "friendly", "遗计")]


def test_ganglie_and_fankui_record_low_weight_counter_toward_damage_source():
    engine = game()
    target, source = engine.game_state.players[:2]
    handler = _wei_handler(engine)
    handler.has = lambda p, name: p is target and name in ("刚烈", "反馈")
    source.hand.append(card("fk", "杀"))
    engine.skill_manager.ask_confirm = AsyncMock(return_value=True)
    engine.skill_manager.judge = AsyncMock(return_value=card("j", "杀", "heart"))
    engine.skill_manager.ask_choose_cards_result = AsyncMock(
        return_value={"status": "resolved", "cards": [source.hand[0]]})
    run(handler.after_damage(source, target, 1))
    assert {r[3] for r in rows(engine)} == {"反馈", "刚烈"}
    assert {r[2] for r in rows(engine)} == {"counter"}
    assert all(e.weight == WEIGHT_LOW and (e.source_id, e.target_id) == (target.id, source.id)
               for e in engine.ledger.entries)


def test_declined_counter_skill_is_not_recorded():
    engine = game()
    target, source = engine.game_state.players[:2]
    handler = _wei_handler(engine)
    handler.has = lambda p, name: p is target and name in ("刚烈", "反馈")
    source.hand.append(card("fk", "杀"))
    engine.skill_manager.ask_confirm = AsyncMock(return_value=False)
    run(handler.after_damage(source, target, 1))
    assert engine.ledger.entries == []


# ───────────────────────── 6.3 手牌区被拿走的牌名不入账 ─────────────────────────

def test_shunshou_from_hand_records_only_that_a_card_was_targeted_not_its_name():
    engine = game()
    p0, p1 = engine.game_state.players[:2]
    secret = card("secret_hand", "桃", "heart")
    p1.hand.append(secret)
    run(engine.card_system.use_card(p0, card("ss", "顺手牵羊"), [p1]))
    assert secret in p0.hand                                       # 确实从手牌区拿走了
    assert rows(engine) == [(0, 1, "hostile", "顺手牵羊")]
    dump = json.dumps(engine.ledger.snapshot(), ensure_ascii=False)
    assert "桃" not in dump
    assert "桃" not in engine.ledger.summarize(engine.game_state)


def test_guohe_from_hand_does_not_leak_the_discarded_hand_card_name():
    engine = game()
    p0, p1 = engine.game_state.players[:2]
    secret = card("secret_hand2", "闪", "heart")
    p1.hand.append(secret)
    run(engine.card_system.use_card(p0, card("gh4", "过河拆桥"), [p1]))
    assert secret in engine.game_state.discard_pile
    dump = json.dumps(engine.ledger.snapshot(), ensure_ascii=False) + engine.ledger.summarize(engine.game_state)
    assert "闪" not in dump


# ───────────────────────── 账本基础行为 ─────────────────────────

def test_ledger_ignores_self_unknown_kind_and_missing_source():
    ledger = BehaviorLedger()
    assert ledger.record(1, 0, 0, "hostile", "杀") is None
    assert ledger.record(1, 0, 1, "weird", "杀") is None
    assert ledger.record(1, None, 1, "hostile", "杀") is None
    assert ledger.record(1, 0, None, "hostile", "杀") is None
    assert ledger.entries == []
    assert ledger.record_group(1, 0, "南蛮入侵").target_id is None


def test_stance_counts_hostile_minus_friendly_and_protect_only():
    ledger = BehaviorLedger()
    ledger.record(1, 2, 0, "hostile", "杀")
    ledger.record(2, 2, 0, "hostile", "决斗")
    ledger.record(3, 2, 0, "protect", "无懈保护")
    ledger.record(3, 3, 0, "friendly", "救援", 3.0)
    assert ledger.stance_toward(2, 0) == 1.0
    assert ledger.stance_toward(3, 0) == -3.0
    assert ledger.stance_toward(0, 2) == 0.0


def test_remove_only_drops_given_entries():
    ledger = BehaviorLedger()
    a = ledger.record(1, 0, 1, "hostile", "杀")
    b = ledger.record(1, 1, 2, "hostile", "杀")
    ledger.remove([a, None])
    assert ledger.entries == [b]


# ───────────────────────── T1-3 汇总文本 ─────────────────────────

def _players(engine):
    lord = engine.game_state.players[0]
    lord.identity, lord.identity_revealed = "lord", True
    for p in engine.game_state.players[1:]:
        p.identity, p.identity_revealed = "rebel", False
    return engine.game_state.players


def test_summary_format_matches_scheme_6_4():
    engine = game()
    _players(engine)
    engine.game_state.round_number = 4
    ledger = engine.ledger
    ledger.record(1, 2, 0, "hostile", "杀")
    ledger.record(2, 2, 0, "hostile", "杀")
    ledger.record(3, 2, 0, "hostile", "过河拆桥")
    ledger.record(3, 1, 0, "friendly", "救援", 3.0)
    ledger.record(4, 3, 2, "hostile", "杀")
    ledger.record(4, 4, 1, "protect", "无懈保护")
    text = ledger.summarize(engine.game_state)
    lines = text.split("\n")
    assert lines[0] == f"{SUMMARY_HEADER}（截至第4轮）"
    assert "3号→1号(主公)：杀×2 过河拆桥×1" in text
    assert "2号→1号(主公)：救援×1" in text
    assert "4号→3号：杀×1" in text and "5号→2号：无懈保护×1" in text
    assert lines[-1] == "关键事件：第3轮 2号救援1号(主公)"


def test_summary_only_tags_a_revealed_lord_never_hidden_identities():
    engine = game()
    players = _players(engine)
    players[2].identity = "spy"                       # 未揭示的内奸
    engine.ledger.record(1, 1, 2, "hostile", "杀")
    text = engine.ledger.summarize(engine.game_state)
    assert "(主公)" not in text and "内奸" not in text and "反贼" not in text
    engine.ledger.record(1, 1, 0, "hostile", "杀")
    assert "2号→1号(主公)" in engine.ledger.summarize(engine.game_state)


def test_summary_empty_when_no_attributable_entries():
    engine = game()
    assert engine.ledger.summarize(engine.game_state) == ""
    engine.ledger.record_group(1, 0, "南蛮入侵")
    assert engine.ledger.summarize(engine.game_state) == ""


def test_summary_limit_scales_with_table_size():
    assert summary_limit(5) == 300 and summary_limit(8) == 600
    assert summary_limit(3) == 300


@pytest.mark.parametrize("players,expected", [(5, 300), (8, 600)])
def test_summary_never_exceeds_limit_even_with_a_huge_ledger(players, expected):
    class Gs:
        round_number = 30
    gs = Gs()
    gs.players = [type("P", (), {"id": i, "identity": "lord" if i == 0 else "rebel",
                                 "identity_revealed": i == 0})() for i in range(players)]
    ledger = BehaviorLedger()
    labels = ["杀", "决斗", "过河拆桥", "顺手牵羊", "乐不思蜀", "兵粮寸断", "火攻"]
    for rnd in range(1, 30):
        for s in range(players):
            for t in range(players):
                if s != t:
                    ledger.record(rnd, s, t, "hostile", labels[(rnd + s + t) % len(labels)])
        ledger.record(rnd, rnd % players, (rnd + 1) % players, "friendly", "救援", 3.0)
    text = ledger.summarize(gs)
    assert 0 < len(text) <= expected
    assert text.startswith(SUMMARY_HEADER)


def test_summary_merges_low_weight_entries_before_dropping_anything():
    class Gs:
        round_number = 9
        players = [type("P", (), {"id": i, "identity": "rebel", "identity_revealed": False})()
                   for i in range(5)]
    ledger = BehaviorLedger()
    for rnd in range(40):
        ledger.record(rnd, 1, 2, "counter", "刚烈")
        ledger.record(rnd, 1, 2, "transfer", "流离")
        ledger.record(rnd, 1, 2, "hostile", "杀")
    small = BehaviorLedger()
    small.entries = list(ledger.entries)
    text = small.summarize(Gs(), max_chars=45)
    assert "杀×40" in text and "其他×40" in text and "刚烈" not in text


# ───────────────────────── T1-4 注入决策 L2 ─────────────────────────

def _ai_engine():
    engine = game()
    engine.game_state.round_number = 2
    return engine


def test_decision_turn_message_has_ledger_block_before_untrusted_chat():
    engine = _ai_engine()
    _players(engine)
    p1 = engine.game_state.players[1]
    engine.ledger.record(1, 2, 0, "hostile", "杀")
    engine.table_chat.append({"seq": 1, "from_id": 2, "name": "P2", "kind": "ai", "text": "我是忠臣"})
    msg = engine.ai_decision.build_decision_turn_message(p1, [{"type": "end_phase"}])
    assert SUMMARY_HEADER in msg and "【发言·未验证】" in msg
    assert msg.index(SUMMARY_HEADER) < msg.index("【发言·未验证】") < msg.index("合法操作列表")
    assert "3号→1号(主公)：杀×1" in msg


def test_decision_turn_message_omits_block_when_ledger_empty():
    engine = _ai_engine()
    msg = engine.ai_decision.build_decision_turn_message(
        engine.game_state.players[1], [{"type": "end_phase"}])
    assert SUMMARY_HEADER not in msg


def test_only_play_decisions_carry_the_ledger_response_and_choice_calls_do_not():
    engine = _ai_engine()
    _players(engine)
    engine.ledger.record(1, 2, 0, "hostile", "杀")
    p1 = engine.game_state.players[1]
    p1.ai_config = {"provider": "deepseek", "model": "m", "api_key": "k"}
    sent = []

    async def fake_call(player, kind, message, *a, **k):
        sent.append((kind, message))
        return '{"action_index": 0, "option_indices": [0], "response_index": 0}'

    engine.ai_decision._call_with_session = fake_call
    run(engine.ai_decision.make_decision(p1, [{"type": "end_phase"}]))
    run(engine.ai_decision.make_choice_decision(p1, {
        "kind": "choose_option", "prompt": "选一个", "options": [{"label": "甲"}, {"label": "乙"}],
        "min_n": 1, "max_n": 1}))
    response_prompt = engine.ai_decision.build_response_prompt(
        p1, {"kind": "respond", "prompt": "请出闪", "options": [{"card": card("s", "闪")}]})
    by_kind = {kind: message for kind, message in sent}
    assert SUMMARY_HEADER in by_kind["decision"]
    assert "choice" in by_kind and SUMMARY_HEADER not in by_kind["choice"]
    assert SUMMARY_HEADER not in response_prompt


def test_ledger_block_contains_no_hand_cards_or_hidden_identity():
    engine = _ai_engine()
    players = _players(engine)
    players[3].identity = "spy"
    players[1].hand.append(card("mine", "桃", "heart"))
    players[2].hand.append(card("theirs", "无懈可击", "club"))
    engine.ledger.record(1, 2, 3, "hostile", "顺手牵羊")
    block = engine.ai_decision._build_ledger_block()
    assert "无懈可击" not in block and "桃" not in block and "spy" not in block and "内奸" not in block


# ───────────────────────── T1-5 规则 AI 按账本选目标 ─────────────────────────

def _setup_identities(engine, mine_id, mine_identity):
    players = _players(engine)
    players[mine_id].identity = mine_identity
    return players


def test_loyalist_prefers_target_with_highest_hostility_toward_lord():
    engine = game()
    players = _setup_identities(engine, 1, "loyalist")
    for p in players:
        p.hp, p.hand = 4, []
    players[2].hp = 1                                    # 空账本时会选血最少的 2 号
    assert engine.ai_decision._choose_target(players[1], [2, 3, 4]) == [2]
    engine.ledger.record(1, 4, 0, "hostile", "杀")
    engine.ledger.record(2, 4, 0, "hostile", "决斗")
    engine.ledger.record(2, 3, 0, "hostile", "杀")
    assert engine.ai_decision._choose_target(players[1], [2, 3, 4]) == [4]


def test_loyalist_avoids_a_seat_that_protected_the_lord():
    engine = game()
    players = _setup_identities(engine, 1, "loyalist")
    for p in players:
        p.hp, p.hand = 4, []
    players[2].hp = 1
    engine.ledger.record(1, 2, 0, "friendly", "救援", 3.0)
    assert engine.ai_decision._choose_target(players[1], [2, 3, 4]) in ([3], [4])


def test_rebel_targets_lord_first_then_whoever_is_friendliest_to_lord():
    engine = game()
    players = _setup_identities(engine, 1, "rebel")
    for p in players:
        p.hp, p.hand = 4, []
    assert engine.ai_decision._choose_target(players[1], [0, 2, 3]) == [0]
    players[3].hp = 1                                    # 空账本时会选血最少的 3 号
    engine.ledger.record(1, 2, 0, "friendly", "救援", 3.0)
    assert engine.ai_decision._choose_target(players[1], [2, 3, 4]) == [2]


def test_spy_attacks_the_stronger_side():
    engine = game()
    players = _setup_identities(engine, 1, "spy")
    for p in players:
        p.hp, p.hand = 4, []
    players[2].hp = 1                                    # 空账本：打血最少的 2 号
    players[3].hp = 3
    assert engine.ai_decision._choose_target(players[1], [2, 3, 4]) == [2]
    # 3、4 号是公开的主公派（救援过主公），反贼侧只有 2 号 → 主公侧更强 → 优先打主公侧的人。
    engine.ledger.record(1, 3, 0, "friendly", "救援", 3.0)
    engine.ledger.record(1, 4, 0, "protect", "无懈保护")
    assert engine.ai_decision._choose_target(players[1], [2, 3, 4]) in ([3], [4])


def test_rule_ai_target_choice_uses_only_public_information():
    """规则 AI 的账本排序只读 stance(公开账本) 与 identity_revealed 的主公，不读他人隐藏身份。"""
    engine = game()
    players = _setup_identities(engine, 1, "loyalist")
    for p in players:
        p.hp, p.hand = 4, []
    engine.ledger.record(1, 3, 0, "hostile", "杀")
    first = engine.ai_decision._choose_target(players[1], [2, 3, 4])
    # 把所有他人的隐藏身份全部互换，选择结果不能变。
    for p in players[2:]:
        p.identity = {"rebel": "spy", "spy": "loyalist", "loyalist": "rebel"}.get(p.identity, p.identity)
    assert engine.ai_decision._choose_target(players[1], [2, 3, 4]) == first == [3]


def test_rule_ai_without_ledger_attribute_still_chooses_a_target():
    engine = game()
    players = _setup_identities(engine, 1, "loyalist")
    del engine.ledger
    assert engine.ai_decision._choose_target(players[1], [2, 3]) in ([2], [3])


# ───────────────────────── 局后日志 ─────────────────────────

def test_game_log_contains_ledger_field_with_public_facts_only():
    engine = game()
    p0, p1 = engine.game_state.players[:2]
    p1.hand.append(card("secret", "桃", "heart"))
    run(engine.card_system.use_card(p0, card("ss2", "顺手牵羊"), [p1]))
    log = build_game_log(engine, {"state": {"players": []}}, include_thinking=False)
    assert log["ledger"] == engine.ledger.snapshot()
    assert log["ledger"][0]["label"] == "顺手牵羊"
    assert set(log["ledger"][0]) == {"seq", "round", "source_id", "target_id", "kind", "label", "weight"}
    assert "桃" not in json.dumps(log["ledger"], ensure_ascii=False)


def test_game_log_ledger_is_empty_list_for_engines_without_a_ledger():
    class Bare:
        game_id, game_config, game_log, decision_log = "g", {}, [], []
    log = build_game_log(Bare(), {}, include_thinking=False)
    assert log["ledger"] == []


# ───────────────────────── 整局：账本与时间线一致 ─────────────────────────

def test_full_rules_game_ledger_is_consistent_with_timeline():
    logging.disable(logging.CRITICAL)
    try:
        import random
        random.seed(20261018)
        engine = MainEngine(MainEngine.normalize_config({
            "mode": "5人身份局", "selected_hero": {"id": "liubei"},
            "ais": [{"name": f"AI{i}", "api_key": "", "hero": {"id": h}}
                    for i, h in enumerate(["caocao", "sunquan", "huatuo", "zhouyu"], start=1)],
            "deck_id": "standard", "max_turns": 60, "phase_delay": 0, "turn_delay": 0,
        }))
        engine.set_trustee(True, source="rules")
        winner = run(engine.run())
    finally:
        logging.disable(logging.NOTSET)
    assert winner in {"lord", "rebel", "spy"}
    entries = engine.ledger.entries
    assert entries, "一整局全规则 AI 对局应当产生行为账本"
    seqs = [e.seq for e in entries]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    rounds = [e.round for e in entries]
    assert rounds == sorted(rounds)                       # 时间顺序
    names = {p.id: p.name for p in engine.game_state.players}
    messages = [str(m.get("message")) for m in engine.game_log]
    for e in entries:
        if e.kind == "group":
            continue
        assert e.source_id in names and e.target_id in names and e.source_id != e.target_id
        assert e.weight > 0
    # 每条「杀」敌意都能在时间线里找到「X使用【杀】，目标：…Y…」。
    sha_uses = [m for m in messages if "使用【杀】" in m]
    for e in (e for e in entries if e.kind == "hostile" and e.label == "杀"):
        assert any(m.startswith(names[e.source_id]) and names[e.target_id] in m for m in sha_uses)
    # 汇总能生成且不超限；日志字段存在。
    summary = engine.ledger.summarize(engine.game_state)
    assert len(summary) <= summary_limit(5)


# ───────────────────────── 顺带暴露的既有缺陷：火攻目标在无懈链里打光手牌 ─────────────────────────

def test_huogong_fizzles_but_stays_used_when_target_spent_last_card_on_wuxie():
    """账本改变规则 AI 选目标后，30 局里出现：目标把最后一张手牌打成无懈 → 火攻 use 返回 False，
    牌被退回手牌并被判成非法出牌。火攻已使用，只是落空，应返回 True。"""
    engine = game()
    p0, p1 = engine.game_state.players[:2]
    p0.hand.append(card("hg_cost", "杀", "heart"))
    assert run(engine.card_system.use_huogong(p0, card("hg", "火攻", "heart"), p1)) is True
    assert engine.ledger.entries == []                       # use_huogong 本身不记账，记账在 use_card
