#!/usr/bin/env python3
"""武将技能运行时公共结构与工具。"""

from dataclasses import dataclass
from itertools import combinations
from typing import Any, Dict, Iterable, List, Optional


FACTION_CODE = {"魏": "wei", "蜀": "shu", "吴": "wu", "群": "qun", "wei": "wei", "shu": "shu", "wu": "wu", "qun": "qun"}
RED_SUITS = {"heart", "diamond", "红桃", "方块"}
BLACK_SUITS = {"spade", "club", "黑桃", "梅花"}


def hero_id(player) -> str:
    hero = getattr(player, "hero", None)
    return hero.get("id", "") if isinstance(hero, dict) else getattr(hero, "id", "")


def hero_faction(player) -> str:
    hero = getattr(player, "hero", None)
    value = hero.get("faction", "") if isinstance(hero, dict) else getattr(hero, "faction", "")
    return FACTION_CODE.get(value, value)


def card_color(card) -> str:
    if getattr(card, "suit", None) in RED_SUITS:
        return "red"
    if getattr(card, "suit", None) in BLACK_SUITS:
        return "black"
    return "none"


def card_type_group(card) -> str:
    value = getattr(card, "card_type", "")
    if value in ("basic", "基本"):
        return "basic"
    if value in ("trick", "锦囊", "delayed_trick", "延时锦囊"):
        return "trick"
    if value in ("equipment", "装备"):
        return "equipment"
    return value or "unknown"


def alive_others(state, player):
    return [p for p in state.players if p.alive and p is not player]


def player_by_id(state, player_id):
    return next((p for p in state.players if p.id == player_id), None)


def ensure_flags(player):
    if not hasattr(player, "flags") or player.flags is None:
        player.flags = {}
    return player.flags


def once_per_turn(player, key: str) -> bool:
    flags = ensure_flags(player)
    return bool(flags.get("skill_used", {}).get(key))


def mark_once_per_turn(player, key: str):
    flags = ensure_flags(player)
    flags.setdefault("skill_used", {})[key] = True


def reset_turn_flags(player):
    flags = ensure_flags(player)
    flags["skill_used"] = {}
    flags["sha_used_this_turn"] = False
    flags["trick_used_this_turn"] = False
    flags["turn_discard_suits"] = set()
    flags["hand_limit_bonus"] = 0
    flags.pop("cannot_use_hand", None)
    flags.pop("nonlocked_disabled", None)
    flags.pop("yijue_heart_source", None)
    flags.pop("pao_tokens", None)


def combinations_limited(items: Iterable[int], size: int, limit: int = 12):
    result = []
    for combo in combinations(items, size):
        result.append(list(combo))
        if len(result) >= limit:
            break
    return result


@dataclass
class RuntimeSkill:
    skill_id: str
    name: str
    owner_hero_id: str
    skill_type: str
    trigger_event: str
    forced: bool = False
    limited: bool = False
    description: str = ""
    faction: str = ""
    implementation_status: str = "active"

    def public_dict(self) -> Dict[str, Any]:
        return {
            "id": self.skill_id,
            "name": self.name,
            "owner_hero_id": self.owner_hero_id,
            "type": self.skill_type,
            "trigger_event": self.trigger_event,
            "is_forced": self.forced,
            "is_limited": self.limited,
            "description": self.description,
            "implementation_status": self.implementation_status,
        }


class FactionSkillHandler:
    faction = ""

    def __init__(self, manager):
        self.manager = manager
        self.engine = manager.engine
        self.state = manager.engine.game_state if manager.engine else None

    def has(self, player, name: str) -> bool:
        return self.manager.has_skill(player, name)

    def get_actions(self, player) -> List[Dict]:
        return []

    async def execute(self, player, action: Dict, targets: List) -> bool:
        return False

    async def on_turn_start(self, player):
        return None

    async def before_phase(self, player, phase):
        return None

    async def after_phase(self, player, phase):
        return None

    async def before_sha(self, source, target, card, event: Dict):
        return None

    async def on_sha_dodged(self, source, target, card, event: Dict):
        return None

    async def modify_damage(self, source, target, amount: int, card=None, context=None) -> int:
        return amount

    async def after_damage(self, source, target, amount: int, card=None, context=None):
        return None

    async def after_card_used(self, player, card, targets, success: bool):
        return None

    async def on_card_responded(self, player, card, as_name: str, context=None):
        return None

    def response_options(self, player, requested_name: str) -> List[Dict]:
        return []

    def can_target(self, source, target, card_name: str) -> Optional[str]:
        return None

    def modify_distance(self, source, target, distance: int) -> int:
        return distance

    def ignore_distance(self, source, card) -> bool:
        return False

    def hand_limit(self, player, current: int) -> int:
        return current

    def protect_card(self, owner, card, reason: str) -> bool:
        return False

    async def before_judge(self, player, card, context=None):
        return card

    async def after_judge(self, player, card, context=None) -> bool:
        return False

    async def on_card_gained(self, player, cards, reason="unknown"):
        return None

    async def on_cards_lost(self, player, cards, reason="unknown"):
        return None

    async def on_card_discarded(self, player, card, reason="unknown"):
        return None

    async def on_hp_lost(self, player, amount, reason="unknown", source=None):
        return None

    async def on_recover(self, player, amount, source=None, reason="unknown"):
        return None

    async def before_card_target(self, source, target, card):
        return target

    async def before_multi_target_trick(self, source, card, targets):
        return targets


__all__ = [
    "RuntimeSkill", "FactionSkillHandler", "hero_id", "hero_faction", "card_color",
    "card_type_group", "alive_others", "player_by_id", "ensure_flags",
    "once_per_turn", "mark_once_per_turn", "reset_turn_flags", "combinations_limited",
    "RED_SUITS", "BLACK_SUITS",
]
