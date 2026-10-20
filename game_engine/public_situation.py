"""Versioned public and viewer-private game situation snapshots.

This module is deliberately read-only: it serializes facts already owned by the
engine and delegates rule-derived distance values to the engine's rule APIs.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .seats import seat_of
from .state_manager import card_to_dict


def _identity_is_public(engine, player) -> bool:
    return bool(getattr(player, "identity_revealed", False)
                or getattr(engine.game_state, "game_over", False))


def _player_public(engine, player) -> dict[str, Any]:
    hero = getattr(player, "hero", None) or {}
    identity = getattr(player, "identity", None) if _identity_is_public(engine, player) else None
    status = getattr(player, "status", None)
    equipment = getattr(player, "equipment", {}) or {}
    return {
        "id": player.id,
        "seat": seat_of(engine.game_state, player.id),
        "name": player.name,
        "hero_id": hero.get("id"),
        "hero_name": hero.get("name"),
        "hp": int(player.hp),
        "max_hp": int(player.max_hp),
        "alive": bool(player.alive),
        "identity": identity,
        "status": getattr(status, "value", status),
        "chained": bool(getattr(player, "chained", False)),
        "hand_count": int(player.get_hand_count()),
        "equipment": [
            {"slot": slot, "name": card.name}
            for slot, card in sorted(equipment.items())
        ],
        "judge_area": [card.name for card in getattr(player, "judge_area", [])],
        "shown": [card.name for card in getattr(player, "shown", [])],
        "treasure_count": len(getattr(player, "treasure_cards", [])),
        "sha_count": int(getattr(player, "sha_count", 0)),
        "max_sha": int(getattr(player, "max_sha", 1)),
        "attack_range": int(player.get_equipment_range()),
    }


def build_public_situation(engine) -> dict[str, Any]:
    """Build a JSON-safe public snapshot and stable content version."""
    state = engine.game_state
    alive = [player for player in state.players if player.alive]
    player_rows = [_player_public(engine, player) for player in state.players]
    discard = list(state.discard_pile)
    counts: dict[str, int] = {}
    for card in discard:
        counts[card.name] = counts.get(card.name, 0) + 1
    counts = dict(sorted(counts.items()))
    distances: dict[str, dict[str, int]] = {}
    for source in alive:
        targets: dict[str, int] = {}
        for target in alive:
            if target is source:
                continue
            distance = engine.rules.get_distance(source, target)
            distance = engine.skill_manager.modify_distance(source, target, distance)
            targets[str(target.id)] = int(distance)
        distances[str(source.id)] = targets

    phase = getattr(state, "current_phase", None)
    public = {
        "schema_version": 1,
        "event_seq": int(getattr(engine, "_log_seq", 0)),
        "card_move_seq": int(getattr(state, "_card_move_sequence", 0)),
        "round": int(getattr(state, "round_number", 0)),
        "phase": getattr(phase, "value", phase),
        "current_player_id": getattr(getattr(state, "current_player", None), "id", None),
        "deck_count": len(state.deck),
        "discard": {
            "count": len(discard),
            "by_name": counts,
            "latest": [card.name for card in discard[-12:]],
        },
        "players": player_rows,
        "distances": distances,
    }
    canonical = json.dumps(public, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    public["state_version"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return public


def build_private_situation(engine, viewer) -> dict[str, Any]:
    """Add only the viewer's cards and their existing cognitive notes."""
    viewer_id = getattr(viewer, "id", viewer)
    player = next((p for p in engine.game_state.players if p.id == viewer_id), None)
    if player is None:
        raise ValueError("viewer must identify a player in this game")
    notes = []
    note_store = getattr(engine, "notes", None)
    if note_store is not None and callable(getattr(note_store, "view", None)):
        notes = [
            {"target_id": target_id, **{
                key: entry[key] for key in ("guess", "conf", "why", "locked") if key in entry
            }}
            for target_id, entry in note_store.view(player.id).items()
        ]
    return {
        "schema_version": 1,
        "public_state_version": build_public_situation(engine)["state_version"],
        "viewer_id": player.id,
        "hand": [card_to_dict(card) for card in player.hand],
        "treasure": [card_to_dict(card) for card in player.treasure_cards],
        "cognitive_notes": notes,
    }


def compact_public_situation(view) -> str:
    """Return stable compact JSON suitable for a model prompt."""
    return json.dumps(view, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = ["build_public_situation", "build_private_situation", "compact_public_situation"]
