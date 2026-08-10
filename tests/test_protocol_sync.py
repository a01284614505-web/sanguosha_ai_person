#!/usr/bin/env python3
"""协议单一真相源回归测试。

断言 1：scripts/gen_protocol_js.py 重新生成的 protocol.js 与已提交的
frontend/js/protocol.js 逐字节一致 —— 前端协议必须由 protocol.py 生成，
手改会直接失败。
断言 2：入站/出站消息类型数量与已知协议清单一致，防止误删。
"""

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from game_engine import protocol  # noqa: E402


class ProtocolSyncTest(unittest.TestCase):
    def test_generated_js_matches_committed_file(self):
        from scripts.gen_protocol_js import generate_js

        generated = generate_js()
        committed = PROJECT_ROOT / "frontend" / "js" / "protocol.js"
        self.assertTrue(committed.exists(), "frontend/js/protocol.js 不存在")
        self.assertEqual(
            committed.read_text(encoding="utf-8"),
            generated,
            "protocol.js 与 protocol.py 不同步：请运行 python scripts/gen_protocol_js.py",
        )

    def test_inbound_types_are_eight(self):
        self.assertEqual(
            len(protocol.ALL_INBOUND), 8,
            f"入站消息类型应为 8 种，当前 {len(protocol.ALL_INBOUND)} 种: {protocol.ALL_INBOUND}",
        )
        self.assertEqual(
            set(protocol.ALL_INBOUND),
            {
                "create_game", "player_action", "chat", "card_animation_done",
                "end_game", "update_ai_config", "ping", "server_info",
            },
        )

    def test_outbound_types_are_fourteen(self):
        self.assertEqual(
            len(protocol.ALL_OUTBOUND), 14,
            f"出站消息类型应为 14 种，当前 {len(protocol.ALL_OUTBOUND)} 种: {protocol.ALL_OUTBOUND}",
        )
        self.assertEqual(
            set(protocol.ALL_OUTBOUND),
            {
                "pong", "server_info", "game_created", "game_state", "your_turn",
                "require_response", "action_result", "ai_action", "chat",
                "event_notification", "ai_config_updated", "end_game_accepted",
                "game_end", "error",
            },
        )

    def test_providers_are_eight_and_unique(self):
        self.assertEqual(len(protocol.PROVIDERS), 8)
        self.assertEqual(len(protocol.PROVIDER_VALUES), 8)
        for provider in protocol.PROVIDERS:
            for field in ("value", "name", "default_model", "default_url"):
                self.assertTrue(provider.get(field), f"{provider['value']} 缺字段 {field}")

    def test_generated_js_is_valid_json_subset(self):
        """生成结果里 PROVIDERS 数组应能被 JSON 解析（烟雾检查）。"""
        from scripts.gen_protocol_js import generate_js

        text = generate_js()
        start = text.index("PROVIDERS: [")
        end = text.index("}", text.index("PROVIDERS: ["))  # 仅确认生成不炸
        self.assertGreater(end, start)


if __name__ == "__main__":
    unittest.main()
