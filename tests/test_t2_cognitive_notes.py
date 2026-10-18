"""Stage T · T2 认知笔记 + 作弊面板：格式校验、锁定与冻结、注入位置、更新时机、协议闸门、局后日志。

用假网关（脚本化回复）+ 抓服务器出站消息；不需要真 Key。
"""

import asyncio
import json

import pytest

from game_engine import MainEngine
from game_engine.ai_decision import AIDecision
from game_engine.cognitive_notes import CognitiveNotes, validate_entry, WHY_MAX
from game_engine.game_logs import build_game_log
from game_engine.protocol import ENGINE_EVENT, ENGINE_EVENTS, OUTBOUND
from game_engine.state_manager import Card, Phase
from game_server import GameServer

KEY = "sk-fake-for-test"
IDENTITIES = ["lord", "loyalist", "rebel", "rebel", "spy"]


def run(coro):
    return asyncio.run(coro)


class ScriptedGateway:
    """按顺序返回预设回复（用完后重复最后一条）；记录每次收到的消息。"""

    def __init__(self, *replies):
        self.replies = list(replies) or ['{"action_index": 0, "reasoning": "测试"}']
        self.calls = []

    async def call_ai(self, **kwargs):
        self.calls.append([dict(m) for m in kwargs["messages"]])
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if kwargs.get("return_usage"):
            return reply, {"prompt_tokens": 10, "cached_tokens": 0, "completion_tokens": 5}
        return reply


def make_engine(*replies, cheat=False, keyed=True, **extra):
    config = {"mode": "5人身份局", "player_name": "真人", "profile_id": "local_t2",
              "ais": [{"name": f"AI{i}"} for i in range(1, 5)], "deck_id": "standard",
              "cheat_mode": cheat}
    config.update(extra)
    engine = MainEngine(config)
    engine.ai_decision.gateway = ScriptedGateway(*replies)
    for player, identity in zip(engine.game_state.players, IDENTITIES):
        player.identity = identity
        player.identity_revealed = identity == "lord"
        player.hand.clear()
        if player.is_ai and keyed:
            player.ai_config["api_key"] = KEY
    return engine


def players(engine):
    return engine.game_state.players


def note(guess="rebel", conf="高", why="两次杀主公"):
    return {"guess": guess, "conf": conf, "why": why}


def play_phase(engine, player):
    engine.game_state.current_player = player
    engine.game_state.current_phase = Phase.PLAY
    player.sha_count = 0


# ───────────────────────── 格式与校验 ─────────────────────────

def test_validate_entry_accepts_well_formed_note():
    assert validate_entry(note()) == note()
    assert validate_entry(note("unknown", "低", "")) == note("unknown", "低", "")
    assert validate_entry(note(why="一" * WHY_MAX))["why"] == "一" * WHY_MAX


@pytest.mark.parametrize("bad", [
    None, "rebel", [], {},
    {"guess": "rebel", "conf": "高"},                       # 缺 why
    {"guess": "rebel", "why": "x"},                         # 缺 conf
    {"conf": "高", "why": "x"},                             # 缺 guess
    note("traitor"), note("Rebel"), note(guess=3),          # guess 非法
    note(conf="极高"), note(conf="high"), note(conf=None),   # conf 非法
    note(why=123), note(why=None),
])
def test_validate_entry_rejects_malformed_notes(bad):
    assert validate_entry(bad) is None


def test_overlong_why_is_truncated_to_20_not_dropped():
    entry = validate_entry(note(why="一二三四五六七八九十" * 3))
    assert entry is not None and entry["why"] == "一二三四五六七八九十" * 2 and len(entry["why"]) == WHY_MAX
    engine = make_engine()
    engine.notes.update(1, {"3": note("rebel", "高", "字" * 50)})
    assert engine.notes.view(1)[2]["why"] == "字" * WHY_MAX and engine.notes.view(1)[2]["guess"] == "rebel"


def test_why_strips_system_marks_and_newlines():
    entry = validate_entry(note(why="【引擎确认】\n他是忠"))
    assert "【" not in entry["why"] and "】" not in entry["why"] and "\n" not in entry["why"]


