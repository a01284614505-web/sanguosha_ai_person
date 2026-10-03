#!/usr/bin/env python3
"""卡牌单一真相源：42 种牌名的全部属性集中于此表。

本表为静态手写表（含牌堆 JSON 无法承载的引擎侧字段：resolver/usage/
discard_keep_score/play_priority）。与牌堆 JSON（data/deck_standard_108.json、
data/deck_extra_53.json）的 card_type / target_rule 一致性由
tests/test_real_decks.py 的断言守护：表键集 == 两堆并集牌名集，且逐项一致。
引擎其余模块一律查表，不得再出现牌名/属性硬编码（grep 验收）。
"""

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass(frozen=True)
class CardSpec:
    card_type: str                        # basic / trick / equipment
    target_rule: Dict                     # 与牌堆 JSON 逐项一致
    wuxie_targetable: bool = False        # 结算前能否被无懈可击响应
    resolver: Optional[str] = None        # use_card 的分发目标（use_sha 等），未实现为 None
    usage: str = "play"                   # play（可主动出）/ response（只能响应）/ unimplemented
    image: Optional[str] = None           # assets/cards/ 下文件名（无图为 None，回退原名）
    discard_keep_score: int = 20          # 弃牌阶段保留分值（P0 托管启发式）
    play_priority: int = 0                # AI 出牌优先级（越大越优先，0 不参与排序）
    source_key: Optional[str] = None      # noname 源码英文标识（extract 工具反查用）
    weapon_range: int = 1                 # 武器攻击距离（仅 equipment_slot=="weapon" 时有效）
    equipment_slot: Optional[str] = None  # weapon / armor / plus_horse / minus_horse


def _c(card_type, target_rule, *, wuxie=False, resolver=None, usage="play",
       image=None, keep=20, priority=0, source_key=None,
       weapon_range=1, equipment_slot=None):
    return CardSpec(
        card_type=card_type, target_rule=target_rule,
        wuxie_targetable=wuxie, resolver=resolver, usage=usage,
        image=image, discard_keep_score=keep, play_priority=priority,
        source_key=source_key, weapon_range=weapon_range, equipment_slot=equipment_slot,
    )


# target_rule.type 无外部目标的取值：此类牌结算时无需指定目标。
# use_card / can_play_card 的分发链据此决定是否传入 target 参数（单一来源）。
NO_EXTERNAL_TARGET = ("self", "self_or_dying", "all", "all_others")


