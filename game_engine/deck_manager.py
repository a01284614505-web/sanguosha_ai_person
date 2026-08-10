#!/usr/bin/env python3
"""牌堆管理器：加载、校验和切换标准/军争牌堆。"""

import json
from copy import deepcopy
from pathlib import Path
from typing import Dict, List


DECKS = {
    "standard": {
        "id": "standard",
        "name": "标准牌堆",
        "description": "noname 标准 108 张牌",
        "cards_count": 108,
        "data_files": ["data/deck_standard_108.json"],
        "includes": ["standard"],
    },
    "extra": {
        "id": "extra",
        "name": "军争牌堆",
        "description": "noname 军争扩展 53 张牌",
        "cards_count": 53,
        "data_files": ["data/deck_extra_53.json"],
        "includes": ["extra"],
    },
    "combined": {
        "id": "combined",
        "name": "标准+军争",
        "description": "标准 108 张与军争 53 张合并，共 161 张",
        "cards_count": 161,
        "data_files": ["data/deck_standard_108.json", "data/deck_extra_53.json"],
        "includes": ["standard", "extra"],
    },
}
DEFAULT_DECK_ID = "standard"
LEGACY_DECK_IDS = {
    "test_deck": "standard",
    "complete_deck": "standard",
}


class DeckManager:
    """权威牌堆加载入口。切换只改变后续新对局的默认选择。"""

    def __init__(self, project_root):
        self.project_root = Path(project_root).resolve()
        self.settings_path = self.project_root / "data" / "deck_settings.json"
        self.active_deck_id = self._load_active_deck_id()

    @staticmethod
    def normalize_deck_id(deck_id):
        if not isinstance(deck_id, str):
            return DEFAULT_DECK_ID
        return LEGACY_DECK_IDS.get(deck_id, deck_id)

    def _load_active_deck_id(self):
        if not self.settings_path.exists():
            return DEFAULT_DECK_ID
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"牌堆设置文件损坏: {self.settings_path}: {exc}") from exc
        deck_id = self.normalize_deck_id(data.get("active_deck"))
        if deck_id not in DECKS:
            raise ValueError(f"牌堆设置包含未知ID: {deck_id}")
        return deck_id

    def _save_settings(self):
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"active_deck": self.active_deck_id}
        self.settings_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def get_active_deck_id(self):
        return self.active_deck_id

    def get_deck_list(self):
        return [deepcopy(deck) for deck in DECKS.values()]

    def switch_deck(self, deck_id):
        deck_id = self.normalize_deck_id(deck_id)
        if deck_id not in DECKS:
            return False
        self.active_deck_id = deck_id
        self._save_settings()
        return True

    def load_deck_cards(self, deck_id=None) -> List[Dict]:
        selected_id = self.normalize_deck_id(deck_id or self.active_deck_id)
        if selected_id not in DECKS:
            raise ValueError(f"未知牌堆ID: {selected_id}")
        deck = DECKS[selected_id]
        cards = []
        for relative_path in deck["data_files"]:
            path = self.project_root / relative_path
            if not path.exists():
                raise FileNotFoundError(f"牌堆数据文件不存在: {path}")
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"牌堆数据文件损坏: {path}: {exc}") from exc
            file_cards = data.get("cards")
            if not isinstance(file_cards, list):
                raise ValueError(f"牌堆数据缺少 cards 数组: {path}")
            cards.extend(file_cards)
        expected = deck["cards_count"]
        if len(cards) != expected:
            raise ValueError(f"牌堆 {selected_id} 数量错误: {len(cards)} != {expected}")
        ids = [card.get("id") for card in cards]
        if any(not card_id for card_id in ids) or len(set(ids)) != len(ids):
            raise ValueError(f"牌堆 {selected_id} 存在空ID或重复ID")
        return cards

    def get_card_image_path(self, card_name):
        name_map = {
            "杀": "sha", "闪": "shan", "桃": "tao", "酒": "jiu",
            "过河拆桥": "guohe", "顺手牵羊": "shunshou",
            "无懈可击": "wuxie", "决斗": "juedou", "火攻": "huogong",
            "铁索连环": "tiesuo", "兵粮寸断": "bingliang",
            "乐不思蜀": "lebu", "南蛮入侵": "nanman",
            "万箭齐发": "wanjian", "桃园结义": "taoyuan",
            "五谷丰登": "wugu", "借刀杀人": "jiedao",
            "无中生有": "wuzhongshengyou", "闪电": "shandian",
        }
        filename = name_map.get(card_name, card_name)
        return f"assets/cards/{filename}.png"

    def get_deck_info(self, deck_id=None):
        selected_id = self.normalize_deck_id(deck_id or self.active_deck_id)
        if selected_id not in DECKS:
            return {}
        return deepcopy(DECKS[selected_id])
