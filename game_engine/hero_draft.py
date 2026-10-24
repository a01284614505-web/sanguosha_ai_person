#!/usr/bin/env python3
"""正式选将：候选生成、规则 AI 打分、候选的公开展示格式。

流程（引擎在 main_engine._draft_heroes 里串起来）：
先分身份 → 主公从"全部主公技武将 + 随机 2 名非主公武将"里选并公开 →
主公没选的放回将池 → 其余每人各发 5 张互不重复的候选，同时选 → 依赖武将的初始化。

本模块只放"纯逻辑"：随机源由调用方注入（测试固定种子），不碰引擎状态，方便单测。
"""

from __future__ import annotations

import random
from copy import deepcopy
from typing import Any, Dict, List, Optional, Sequence

from .mode_registry import get_mode
from .skill_runtime_core import is_lord_skill_type

# 用户拍板（方案第 2 节 X1 / X3）。
LORD_EXTRA_RANDOM = 2        # 主公候选：全部主公技武将 + 随机 N 名非主公武将
CANDIDATES_PER_PLAYER = 5    # 其余每人的候选张数（将池不够时自动减少，见 candidates_per_player）

IDENTITY_LABEL = {"lord": "主公", "loyalist": "忠臣", "rebel": "反贼", "spy": "内奸"}


# ---------------------------------------------------------------- 主公技判定（单一真相源）

def is_lord_skill(skill: Any) -> bool:
    """技能是否为主公技：只读技能元数据的 type（RuntimeSkill 用 skill_type），不匹配描述文字。"""
    if isinstance(skill, dict):
        return is_lord_skill_type(skill.get("type"))
    return is_lord_skill_type(getattr(skill, "skill_type", None))


def is_lord_hero(hero: Optional[Dict]) -> bool:
    return any(is_lord_skill(skill) for skill in (hero or {}).get("skills", []))


def supports_hero_draft(mode_id: str) -> bool:
    """哪些模式启用正式选将：目前只有"有主公"的身份局（5 人、8 人）。

    2v2、斗地主身份固定且公开，没有"主公先选并公开"的环节，保持原来的自由选将。
    """
    try:
        return get_mode(mode_id).victory == "identity"
    except ValueError:
        return False


# ---------------------------------------------------------------- 候选生成