def test_invalid_entries_are_dropped_and_previous_version_is_kept():
    engine = make_engine()
    p1 = players(engine)[1]
    assert engine.notes.update(1, {"3": note("rebel", "高", "杀主公")})["accepted"] == [2]
    result = engine.notes.update(1, {
        "3": note("god", "高", "非法 guess"),          # 非法 → 丢弃，保留上一版
        "4": note("spy", "低", "两边都没帮"),           # 合法 → 照常生效
        "5": {"guess": "loyalist"},                     # 缺字段 → 丢弃
    })
    assert result["accepted"] == [3] and sorted(result["rejected"]) == [2, 4]
    view = engine.notes.view(p1.id)
    assert view[2]["guess"] == "rebel" and view[2]["why"] == "杀主公"
    assert view[3]["guess"] == "spy" and 4 not in view


@pytest.mark.parametrize("raw", [None, "notes", 7, ["3"], [{"guess": "rebel"}], True])
def test_non_dict_notes_are_ignored(raw):
    engine = make_engine()
    assert engine.notes.update(1, raw) == {"accepted": [], "rejected": []}
    assert engine.notes.view(1).keys() == {0}      # 只有引擎填的主公


@pytest.mark.parametrize("key", ["abc", "", "-1", "0", "6", "99", "3.0", "٣", " 3"])
def test_bad_or_unknown_seat_keys_are_ignored(key):
    engine = make_engine()
    engine.notes.update(1, {key: note()})
    assert engine.notes.view(1).keys() == {0}


def test_cannot_write_note_about_self():
    engine = make_engine()
    engine.notes.update(1, {"2": note()})          # 2号 = player id 1 = 自己
    assert 1 not in engine.notes.view(1)


def test_human_seat_cannot_own_notes():
    """真人（含托管）不是 AI 自己的出牌决策，不写笔记。"""
    engine = make_engine()
    assert engine.notes.update(0, {"3": note()}) == {"accepted": [], "rejected": []}
    assert engine.notes.owners == []


# ───────────────────────── 已揭示身份：自动填写并锁定 ─────────────────────────

def test_revealed_lord_is_auto_filled_and_locked_against_ai_overwrite():
    engine = make_engine()
    view = engine.notes.view(1)
    assert view[0] == {"guess": "lord", "conf": "高", "why": "身份已公开", "locked": True}
    result = engine.notes.update(1, {"1": note("rebel", "高", "我觉得是反贼")})
    assert result["accepted"] == [] and result["rejected"] == [0]
    assert engine.notes.view(1)[0]["guess"] == "lord" and engine.notes.view(1)[0]["locked"] is True


def test_revealed_dead_player_is_auto_filled_by_default():
    engine = make_engine()
    victim = players(engine)[3]
    victim.alive = False
    victim.identity_revealed = True      # 官方规则：阵亡亮明身份
    assert engine.notes.view(1)[3] == {"guess": "rebel", "conf": "高", "why": "身份已公开", "locked": True}
    assert engine.notes.update(1, {"4": note("spy")})["accepted"] == []


def test_hide_dead_identity_engine_does_not_fill_and_dead_seat_stays_guessable():
    """待确认 J 的推荐：阵亡暗置时引擎不自动填阵亡者身份，阵亡者在笔记中照常可猜。"""
    engine = make_engine(hide_dead_identity=True)
    victim = players(engine)[3]
    victim.alive = False                  # 暗置：identity_revealed 保持 False
    assert 3 not in engine.notes.view(1)
    assert engine.notes.update(1, {"4": note("spy", "低", "死前没站队")})["accepted"] == [3]
    assert engine.notes.view(1)[3]["guess"] == "spy" and engine.notes.view(1)[3]["locked"] is False


def test_death_through_card_system_reveals_unless_hidden_and_hooks_notes():
    for hidden in (False, True):
        engine = make_engine(hide_dead_identity=hidden)
        engine.notes.ensure(1)
        victim = players(engine)[3]
        victim.hp = 0
        engine.card_system.responder = None
        run(engine.card_system.enter_dying(victim))
        assert victim.alive is False
        filled = 3 in engine.notes.view(1) and engine.notes.view(1)[3]["locked"]
        assert filled is (not hidden)


