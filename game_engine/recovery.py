"""Versioned, JSON-only snapshots for process-crash recovery.

The snapshot is deliberately taken only at engine safe points.  Async tasks,
Futures, sockets and event handlers are reconstructed by the server and never
cross this boundary.
"""

from __future__ import annotations

import json
import os
from dataclasses import fields
from pathlib import Path
from typing import Any, Dict

from .behavior_ledger import LedgerEntry
from .skill_runtime_state import SkillStateStore
from .state_manager import Card, CardMoveEvent, Phase, Player, PlayerStatus


SNAPSHOT_VERSION = 1


def _card(card: Card) -> Dict[str, Any]:
    return {item.name: getattr(card, item.name) for item in fields(Card)}


def _encode(value: Any) -> Any:
    if isinstance(value, Card):
        return {"$card": value.id}
    if isinstance(value, Player):
        return {"$player": value.id}
    if isinstance(value, (Phase, PlayerStatus)):
        return {"$enum": value.value}
    if isinstance(value, tuple):
        return {"$tuple": [_encode(item) for item in value]}
    if isinstance(value, set):
        return {"$set": [_encode(item) for item in value]}
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        return {"$dict": [[_encode(key), _encode(item)] for key, item in value.items()]}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"recovery snapshot cannot encode {type(value).__name__}")


