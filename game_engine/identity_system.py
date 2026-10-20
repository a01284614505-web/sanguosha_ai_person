#!/usr/bin/env python3
"""身份系统：5人身份局随机身份、身份卡指定与胜利判定。"""

import random
from typing import Dict, List, Optional

from .mode_registry import get_mode, identity_victory


class IdentitySystem:
    IDENTITY_5 = list(get_mode("5人身份局").identities)
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
        return cls._assign(players, list(spec.identities), identity_card or {})

    @classmethod
    def _assign(cls, players: List, pool: List[str], identity_card: Dict) -> Dict:
        requested = None
        if identity_card.get("use"):
            requested = cls.IDENTITY_ALIASES.get(identity_card.get("identity"))
            if requested not in pool:
                raise ValueError(f"身份卡指定了无效身份: {identity_card.get('identity')}")

        if requested:
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
            player.identity_revealed = player.identity == "lord"

        lord = next(player for player in players if player.identity == "lord")
        return {
            "lord": lord,
            "loyalist": [p for p in players if p.identity == "loyalist"],
            "rebel": [p for p in players if p.identity == "rebel"],
            "spy": [p for p in players if p.identity == "spy"],
        }

    @staticmethod
    def check_victory(players: List, mode="5人身份局") -> Dict:
        return identity_victory(players, mode)


__all__ = ["IdentitySystem"]
