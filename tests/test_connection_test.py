"""连接测试应调用对局同一聊天接口，且不回传密钥或供应商响应正文。"""

import io
import json

import httpx

import game_server
from game_engine.ai_decision import _failure_label


def handler_for(body):
    raw = json.dumps(body).encode()
    handler = game_server.CustomHandler.__new__(game_server.CustomHandler)
    handler.headers = {"Content-Length": str(len(raw))}
    handler.rfile = io.BytesIO(raw)
    handler._saved_ai_key = lambda _: ""
    sent = {}
    handler._send_json = lambda status, payload: sent.update(status=status, payload=payload)
    return handler, sent


def test_connection_test_uses_game_gateway_and_hides_key(monkeypatch):
    calls = []

    async def fake_call(self, **kwargs):
        calls.append(kwargs)
        return "OK"

    monkeypatch.setattr(game_server.AIGateway, "call_ai", fake_call)
    handler, sent = handler_for({"provider": "openai", "model": "gpt-test", "api_key": "sk-secret-value",
                                 "api_url": "https://relay.example.com/v1"})
    handler._handle_connection_test()
    assert sent["payload"]["success"] is True
    assert calls[0]["model"] == "gpt-test"
    assert calls[0]["base_url"] == "https://relay.example.com/v1"
    assert calls[0]["api_key"] == "sk-secret-value"
    assert "sk-secret-value" not in json.dumps(sent)


def test_connection_test_reports_http_status_without_response_or_key(monkeypatch):
    async def fake_call(self, **kwargs):
        request = httpx.Request("POST", "https://relay.example.com/v1/chat/completions")
        response = httpx.Response(401, request=request, text="sk-secret-value denied")
        raise httpx.HTTPStatusError("sk-secret-value denied", request=request, response=response)

    monkeypatch.setattr(game_server.AIGateway, "call_ai", fake_call)
    handler, sent = handler_for({"provider": "openai", "model": "gpt-test", "api_key": "sk-secret-value"})
    handler._handle_connection_test()
    assert sent["payload"] == {"success": False, "message": "Key 无效或没有权限（HTTP 401）"}


def test_connection_test_requires_key_and_model():
    handler, sent = handler_for({"model": "gpt-test", "api_key": ""})
    handler._handle_connection_test()
    assert sent["payload"]["success"] is False
    assert "API Key" in sent["payload"]["message"]


def test_model_failure_keeps_http_status_without_provider_body():
    request = httpx.Request("POST", "https://relay.example.com/v1/chat/completions")
    response = httpx.Response(403, request=request, text="sk-secret-value denied")
    error = httpx.HTTPStatusError("sk-secret-value denied", request=request, response=response)
    assert _failure_label(error) == "HTTP 403"
