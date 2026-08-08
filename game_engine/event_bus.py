#!/usr/bin/env python3
"""同步事件总线。技能异步询问由TriggerManager负责。"""

from enum import Enum
from typing import Any, Callable, Dict, List


class EventType(Enum):
    GAME_START = "game_start"
    GAME_END = "game_end"
    ROUND_START = "round_start"
    ROUND_END = "round_end"

    PHASE_BEGIN = "phase_begin"
    PHASE_END = "phase_end"
    PHASE_PREPARE = "phase_prepare"
    PHASE_JUDGE = "phase_judge"
    PHASE_DRAW = "phase_draw"
    PHASE_PLAY = "phase_play"
    PHASE_DISCARD = "phase_discard"

    CARD_USE = "card_use"
    CARD_RESPOND = "card_respond"
    CARD_DISCARD = "card_discard"
    CARD_GAIN = "card_gain"
    CARD_LOSE = "card_lose"

    DAMAGE_BEGIN = "damage_begin"
    DAMAGE = "damage"
    DAMAGE_END = "damage_end"
    DAMAGE_SOURCE = "damage_source"

    HP_LOSE = "hp_lose"
    HP_RECOVER = "hp_recover"
    HP_CHANGE = "hp_change"
    DYING = "dying"
    DYING_END = "dying_end"
    DIE = "die"

    JUDGE_BEGIN = "judge_begin"
    JUDGE = "judge"
    JUDGE_END = "judge_end"
    SKILL_USE = "skill_use"
    SKILL_TRIGGER = "skill_trigger"


class GameEvent(dict):
    """兼容字典访问与属性访问的可变事件。"""

    def __init__(self, event_type: EventType, **kwargs):
        super().__init__(type=event_type, cancelled=False, **kwargs)

    @property
    def type(self):
        return self["type"]

    @property
    def cancelled(self):
        return self.get("cancelled", False)

    @cancelled.setter
    def cancelled(self, value):
        self["cancelled"] = bool(value)

    def cancel(self):
        self.cancelled = True

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


class EventBus:
    def __init__(self):
        self.listeners: Dict[EventType, List[Dict[str, Any]]] = {}

    def on(self, event_type: EventType, callback: Callable, priority: int = 0):
        self.listeners.setdefault(event_type, []).append(
            {"callback": callback, "priority": priority}
        )
        self.listeners[event_type].sort(key=lambda item: item["priority"], reverse=True)

    def off(self, event_type: EventType, callback: Callable):
        self.listeners[event_type] = [
            item for item in self.listeners.get(event_type, []) if item["callback"] != callback
        ]

    def emit(self, event: GameEvent) -> GameEvent:
        for listener in self.listeners.get(event.type, []):
            if event.cancelled:
                break
            try:
                listener["callback"](event)
            except Exception as exc:
                print(f"事件处理错误: {event.type.value} - {exc}")
        return event

    def trigger(self, event_type: EventType, **kwargs) -> GameEvent:
        return self.emit(GameEvent(event_type, **kwargs))


event_bus = EventBus()


def register_skill_trigger(skill_name: str, trigger_event: EventType, callback: Callable):
    event_bus.on(trigger_event, callback, priority=10)


__all__ = ["EventType", "GameEvent", "EventBus", "event_bus", "register_skill_trigger"]
