"""Stage T · T2 验收补充（验收代理）：信息边界的逐条核对与方案第 7、12 节缺口补测。

只新增测试，不改运行代码。复用 test_t2_cognitive_notes 的假网关与辅助函数（不导入任何 test_* 名字，避免被重复收集）。
暴露运行代码与方案字面不符的用例标 xfail(strict=True)，reason 写明出处。
"""

import asyncio
import json
import random

import pytest

from game_engine import MainEngine
from game_engine.protocol import ENGINE_EVENT, OUTBOUND
from game_engine.state_manager import Card
from game_server import GameServer
from tests.test_t2_cognitive_notes import (
    KEY, NOTES_REPLY, ScriptedGateway, Socket, attach, decision_message,
    make_engine, note, play_phase, players, run,
)


def walk_keys(obj, acc=None):
    """递归收集 JSON 结构里出现过的所有键名。"""
    acc = set() if acc is None else acc
    if isinstance(obj, dict):
        for key, value in obj.items():
            acc.add(key)
            walk_keys(value, acc)
    elif isinstance(obj, list):
        for value in obj:
            walk_keys(value, acc)
    return acc


def user_texts(messages):
    return [m["content"] for m in messages if m.get("role") == "user"]


# ───────────────────────── 1a 非作弊局：服务器出站全文不含笔记 ─────────────────────────

@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("cheat", [False, True])
def test_full_game_outbound_carries_note_text_only_in_cheat_games(tmp_path, cheat, seed):
    """整局跑完（所有座位都是模型 AI），用服务器真实的 _forward 抓全部出站消息，全文搜索一个独特的笔记理由。

    非作弊局：任何出站消息（含 game_state、decision_trace、game_end）都不得出现该字符串，也不得有 cognitive_notes。
    作弊局：该字符串只能出现在 cognitive_notes 里（正向对照，证明搜索有效）。
    """
    random.seed(seed)                 # 引擎用全局 random 洗牌；固定种子保证每次同一局
    marker = "独特标记甲乙"
    reply = json.dumps({"action_index": 0, "option_index": 0, "reasoning": "测试理由",
                        "notes": {"3": note("rebel", "中", marker)}})
    engine = make_engine(reply, cheat=cheat, max_turns=8, turn_delay=0, phase_delay=0)
    for p in players(engine):
        p.is_ai = True
        p.ai_config["api_key"] = KEY
    server = GameServer(history_path=tmp_path / "h.json")
    ws = Socket()

    async def scenario():
        attach(server, engine, "g1", ws)
        engine.response_timeout = 1
        return await asyncio.wait_for(engine.run(), timeout=60)

    run(scenario())
    assert any(marker in json.dumps(s["notes"], ensure_ascii=False) for s in engine.notes.snapshots), \
        "笔记确实写入了（否则下面的'不含'断言没有意义）"
    types = set(ws.types())
    assert {"game_state", "decision_trace", "game_end"} <= types, f"应覆盖这些出站类型，实际: {sorted(types)}"
    notes_msgs = [m for m in ws.messages if m["type"] == OUTBOUND.COGNITIVE_NOTES]
    if cheat:
        assert notes_msgs and marker in json.dumps(notes_msgs, ensure_ascii=False)
    else:
        assert not notes_msgs
        assert marker not in json.dumps(ws.messages, ensure_ascii=False)
        assert "cognitive_notes" not in json.dumps(ws.messages, ensure_ascii=False)


# ───────────────────────── 1b 作弊局：cognitive_notes 结构与信息边界 ─────────────────────────

