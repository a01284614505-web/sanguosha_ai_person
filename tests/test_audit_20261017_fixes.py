"""2026-10-17 核查修复：麒麟弓选马、牌堆空时洗牌、铁索传导顺序。"""

import asyncio
from unittest.mock import AsyncMock

from game_engine import MainEngine
from game_engine.state_manager import Card, Phase


def run(coro):
    return asyncio.run(coro)


def game():
    engine = MainEngine({"mode": "5人身份局", "player_name": "P0",
                         "ais": [{"name": f"P{i}"} for i in range(1, 5)],
                         "deck_id": "standard"})
    for p in engine.game_state.players:
        p.hand.clear()
        p.equipment.clear()
        p.judge_area.clear()
    engine.game_state.current_player = engine.game_state.players[0]
    engine.game_state.current_player_index = 0
    engine.game_state.current_phase = Phase.PLAY
    return engine


def card(tag, name, suit="spade", card_type="equipment", nature=None, rank=5):
    return Card(tag, name, suit, rank, card_type, nature=nature)


# ---------- 麒麟弓 ----------

def test_qilin_lets_holder_choose_which_mount_when_target_has_both():
    engine = game()
    source, target = engine.game_state.players[1:3]
    source.equipment["weapon"] = card("au_qilin", "麒麟弓")
    plus = card("au_plus", "绝影")
    minus = card("au_minus", "赤兔")
    target.equipment["plus_horse"] = plus
    target.equipment["minus_horse"] = minus
    asked = {}

    async def choose(player, prompt, candidates, **kwargs):
        asked["player"] = player
        asked["candidates"] = list(candidates)
        return [minus]

    engine.ask_choose_cards = choose
    run(engine.card_system.damage(source, target, 1,
                                  card=card("au_sha", "杀", "heart", "basic")))
    assert asked["player"] is source
    assert [c.id for c in asked["candidates"]] == [plus.id, minus.id]
    assert target.equipment.get("plus_horse") is plus
    assert "minus_horse" not in target.equipment
    assert minus in engine.game_state.discard_pile


def test_qilin_single_mount_does_not_ask_for_a_card_choice():
    engine = game()
    source, target = engine.game_state.players[1:3]
    source.equipment["weapon"] = card("au_qilin1", "麒麟弓")
    horse = card("au_only", "大宛")
    target.equipment["minus_horse"] = horse
    engine.ask_choose_cards = AsyncMock(side_effect=AssertionError("不应询问选牌"))
    run(engine.card_system.damage(source, target, 1,
                                  card=card("au_sha1", "杀", "heart", "basic")))
    assert horse in engine.game_state.discard_pile


# ---------- 牌堆空时洗牌 ----------

def _empty_deck_with_discards(engine, count):
    state = engine.game_state
    pool = state.deck + state.discard_pile
    state.deck = []
    state.discard_pile = pool[:count]
    return list(state.discard_pile)


def test_kill_rebel_reward_reshuffles_discard_pile_when_deck_runs_out():
    engine = game()
    state = engine.game_state
    killer, victim = state.players[0], state.players[1]
    killer.identity, victim.identity = "loyalist", "rebel"
    for p in state.players:
        if p not in (killer, victim):
            p.identity = {"lord": "lord"}.get(p.identity, p.identity)
    state.players[2].identity = "lord"
    state.players[3].identity = "rebel"
    state.players[4].identity = "spy"
    reshuffle_pool = _empty_deck_with_discards(engine, 5)
    run(engine.card_system._settle_identity_death(victim, killer))
    assert len(killer.hand) == 3
    assert all(c in reshuffle_pool for c in killer.hand)


def test_draw_helper_reports_nothing_only_when_both_piles_are_empty():
    engine = game()
    state = engine.game_state
    state.deck = []
    state.discard_pile = []
    killer, victim = state.players[0], state.players[1]
    victim.identity = "rebel"
    run(engine.card_system._settle_identity_death(victim, killer))
    assert killer.hand == []


def test_luoshen_reshuffles_and_keeps_judging_when_deck_runs_out():
    engine = game()
    state = engine.game_state
    zhenji = state.players[0]
    black = [card(f"au_black_{i}", "杀", "spade", "basic", rank=3) for i in range(2)]
    red = card("au_red", "闪", "heart", "basic", rank=4)
    state.deck = [black[0]]
    state.discard_pile = [black[1], red]
    import random as _random
    _random.seed(1)
    # 固定洗牌结果：先黑后红，验证洗牌后继续判定直到红色。
    state.shuffle_deck = lambda: state.deck.sort(key=lambda c: 0 if c is black[1] else 1)
    handler = next(h for h in engine.skill_manager.handlers if hasattr(h, "_luoshen"))
    run(handler._luoshen(zhenji))
    assert black[0] in zhenji.hand and black[1] in zhenji.hand
    assert red not in zhenji.hand


# ---------- 铁索传导顺序 ----------

