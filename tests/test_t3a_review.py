"""Stage T · T3a 验收补充测试（验收代理编写，不改运行代码）。

补的是 test_t3a_chat_director.py 没有直接覆盖的点：
- 对局结束（run() 收尾、request_end_game）后没有调度器遗留任务；
- 聊天与决策并发时会话消息顺序不被破坏；
- 聊天临时尾巴只含公开信息 + 该 AI 自己的笔记 / 手牌（抓发给假网关的全文核对）；
- 聊天超时默认 15 秒；update_settings 对更多非 chat_level 字段一律拒绝。

暴露运行代码缺陷的用例标 xfail(strict=True)，不修运行代码。
"""

import asyncio

import pytest

import game_server
from game_engine.chat_director import ChatDirector, REQUEST_TIMEOUT
from game_engine.state_manager import Card

from tests.test_t3a_chat_director import (
    FakeGateway, make_engine, run, seats, settle, _speak,
)


def _director_tasks():
    """当前事件循环里属于聊天调度器的协程任务。"""
    current = asyncio.current_task()
    found = []
    for task in asyncio.all_tasks():
        if task is current:
            continue
        qualname = getattr(task.get_coro(), "__qualname__", "")
        if "ChatDirector" in qualname or qualname.startswith("ChatDirector"):
            found.append(qualname)
    return found


# ---------- 1. 对局结束后无遗留调度器任务 ----------

def test_run_ending_by_request_end_game_leaves_no_director_task_behind():
    """跑真的 engine.run()：回合中有聊天在途，回合里发起 request_end_game，run() 收尾后不应留下任何调度器任务。"""
    engine, clock, gateway = make_engine("lively", keyed=(1, 2, 3), gateway=FakeGateway(delay=5.0))
    leftovers = {}

    async def fake_turn(player):
        await engine.submit_chat(0, "开打吧")
        await settle()
        assert engine.chat_director.pending_tasks, "前提：回合结束前应有聊天在途"
        await engine.request_end_game()

    engine._human_turn = fake_turn
    engine._ai_turn = fake_turn

    async def scenario():
        winner = await asyncio.wait_for(engine.run(), timeout=20)
        await settle(0.05)                 # 让取消真正生效（cancel 之后任务要再跑一轮才结束）
        leftovers["tasks"] = _director_tasks()
        leftovers["pending"] = list(engine.chat_director.pending_tasks)
        leftovers["watcher"] = engine.chat_director._watcher
        return winner

    winner = run(scenario())
    assert winner == "aborted"
    assert leftovers["tasks"] == [], f"对局结束后仍有调度器任务: {leftovers['tasks']}"
    assert leftovers["pending"] == []
    assert leftovers["watcher"] is None


def test_request_end_game_cancels_inflight_chat_immediately():
    engine, clock, gateway = make_engine("lively", keyed=(1, 2, 3), gateway=FakeGateway(delay=5.0))

    async def scenario():
        await engine.submit_chat(0, "你们呢")
        await settle()
        assert engine.chat_director.pending_tasks, "前提：聊天在途"
        await engine.request_end_game()
        await settle()
        return list(engine.chat_director.pending_tasks)

    assert run(scenario()) == []


def test_idle_watchdog_abort_cancels_inflight_chat_immediately():
    engine, clock, gateway = make_engine("lively", keyed=(1, 2, 3), gateway=FakeGateway(delay=5.0))
    engine.idle_abort_seconds = 60

    async def scenario():
        await engine.submit_chat(0, "你们呢")
        await settle()
        assert engine.chat_director.pending_tasks, "前提：聊天在途"
        engine._human_idle_since = clock()          # 真人开始离席计时
        clock.t += 120                              # 离席超过 idle_abort_seconds
        assert await engine._check_idle_timeout() is True
        await settle()
        return list(engine.chat_director.pending_tasks), engine.game_state.winner

    pending, winner = run(scenario())
    assert winner == "aborted"
    assert pending == []


# ---------- 2. 聊天与决策并发：会话消息顺序不被破坏 ----------

class SplitGateway:
    """聊天请求慢、决策请求快；记录每个请求发出时的消息尾。"""

    def __init__(self, chat_delay=0.3, decision_delay=0.02):
        self.chat_delay, self.decision_delay = chat_delay, decision_delay
        self.calls = []
        self.chat_calls = 0
        self.decision_calls = 0

    async def call_ai(self, **kwargs):
        self.calls.append(kwargs)
        if "【聊天回合】" in kwargs["messages"][-1]["content"]:
            self.chat_calls += 1
            await asyncio.sleep(self.chat_delay)
            return '{"say": "别急"}', {"prompt_tokens": 10, "cached_tokens": 0, "completion_tokens": 3}
        self.decision_calls += 1
        await asyncio.sleep(self.decision_delay)
        return '{"action_index": 0}', {"prompt_tokens": 10, "cached_tokens": 0, "completion_tokens": 3}


