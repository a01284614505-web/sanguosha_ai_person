"""Declarative game-mode rules used by config, setup, turns and settlement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ModeSpec:
    mode_id: str
    player_count: int
    identities: tuple[str, ...]
    initial_hand: int
    first_player_identity: str
    lord_hp_bonus: int
    turn_order: str
    rebel_kill_draw: int
    lord_kills_loyalist_discards: bool

    @property
    def ai_count(self) -> int:
        return self.player_count - 1

    def public_dict(self) -> dict:
        return {
            "id": self.mode_id,
            "player_count": self.player_count,
            "ai_count": self.ai_count,
            "identity_pool": list(self.identities),
            "initial_hand": self.initial_hand,
            "first_player_identity": self.first_player_identity,
            "lord_hp_bonus": self.lord_hp_bonus,
            "turn_order": self.turn_order,
        }


IDENTITY_FIVE = ModeSpec(
    mode_id="5人身份局",
    player_count=5,
    identities=("lord", "loyalist", "rebel", "rebel", "spy"),
    initial_hand=4,
    first_player_identity="lord",
    lord_hp_bonus=1,
    turn_order="seat_clockwise",
    rebel_kill_draw=3,
    lord_kills_loyalist_discards=True,
)

MODE_REGISTRY = {IDENTITY_FIVE.mode_id: IDENTITY_FIVE}


def get_mode(mode_id: str) -> ModeSpec:
    try:
        return MODE_REGISTRY[str(mode_id)]
    except KeyError as exc:
        raise ValueError(f"当前引擎暂不支持模式: {mode_id}") from exc


def supported_modes() -> list[dict]:
    return [spec.public_dict() for spec in MODE_REGISTRY.values()]


def identity_victory(players: Iterable, mode_id="5人身份局") -> dict:
    """Evaluate the currently registered identity-mode victory contract."""
    spec = get_mode(mode_id)
    if spec.first_player_identity != "lord":
        raise ValueError(f"模式尚未提供胜负实现: {mode_id}")
    players = list(players)
    alive_players = [player for player in players if player.alive]
    lord = next((player for player in players if player.identity == "lord"), None)
    if lord is None:
        return {"game_over": False}
    if not lord.alive:
        if len(alive_players) == 1 and alive_players[0].identity == "spy":
            return {"game_over": True, "winner": "spy", "message": "内奸获胜！"}
        return {"game_over": True, "winner": "rebel", "message": "反贼获胜！"}
    alive_identities = {player.identity for player in alive_players}
    if "rebel" not in alive_identities and "spy" not in alive_identities:
        return {"game_over": True, "winner": "lord", "message": "主公和忠臣获胜！"}
    return {"game_over": False}


__all__ = ["ModeSpec", "MODE_REGISTRY", "get_mode", "supported_modes", "identity_victory"]
