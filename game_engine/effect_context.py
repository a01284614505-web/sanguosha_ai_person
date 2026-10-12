"""Serializable context carried while one card or skill effect resolves."""

from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from .state_manager import Card


def _json_value(value: Any) -> Any:
    """Convert event payload values to JSON-compatible values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_value(to_dict())
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    raise TypeError(f"EffectContext value is not serializable: {type(value).__name__}")


@dataclass
class EffectContext:
    """Runtime and serializable state for a single effect resolution.

    ``card`` keeps the live card object for engine consumers. ``to_dict`` emits
    its value fields, and never exposes the Python object itself.
    """

    effect_id: str
    sequence: int = 0
    card: Optional[Card] = None
    card_cost_ids: Optional[List[str]] = None
    skill_source: Optional[str] = None
    source_id: Optional[int] = None
    current_target_id: Optional[int] = None
    damage_nature: Optional[str] = None
    cancelled_target_ids: Optional[List[int]] = None
    pending_events: Optional[List[Any]] = None
    abort_reason: Optional[str] = None
    status: str = "active"

    def __post_init__(self):
        self.card_cost_ids = list(self.card_cost_ids or [])
        self.cancelled_target_ids = list(self.cancelled_target_ids or [])
        self.pending_events = list(self.pending_events or [])

    @classmethod
    def from_entity_card(
        cls,
        effect_id: str,
        card: Card,
        source_id: Optional[int],
        *,
        current_target_id: Optional[int] = None,
        damage_nature: Optional[str] = None,
        sequence: int = 0,
    ) -> "EffectContext":
        """Create a context for an effect played with one physical card."""
        return cls(
            effect_id=effect_id,
            sequence=sequence,
            card=card,
            card_cost_ids=[card.id],
            source_id=source_id,
            current_target_id=current_target_id,
            damage_nature=damage_nature or card.nature,
        )

    @classmethod
    def from_skill_virtual_card(
        cls,
        effect_id: str,
        card: Card,
        card_cost_ids: List[str],
        skill_source: str,
        source_id: Optional[int],
        *,
        current_target_id: Optional[int] = None,
        damage_nature: Optional[str] = None,
        sequence: int = 0,
    ) -> "EffectContext":
        """Create a context for a virtual card produced by a skill.

        The virtual card remains the effect card; the physical payment cards
        are preserved separately by their entity IDs.
        """
        return cls(
            effect_id=effect_id,
            sequence=sequence,
            card=card,
            card_cost_ids=list(card_cost_ids),
            skill_source=skill_source,
            source_id=source_id,
            current_target_id=current_target_id,
            damage_nature=damage_nature or card.nature,
        )

    def next_sequence(self) -> int:
        """Advance and return the sequence number for the next effect step."""
        self.sequence += 1
        return self.sequence

    def cancel_target(self, target_id: int) -> bool:
        """Record a cancelled target once; return whether it was newly added."""
        if target_id in self.cancelled_target_ids:
            return False
        self.cancelled_target_ids.append(target_id)
        if self.current_target_id == target_id:
            self.current_target_id = None
        return True

    def abort(self, reason: str) -> None:
        """Mark the effect as aborted and preserve the reason for consumers."""
        self.abort_reason = reason
        self.status = "aborted"

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-compatible representation of the context."""
        card = None
        if self.card is not None:
            card = {
                "id": self.card.id,
                "name": self.card.name,
                "suit": self.card.suit,
                "rank": self.card.rank,
                "card_type": self.card.card_type,
                "effect": self.card.effect,
                "target_rule": _json_value(self.card.target_rule),
                "sub_type": self.card.sub_type,
                "nature": self.card.nature,
            }
        return {
            "effect_id": self.effect_id,
            "sequence": self.sequence,
            "card": card,
            "card_cost_ids": list(self.card_cost_ids),
            "skill_source": self.skill_source,
            "source_id": self.source_id,
            "current_target_id": self.current_target_id,
            "damage_nature": self.damage_nature,
            "cancelled_target_ids": list(self.cancelled_target_ids),
            "pending_events": _json_value(self.pending_events),
            "abort_reason": self.abort_reason,
            "status": self.status,
        }


__all__ = ["EffectContext"]