def candidates_per_player(pool_size: int, others: int) -> int:
    """每人发几张：默认 5 张；将池放不下互不重复的 5×人数时减少（8 人局只够 3 张）。"""
    if others <= 0:
        return 0
    return max(0, min(CANDIDATES_PER_PLAYER, pool_size // others))


def lord_candidates(pool: Sequence[Dict], rng=random, extra: int = LORD_EXTRA_RANDOM) -> List[Dict]:
    """主公候选：全部主公技武将 + 随机 extra 名非主公武将，打乱顺序（位置不泄露哪些是"凑数"的）。"""
    lords = [hero for hero in pool if is_lord_hero(hero)]
    others = [hero for hero in pool if not is_lord_hero(hero)]
    rng.shuffle(others)
    result = [deepcopy(hero) for hero in lords + others[:max(0, extra)]]
    rng.shuffle(result)
    return result


def deal_candidates(pool: Sequence[Dict], count: int, per_player: int,
                    exclude_ids: Sequence[str] = (), rng=random) -> List[List[Dict]]:
    """给 count 个人各发 per_player 张互不重复的候选；exclude_ids 里的武将（主公已选）不再出现。"""
    available = [hero for hero in pool if hero.get("id") not in set(exclude_ids)]
    if per_player * count > len(available):
        raise ValueError(f"将池不足：需要 {per_player * count} 张，只剩 {len(available)} 张")
    rng.shuffle(available)
    return [[deepcopy(hero) for hero in available[i * per_player:(i + 1) * per_player]]
            for i in range(count)]


# ---------------------------------------------------------------- 规则 AI 打分

# 每名武将三项定位，0~5：攻（输出/压制）、守（自保/续航）、辅（给牌/回血/帮队友）。
# 只覆盖内置 27 将；导入的武将包没有定位时按体力给中等分（见 score_hero）。
HERO_ROLE = {
    "caocao": (1, 3, 2), "simayi": (1, 4, 2), "xiahoudun": (2, 3, 2), "zhangliao": (4, 1, 0),
    "xuchu": (5, 1, 0), "guojia": (0, 3, 4), "zhenji": (1, 4, 1),
    "liubei": (1, 1, 5), "guanyu": (5, 1, 0), "zhangfei": (5, 1, 0), "zhugeliang": (0, 4, 3),
    "zhaoyun": (3, 3, 1), "machao": (5, 1, 0), "huangyueying": (1, 2, 3),
    "sunquan": (1, 2, 3), "ganning": (4, 1, 0), "lvmeng": (2, 3, 1), "huanggai": (4, 0, 1),
    "zhouyu": (4, 1, 1), "daqiao": (0, 3, 4), "luxun": (1, 4, 2),
    "huatuo": (0, 2, 5), "lvbu": (5, 1, 0), "diaochan": (3, 2, 2), "huaxiong": (3, 2, 0),
    "yuanshao": (4, 1, 0), "zhangjiao": (3, 2, 2),
}
DEFAULT_ROLE = (2, 2, 2)

# 各身份对（攻, 守, 辅）的偏好权重：主公/忠臣偏防守与辅助，反贼偏进攻，内奸求稳并留后手。
IDENTITY_WEIGHT = {
    "lord": (0.5, 2.0, 1.5),
    "loyalist": (0.5, 1.5, 2.0),
    "rebel": (2.0, 0.5, 0.0),
    "spy": (1.0, 1.5, 0.5),
}
LORD_SKILL_BONUS = 1.5       # 主公自己选到主公技武将：技能能用，加分
LORD_SKILL_WASTED = 1.5      # 非主公选主公技武将：主公技用不上，扣分
SAME_FACTION_LOYAL = 1.0     # 忠臣与主公同势力：能吃到主公技的联动
SAME_FACTION_REBEL = 0.5     # 反贼与主公同势力：主公技更强，略扣分


def score_hero(hero: Dict, identity: str, lord_hero: Optional[Dict] = None) -> float:
    """规则 AI 的武将打分；越高越想要。lord_hero 是主公已公开的武将（主公本人选将时为 None）。"""
    attack, defense, support = HERO_ROLE.get(hero.get("id"), DEFAULT_ROLE)
    w_attack, w_defense, w_support = IDENTITY_WEIGHT.get(identity, IDENTITY_WEIGHT["spy"])
    score = attack * w_attack + defense * w_defense + support * w_support
    score += 0.3 * int(hero.get("max_hp", 4))            # 体力多一点总不吃亏
    if is_lord_hero(hero):
        score += LORD_SKILL_BONUS if identity == "lord" else -LORD_SKILL_WASTED
    if lord_hero and identity != "lord" and hero.get("faction") == lord_hero.get("faction"):
        score += SAME_FACTION_LOYAL if identity == "loyalist" else (
            -SAME_FACTION_REBEL if identity == "rebel" else 0.0)
    return score


def pick_by_rules(heroes: Sequence[Dict], identity: str, lord_hero: Optional[Dict] = None,
                  rng=random) -> int:
    """返回得分最高的候选下标；同分随机（用注入的 rng，测试可固定）。"""
    if not heroes:
        return 0
    scores = [score_hero(hero, identity, lord_hero) for hero in heroes]
    best = max(scores)
    tied = [index for index, value in enumerate(scores) if abs(value - best) < 1e-9]
    return tied[0] if len(tied) == 1 else rng.choice(tied)


# ---------------------------------------------------------------- 公开展示

def public_hero_card(hero: Optional[Dict]) -> Optional[Dict]:
    """选将面板 / AI 提示用的武将公开资料：名称、势力、体力、技能全文；不带世界书等内部字段。"""
    if not hero:
        return None
    return {
        "id": hero.get("id", ""),
        "name": hero.get("name", ""),
        "title": hero.get("title", ""),
        "faction": hero.get("faction", ""),
        "max_hp": int(hero.get("max_hp", 4)),
        "skills": [
            {"name": skill.get("name", ""), "description": skill.get("description", ""),
             "type": skill.get("type", "trigger"), "lord_skill": is_lord_skill(skill)}
            for skill in hero.get("skills", []) if isinstance(skill, dict)
        ],
    }


def hero_text(hero: Dict) -> str:
    """一名武将的技能全文，供模型 AI 的选将提示使用。"""
    skills = "；".join(
        f"【{skill.get('name')}】{'（主公技）' if is_lord_skill(skill) else ''}{skill.get('description', '')}"
        for skill in hero.get("skills", []) if isinstance(skill, dict)
    ) or "无技能"
    return f"{hero.get('name', '?')}（{hero.get('faction', '?')}势力，体力{hero.get('max_hp', 4)}）{skills}"


__all__ = [
    "LORD_EXTRA_RANDOM", "CANDIDATES_PER_PLAYER", "IDENTITY_LABEL", "HERO_ROLE",
    "is_lord_skill", "is_lord_hero", "supports_hero_draft", "candidates_per_player",
    "lord_candidates", "deal_candidates", "score_hero", "pick_by_rules",
    "public_hero_card", "hero_text",
]
