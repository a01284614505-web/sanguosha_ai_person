#!/usr/bin/env python3
"""从 noname 源码提取标准牌堆与军争牌堆。"""

import argparse
import json
from collections import Counter
from pathlib import Path


NAME_MAP = {
    "sha": "杀", "shan": "闪", "tao": "桃", "jiu": "酒",
    "wugu": "五谷丰登", "taoyuan": "桃园结义", "nanman": "南蛮入侵",
    "wanjian": "万箭齐发", "wuzhong": "无中生有", "juedou": "决斗",
    "shunshou": "顺手牵羊", "guohe": "过河拆桥", "jiedao": "借刀杀人",
    "wuxie": "无懈可击", "lebu": "乐不思蜀", "shandian": "闪电",
    "huogong": "火攻", "tiesuo": "铁索连环", "bingliang": "兵粮寸断",
    "zhuge": "诸葛连弩", "cixiong": "雌雄双股剑", "qinggang": "青釭剑",
    "hanbing": "寒冰剑", "qinglong": "青龙偃月刀", "zhangba": "丈八蛇矛",
    "guanshi": "贯石斧", "fangtian": "方天画戟", "qilin": "麒麟弓",
    "bagua": "八卦阵", "renwang": "仁王盾", "jueying": "绝影",
    "dilu": "的卢", "zhuahuang": "爪黄飞电", "chitu": "赤兔",
    "dawan": "大宛", "zixin": "紫骍", "hualiu": "骅骝",
    "baiyin": "白银狮子", "tengjia": "藤甲", "guding": "古锭刀",
    "zhuque": "朱雀羽扇", "muniu": "木牛流马",
}

BASIC = {"sha", "shan", "tao", "jiu"}
DELAYED_TRICK = {"lebu", "shandian", "bingliang"}
TRICK = {
    "wugu", "taoyuan", "nanman", "wanjian", "wuzhong", "juedou",
    "shunshou", "guohe", "jiedao", "wuxie", "huogong", "tiesuo",
} | DELAYED_TRICK
EQUIPMENT_SUBTYPE = {
    "zhuge": "weapon", "cixiong": "weapon", "qinggang": "weapon",
    "hanbing": "weapon", "qinglong": "weapon", "zhangba": "weapon",
    "guanshi": "weapon", "fangtian": "weapon", "qilin": "weapon",
    "guding": "weapon", "zhuque": "weapon",
    "bagua": "armor", "renwang": "armor", "baiyin": "armor",
    "tengjia": "armor",
    "jueying": "plus_horse", "dilu": "plus_horse",
    "zhuahuang": "plus_horse", "hualiu": "plus_horse",
    "chitu": "minus_horse", "dawan": "minus_horse", "zixin": "minus_horse",
    "muniu": "treasure",
}

DEFAULT_RULES = {
    "杀": ("对一名其他角色造成1点伤害", {"min": 1, "max": 1, "type": "other", "distance_limit": 1}),
    "闪": ("抵消一张【杀】", {"min": 0, "max": 0, "type": "response"}),
    "桃": ("回复1点体力", {"min": 0, "max": 0, "type": "self"}),
    "酒": ("本回合下一张【杀】伤害+1；濒死时回复1点体力", {"min": 0, "max": 0, "type": "self"}),
    "五谷丰登": ("所有角色依次获得一张展示牌", {"min": 0, "max": 0, "type": "all"}),
    "桃园结义": ("所有受伤角色回复1点体力", {"min": 0, "max": 0, "type": "all"}),
    "南蛮入侵": ("其他角色打出【杀】，否则受到1点伤害", {"min": 0, "max": 0, "type": "all_others"}),
    "万箭齐发": ("其他角色打出【闪】，否则受到1点伤害", {"min": 0, "max": 0, "type": "all_others"}),
    "无中生有": ("摸两张牌", {"min": 0, "max": 0, "type": "self"}),
    "决斗": ("双方轮流打出【杀】，未打出者受到1点伤害", {"min": 1, "max": 1, "type": "other"}),
    "顺手牵羊": ("获得距离1角色区域内的一张牌", {"min": 1, "max": 1, "type": "other", "distance_limit": 1}),
    "过河拆桥": ("弃置一名其他角色区域内的一张牌", {"min": 1, "max": 1, "type": "other"}),
    "借刀杀人": ("令有武器的角色使用【杀】，否则获得其武器", {"min": 2, "max": 2, "type": "other"}),
    "无懈可击": ("抵消锦囊牌或另一张【无懈可击】", {"min": 0, "max": 0, "type": "response"}),
    "乐不思蜀": ("判定不为红桃时跳过出牌阶段", {"min": 1, "max": 1, "type": "other"}),
    "闪电": ("判定为黑桃2至9时受到3点雷电伤害，否则传递", {"min": 0, "max": 0, "type": "self"}),
    "火攻": ("展示目标一张手牌，弃置同花色牌可造成1点火焰伤害", {"min": 1, "max": 1, "type": "other"}),
    "铁索连环": ("横置或重置一至两名角色", {"min": 1, "max": 2, "type": "any"}),
    "兵粮寸断": ("判定不为梅花时跳过摸牌阶段", {"min": 1, "max": 1, "type": "other", "distance_limit": 1}),
}