def test_chain_damage_propagates_from_current_player_in_seat_order():
    engine = game()
    state = engine.game_state
    players = state.players
    state.current_player = players[3]
    state.current_player_index = 3
    target = players[1]
    for p in (players[0], players[1], players[2], players[4]):
        p.chained = True
        p.hp = 4
    order = []
    original = engine.card_system.damage

    async def spy_damage(source, victim, amount, card=None, context=None):
        order.append(victim.id)
        return await original(source, victim, amount, card=card, context=context)

    engine.card_system.damage = spy_damage
    run(original(players[3], target, 1,
                 card=card("au_fire", "杀", "heart", "basic", nature="fire"),
                 context={"nature": "fire"}))
    # 当前回合角色为 3 号；从 3 号起按座次：4 → 0 → 2（1 号是原目标）。
    assert order == [4, 0, 2]


def test_skill_judgment_reshuffles_discard_pile_when_deck_is_empty():
    """旧代码用 draw_card(player, 0) 代表“洗牌”，但 0 张循环零次，从不洗牌。"""
    engine = game()
    state = engine.game_state
    only = card("au_judge", "桃", "heart", "basic", rank=7)
    state.deck = []
    state.discard_pile = [only]
    engine.announce_judge = None
    result = run(engine.skill_manager.judge(state.players[0], "测试判定"))
    assert result is only


# ---------- 中断局与连胜 ----------

def _result(winner, round_number, identity="rebel"):
    return {"winner": winner, "state": {"round": round_number, "players": [
        {"is_ai": False, "identity": identity, "hero_name": "界刘备", "stats": {}}]}}


def test_interrupt_within_two_rounds_keeps_streak_but_later_interrupt_resets(tmp_path):
    from game_engine.game_history import GameHistoryStore
    store = GameHistoryStore(tmp_path / "history.json")
    store.record_result("p1", "g1", _result("rebel", 4))
    store.record_result("p1", "g2", _result("rebel", 5))
    assert store.profile("p1")["win_streak"] == 2
    store.record_result("p1", "g3", _result("aborted", 2))
    assert store.profile("p1")["win_streak"] == 2
    store.record_result("p1", "g4", _result("aborted", 3))
    assert store.profile("p1")["win_streak"] == 0
    history = store.profile("p1")["history"]
    assert history[0]["status"] == "interrupted" and history[0]["rounds"] == 3


# ---------- 客户端配置白名单 ----------

def test_client_cannot_override_iron_rule_timing_or_play_as_ai():
    from game_engine.config_validator import sanitize_client_config, SERVER_ONLY_KEYS
    raw = {"mode": "5人身份局", "ais": [{"name": f"AI{i}"} for i in range(4)],
           "player": {"name": "我", "is_ai": True, "ai_config": {"api_key": "x"}}}
    raw.update({key: 1 for key in SERVER_ONLY_KEYS})
    cleaned = sanitize_client_config(raw)
    assert not any(key in cleaned for key in SERVER_ONLY_KEYS)
    assert cleaned["player"]["is_ai"] is False and "ai_config" not in cleaned["player"]
    cfg = MainEngine.normalize_config(cleaned)
    engine = MainEngine(cfg)
    assert engine.idle_abort_seconds == 300
    assert engine.max_turns == 300
    assert engine.game_state.players[0].is_ai is False


# ---------- 规则 AI：救主公、替主公挡锦囊 ----------

def _rule_ai_setup():
    engine = game()
    players = engine.game_state.players
    lord, loyalist, rebel, spy = players[1], players[2], players[3], players[4]
    lord.identity, lord.identity_revealed = "lord", True
    loyalist.identity, rebel.identity, spy.identity = "loyalist", "rebel", "spy"
    return engine, lord, loyalist, rebel, spy


def _public(player):
    from game_engine import MainEngine as _M
    return _M._public_decision_value(player)


def test_rule_ai_loyalist_and_spy_save_the_dying_lord_but_rebel_does_not():
    engine, lord, loyalist, rebel, spy = _rule_ai_setup()
    ai = engine.ai_decision
    request = {"kind": "dying", "options": [{"card": {"name": "桃"}}],
               "context": {"target": _public(lord)}}
    ai._playable_options = lambda req: [0]
    assert ai.simple_response_decision(loyalist, request) == 0
    assert ai.simple_response_decision(spy, request) == 0
    assert ai.simple_response_decision(rebel, request) is None


def test_rule_ai_loyalist_blocks_harmful_trick_on_lord_but_not_peach_garden():
    engine, lord, loyalist, rebel, spy = _rule_ai_setup()
    ai = engine.ai_decision
    ai._playable_options = lambda req: [0]
    harmful = {"kind": "wuxie", "context": {"targets": [_public(lord)], "card_name": "乐不思蜀", "layer": 1}}
    kind = {"kind": "wuxie", "context": {"targets": [_public(lord)], "card_name": "桃园结义", "layer": 1}}
    assert ai.simple_response_decision(loyalist, harmful) == 0
    assert ai.simple_response_decision(rebel, harmful) is None
    assert ai.simple_response_decision(loyalist, kind) is None
