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
    assignment: str
    identities_public: bool
    victory: str
    draw_bonus_identity: str | None
    draw_bonus_per_phase: int

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
            "identities_public": self.identities_public,
            "victory": self.victory,
            "draw_bonus_identity": self.draw_bonus_identity,
            "draw_bonus_per_phase": self.draw_bonus_per_phase,
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
    assignment="shuffle",
    identities_public=False,
    victory="identity",
    draw_bonus_identity=None,
    draw_bonus_per_phase=0,
)

IDENTITY_EIGHT = ModeSpec(
    mode_id="8人身份局",
    player_count=8,
    identities=("lord", "loyalist", "loyalist", "rebel", "rebel", "rebel", "rebel", "spy"),
    initial_hand=4,
    first_player_identity="lord",
    lord_hp_bonus=1,
    turn_order="seat_clockwise",
    rebel_kill_draw=3,
    lord_kills_loyalist_discards=True,
    assignment="shuffle",
    identities_public=False,
    victory="identity",
    draw_bonus_identity=None,
    draw_bonus_per_phase=0,
)

TEAM_TWO_V_TWO = ModeSpec(
    mode_id="2v2",
    player_count=4,
    identities=("team_a", "team_b", "team_a", "team_b"),
    initial_hand=4,
    first_player_identity="team_a",
    lord_hp_bonus=0,
    turn_order="seat_clockwise",
    rebel_kill_draw=0,
    lord_kills_loyalist_discards=False,
    assignment="fixed",
    identities_public=True,
    victory="team_elimination",
    draw_bonus_identity=None,
    draw_bonus_per_phase=0,
)

LANDLORD = ModeSpec(
    mode_id="斗地主",
    player_count=3,
    identities=("landlord", "farmer", "farmer"),
    initial_hand=4,
    first_player_identity="landlord",
    lord_hp_bonus=1,
    turn_order="seat_clockwise",
    rebel_kill_draw=0,
    lord_kills_loyalist_discards=False,
    assignment="fixed",
    identities_public=True,
    victory="landlord",
    draw_bonus_identity="landlord",
    draw_bonus_per_phase=1,
)

MODE_REGISTRY = {
    IDENTITY_FIVE.mode_id: IDENTITY_FIVE,
    IDENTITY_EIGHT.mode_id: IDENTITY_EIGHT,
    TEAM_TWO_V_TWO.mode_id: TEAM_TWO_V_TWO,
    LANDLORD.mode_id: LANDLORD,
}


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
    players = list(players)
    alive_players = [player for player in players if player.alive]
    if spec.victory == "team_elimination":
        alive_teams = {player.identity for player in alive_players}
        if alive_teams == {"team_a"}:
            return {"game_over": True, "winner": "team_a", "message": "A队获胜！"}
        if alive_teams == {"team_b"}:
            return {"game_over": True, "winner": "team_b", "message": "B队获胜！"}
        return {"game_over": False}
    if spec.victory == "landlord":
        landlord = next((player for player in players if player.identity == "landlord"), None)
        farmers = [player for player in players if player.identity == "farmer"]
        if landlord is not None and not landlord.alive:
            return {"game_over": True, "winner": "farmer", "message": "农民获胜！"}
        if farmers and not any(player.alive for player in farmers):
            return {"game_over": True, "winner": "landlord", "message": "地主获胜！"}
        return {"game_over": False}
    if spec.victory != "identity":
        raise ValueError(f"模式尚未提供胜负实现: {mode_id}")
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


__all__ = ["ModeSpec", "MODE_REGISTRY", "IDENTITY_FIVE", "IDENTITY_EIGHT", "TEAM_TWO_V_TWO", "LANDLORD",
           "get_mode", "supported_modes", "identity_victory"]
