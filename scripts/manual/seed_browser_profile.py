"""预置一个唯一命名的本地浏览器验收档案（两场胜利，触发连胜奖励；档案另有见面礼，共 >=2 张身份卡）。
用法：SANGUOSHA_HISTORY_PATH=<隔离路径> python3 scripts/manual/seed_browser_profile.py <档案ID>"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from game_engine.game_history import GameHistoryStore
from game_server import HISTORY_PATH

if not os.environ.get("SANGUOSHA_HISTORY_PATH"):
    raise SystemExit("Refusing to seed default runtime history; set SANGUOSHA_HISTORY_PATH to an isolated temporary file")
profile_id = sys.argv[1]
store = GameHistoryStore(HISTORY_PATH)
payload = {"winner": "lord", "duration": 1, "state": {"players": [
    {"is_ai": False, "identity": "lord", "hero_name": "验收测试", "stats": {}}
]}}
store.record_result(profile_id, profile_id + "_win1", payload)
store.record_result(profile_id, profile_id + "_win2", payload)
assert store.profile(profile_id)["identity_cards"] >= 1
print(profile_id)
