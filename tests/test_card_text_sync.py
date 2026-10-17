"""引擎 CARD_TEXT 与前端 card_info.js 的牌面文字逐字一致，且覆盖牌表全部 42 种牌名。"""

import json
import re
from pathlib import Path

from game_engine.card_table import CARD_TABLE
from game_engine.card_text import CARD_TEXT

ROOT = Path(__file__).resolve().parents[1]


def _frontend_card_info():
    js = (ROOT / "frontend" / "js" / "card_info.js").read_text(encoding="utf-8")
    consts = dict(re.findall(r"const (HORSE_\w+) = '([^']*)';", js))
    pattern = re.compile(
        r"'([^']+)': \{ type: '([^']+)'(?:, range: \d+)?(?:, horse: '[^']+')?, "
        r"text: (?:'([^']*)'|(HORSE_\w+)) \}")
    return {name: (kind, consts[const] if const else text)
            for name, kind, text, const in pattern.findall(js)}


def test_card_text_covers_every_card_in_the_table():
    assert set(CARD_TEXT) == set(CARD_TABLE)


def test_card_text_matches_frontend_card_info_exactly():
    assert _frontend_card_info() == CARD_TEXT


def test_no_equipment_is_marked_unimplemented_in_frontend():
    js = (ROOT / "frontend" / "js" / "card_info.js").read_text(encoding="utf-8")
    assert "pending: true" not in js


def test_settings_manifest_reports_card_kinds():
    manifest = json.loads((ROOT / "frontend" / "system_manifest.json").read_text(encoding="utf-8"))
    assert manifest["card_kinds"] == len(CARD_TABLE)


def test_ai_global_rules_list_all_card_kinds_once():
    from game_engine import MainEngine
    engine = MainEngine({"mode": "5人身份局", "player_name": "P",
                         "ais": [{"name": f"AI{i}"} for i in range(4)]})
    text = engine.ai_decision.worldbook_manager.build_global_rules()
    for name in CARD_TABLE:
        assert text.count(f"- 【{name}】") == 1, name
    assert "（范围5）" in text  # 麒麟弓攻击范围
    assert "杀死反贼后摸3张牌" in text