def test_cheat_payload_has_fixed_shape_and_no_hands_or_unrevealed_identity(tmp_path):
    engine = make_engine(cheat=True)
    seats = players(engine)
    # 他人手牌：座位 3（id2）与 座位 4（id3）各一张带独特标记的牌
    seats[2].hand.append(Card("uid-hand-A", "独特手牌甲", "spade", 7, "basic"))
    seats[3].hand.append(Card("uid-hand-B", "独特手牌乙", "heart", 2, "basic"))
    # AI 1 对 座位 5（id4，真实身份 spy，未揭示）写 loyalist；对 座位 3 不写
    engine.notes.update(1, {"5": note("loyalist", "低", "独特理由丙")})
    engine.ai_decision.last_reasoning[1] = "公开理由丁"
    server = GameServer(history_path=tmp_path / "h.json")
    ws = Socket()
    attach(server, engine, "g1", ws)
    run(engine._emit_cognitive_notes_if_changed())

    sent = [m for m in ws.messages if m["type"] == OUTBOUND.COGNITIVE_NOTES]
    assert len(sent) == 1
    msg = sent[0]
    assert set(msg) == {"type", "round", "players"}
    row = next(r for r in msg["players"] if r["player_id"] == 1)
    assert set(row) == {"player_id", "seat", "name", "frozen", "reason", "notes"}
    assert row["reason"] == "公开理由丁"
    assert all(set(n) == {"target_id", "seat", "guess", "conf", "why", "locked"} for n in row["notes"])
    # 未揭示座位只能是 AI 自己写的判断：座位 5 显示 loyalist，不会变成真实身份 spy；座位 3 没有任何条目
    by_seat = {n["seat"]: n for n in row["notes"]}
    assert by_seat[5]["guess"] == "loyalist" and by_seat[5]["locked"] is False
    assert 3 not in by_seat
    # 整条消息（含所有出站）不出现他人手牌牌名与牌 id，不出现 hand/identity/cards 等键
    dump = json.dumps(ws.messages, ensure_ascii=False)
    for needle in ("独特手牌甲", "独特手牌乙", "uid-hand-A", "uid-hand-B"):
        assert needle not in dump, needle
    forbidden = {"hand", "identity", "cards", "equipment", "judge_area", "identity_revealed"}
    assert not (walk_keys(msg) & forbidden), walk_keys(msg) & forbidden


# ───────────────────────── 1c AI 的 prompt 只含自己的笔记 ─────────────────────────

def test_each_ai_prompt_contains_only_its_own_notes():
    engine = make_engine()
    p1, p2 = players(engine)[1], players(engine)[2]
    engine.notes.update(1, {"4": note("rebel", "高", "独特甲理由")})
    engine.notes.update(2, {"5": note("spy", "中", "独特乙理由")})
    msg1 = decision_message(engine, p1)
    msg2 = decision_message(engine, p2)
    assert "【仅你可见·你的判断】" in msg1 and "独特甲理由" in msg1
    assert "独特乙理由" not in msg1
    assert "独特甲理由" not in msg2 and "独特乙理由" in msg2


def test_notes_sent_to_model_never_include_other_ais_notes():
    """真正发给网关的消息（不只是拼好的字符串）：AI 1 的调用里不得出现 AI 2 的笔记。"""
    engine = make_engine(json.dumps({"action_index": 0, "reasoning": "x"}))
    engine.notes.update(2, {"5": note("spy", "中", "独特乙理由")})
    p1 = players(engine)[1]
    play_phase(engine, p1)
    run(engine.ai_decision.make_decision(p1, [{"type": "end_phase"}]))
    run(engine.ai_decision.make_decision(p1, [{"type": "end_phase"}]))
    for call in engine.ai_decision.gateway.calls:
        assert all("独特乙理由" not in text for text in user_texts(call))


# ───────────────────────── 1d hide_dead_identity：阵亡者不自动填写、不锁定 ─────────────────────────

def _notes_row_lines(prompt, seat):
    return [line for line in prompt.splitlines() if line.startswith(f"- {seat}号：")]


def test_prompt_marks_dead_seat_as_locked_only_when_identity_is_public():
    shown = make_engine()
    shown.notes.ensure(1)
    victim = players(shown)[3]
    victim.alive = False
    victim.identity_revealed = True                    # 默认：card_system 阵亡亮明身份
    shown.on_player_death(victim)
    lines = _notes_row_lines(decision_message(shown, players(shown)[1]), 4)
    assert lines and "已公开" in lines[0] and "反贼" in lines[0]

    hidden = make_engine(hide_dead_identity=True)
    hidden.notes.ensure(1)
    victim = players(hidden)[3]
    victim.alive = False
    hidden.on_player_death(victim)                     # 暗置：card_system 不设 identity_revealed
    assert _notes_row_lines(decision_message(hidden, players(hidden)[1]), 4) == []
    hidden.notes.update(1, {"4": note("spy", "低", "独特死前理由")})
    lines = _notes_row_lines(decision_message(hidden, players(hidden)[1]), 4)
    assert lines and "已公开" not in lines[0] and "内奸" in lines[0] and "独特死前理由" in lines[0]
    assert "反贼" not in lines[0]