# ───────────────────────── 阵亡冻结 / 复核标记 ─────────────────────────

def test_notes_freeze_when_owner_dies():
    engine = make_engine()
    engine.notes.update(1, {"3": note("rebel", "中", "杀过主公")})
    owner = players(engine)[1]
    owner.alive = False
    engine.on_player_death(owner)
    frozen = engine.notes.view(1)
    assert engine.notes.is_frozen(1)
    assert engine.notes.update(1, {"3": note("spy")}) == {"accepted": [], "rejected": []}
    # 之后别人阵亡揭示，冻结的视图也不再自动填写
    other = players(engine)[3]
    other.alive = False
    other.identity_revealed = True
    assert engine.notes.view(1) == frozen and 3 not in engine.notes.view(1)


def test_major_event_marks_every_living_owner_for_review_exactly_once():
    engine = make_engine()
    for pid in (1, 2, 3, 4):
        engine.notes.ensure(pid)
    victim = players(engine)[2]
    victim.alive = False
    engine.on_player_death(victim)
    assert engine.notes.consume_review(1) is True
    assert engine.notes.consume_review(1) is False
    assert engine.notes.consume_review(2) is False        # 死者自己不需要复核
    assert engine.notes.consume_review(3) is True


# ───────────────────────── 快照 ─────────────────────────

def test_round_snapshots_one_per_owner_per_round_and_dead_owner_only_in_death_round():
    engine = make_engine()
    engine.notes.ensure(1)
    engine.notes.ensure(2)
    engine.notes.update(1, {"3": note()})
    engine.notes.snapshot(1)
    engine.notes.update(1, {"3": note("spy", "低", "改判")})
    owner = players(engine)[2]
    owner.alive = False
    engine.game_state.round_number = 2
    engine.on_player_death(owner)
    engine.notes.snapshot(2)
    engine.game_state.round_number = 3
    engine.notes.snapshot(3)
    got = [(s["round"], s["player_id"]) for s in engine.notes.snapshots]
    assert got == [(1, 1), (1, 2), (2, 1), (2, 2), (3, 1)]
    r1 = next(s for s in engine.notes.snapshots if s["round"] == 1 and s["player_id"] == 1)
    r3 = next(s for s in engine.notes.snapshots if s["round"] == 3 and s["player_id"] == 1)
    assert r1["notes"]["3"]["guess"] == "rebel" and r3["notes"]["3"]["guess"] == "spy"
    assert r1["notes"]["1"]["locked"] is True


def test_run_loop_snapshots_when_round_advances_and_at_the_end():
    engine = make_engine()
    engine.notes.ensure(1)
    engine._notes_round = 1
    engine.game_state.round_number = 1
    engine._roll_notes_round()
    assert engine.notes.snapshots == []                    # 轮没变，不存
    engine.game_state.round_number = 2
    engine._roll_notes_round()
    assert [s["round"] for s in engine.notes.snapshots] == [1]
    engine._roll_notes_round(final=True)
    assert [s["round"] for s in engine.notes.snapshots] == [1, 2]


def test_full_game_with_fake_gateway_records_snapshots_per_round():
    """整局跑完：所有座位都是模型 AI（假网关），每轮每个 AI 一份快照，且对局正常结束。"""
    reply = json.dumps({"action_index": 0, "option_index": 0, "reasoning": "测试",
                        "notes": {"1": note("lord", "高", "胡写")}})
    engine = make_engine(reply, max_turns=12, turn_delay=0, phase_delay=0)
    for p in players(engine):
        p.is_ai = True
        p.ai_config["api_key"] = KEY

    async def scenario():
        engine.response_timeout = 1
        return await asyncio.wait_for(engine.run(), timeout=60)

    run(scenario())
    snaps = engine.notes.snapshots
    assert snaps, "整局至少应有一轮快照"
    rounds = sorted({s["round"] for s in snaps})
    assert rounds == list(range(rounds[0], rounds[-1] + 1))
    for rnd in rounds:
        ids = [s["player_id"] for s in snaps if s["round"] == rnd]
        assert len(ids) == len(set(ids))


