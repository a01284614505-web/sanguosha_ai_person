"""Stage T · T1 行为账本验收复核（验收代理新增）。

- 无 xfail 的用例：验证 6.3 信息边界在「阵亡暗置 / 阵亡明置」两种开局下都成立。
- 原 strict xfail 两条已按调度裁定处理：缺陷 1 已修成普通测试，缺陷 2 改为断言当前（认可的）行为。
"""

import asyncio

import pytest

from game_engine import MainEngine
from game_engine.behavior_ledger import SUMMARY_HEADER
from game_engine.card_table import CARD_TABLE
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
        player.is_ai = True
    return engine


def card(tag, name, suit="spade", rank=7):
    spec = CARD_TABLE.get(name)
    return Card(tag, name, suit, rank, spec.card_type if spec else "basic")


def rows(engine):
    return [(e.source_id, e.target_id, e.kind, e.label) for e in engine.ledger.entries]


def scripted_responder(allowed_names_by_player):
    async def responder(player, request):
        wanted = allowed_names_by_player.get(player.id, set())
        for option in request["options"]:
            if option.get("card") is not None and option.get("as_name") in wanted \
                    and option.get("owner") is player:
                return {"bool": True, "card": option["card"], "owner": option["owner"],
                        "as_name": option["as_name"], "source_zone": option.get("source_zone", "hand")}
        return {"bool": False}
    return responder


# ───────────── 6.3 信息边界：阵亡身份在两种开局设置下都不泄露 ─────────────

def _seat_tagged(text, seat_no):
    """「N号(」出现 = 该座位被标了身份。"""
    return f"{seat_no}号(" in text


@pytest.mark.parametrize("hide_dead", [True, False])
def test_review_dead_rebel_identity_never_tagged_in_summary(hide_dead):
    engine = game()
    engine.hide_dead_identity = hide_dead
    lord, _, rebel, *_ = engine.game_state.players
    lord.identity, lord.identity_revealed = "lord", True
    rebel.identity, rebel.identity_revealed = "rebel", False
    rebel.hp = 0
    engine.card_system.responder = scripted_responder({})     # 谁都不救，rebel 阵亡
    run(engine.card_system.enter_dying(rebel))
    assert not rebel.alive
    # 6.3 / 第 20 节 J：暗置开局阵亡者保持隐藏；明置开局阵亡者可以公开，但汇总只标主公。
    assert rebel.identity_revealed is (not hide_dead)
    engine.ledger.record(1, 0, rebel.id, "hostile", "杀")
    text = engine.ledger.summarize(engine.game_state)
    assert text.startswith(SUMMARY_HEADER)
    assert not _seat_tagged(text, rebel.id + 1)
    for word in ("反贼", "内奸", "忠臣"):
        assert word not in text


def test_review_summary_tags_only_the_lord_even_when_all_identities_are_revealed():
    engine = game()
    players = engine.game_state.players
    roles = ["lord", "loyalist", "rebel", "spy", "rebel"]
    for p, role in zip(players, roles):
        p.identity, p.identity_revealed = role, True
    for s in range(1, 5):
        engine.ledger.record(1, s, 0 if s != 1 else 2, "hostile", "杀")
    text = engine.ledger.summarize(engine.game_state)
    assert text.count("(主公)") >= 1
    for word in ("忠臣", "反贼", "内奸", "(忠)", "(反)", "(内)"):
        assert word not in text


def test_review_summary_identity_tag_depends_only_on_lord_flag_not_on_death():
    """阵亡不改变标签逻辑：阵亡的非主公不标；主公（开局即公开）照常标。"""
    engine = game()
    players = engine.game_state.players
    players[0].identity, players[0].identity_revealed = "lord", True
    players[1].identity, players[1].identity_revealed = "rebel", True
    players[1].alive = False
    engine.ledger.record(1, 2, 1, "hostile", "杀")
    engine.ledger.record(1, 2, 0, "hostile", "杀")
    text = engine.ledger.summarize(engine.game_state)
    assert not _seat_tagged(text, 2)
    assert _seat_tagged(text, 1)


# ───────────── 6.3 / 6.2 复核：无懈链、借刀（缺陷已修，见交接） ─────────────

def test_review_delayed_trick_wuxie_layer2_backs_the_trick_user_not_the_victim():
    engine = game()
    p0, victim, p2, p3 = engine.game_state.players[:4]
    lebu = card("lebu", "乐不思蜀", "heart")
    # 真实路径：p0 出乐不思蜀，经 move_card 放入 victim 判定区（记录 actor）。
    engine.game_state.discard_pile.append(lebu)
    run(engine.card_system._use_delayed_trick(p0, lebu, victim))
    engine.ledger.entries.clear()
    p2.hand.append(card("wx1", "无懈可击", "club"))
    p3.hand.append(card("wx2", "无懈可击", "spade"))
    engine.card_system.responder = scripted_responder({2: {"无懈可击"}, 3: {"无懈可击"}})
    run(engine.phase_controller.execute_judge(victim, lebu))
    # 第 1 层：2 号抵消乐不思蜀 → 保护被判定者（正确）。
    assert (2, victim.id, "protect", "无懈保护") in rows(engine)
    # 第 2 层：3 号抵消 2 号的无懈 → 应当是帮乐不思蜀的使用者，不是保护被判定者。
    assert (3, victim.id, "protect", "无懈保护") not in rows(engine)
    assert (3, p0.id, "protect", "无懈保护") in rows(engine)


def test_review_delayed_trick_wuxie_layer2_records_nothing_when_user_unknown():
    engine = game()
    p0, victim, p2, p3 = engine.game_state.players[:4]
    lebu = card("lebu2", "乐不思蜀", "heart")
    victim.judge_area.append(lebu)                         # 没有放置记录：使用者不可得
    p2.hand.append(card("wx1", "无懈可击", "club"))
    p3.hand.append(card("wx2", "无懈可击", "spade"))
    engine.card_system.responder = scripted_responder({2: {"无懈可击"}, 3: {"无懈可击"}})
    run(engine.phase_controller.execute_judge(victim, lebu))
    assert rows(engine) == [(2, victim.id, "protect", "无懈保护")]


def test_review_jiedao_records_no_weapon_hostility_even_when_executor_complies():
    engine = game()
    p0, p1, p2 = engine.game_state.players[:3]
    p1.equipment["weapon"] = card("w", "诸葛连弩", "club")
    p1.hand.append(card("sha_exec", "杀"))
    engine.card_system.responder = scripted_responder({1: {"杀"}})
    run(engine.card_system.use_card(p0, card("jd", "借刀杀人"), [p1, p2]))
    # 2026-10-18 用户裁定：借刀可能是借队友的刀去打敌人，取武器不带敌意，不记"借刀夺武器"。
    assert p1.equipment.get("weapon") is not None          # 武器没有被夺走
    assert [e for e in engine.ledger.entries if e.label == "借刀夺武器"] == []
    assert not any(e.target_id == 1 for e in engine.ledger.entries)   # 被借刀者没有任何入账
    assert [(e.source_id, e.target_id, e.kind) for e in engine.ledger.entries] == [(0, 2, "hostile")]
