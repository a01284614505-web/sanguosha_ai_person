"""Exercise the OpenAI-compatible HTTP boundary with a local response server."""

import asyncio
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

from game_engine.ai_decision import AIGateway


class _CompletionHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.received.append((self.path, self.headers.get("Authorization"), payload))
        if payload["model"] == "timeout":
            time.sleep(0.2)
        if payload["model"] == "error":
            self.send_response(503)
            self.end_headers()
            return
        body = json.dumps({
            "choices": [{"message": {"content": '{"option_index": 0, "reasoning": "公开理由"}'}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7,
                      "prompt_tokens_details": {"cached_tokens": 3}},
        }).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_args):
        pass


class GatewayHTTPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _CompletionHandler)
        cls.server.received = []
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=1)

    def call(self, model, timeout=1):
        return asyncio.run(AIGateway(timeout=timeout).call_ai(
            provider="openai", model=model, api_key="local_test_key",
            messages=[{"role": "user", "content": "choose"}],
            base_url=self.base_url, return_usage=True,
        ))

    def test_success_returns_public_content_and_measured_tokens(self):
        content, usage = self.call("success")
        self.assertIn("公开理由", content)
        self.assertEqual(usage, {"prompt_tokens": 11, "cached_tokens": 3,
                                 "completion_tokens": 7})
        path, auth, payload = self.server.received[-1]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(auth, "Bearer local_test_key")
        self.assertEqual(payload["messages"][0]["content"], "choose")

    def test_http_error_reaches_model_fallback_boundary(self):
        with self.assertRaises(httpx.HTTPStatusError):
            self.call("error")

    def test_timeout_reaches_model_fallback_boundary(self):
        with self.assertRaises(httpx.TimeoutException):
            self.call("timeout", timeout=0.02)