# ───────────────────────── 注入 prompt ─────────────────────────

def decision_message(engine, player):
    play_phase(engine, player)
    return engine.ai_decision.build_decision_turn_message(player, [{"type": "end_phase"}])


def test_notes_block_sits_after_ledger_and_chat_and_before_legal_actions():
    engine = make_engine()
    p1 = players(engine)[1]
    engine.ledger.record(1, 2, 0, "hostile", "杀")
    run(engine.submit_chat(0, "我是忠臣"))
    engine.notes.update(1, {"3": note("rebel", "高", "两次杀主公")})
    msg = decision_message(engine, p1)
    ledger_at = msg.index("【引擎确认·行为账本】")
    chat_at = msg.index("【发言·未验证】")
    notes_at = msg.index("【仅你可见·你的判断】")
    actions_at = msg.index("合法操作列表")
    assert ledger_at < chat_at < notes_at < actions_at
    assert "3号：反贼（把握高）两次杀主公" in msg
    assert "1号：主公（已公开，引擎填写，不可改）" in msg


def test_json_example_includes_notes_and_asks_only_for_changes():
    engine = make_engine()
    msg = decision_message(engine, players(engine)[1])
    assert '"notes": {"3": {"guess": "rebel", "conf": "高", "why": "两次杀主公"}}' in msg
    assert "只写有变化的座位" in msg and "20字" in msg


def test_block_shows_previous_version_and_says_when_empty():
    engine = make_engine()
    p1 = players(engine)[1]
    assert "你还没有对任何座位做出自己的判断" in decision_message(engine, p1)
    engine.notes.update(1, {"4": note("spy", "低", "两边都没帮")})
    msg = decision_message(engine, p1)
    assert "你还没有对任何座位做出自己的判断" not in msg and "4号：内奸（把握低）两边都没帮" in msg


def test_review_sentence_appears_once_for_first_play_decision_after_a_death():
    engine = make_engine()
    p1 = players(engine)[1]
    assert "局势有变" not in decision_message(engine, p1)
    victim = players(engine)[3]
    victim.alive = False
    engine.on_player_death(victim)
    msg = decision_message(engine, p1)
    assert "局势有变" in msg and "请复核" in msg
    assert "局势有变" not in decision_message(engine, p1)       # 标记已消费


def test_review_sentence_is_per_ai_and_survives_until_that_ais_own_play_decision():
    engine = make_engine()
    p1, p2 = players(engine)[1], players(engine)[2]
    engine.notes.ensure(1)
    engine.notes.ensure(2)
    victim = players(engine)[4]
    victim.alive = False
    engine.on_player_death(victim)
    assert "局势有变" in decision_message(engine, p1)
    assert "局势有变" in decision_message(engine, p2)      # p1 消费不影响 p2
    assert "局势有变" not in decision_message(engine, p1)


def test_response_and_choice_prompts_never_carry_notes():
    engine = make_engine()
    p1 = players(engine)[1]
    engine.notes.update(1, {"3": note()})
    response = engine.ai_decision.build_response_prompt(
        p1, {"kind": "respond", "prompt": "请出闪", "options": [{"card": Card("s", "闪", "heart", 2, "basic")}]})
    assert "【仅你可见·你的判断】" not in response and "notes" not in response
    sent = []
    engine.ai_decision.gateway = ScriptedGateway('{"option_index": 0, "option_indices": [0]}')
    original = engine.ai_decision._call_with_session

    async def spy(player, kind, message):
        sent.append((kind, message))
        return await original(player, kind, message)

    engine.ai_decision._call_with_session = spy
    run(engine.ai_decision.make_choice_decision(p1, {
        "kind": "choose_option", "prompt": "选一个", "options": [{"label": "甲"}, {"label": "乙"}],
        "min_n": 1, "max_n": 1}))
    run(engine.ai_decision.make_response_decision(
        p1, {"kind": "respond", "prompt": "请出闪", "options": [{"card": Card("s2", "闪", "heart", 3, "basic")}]}))
    assert sent and all("【仅你可见·你的判断】" not in message for _, message in sent)