def test_concurrent_chat_and_decisions_keep_session_pairs_in_order():
    engine, clock, _ = make_engine("lively", keyed=(1, 2, 3))
    gateway = SplitGateway()
    engine.chat_director.gateway = gateway
    engine.ai_decision.gateway = gateway
    ais = [seats(engine)[i] for i in (1, 2, 3)]

    async def scenario():
        await engine.submit_chat(0, "谁先出手？")          # 启动 2 个聊天（在途，较慢）
        await asyncio.sleep(0)                           # 让聊天任务开始
        async def decide_twice(ai):
            # 同一座位的决策是顺序的（引擎回合制）；不同座位之间并发。
            for n in range(2):
                await engine.ai_decision._call_with_session(ai, "decision", f"局势{ai.id}-{n}")

        await asyncio.gather(*(decide_twice(ai) for ai in ais))
        await settle(0.5)

    run(scenario())
    assert gateway.chat_calls >= 1 and gateway.decision_calls == 6

    for ai in ais:
        messages = engine.ai_decision.get_session(ai)["messages"]
        assert all("【聊天回合】" not in m["content"] for m in messages), "聊天尾巴写进了会话"
        roles = [m["role"] for m in messages if m["role"] != "system"]   # 跳过 L0/L1 系统前缀
        assert roles and roles[0] == "user" and set(roles) <= {"user", "assistant"}
        # 决策写入的是「用户局势 → 助手回复」成对的顺序：每条 assistant 前一条必是 user
        for index, role in enumerate(roles):
            if role == "assistant":
                assert index > 0 and roles[index - 1] == "user"
        assert roles.count("assistant") == 2 and len(roles) == 4


# ---------- 3. 聊天临时尾巴的信息边界（抓发给假网关的全文） ----------

def test_chat_tail_carries_only_public_facts_and_the_speakers_own_notes_and_hand():
    engine, clock, gateway = make_engine("normal", keyed=(1, 2, 3))
    speaker, other, third = seats(engine)[1], seats(engine)[2], seats(engine)[3]

    # 别人的隐藏身份、别人的手牌、别人的笔记都是「只有自己知道」的信息
    other.identity, other.identity_revealed = "spy", False            # 内奸（未揭示）
    other.hand = [Card(id="x1", name="藤甲", suit="spade", rank=2, card_type="equipment")]
    third.identity, third.identity_revealed = "rebel", False
    engine.notes.update(speaker.id, {"4": {"guess": "rebel", "conf": "高", "why": "SPEAKER_WHY"}})
    engine.notes.update(other.id, {"4": {"guess": "loyalist", "conf": "高", "why": "OTHER_WHY_TOKEN"}})

    reason_speaker = engine.chat_director.idle_reason(speaker)
    reason_other = engine.chat_director.idle_reason(other)
    assert reason_speaker and "4号" in reason_speaker and "反贼" in reason_speaker
    assert reason_other and "忠臣" in reason_other

    async def scenario():
        await engine.chat_director.run_chat_turn(speaker, reason_speaker)
        await engine.chat_director.run_chat_turn(other, reason_other)

    run(scenario())
    speaker_tail = gateway.calls[0]["messages"][-1]["content"]
    other_tail = gateway.calls[1]["messages"][-1]["content"]

    # 发言者自己的笔记：允许出现在它自己的尾巴里
    assert "你高把握怀疑4号是反贼" in speaker_tail
    # 别人的笔记、别人的隐藏身份、别人的手牌、别人对 4 号的判断：一律不出现
    for leak in ("OTHER_WHY_TOKEN", "SPEAKER_WHY", "内奸", "藤甲", "忠臣"):
        assert leak not in speaker_tail, f"发言者尾巴泄露了 {leak!r}"
    # 反过来：其他 AI 的尾巴里只有它自己的笔记
    assert "你高把握怀疑4号是忠臣" in other_tail
    for leak in ("SPEAKER_WHY", "OTHER_WHY_TOKEN", "内奸", "藤甲", "反贼"):
        assert leak not in other_tail, f"另一个 AI 的尾巴泄露了 {leak!r}"
    # 手牌与身份不随任何尾巴进入
    assert "藤甲" not in speaker_tail


def test_chat_tails_never_carry_another_seats_hand():
    engine, clock, gateway = make_engine("lively", keyed=(1, 2))
    other = seats(engine)[2]
    other.hand = [Card(id="x2", name="诸葛连弩", suit="club", rank=12, card_type="equipment")]

    run(_speak(engine, "你们手上有什么？"))
    for call in gateway.calls:
        assert "诸葛连弩" not in call["messages"][-1]["content"]


# ---------- 4. 成本闸门：默认参数 ----------

def test_chat_request_timeout_defaults_to_fifteen_seconds():
    engine, _, _ = make_engine()
    assert REQUEST_TIMEOUT == 15.0
    assert ChatDirector(engine).request_timeout == 15.0


# ---------- 5. update_settings 只放行 chat_level（更多字段） ----------

@pytest.mark.parametrize("key", [
    "max_turns", "human_action_timeout", "phase_delay", "turn_delay", "chat", "chat_enabled",
    "spectator", "spectator_mode", "deck_id", "ais", "player_name", "mode", "hide_dead_identity",
])
def test_update_settings_rejects_every_field_other_than_chat_level(key):
    engine, _, _ = make_engine()
    with pytest.raises(ValueError):
        engine.update_settings({key: 1})
    with pytest.raises(ValueError):
        engine.update_settings({"chat_level": "lively", key: 1})
    assert engine.chat_level == "normal"


def test_server_update_settings_refuses_chat_switch_and_cheat_toggle_together():
    engine, _, _ = make_engine()
    ws = _FakeWS()
    server = game_server.GameServer.__new__(game_server.GameServer)
    server.engine_for = lambda _ws: engine
    sent = []

    async def capture(ws_, message):
        sent.append(message)

    async def send_error(ws_, text):
        sent.append({"type": "error", "message": text})

    server.send = capture
    server.send_error = send_error
    run(server.do_update_settings(ws, {"settings": {"chat_level": "quiet", "cheat_mode": True}}))
    assert engine.chat_level == "normal"
    assert engine.cheat_mode is False
    assert sent and sent[-1]["type"] == "error"


class _FakeWS:
    pass
