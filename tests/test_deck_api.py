#!/usr/bin/env python3
"""牌堆切换 API 与开局配置校验的回归测试。

真实启动一个 HTTPServer（随机端口），走完整 HTTP 请求，不做 mock。
测试会写 data/deck_settings.json，结束时恢复原始内容。
"""

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

from game_engine import MainEngine
from game_engine.deck_manager import DECKS, DeckManager
from game_server import CustomHandler

SETTINGS_PATH = PROJECT_ROOT / "data" / "deck_settings.json"


class QuietHandler(CustomHandler):
    def log_message(self, *args):
        pass


class DeckApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_settings = (
            SETTINGS_PATH.read_text(encoding="utf-8") if SETTINGS_PATH.exists() else None
        )
        cls.server = HTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        if cls.original_settings is None:
            if SETTINGS_PATH.exists():
                SETTINGS_PATH.unlink()
        else:
            SETTINGS_PATH.write_text(cls.original_settings, encoding="utf-8")

    def request(self, path, payload=None):
        url = self.base_url + path
        if payload is None:
            request = urllib.request.Request(url)
        else:
            request = urllib.request.Request(
                url,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_deck_list_matches_registry(self):
        status, data = self.request("/api/decks")
        self.assertEqual(status, 200)
        self.assertTrue(data["success"])
        listed = {deck["id"]: deck["cards_count"] for deck in data["decks"]}
        self.assertEqual(listed, {"standard": 108, "extra": 53, "combined": 161})
        self.assertIn(data["active_deck"], DECKS)
        print(f"GET /api/decks -> {listed}, active={data['active_deck']}")

    def test_switch_persists_and_loads_real_cards(self):
        for deck_id, expected_count in (("extra", 53), ("combined", 161), ("standard", 108)):
            with self.subTest(deck_id=deck_id):
                status, data = self.request("/api/switch_deck", {"deck_id": deck_id})
                self.assertEqual(status, 200)
                self.assertTrue(data["success"])
                self.assertEqual(data["active_deck"], deck_id)
                self.assertEqual(data["deck"]["cards_count"], expected_count)

                saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                self.assertEqual(saved["active_deck"], deck_id)

                _, listed = self.request("/api/decks")
                self.assertEqual(listed["active_deck"], deck_id)

                cards = DeckManager(PROJECT_ROOT).load_deck_cards()
                self.assertEqual(len(cards), expected_count)
                print(f"POST switch_deck {deck_id} -> 持久化并加载 {len(cards)} 张")

    def test_legacy_ids_switch_to_standard(self):
        for legacy in ("test_deck", "complete_deck"):
            with self.subTest(legacy=legacy):
                status, data = self.request("/api/switch_deck", {"deck_id": legacy})
                self.assertEqual(status, 200)
                self.assertEqual(data["active_deck"], "standard")

    def test_unknown_deck_is_rejected_without_changing_default(self):
        self.request("/api/switch_deck", {"deck_id": "standard"})
        status, data = self.request("/api/switch_deck", {"deck_id": "no_such_deck"})
        self.assertEqual(status, 400)
        self.assertFalse(data["success"])
        self.assertEqual(data["active_deck"], "standard")
        saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(saved["active_deck"], "standard")

    def test_missing_deck_id_falls_back_to_default(self):
        status, data = self.request("/api/switch_deck", {})
        self.assertEqual(status, 200)
        self.assertEqual(data["active_deck"], "standard")

    def test_static_files_still_served(self):
        with urllib.request.urlopen(self.base_url + "/settings.html", timeout=10) as response:
            self.assertEqual(response.status, 200)
            body = response.read().decode("utf-8")
        self.assertIn("/api/decks", body)
        self.assertNotIn('value="test_deck"', body)


class ConfigDeckTest(unittest.TestCase):
    def setUp(self):
        self.raw_config = {
            "mode": "5人身份局",
            "player_name": "测试玩家",
            "ais": [{"name": f"AI{i}"} for i in range(1, 5)],
        }

    def test_legacy_deck_id_normalized_into_config(self):
        cfg = MainEngine.normalize_config({**self.raw_config, "deck_id": "complete_deck"})
        self.assertEqual(cfg["deck_id"], "standard")

    def test_valid_deck_id_passthrough(self):
        cfg = MainEngine.normalize_config({**self.raw_config, "deck_id": "combined"})
        self.assertEqual(cfg["deck_id"], "combined")

    def test_absent_deck_id_left_to_server_default(self):
        cfg = MainEngine.normalize_config(dict(self.raw_config))
        self.assertNotIn("deck_id", cfg)

    def test_unknown_deck_id_rejected_at_create(self):
        with self.assertRaises(ValueError):
            MainEngine.normalize_config({**self.raw_config, "deck_id": "no_such_deck"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