def test_trustee_view_of_the_human_gets_no_notes_block_and_old_json_example():
    engine = make_engine()
    human = players(engine)[0]
    msg = engine.ai_decision.build_decision_turn_message(
        engine._trustee_view(human), [{"type": "end_phase"}])
    assert "【仅你可见·你的判断】" not in msg and '"notes"' not in msg


def test_notes_block_contains_no_hands_or_hidden_identity_of_others():
    engine = make_engine()
    p1 = players(engine)[1]
    players(engine)[2].hand.append(Card("secret", "无懈可击", "club", 5, "trick"))
    engine.notes.update(1, {"3": note("rebel", "中", "猜的")})
    block = engine.notes.prompt_block(1)
    assert "无懈可击" not in block and "spy" not in block and "内奸" not in block
    # 他人真实身份（未揭示）不会出现在笔记里
    assert "忠臣" not in block


# ───────────────────────── 更新时机：只在 AI 自己的出牌决策 ─────────────────────────

def test_play_decision_updates_notes_from_model_reply():
    reply = json.dumps({"action_index": 0, "reasoning": "先观察",
                        "notes": {"3": note("rebel", "高", "杀主公"), "4": note("spy", "低", "没表态")}})
    engine = make_engine(reply)
    p1 = players(engine)[1]
    play_phase(engine, p1)
    decision = run(engine.ai_decision.make_decision(p1, [{"type": "end_phase"}]))
    assert decision["action"]["type"] == "end_phase"
    view = engine.notes.view(1)
    assert view[2]["guess"] == "rebel" and view[3]["guess"] == "spy"


def test_bad_notes_field_is_dropped_but_action_still_executes():
    for bad in ('"notes": "不是对象"', '"notes": [1, 2]', '"notes": {"3": "oops"}', '"notes": null'):
        reply = '{"action_index": 0, "reasoning": "r", ' + bad + '}'
        engine = make_engine(reply)
        p1 = players(engine)[1]
        play_phase(engine, p1)
        decision = run(engine.ai_decision.make_decision(p1, [{"type": "end_phase"}]))
        assert decision["action"]["type"] == "end_phase" and decision["reasoning"] == "r"
        assert engine.ai_decision.last_failure[1] is None
        assert engine.notes.view(1).keys() == {0}


def test_response_and_choice_decisions_do_not_update_notes():
    reply = json.dumps({"option_index": 0, "option_indices": [0], "chat_message": "",
                        "notes": {"3": note("rebel")}})
    engine = make_engine(reply)
    p1 = players(engine)[1]
    run(engine.ai_decision.make_response_decision(
        p1, {"kind": "respond", "prompt": "请出闪", "options": [{"card": Card("s", "闪", "heart", 2, "basic")}]}))
    run(engine.ai_decision.make_choice_decision(p1, {
        "kind": "choose_option", "prompt": "选一个", "options": [{"label": "甲"}, {"label": "乙"}],
        "min_n": 1, "max_n": 1}))
    assert 2 not in engine.notes.view(1)


def test_rule_ai_without_key_never_writes_notes_and_gets_no_block():
    engine = make_engine(keyed=False)
    p1 = players(engine)[1]
    play_phase(engine, p1)
    p1.hand.clear()
    run(engine.ai_decision.make_decision(p1, [{"type": "end_phase"}]))
    assert engine.ai_decision.gateway.calls == []
    assert engine.notes.owners == [] and engine.notes.view(1).keys() == {0}
    # 即使直接把模型回复喂给解析器，无 Key 座位也不在 owners 里；run() 启动时也不会登记
    engine.notes.update(1, {"3": note()})
    engine2 = make_engine(keyed=False)
    for p in players(engine2):
        if p.is_ai and engine2._has_model_key(p):
            engine2.notes.ensure(p.id)
    assert engine2.notes.owners == []


