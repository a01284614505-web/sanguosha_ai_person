#!/usr/bin/env python3
"""身份系统：5人身份局随机身份、身份卡指定与胜利判定。"""

import random
from typing import Dict, List, Optional


class IdentitySystem:
    IDENTITY_5 = ["lord", "loyalist", "rebel", "rebel", "spy"]
    IDENTITY_ALIASES = {
        "主公": "lord", "lord": "lord",
        "忠臣": "loyalist", "loyalist": "loyalist",
        "反贼": "rebel", "rebel": "rebel",
        "内奸": "spy", "spy": "spy",
    }

    @classmethod
    def assign_identities(cls, players: List, mode="5人身份局", identity_card: Optional[Dict] = None) -> Dict:
        if mode != "5人身份局" or len(players) != 5:
            return {}
        return cls._assign_5players(players, identity_card or {})

    @classmethod
    def _assign_5players(cls, players: List, identity_card: Dict) -> Dict:
        pool = list(cls.IDENTITY_5)
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
    def check_victory(players: List) -> Dict:
        alive_players = [p for p in players if p.alive]
        lord = next((p for p in players if p.identity == "lord"), None)
        if not lord:
            return {"game_over": False}

        if not lord.alive:
            if len(alive_players) == 1 and alive_players[0].identity == "spy":
                return {"game_over": True, "winner": "spy", "message": "内奸获胜！"}
            return {"game_over": True, "winner": "rebel", "message": "反贼获胜！"}

        alive_identities = {p.identity for p in alive_players}
        if "rebel" not in alive_identities and "spy" not in alive_identities:
            return {"game_over": True, "winner": "lord", "message": "主公和忠臣获胜！"}
        return {"game_over": False}


__all__ = ["IdentitySystem"]
