import asyncio
import json
import logging
import pytest

from game_engine.chat_facts import contradiction
from game_engine.game_logs import build_game_log
from game_engine.protocol import ENGINE_EVENT
from test_ai_smart_p0 import make_engine


def test_decision_chat_is_absent_from_contract_and_ignored_on_both_paths():
    e = make_engine()
    ai, p = e.ai_decision, e.game_state.players[1]
    prompt = ai.build_decision_turn_message(p, [{"type": "end_phase"}])
    assert "chat_message" not in prompt
    decision = ai.parse_ai_response('{"action_index":0,"chat_message":"我是内奸"}', p, [{"type": "end_phase"}])
    assert "chat" not in decision
    request = {"options": [{"label": "不响应"}]}
    assert "chat_message" not in ai.build_response_prompt(p, request)
    assert ai.parse_response_choice('{"option_index":0,"chat_message":"打出闪"}', p, request) == 0
    assert not hasattr(ai, "last_chat")
    assert not e.table_chat


@pytest.mark.parametrize("text", ["4号对1号杀了两次", "4号杀过1号两次", "4号杀过主公两次"])
def test_fact_check_uses_canonical_seats_and_only_public_ledger(text):
    e = make_engine()
    e.ledger.record(1, 0, 2, "hostile", "杀")
    conflict = contradiction(text, e.game_state, e.ledger)
    assert conflict["actual"] == 1 and conflict["claimed"] == 2
    assert conflict["ledger_sequences"] == [1]


@pytest.mark.parametrize("text", ["4号对1号杀过一次", "4号对1号杀过零次吗？", "我有桃", "我是忠臣",
    "如果4号对1号杀了两次", "如果，4号对1号杀了两次", "听说4号对1号杀了两次",
    "他说“4号对1号杀了两次”", "这轮，4号对1号杀了两次", "你们看着办吧"])
def test_hidden_information_hypotheses_quotes_and_unrecognized_speech_pass(text):
    e = make_engine()
    e.ledger.record(1, 0, 2, "hostile", "杀")
    assert contradiction(text, e.game_state, e.ledger) is None


def test_block_is_private_logged_and_corrected_once_next_chat(caplog):
    e = make_engine()
    p = e.game_state.players[1]
    events = []
    async def collect(**data):
        events.append(data)
    e.on(ENGINE_EVENT.CHAT, collect)
    e.on(ENGINE_EVENT.CHAT_REJECTED, collect)
    with caplog.at_level(logging.WARNING):
        assert asyncio.run(e._record_ai_chat(p, "4号对1号杀了两次")) is None
    assert events == [] and not e.chat_log and not e.table_chat
    assert "发言被拦截" in caplog.text and "账本记录0次" in caplog.text
    assert e.blocked_chat[0]["seat"] == 5
    prompt = e.chat_director.build_tail(p, "复核")
    assert "你上一句因与引擎记录矛盾未发出" in prompt
    assert "你上一句因与引擎记录矛盾未发出" not in e.chat_director.build_tail(p, "下一句")
    assert '"intent"' in prompt and prompt.index('"intent"') < prompt.index('"say"')
    assert "全桌" in prompt and "跳假身份" in prompt and "不能歪曲公开事实" in prompt
    record = build_game_log(e, {}, include_thinking=False)
    assert record["blocked_chat"][0]["actual"] == 0
    assert asyncio.run(e._record_ai_chat(p, "我有桃")) is not None
    assert len(events) == 1 and "free" not in events[0]


def test_cheat_game_rejection_is_a_separate_event_without_chat_bubble():
    e = make_engine()
    e.cheat_mode = True
    events, chats = [], []
    async def reject(**data): events.append(data)
    async def chat(**data): chats.append(data)
    e.on(ENGINE_EVENT.CHAT_REJECTED, reject)
    e.on(ENGINE_EVENT.CHAT, chat)
    asyncio.run(e._record_ai_chat(e.game_state.players[1], "4号对1号拆了三次"))
    assert len(events) == 1 and chats == []