def test_failed_model_call_falls_back_to_rules_and_leaves_notes_untouched():
    engine = make_engine()
    engine.notes.update(1, {"3": note("rebel", "高", "旧判断")})

    class Boom:
        async def call_ai(self, **kwargs):
            raise RuntimeError("down")

    engine.ai_decision.gateway = Boom()
    p1 = players(engine)[1]
    play_phase(engine, p1)
    run(engine.ai_decision.make_decision(p1, [{"type": "end_phase"}]))
    assert engine.notes.view(1)[2]["why"] == "旧判断"


# ───────────────────────── 不进会话、不参与压缩 ─────────────────────────

def test_notes_survive_session_compression_and_are_fully_reinjected():
    reply = json.dumps({"action_index": 0, "reasoning": "r"})
    engine = make_engine(reply)
    ai = engine.ai_decision
    ai.session_max_l2 = 4
    ai.session_max_chars = 10 ** 9
    p1 = players(engine)[1]
    play_phase(engine, p1)
    engine.notes.update(1, {"3": note("rebel", "高", "两次杀主公"), "4": note("spy", "低", "两边都没帮"),
                            "5": note("loyalist", "中", "替主公挡刀")})
    expected = engine.notes.prompt_block(1)
    for _ in range(12):
        run(ai.make_decision(p1, [{"type": "end_phase"}]))
    session = ai.get_session(p1)
    assert session["compressions"] >= 1, "必须真的发生过压缩"
    last_user = ai.gateway.calls[-1][-1]["content"]
    assert expected.strip() in last_user, "压缩后笔记仍完整注入"
    # 笔记是独立结构：压缩前后内容不变，会话摘要不是它的来源
    assert engine.notes.view(1)[2]["why"] == "两次杀主公" and len(engine.notes.view(1)) == 4
    summary = next(m for m in session["messages"] if m["content"].startswith(ai.SUMMARY_MARK))
    assert "【仅你可见·你的判断】" not in summary["content"]


def test_notes_store_is_not_part_of_the_session_object():
    engine = make_engine()
    p1 = players(engine)[1]
    engine.notes.update(1, {"3": note()})
    session = engine.ai_decision.get_session(p1)
    assert "notes" not in session and "cognitive" not in json.dumps(session, ensure_ascii=False)


# ───────────────────────── 协议：仅作弊局下发 ─────────────────────────

class Socket:
    def __init__(self):
        self.messages = []
        self.remote_address = ("test", 0)

    async def send(self, raw):
        self.messages.append(json.loads(raw))

    def types(self):
        return [m["type"] for m in self.messages]


def attach(server, engine, gid, ws):
    engine.game_id = gid
    server.engines[gid] = engine
    server.ws_map[ws] = gid
    server.viewers[gid] = ws
    for event in ENGINE_EVENTS:
        engine.on(event, server._forward(gid, event))


NOTES_REPLY = json.dumps({"action_index": 0, "target_ids": [1], "reasoning": "公开理由甲",
                          "notes": {"3": note("rebel", "高", "杀主公")}})


async def one_ai_turn(engine, player):
    play_phase(engine, player)
    await engine._auto_play_phase(player)


def test_cheat_game_server_sends_cognitive_notes_with_latest_public_reason(tmp_path):
    async def scenario():
        server = GameServer(history_path=tmp_path / "h.json")
        engine = make_engine(NOTES_REPLY, cheat=True)
        ws = Socket()
        attach(server, engine, "g1", ws)
        p1 = players(engine)[1]
        # 手里没牌：可用操作只有「结束出牌」时 _auto_play_phase 不会调用模型，这里给一张闪让它有 >1 个候选
        p1.hand.append(Card("c1", "杀", "spade", 7, "basic"))
        await one_ai_turn(engine, p1)
        return ws

    ws = run(scenario())
    sent = [m for m in ws.messages if m["type"] == OUTBOUND.COGNITIVE_NOTES]
    assert sent, f"作弊局应下发 cognitive_notes，实际类型: {ws.types()}"
    row = next(r for r in sent[-1]["players"] if r["player_id"] == 1)
    assert row["seat"] == 2 and row["reason"] == "公开理由甲" and row["frozen"] is False
    target = next(n for n in row["notes"] if n["seat"] == 3)
    assert (target["guess"], target["conf"], target["why"], target["locked"]) == ("rebel", "高", "杀主公", False)
    lord = next(n for n in row["notes"] if n["seat"] == 1)
    assert lord["locked"] is True and lord["guess"] == "lord"
    # 作弊局也不能带出手牌与未揭示身份
    dumped = json.dumps(sent, ensure_ascii=False)
    assert "c1" not in dumped and "hand" not in dumped and "identity" not in dumped