def _decode(value: Any, cards: Dict[str, Card], players: Dict[int, Player]) -> Any:
    if isinstance(value, list):
        return [_decode(item, cards, players) for item in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {"$card"}:
        return cards[value["$card"]]
    if set(value) == {"$player"}:
        return players[int(value["$player"])]
    if set(value) == {"$tuple"}:
        return tuple(_decode(item, cards, players) for item in value["$tuple"])
    if set(value) == {"$set"}:
        return {_decode(item, cards, players) for item in value["$set"]}
    if set(value) == {"$enum"}:
        raw = value["$enum"]
        return Phase(raw) if raw in {item.value for item in Phase} else PlayerStatus(raw)
    if set(value) == {"$dict"}:
        return {_decode(key, cards, players): _decode(item, cards, players)
                for key, item in value["$dict"]}
    return {key: _decode(item, cards, players) for key, item in value.items()}


def dump_engine(engine) -> Dict[str, Any]:
    state = engine.game_state
    all_cards: Dict[str, Card] = {}
    zones = [state.deck, state.discard_pile]
    for player in state.players:
        zones.extend([player.hand, player.judge_area, player.shown, player.temporary,
                      player.treasure_cards, list(player.equipment.values())])
    for zone in zones:
        for card in zone:
            if card.id in all_cards:
                raise ValueError(f"duplicate physical card id in snapshot: {card.id}")
            all_cards[card.id] = card

    players = []
    for player in state.players:
        players.append({
            "id": player.id, "name": player.name, "hero": _encode(player.hero),
            "identity": player.identity, "identity_revealed": player.identity_revealed,
            "hp": player.hp, "max_hp": player.max_hp, "status": player.status.value,
            "chained": player.chained, "alive": player.alive, "is_ai": player.is_ai,
            "ai_config": _encode(player.ai_config), "title": _encode(player.title),
            "flags": _encode(player.flags), "hand": [c.id for c in player.hand],
            "equipment": {slot: card.id for slot, card in player.equipment.items()},
            "judge_area": [c.id for c in player.judge_area], "shown": [c.id for c in player.shown],
            "temporary": [c.id for c in player.temporary],
            "treasure_cards": [c.id for c in player.treasure_cards],
            "sha_count": player.sha_count, "max_sha": player.max_sha,
            "jiu_used_this_turn": bool(getattr(player, "jiu_used_this_turn", False)),
            "jiu_buff": bool(getattr(player, "jiu_buff", False)),
        })
    payload = {
        "version": SNAPSHOT_VERSION, "game_id": engine.game_id,
        "profile_id": engine.game_config.get("profile_id"),
        "config": _encode(engine.game_config),
        "state": {
            "players": players, "cards": [_card(card) for card in all_cards.values()],
            "deck": [c.id for c in state.deck], "discard_pile": [c.id for c in state.discard_pile],
            "current_player_id": getattr(state.current_player, "id", None),
            "current_player_index": state.current_player_index,
            "current_phase": state.current_phase.value, "round_number": state.round_number,
            "round_anchor_index": state.round_anchor_index, "deck_id": state.deck_id,
            "initial_deck_count": state.initial_deck_count, "mode": state.mode,
            "event_queue": _encode(state.event_queue), "game_over": state.game_over,
            "winner": state.winner, "last_damage_source": state.last_damage_source,
            "card_move_sequence": state._card_move_sequence,
            "card_move_events": [event.to_dict() for event in state.card_move_events],
        },
        "engine": _encode({
            "completed_turns": engine.completed_turns, "request_seq": engine._request_seq,
            "effect_seq": engine._effect_seq, "log_seq": engine._log_seq,
            "game_log": engine.game_log, "usage_stats": engine.usage_stats,
            "decision_log": engine.decision_log, "chat_log": engine.chat_log,
            "blocked_chat": engine.blocked_chat, "chat_corrections": engine.chat_corrections,
            "table_chat": list(engine.table_chat), "chat_counts": engine._chat_counts,
            "shown_pool": engine.shown_pool, "spy_duel_lord": engine.spy_duel_lord,
            "spy_duel_lord_ready": engine._spy_duel_lord_ready,
            "notes_round": engine._notes_round, "request_outcomes": engine._request_outcomes,
            "trustee_active": engine._trustee_active, "trustee_source": engine._trustee_source,
            "trustee_config": engine._trustee_config, "trustee_failures": engine._trustee_failures,
            "trustee_degraded": engine._trustee_degraded,
            "trustee_degrade_reason": engine._trustee_degrade_reason,
            "trustee_generation": engine._trustee_generation,
        }),
        "stats": engine.stats.snapshot(),
        "skills": engine.skill_manager.skill_state.to_dict(),
        "skill_runtime": _encode({
            "activation_log": engine.skill_manager.activation_log,
            "dsl_actor_usage": engine.skill_manager._dsl_actor_usage,
            "loss_batches": engine.skill_manager._loss_batches,
            "skip_phases": engine.phase_controller.skip_phases,
        }),
        "ledger": {"seq": engine.ledger._seq, "entries": engine.ledger.snapshot()},
        "notes": _encode({key: getattr(engine.notes, key) for key in (
            "_notes", "_frozen", "_death_round", "_review", "high_guess_events",
            "_judged_round", "_changed", "snapshots")}),
        "ai_decision": _encode({key: getattr(engine.ai_decision, key) for key in (
            "_sessions", "last_failure", "last_reasoning", "last_meta", "_chat_seen",
            "notes_diagnostics", "plans", "last_situation_versions")}),
    }
    json.dumps(payload, ensure_ascii=False)
    return payload


def restore_engine(payload: Dict[str, Any], engine_class):
    if payload.get("version") != SNAPSHOT_VERSION:
        raise ValueError(f"unsupported recovery snapshot version: {payload.get('version')}")
    raw_state = payload["state"]
    card_ids = [row["id"] for row in raw_state["cards"]]
    zone_ids = list(raw_state["deck"]) + list(raw_state["discard_pile"])
    for row in raw_state["players"]:
        for name in ("hand", "judge_area", "shown", "temporary", "treasure_cards"):
            zone_ids.extend(row[name])
        zone_ids.extend(row["equipment"].values())
    if (len(card_ids) != len(set(card_ids)) or len(zone_ids) != len(set(zone_ids))
            or set(zone_ids) != set(card_ids)):
        raise ValueError("recovery snapshot has duplicate or unplaced physical cards")
    config = _decode(payload.get("config") or {}, {}, {})
    engine = engine_class(config)
    engine.game_id = str(payload["game_id"])
    cards = {row["id"]: Card(**row) for row in raw_state["cards"]}
    players: Dict[int, Player] = {}
    restored_players = []
    for row in raw_state["players"]:
        player = Player(id=int(row["id"]), name=row["name"])
        players[player.id] = player
        restored_players.append(player)
    for row in raw_state["players"]:
        player = players[int(row["id"])]
        player.hero = _decode(row["hero"], cards, players)
        player.identity = row["identity"]; player.identity_revealed = bool(row["identity_revealed"])
        player.hp = int(row["hp"]); player.max_hp = int(row["max_hp"])
        player.status = PlayerStatus(row["status"]); player.chained = bool(row["chained"])
        player.alive = bool(row["alive"]); player.is_ai = bool(row["is_ai"])
        player.ai_config = _decode(row["ai_config"], cards, players)
        player.title = _decode(row["title"], cards, players)
        player.flags = _decode(row["flags"], cards, players)
        player.hand = [cards[cid] for cid in row["hand"]]
        player.equipment = {slot: cards[cid] for slot, cid in row["equipment"].items()}
        for name in ("judge_area", "shown", "temporary", "treasure_cards"):
            setattr(player, name, [cards[cid] for cid in row[name]])
        player.sha_count = int(row["sha_count"]); player.max_sha = int(row["max_sha"])
        player.jiu_used_this_turn = bool(row.get("jiu_used_this_turn", False))
        player.jiu_buff = bool(row.get("jiu_buff", False))
    state = engine.game_state
    state.players = restored_players; state.deck = [cards[cid] for cid in raw_state["deck"]]
    state.discard_pile = [cards[cid] for cid in raw_state["discard_pile"]]
    state.current_player_index = int(raw_state["current_player_index"])
    state.current_player = players.get(raw_state["current_player_id"])
    state.current_phase = Phase(raw_state["current_phase"]); state.round_number = int(raw_state["round_number"])
    state.round_anchor_index = int(raw_state["round_anchor_index"]); state.deck_id = raw_state["deck_id"]
    state.initial_deck_count = int(raw_state["initial_deck_count"]); state.mode = raw_state["mode"]
    state.event_queue = _decode(raw_state["event_queue"], cards, players)
    state.game_over = bool(raw_state["game_over"]); state.winner = raw_state["winner"]
    state.last_damage_source = {int(k): v for k, v in raw_state["last_damage_source"].items()}
    state._card_move_sequence = int(raw_state["card_move_sequence"])
    state.card_move_events = [CardMoveEvent(**row) for row in raw_state["card_move_events"]]
    state.game_config = config

    values = _decode(payload["engine"], cards, players)
    mapping = {
        "completed_turns": "completed_turns", "request_seq": "_request_seq",
        "effect_seq": "_effect_seq", "log_seq": "_log_seq", "game_log": "game_log",
        "usage_stats": "usage_stats", "decision_log": "decision_log", "chat_log": "chat_log",
        "blocked_chat": "blocked_chat", "chat_corrections": "chat_corrections",
        "shown_pool": "shown_pool", "spy_duel_lord": "spy_duel_lord",
        "spy_duel_lord_ready": "_spy_duel_lord_ready", "notes_round": "_notes_round",
        "request_outcomes": "_request_outcomes", "trustee_active": "_trustee_active",
        "trustee_source": "_trustee_source", "trustee_config": "_trustee_config",
        "trustee_failures": "_trustee_failures", "trustee_degraded": "_trustee_degraded",
        "trustee_degrade_reason": "_trustee_degrade_reason", "trustee_generation": "_trustee_generation",
    }
    for source, target in mapping.items(): setattr(engine, target, values[source])
    engine.table_chat.clear(); engine.table_chat.extend(values["table_chat"])
    engine._chat_counts = values["chat_counts"]
    engine.stats.by_player = {int(pid): row for pid, row in payload["stats"].items()}
    engine.skill_manager.skill_state = SkillStateStore.from_dict(payload["skills"])
    runtime = _decode(payload["skill_runtime"], cards, players)
    engine.skill_manager.activation_log = runtime["activation_log"]
    engine.skill_manager._dsl_actor_usage = runtime["dsl_actor_usage"]
    engine.skill_manager._loss_batches = runtime["loss_batches"]
    engine.phase_controller.skip_phases = runtime["skip_phases"]
    engine.ledger.entries = [LedgerEntry(**row) for row in payload["ledger"]["entries"]]
    engine.ledger._seq = int(payload["ledger"]["seq"])
    notes = _decode(payload["notes"], cards, players)
    for key, value in notes.items(): setattr(engine.notes, key, value)
    ai_state = _decode(payload.get("ai_decision") or {"$dict": []}, cards, players)
    for key, value in ai_state.items():
        setattr(engine.ai_decision, key, value)
    engine._pending_requests.clear(); engine._pending_request_specs.clear(); engine._open_prompts.clear()
    engine._player_input = None; engine._waiting_for_action = False; engine._human_idle_since = None
    engine._restored_from_checkpoint = True
    return engine


class RecoveryStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def path(self, game_id: str) -> Path:
        if not game_id or any(ch not in "0123456789abcdef-" for ch in game_id.lower()):
            raise ValueError("invalid game id")
        return self.root / f"{game_id}.json"

    def save(self, engine) -> Path:
        return self.save_payload(engine.game_id, dump_engine(engine))

    def save_payload(self, game_id: str, payload: Dict[str, Any]) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.path(game_id); temporary = target.with_suffix(".json.tmp")
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with open(temporary, "w", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600); stream.write(text); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, target)
        return target

    def load(self, game_id: str) -> Dict[str, Any]:
        with open(self.path(game_id), encoding="utf-8") as stream:
            data = json.load(stream)
        if data.get("game_id") != game_id:
            raise ValueError("snapshot game id mismatch")
        return data

    def delete(self, game_id: str) -> None:
        try: self.path(game_id).unlink()
        except FileNotFoundError: pass