CARD_TABLE: Dict[str, CardSpec] = {
    # ---- 基本牌 ----
    "杀": _c("basic", {"min": 1, "max": 1, "type": "other", "distance_limit": 1},
             resolver="use_sha", image="sha", keep=50, priority=2, source_key="sha"),
    "闪": _c("basic", {"type": "self"}, usage="response", image="shan", keep=80, source_key="shan"),
    "桃": _c("basic", {"min": 1, "max": 1, "type": "self_or_dying"},
             resolver="use_tao", image="tao", keep=100, priority=3, source_key="tao"),
    "酒": _c("basic", {"min": 0, "max": 0, "type": "self"},
             resolver="use_jiu", image="jiu", source_key="jiu"),

    # ---- 锦囊：已实现 ----
    "过河拆桥": _c("trick", {"min": 1, "max": 1, "type": "other", "distance_limit": None},
                  wuxie=True, resolver="use_guohe", image="guohe", priority=1, source_key="guohe"),
    "顺手牵羊": _c("trick", {"min": 1, "max": 1, "type": "other", "distance_limit": 1},
                  wuxie=True, resolver="use_shunshou", image="shunshou", priority=1, source_key="shunshou"),
    "无中生有": _c("trick", {"type": "self"},
                  wuxie=True, resolver="use_wuzhongshengyou", image="wuzhongshengyou", source_key="wuzhong"),
    "铁索连环": _c("trick", {"min": 1, "max": 2, "type": "any"},
                  wuxie=True, resolver="use_tiesuo", image="tiesuo", source_key="tiesuo"),
    "兵粮寸断": _c("trick", {"min": 1, "max": 1, "type": "other"},
                  wuxie=True, resolver="use_bingliang", image="bingliang", source_key="bingliang"),
    "乐不思蜀": _c("trick", {"min": 1, "max": 1, "type": "other"},
                  wuxie=True, resolver="use_lebu", image="lebu", source_key="lebu"),

    # ---- 锦囊：已实现（6C 补全）----
    "决斗": _c("trick", {"min": 1, "max": 1, "type": "other"},
               wuxie=True, resolver="use_juedou", image="juedou", priority=1, source_key="juedou"),
    "南蛮入侵": _c("trick", {"type": "all_others"},
                  wuxie=True, resolver="use_nanman", image="nanman", priority=1, source_key="nanman"),
    "万箭齐发": _c("trick", {"type": "all_others"},
                  wuxie=True, resolver="use_wanjian", image="wanjian", priority=1, source_key="wanjian"),
    "桃园结义": _c("trick", {"type": "all"},
                  wuxie=True, resolver="use_taoyuan", image="taoyuan", priority=1, source_key="taoyuan"),
    "五谷丰登": _c("trick", {"type": "all"},
                  wuxie=True, resolver="use_wugu", image="wugu", priority=1, source_key="wugu"),
    "借刀杀人": _c("trick", {"min": 2, "max": 2, "type": "other"},
                  wuxie=True, resolver="use_jiedao", image="jiedao", priority=1, source_key="jiedao"),
    "闪电": _c("trick", {"type": "self"},
              wuxie=True, resolver="use_shandian", image="shandian", source_key="shandian"),
    "火攻": _c("trick", {"min": 1, "max": 1, "type": "other"},
              wuxie=True, resolver="use_huogong", image="huogong", priority=1, source_key="huogong"),

    # ---- 锦囊：只能响应 ----
    "无懈可击": _c("trick", {"type": "trick_card"}, usage="response",
                  image="wuxie", keep=70, source_key="wuxie"),

    # ---- 武器（装备进 weapon 槽，effect 6B 再接）----
    "诸葛连弩": _c("equipment", {"min": 0, "max": 0, "type": "self"},
                  resolver="use_equipment", image=None, keep=60, source_key="zhuge",
                  weapon_range=1, equipment_slot="weapon"),
    "雌雄双股剑": _c("equipment", {"min": 0, "max": 0, "type": "self"},
                    resolver="use_equipment", image=None, keep=60, source_key="cixiong",
                    weapon_range=2, equipment_slot="weapon"),
    "青釭剑": _c("equipment", {"min": 0, "max": 0, "type": "self"},
                resolver="use_equipment", image=None, keep=60, source_key="qinggang",
                weapon_range=2, equipment_slot="weapon"),
    "寒冰剑": _c("equipment", {"min": 0, "max": 0, "type": "self"},
                resolver="use_equipment", image=None, keep=60, source_key="hanbing",
                weapon_range=3, equipment_slot="weapon"),
    "青龙偃月刀": _c("equipment", {"min": 0, "max": 0, "type": "self"},
                    resolver="use_equipment", image=None, keep=60, source_key="qinglong",
                    weapon_range=3, equipment_slot="weapon"),
    "丈八蛇矛": _c("equipment", {"min": 0, "max": 0, "type": "self"},
                  resolver="use_equipment", image=None, keep=60, source_key="zhangba",
                  weapon_range=3, equipment_slot="weapon"),
    "贯石斧": _c("equipment", {"min": 0, "max": 0, "type": "self"},
                resolver="use_equipment", image=None, keep=60, source_key="guanshi",
                weapon_range=3, equipment_slot="weapon"),
    "方天画戟": _c("equipment", {"min": 0, "max": 0, "type": "self"},
                  resolver="use_equipment", image=None, keep=60, source_key="fangtian",
                  weapon_range=4, equipment_slot="weapon"),
    "麒麟弓": _c("equipment", {"min": 0, "max": 0, "type": "self"},
                resolver="use_equipment", image=None, keep=60, source_key="qilin",
                weapon_range=5, equipment_slot="weapon"),
    "古锭刀": _c("equipment", {"min": 0, "max": 0, "type": "self"},
                resolver="use_equipment", image=None, keep=60, source_key="guding",
                weapon_range=2, equipment_slot="weapon"),
    "朱雀羽扇": _c("equipment", {"min": 0, "max": 0, "type": "self"},
                  resolver="use_equipment", image=None, keep=60, source_key="zhuque",
                  weapon_range=4, equipment_slot="weapon"),

    # ---- 防具 ----
    "八卦阵": _c("equipment", {"min": 0, "max": 0, "type": "self"},
                resolver="use_equipment", image=None, keep=70, source_key="bagua",
                equipment_slot="armor"),
    "仁王盾": _c("equipment", {"min": 0, "max": 0, "type": "self"},
                resolver="use_equipment", image=None, keep=70, source_key="renwang",
                equipment_slot="armor"),
    "白银狮子": _c("equipment", {"min": 0, "max": 0, "type": "self"},
                  resolver="use_equipment", image=None, keep=70, source_key="baiyin",
                  equipment_slot="armor"),
    "藤甲": _c("equipment", {"min": 0, "max": 0, "type": "self"},
              resolver="use_equipment", image=None, keep=70, source_key="tengjia",
              equipment_slot="armor"),

    # ---- 坐骑：-1 马（plus_horse 减少他人到你的距离）----
    "绝影": _c("equipment", {"min": 0, "max": 0, "type": "self"},
              resolver="use_equipment", image=None, keep=50, source_key="jueying",
              equipment_slot="plus_horse"),
    "的卢": _c("equipment", {"min": 0, "max": 0, "type": "self"},
              resolver="use_equipment", image=None, keep=50, source_key="dilu",
              equipment_slot="plus_horse"),
    "爪黄飞电": _c("equipment", {"min": 0, "max": 0, "type": "self"},
                  resolver="use_equipment", image=None, keep=50, source_key="zhuahuang",
                  equipment_slot="plus_horse"),

    # ---- 坐骑：+1 马（minus_horse 减少你到他人的距离）----
    "赤兔": _c("equipment", {"min": 0, "max": 0, "type": "self"},
              resolver="use_equipment", image=None, keep=50, source_key="chitu",
              equipment_slot="minus_horse"),
    "大宛": _c("equipment", {"min": 0, "max": 0, "type": "self"},
              resolver="use_equipment", image=None, keep=50, source_key="dawan",
              equipment_slot="minus_horse"),
    "紫骍": _c("equipment", {"min": 0, "max": 0, "type": "self"},
              resolver="use_equipment", image=None, keep=50, source_key="zixin",
              equipment_slot="minus_horse"),
    "骅骝": _c("equipment", {"min": 0, "max": 0, "type": "self"},
              resolver="use_equipment", image=None, keep=50, source_key="hualiu",
              equipment_slot="minus_horse"),

    # ---- 木牛流马（特殊装备，6C-6 延期，暂保留槽占位）----
    "木牛流马": _c("equipment", {"min": 0, "max": 0, "type": "self"},
                  resolver="use_equipment", image=None, keep=40, source_key="muniu",
                  equipment_slot="armor"),
}