def test_non_cheat_game_server_never_emits_cognitive_notes(tmp_path):
    """直接断言服务器发出的消息里没有 cognitive_notes（也没有笔记内容）。"""
    async def scenario():
        server = GameServer(history_path=tmp_path / "h.json")
        engine = make_engine(NOTES_REPLY, cheat=False)
        ws = Socket()
        attach(server, engine, "g1", ws)
        p1 = players(engine)[1]
        p1.hand.append(Card("c1", "杀", "spade", 7, "basic"))
        await one_ai_turn(engine, p1)
        await engine.emit(ENGINE_EVENT.STATE_CHANGED, state=engine.serialize())
        return server, engine, ws

    server, engine, ws = run(scenario())
    assert engine.notes.view(1)[2]["why"] == "杀主公", "笔记照常记录（供局后日志）"
    assert engine.cheat_notes_payload() is None
    assert OUTBOUND.COGNITIVE_NOTES not in ws.types()
    assert "cognitive_notes" not in json.dumps(ws.messages, ensure_ascii=False)
    assert "杀主公" not in json.dumps(ws.messages, ensure_ascii=False)


def test_server_gate_blocks_cognitive_notes_even_if_engine_emitted_by_mistake(tmp_path):
    async def scenario():
        server = GameServer(history_path=tmp_path / "h.json")
        engine = make_engine(cheat=False)
        ws = Socket()
        attach(server, engine, "g1", ws)
        await engine.emit(ENGINE_EVENT.COGNITIVE_NOTES, round=1, players=[{"player_id": 1, "notes": []}])
        return ws

    assert OUTBOUND.COGNITIVE_NOTES not in run(scenario()).types()


def test_cheat_notes_are_not_in_state_snapshot_or_other_messages(tmp_path):
    async def scenario():
        server = GameServer(history_path=tmp_path / "h.json")
        engine = make_engine(NOTES_REPLY, cheat=True)
        ws = Socket()
        attach(server, engine, "g1", ws)
        p1 = players(engine)[1]
        p1.hand.append(Card("c1", "杀", "spade", 7, "basic"))
        await one_ai_turn(engine, p1)
        return ws

    ws = run(scenario())
    for message in ws.messages:
        if message["type"] != OUTBOUND.COGNITIVE_NOTES:
            assert "杀主公" not in json.dumps(message, ensure_ascii=False), message["type"]


def test_reconnect_resends_latest_notes_only_in_cheat_game(tmp_path):
    async def scenario(cheat):
        server = GameServer(history_path=tmp_path / f"h{cheat}.json")
        engine = make_engine(NOTES_REPLY, cheat=cheat)
        first = Socket()
        attach(server, engine, "g1", first)
        server.tasks["g1"] = asyncio.create_task(asyncio.sleep(30))
        p1 = players(engine)[1]
        p1.hand.append(Card("c1", "杀", "spade", 7, "basic"))
        await one_ai_turn(engine, p1)
        await server._detach(first)
        second = Socket()
        await server.do_resume(second, {"game_id": "g1", "profile_id": "local_t2"})
        server.tasks["g1"].cancel()
        return second

    cheat_ws = run(scenario(True))
    resent = [m for m in cheat_ws.messages if m["type"] == OUTBOUND.COGNITIVE_NOTES]
    assert len(resent) == 1
    assert next(r for r in resent[0]["players"] if r["player_id"] == 1)["notes"]
    plain_ws = run(scenario(False))
    assert OUTBOUND.COGNITIVE_NOTES not in plain_ws.types()
    assert "杀主公" not in json.dumps(plain_ws.messages, ensure_ascii=False)


