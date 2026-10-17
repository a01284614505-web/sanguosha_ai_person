"""拉取模型列表：各服务商请求格式、错误提示、Key 不外泄，以及局内沿用已保存 Key。"""

import io
import json
import types

import httpx
import pytest

import game_server
from game_engine.card_table import CARD_TABLE
from game_engine.model_catalog import ModelListError, list_models, parse_models


def _transport(handler):
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    return httpx.MockTransport(wrapped), seen


def test_openai_compatible_lists_sorted_unique_ids_with_bearer_key():
    transport, seen = _transport(lambda r: httpx.Response(200, json={
        "data": [{"id": "deepseek-reasoner"}, {"id": "deepseek-chat"}, {"id": "deepseek-chat"}]}))
    result = list_models("deepseek", "", "sk-test", transport=transport)
    assert result["models"] == ["deepseek-chat", "deepseek-reasoner"]
    assert str(seen[0].url) == "https://api.deepseek.com/v1/models"
    assert seen[0].headers["Authorization"] == "Bearer sk-test"


def test_chat_completions_suffix_in_custom_url_is_stripped():
    transport, seen = _transport(lambda r: httpx.Response(200, json={"data": [{"id": "m1"}]}))
    list_models("openai", "https://relay.example.com/v1/chat/completions/", "k", transport=transport)
    assert str(seen[0].url) == "https://relay.example.com/v1/models"


def test_claude_uses_anthropic_headers():
    transport, seen = _transport(lambda r: httpx.Response(200, json={"data": [{"id": "claude-x"}]}))
    assert list_models("claude", "", "ak", transport=transport)["models"] == ["claude-x"]
    assert seen[0].headers["x-api-key"] == "ak"
    assert seen[0].headers["anthropic-version"]


def test_gemini_native_keeps_only_generate_content_models_without_prefix():
    payload = {"models": [
        {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
    ]}
    transport, seen = _transport(lambda r: httpx.Response(200, json=payload))
    assert list_models("gemini", "", "gk", transport=transport)["models"] == ["gemini-2.5-flash"]
    assert seen[0].headers["x-goog-api-key"] == "gk"
    assert "key=" not in str(seen[0].url)


def test_gemini_openai_compatible_url_is_treated_as_openai():
    transport, seen = _transport(lambda r: httpx.Response(200, json={"data": [{"id": "models/gemini-2.5-pro"}]}))
    list_models("gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "gk", transport=transport)
    assert seen[0].headers["Authorization"] == "Bearer gk"


@pytest.mark.parametrize("status, text", [(401, "Key 无效"), (404, "不支持拉取"), (500, "HTTP 500")])
def test_http_errors_become_readable_messages_without_the_key(status, text):
    transport, _ = _transport(lambda r: httpx.Response(status, text="secret sk-leak"))
    with pytest.raises(ModelListError) as info:
        list_models("openai", "", "sk-leak", transport=transport)
    assert text in str(info.value)
    assert "sk-leak" not in str(info.value)


def test_missing_key_bad_scheme_and_non_json_are_rejected():
    with pytest.raises(ModelListError, match="API Key"):
        list_models("openai", "", "  ")
    with pytest.raises(ModelListError, match="http"):
        list_models("openai", "file:///etc/passwd", "k")
    transport, _ = _transport(lambda r: httpx.Response(200, text="<html>"))
    with pytest.raises(ModelListError, match="JSON"):
        list_models("openai", "", "k", transport=transport)


def test_redirects_are_not_followed():
    transport, seen = _transport(lambda r: httpx.Response(302, headers={"Location": "http://127.0.0.1/admin"}))
    with pytest.raises(ModelListError):
        list_models("openai", "", "k", transport=transport)
    assert len(seen) == 1


def test_parse_models_accepts_bare_lists():
    assert parse_models(["b", "a", ""], "openai") == ["a", "b"]


def _handler(body):
    raw = json.dumps(body).encode()
    handler = game_server.CustomHandler.__new__(game_server.CustomHandler)
    handler.headers = {"Content-Length": str(len(raw))}
    handler.rfile = io.BytesIO(raw)
    sent = {}
    handler._send_json = lambda status, payload: sent.update(status=status, payload=payload)
    return handler, sent


def _fake_server(api_key="saved-key", profile="p1"):
    player = types.SimpleNamespace(id=2, is_ai=True, ai_config={"api_key": api_key})
    engine = types.SimpleNamespace(game_config={"profile_id": profile},
                                   game_state=types.SimpleNamespace(players=[player]))
    return types.SimpleNamespace(engines={"g1": engine})


def test_in_game_blank_key_reuses_saved_key_only_for_matching_profile(monkeypatch):
    calls = []
    monkeypatch.setattr(game_server, "list_models",
                        lambda provider, url, key: calls.append(key) or {"models": ["m"], "base_url": "u"})
    monkeypatch.setattr(game_server, "ACTIVE_SERVER", _fake_server())
    handler, sent = _handler({"provider": "deepseek", "api_key": "", "game_id": "g1",
                              "profile_id": "p1", "player_id": 2})
    handler._handle_list_models()
    assert calls == ["saved-key"] and sent["payload"]["models"] == ["m"]
    assert "saved-key" not in json.dumps(sent["payload"])

    handler, sent = _handler({"provider": "deepseek", "api_key": "", "game_id": "g1",
                              "profile_id": "someone-else", "player_id": 2})
    handler._handle_list_models()
    assert calls[-1] == ""


def test_endpoint_reports_failure_as_message(monkeypatch):
    def boom(*_):
        raise ModelListError("API Key 无效或没有权限（HTTP 401）")
    monkeypatch.setattr(game_server, "list_models", boom)
    handler, sent = _handler({"provider": "openai", "api_key": "k"})
    handler._handle_list_models()
    assert sent["payload"] == {"success": False, "message": "API Key 无效或没有权限（HTTP 401）"}


def test_hualiu_is_a_plus_one_horse():
    assert CARD_TABLE["骅骝"].equipment_slot == "plus_horse"