def extract_list(source_path: Path):
    text = source_path.read_text(encoding="utf-8")
    marker = "list: ["
    marker_index = text.rfind(marker)
    if marker_index < 0:
        raise ValueError(f"未找到 list 数组: {source_path}")
    start = text.index("[", marker_index)
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                fragment = text[start:index].rstrip()
                if fragment.endswith(","):
                    fragment = fragment[:-1]
                return json.loads(fragment + "]")
    raise ValueError(f"list 数组未闭合: {source_path}")


def load_worldbook_rules(project_root: Path):
    by_exact = {}
    by_name = {}
    rules_dir = project_root / "worldbook_generated" / "cards"
    for path in sorted(rules_dir.glob("*_cards.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for card in data.get("cards", []):
            name = card.get("name")
            if not name:
                continue
            rule = {
                key: card[key]
                for key in ("effect", "target_rule", "worldbook", "usage_phase", "can_wuxie")
                if key in card
            }
            by_name.setdefault(name, rule)
            by_exact[(name, card.get("suit"), card.get("rank"))] = rule
    return by_exact, by_name


def card_type(raw_name):
    if raw_name in BASIC:
        return "basic", None
    if raw_name in TRICK:
        subtype = "delayed" if raw_name in DELAYED_TRICK else "normal"
        return "trick", subtype
    if raw_name in EQUIPMENT_SUBTYPE:
        return "equipment", EQUIPMENT_SUBTYPE[raw_name]
    raise ValueError(f"未登记的 noname 牌名: {raw_name}")


def convert_cards(raw_cards, deck_id, by_exact, by_name):
    occurrences = Counter()
    cards = []
    for item in raw_cards:
        if len(item) not in (3, 4):
            raise ValueError(f"不支持的牌数据: {item!r}")
        suit, rank, raw_name = item[:3]
        nature = item[3] if len(item) == 4 else None
        name = NAME_MAP.get(raw_name)
        if not name:
            raise ValueError(f"缺少中文名映射: {raw_name}")
        kind, subtype = card_type(raw_name)
        key = (raw_name, suit, rank, nature)
        occurrences[key] += 1
        suffix = occurrences[key]
        card_id = f"{deck_id}_{raw_name}_{suit}_{rank}_{suffix}"
        default_effect, default_target = DEFAULT_RULES.get(name, (f"装备牌【{name}】", {"min": 0, "max": 0, "type": "self"}))
        rule = by_exact.get((name, suit, rank), by_name.get(name, {}))
        card = {
            "id": card_id,
            "source_name": raw_name,
            "name": name,
            "suit": suit,
            "rank": rank,
            "type": kind,
            "effect": rule.get("effect", default_effect),
            "target_rule": rule.get("target_rule", default_target),
        }
        if subtype:
            card["sub_type"] = subtype
        if nature:
            card["nature"] = nature
        for field in ("worldbook", "usage_phase", "can_wuxie"):
            if field in rule:
                card[field] = rule[field]
        cards.append(card)
    return cards


def build_deck(project_root, source_relative, deck_id, name, expected_count):
    source_path = project_root / source_relative
    raw_cards = extract_list(source_path)
    if len(raw_cards) != expected_count:
        raise ValueError(f"{deck_id} 数量错误: {len(raw_cards)} != {expected_count}")
    by_exact, by_name = load_worldbook_rules(project_root)
    cards = convert_cards(raw_cards, deck_id, by_exact, by_name)
    type_counts = Counter(card["type"] for card in cards)
    name_counts = Counter(card["name"] for card in cards)
    return {
        "meta": {
            "id": deck_id,
            "name": name,
            "source": source_relative.as_posix(),
            "cards_count": len(cards),
            "type_counts": dict(sorted(type_counts.items())),
            "name_counts": dict(sorted(name_counts.items())),
        },
        "cards": cards,
    }


def main():
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=default_root)
    args = parser.parse_args()
    project_root = args.project_root.resolve()

    specs = [
        (Path("noname-main/apps/core/card/standard.js"), "standard", "标准牌堆", 108, "deck_standard_108.json"),
        (Path("noname-main/apps/core/card/extra.js"), "extra", "军争牌堆", 53, "deck_extra_53.json"),
    ]
    for source, deck_id, name, count, filename in specs:
        deck = build_deck(project_root, source, deck_id, name, count)
        output_path = project_root / "data" / filename
        output_path.write_text(json.dumps(deck, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{deck_id}: {deck['meta']['cards_count']} 张 -> {output_path}")
        print(f"  类型: {deck['meta']['type_counts']}")
        print(f"  牌名: {deck['meta']['name_counts']}")


if __name__ == "__main__":
    main()