def test_cheat_flag_is_frozen_at_game_start_and_no_inbound_can_change_it(tmp_path):
    engine = make_engine(cheat=False)
    engine.game_config["cheat_mode"] = True       # 开局后改配置无效：引擎已冻结标志
    assert engine.cheat_mode is False and engine.cheat_notes_payload() is None

    async def scenario():
        server = GameServer(history_path=tmp_path / "h.json")
        ws = Socket()
        attach(server, engine, "g1", ws)
        for data in ({"player_id": 1, "config": {"cheat_mode": True}, "cheat_mode": True},
                     {"cheat_mode": True}):
            await server.dispatch(ws, {"type": "update_ai_config", **data})
        await server.dispatch(ws, {"type": "set_cheat_mode", "cheat_mode": True})
        return ws

    ws = run(scenario())
    assert engine.cheat_mode is False and engine.cheat_notes_payload() is None
    assert OUTBOUND.COGNITIVE_NOTES not in ws.types()


# ───────────────────────── 局后日志 ─────────────────────────

def test_game_log_contains_notes_snapshots_even_in_non_cheat_game_and_no_key():
    engine = make_engine(NOTES_REPLY, cheat=False)
    p1 = players(engine)[1]
    p1.hand.append(Card("c1", "杀", "spade", 7, "basic"))
    run(one_ai_turn(engine, p1))
    engine.notes.snapshot(engine.game_state.round_number)
    log = build_game_log(engine, {"winner": "lord", "message": "x"}, include_thinking=True)
    assert log["options"]["cheat_mode"] is False
    snaps = log["cognitive_notes"]
    mine = next(s for s in snaps if s["player_id"] == 1)
    assert mine["notes"]["3"]["guess"] == "rebel" and mine["notes"]["1"]["locked"] is True
    assert KEY not in json.dumps(log, ensure_ascii=False)
    json.dumps(log)       # 可序列化


def test_game_log_notes_field_is_empty_list_when_no_model_ai():
    engine = make_engine(keyed=False)
    assert build_game_log(engine, {"winner": "lord"}, include_thinking=True)["cognitive_notes"] == []


# ───────────────────────── 模块自身 ─────────────────────────

def test_client_payload_lists_only_owners_and_marks_frozen():
    engine = make_engine()
    engine.notes.update(1, {"3": note()})
    engine.notes.ensure(2)
    owner = players(engine)[2]
    owner.alive = False
    engine.on_player_death(owner)
    payload = engine.notes.client_payload({1: "理由", 2: "遗言"})
    by_id = {r["player_id"]: r for r in payload["players"]}
    assert sorted(by_id) == [1, 2]
    assert by_id[2]["frozen"] is True and by_id[1]["frozen"] is False
    assert by_id[1]["reason"] == "理由"


def test_notes_module_is_independent_of_ai_decision_session_state():
    engine = make_engine()
    assert isinstance(engine.notes, CognitiveNotes)
    assert not hasattr(AIDecision, "_notes") and not hasattr(engine.ai_decision, "_notes")


def test_cheat_game_pushes_notes_immediately_when_an_ai_dies_with_frozen_flag(tmp_path):
    async def scenario(cheat):
        server = GameServer(history_path=tmp_path / f"h{cheat}.json")
        engine = make_engine(cheat=cheat)
        ws = Socket()
        attach(server, engine, "g1", ws)
        engine.notes.update(1, {"3": note("rebel", "高", "杀主公")})
        victim = players(engine)[1]
        victim.hp = 0
        engine.card_system.responder = None
        await engine.card_system.enter_dying(victim)
        return ws

    ws = run(scenario(True))
    sent = [m for m in ws.messages if m["type"] == OUTBOUND.COGNITIVE_NOTES]
    assert sent, "作弊局 AI 阵亡应立刻推送笔记"
    row = next(r for r in sent[-1]["players"] if r["player_id"] == 1)
    assert row["frozen"] is True and any(n["seat"] == 3 and n["why"] == "杀主公" for n in row["notes"])
    plain = run(scenario(False))
    assert OUTBOUND.COGNITIVE_NOTES not in plain.types() and "杀主公" not in json.dumps(plain.messages, ensure_ascii=False)
