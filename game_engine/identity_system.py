#!/usr/bin/env python3
"""身份系统：声明式身份局的随机身份、身份卡指定与胜利判定。"""

import random
from typing import Dict, List, Optional

from .mode_registry import get_mode, identity_victory


class IdentitySystem:
    IDENTITY_5 = list(get_mode("5人身份局").identities)
    IDENTITY_8 = list(get_mode("8人身份局").identities)
    TEAM_2V2 = list(get_mode("2v2").identities)
    LANDLORD = list(get_mode("斗地主").identities)
    IDENTITY_ALIASES = {
        "主公": "lord", "lord": "lord",
        "忠臣": "loyalist", "loyalist": "loyalist",
        "反贼": "rebel", "rebel": "rebel",
        "内奸": "spy", "spy": "spy",
    }

    @classmethod
    def assign_identities(cls, players: List, mode="5人身份局", identity_card: Optional[Dict] = None) -> Dict:
        try:
            spec = get_mode(mode)
        except ValueError:
            return {}
        if len(players) != spec.player_count:
            return {}
        return cls._assign(players, spec, identity_card or {})

    @classmethod
    def _assign(cls, players: List, spec, identity_card: Dict) -> Dict:
        pool = list(spec.identities)
        requested = None
        if spec.assignment == "fixed" and identity_card.get("use"):
            raise ValueError(f"{spec.mode_id}不支持身份卡")
        if identity_card.get("use"):
            requested = cls.IDENTITY_ALIASES.get(identity_card.get("identity"))
            if requested not in pool:
                raise ValueError(f"身份卡指定了无效身份: {identity_card.get('identity')}")

        if spec.assignment == "fixed":
            for player, identity in zip(players, pool):
                player.identity = identity
        elif requested:
            players[0].identity = requested
            pool.remove(requested)
            random.shuffle(pool)
            for player, identity in zip(players[1:], pool):
                player.identity = identity
        else:
            random.shuffle(pool)
            for player, identity in zip(players, pool):
                player.identity = identity

        for player in players:
            player.identity_revealed = spec.identities_public or player.identity == "lord"

        groups = {identity: [p for p in players if p.identity == identity]
                  for identity in dict.fromkeys(spec.identities)}
        first = next(player for player in players if player.identity == spec.first_player_identity)
        result = {**groups, "first_player": first}
        if "lord" in groups:
            result["lord"] = groups["lord"][0]
        return result

    @staticmethod
    def check_victory(players: List, mode="5人身份局") -> Dict:
        return identity_victory(players, mode)


__all__ = ["IdentitySystem"]