# ───────────────────────── 第 12 节 作弊模式：开关默认关 ─────────────────────────

BASE_CONFIG = {"mode": "5人身份局", "player_name": "真人", "profile_id": "local_t2",
               "ais": [{"name": f"AI{i}"} for i in range(1, 5)], "deck_id": "standard"}


def test_cheat_mode_defaults_off_and_only_literal_true_enables_it():
    assert MainEngine.normalize_config(dict(BASE_CONFIG)).get("cheat_mode") is False
    for truthy_but_not_true in ("true", 1, "yes"):
        cfg = MainEngine.normalize_config(dict(BASE_CONFIG, cheat_mode=truthy_but_not_true))
        assert cfg.get("cheat_mode") is False, truthy_but_not_true
    assert MainEngine.normalize_config(dict(BASE_CONFIG, cheat_mode=True)).get("cheat_mode") is True


# ───────────────────────── 第 7.2 节：每次出牌决策都注入，且复核句只出现一次 ─────────────────────────

def test_current_note_version_is_injected_into_each_play_decision():
    reply_a = json.dumps({"action_index": 0, "notes": {"3": note("rebel", "中", "旧版甲")}})
    reply_b = json.dumps({"action_index": 0, "notes": {"3": note("spy", "高", "新版乙")}})
    engine = make_engine(reply_a, reply_b)
    p1 = players(engine)[1]
    play_phase(engine, p1)
    for _ in range(3):
        run(engine.ai_decision.make_decision(p1, [{"type": "end_phase"}]))
    calls = engine.ai_decision.gateway.calls
    assert len(calls) == 3
    assert "新版乙" in user_texts(calls[2])[-1] and "旧版甲" not in user_texts(calls[2])[-1]


# ───────────────────────── 方案 7.3 字面：笔记不进会话消息（作者已列为待确认 1） ─────────────────────────

@pytest.mark.xfail(strict=True, reason=(
    "方案 7.3 写'不进会话消息'；实现里 L2 整段（含【仅你可见·你的判断】区块）经 push_user 永久追加进会话，"
    "旧版笔记会留在窗口里（交接 20261018_1011 第 6 节 裁定 2 / 待确认 1，待调度裁定）"))
def test_superseded_note_text_is_not_kept_in_session_user_messages():
    reply_a = json.dumps({"action_index": 0, "notes": {"3": note("rebel", "中", "旧版甲")}})
    reply_b = json.dumps({"action_index": 0, "notes": {"3": note("spy", "高", "新版乙")}})
    engine = make_engine(reply_a, reply_b, reply_b)
    p1 = players(engine)[1]
    play_phase(engine, p1)
    for _ in range(3):
        run(engine.ai_decision.make_decision(p1, [{"type": "end_phase"}]))
    third_call_users = user_texts(engine.ai_decision.gateway.calls[2])
    assert all("旧版甲" not in text for text in third_call_users)


# ───────────────────────── 第 12 节：只展示模型主动返回的公开理由 ─────────────────────────

def test_rule_ai_without_key_gets_no_reason_and_never_becomes_a_notes_owner():
    """第 12 节：只展示模型主动返回的理由；规则 AI（无 Key）既没有理由也不写笔记。"""
    engine = make_engine(cheat=True)
    p1 = players(engine)[1]
    p1.ai_config["api_key"] = ""
    play_phase(engine, p1)
    run(engine.ai_decision.make_decision(p1, [{"type": "end_phase"}]))
    assert engine.ai_decision.last_reasoning.get(1, "") == ""
    assert engine.notes.owners == []
    assert engine.cheat_notes_payload()["players"] == []
