#!/usr/bin/env python3
"""真实对局统计：七项指标的唯一口径与记录入口（ROADMAP 7B-1）。

统计口径（与 UI 无关，全部在真实状态变化点记录）：
- damage_dealt / damage_taken：按技能修正后的最终伤害值计。自伤（来源==目标，
  如闪电）只计 damage_taken，不计 damage_dealt。
- healing：造成的实际治疗量（按最终生命增加量计，超过上限的部分不计）。
- kills：击杀归属给「最后一次对死者造成伤害的来源」；闪电等无来源或自己为自己的
  伤害不产生击杀，失去体力（非伤害）死亡同样不产生击杀。
- cards_played：实际使用/打出的手牌数（主动用牌、响应打出、技能转化的消耗牌）。
- cards_lost：实际失去的牌数（弃置、被拆、被拿、使用、响应、技能消耗等全部离开
  原持有者手牌或装备区的行为，以统一失去牌事件 on_cards_lost 为主口径）。
- skill_activations：实际发动技能次数（SkillManager.record 的 activate 事件）。

本模块不依赖前端，也不持久化；快照由引擎在 game_end 中下发。
"""

from typing import Dict, Iterable, List, Optional


STAT_KEYS = (
    "damage_dealt",
    "damage_taken",
    "healing",
    "kills",
    "cards_played",
    "cards_lost",
    "skill_activations",
)

# MVP 权重表（ROADMAP 7B-3）：击杀最重，伤害/治疗次之，技能与小牌数作为辅助项。
MVP_WEIGHTS = {
    "kills": 3.0,
    "damage_dealt": 1.0,
    "healing": 1.0,
    "skill_activations": 0.5,
    "cards_played": 0.2,
}


def empty_row() -> Dict[str, int]:
    return {key: 0 for key in STAT_KEYS}


class GameStats:
    """按玩家 id 维护七项计数器。"""

    def __init__(self, players: Iterable = ()):
        self.by_player: Dict[int, Dict[str, int]] = {}
        for player in players:
            self.ensure(player)

    def ensure(self, player) -> Dict[str, int]:
        return self.by_player.setdefault(player.id, empty_row())

    def add(self, player, key: str, amount: int = 1) -> None:
        if player is None or key not in STAT_KEYS:
            return
        try:
            delta = int(amount)
        except (TypeError, ValueError):
            return
        row = self.ensure(player)
        row[key] = max(0, row[key] + delta)

    def row(self, player) -> Dict[str, int]:
        return dict(self.by_player.get(player.id, empty_row()))

    def snapshot(self) -> Dict[int, Dict[str, int]]:
        return {pid: dict(row) for pid, row in self.by_player.items()}

    @staticmethod
    def score(row: Dict[str, int]) -> float:
        return round(sum(weight * row.get(key, 0) for key, weight in MVP_WEIGHTS.items()), 2)

    def mvp(self, players) -> Optional[Dict]:
        """全场最高分；同分依次比伤害、击杀，再按座次取小。全员零分（如主动终止局）返回 None。"""
        candidates = [
            p for p in players
            if p.id in self.by_player and self.score(self.by_player[p.id]) > 0
        ]
        if not candidates:
            return None
        ranked = sorted(
            candidates,
            key=lambda p: (
                -self.score(self.by_player[p.id]),
                -self.by_player[p.id]["damage_dealt"],
                -self.by_player[p.id]["kills"],
                p.id,
            ),
        )
        winner = ranked[0]
        row = dict(self.by_player[winner.id])
        hero = winner.hero or {}
        return {
            "player_id": winner.id,
            "player_name": winner.name,
            "hero_id": hero.get("id", ""),
            "hero_name": hero.get("name", ""),
            "score": self.score(row),
            **row,
        }


def record_stat(host, player, key: str, amount: int = 1) -> None:
    """安全记录入口：host 可为引擎、CardSystem、SkillManager 或测试替身。

    兼容测试中的 MagicMock 引擎与 engine=None 的裸调用点，缺失统计容器时静默跳过。
    """
    if host is None or player is None:
        return
    stats = getattr(host, "stats", None)
    add = getattr(stats, "add", None)
    if add is None:
        return
    add(player, key, amount)


def mark_damage_source(state, target, source) -> None:
    """记录最近一次伤害来源，供死亡时归属击杀；非真实 GameState（测试替身）静默跳过。"""
    store = getattr(state, "last_damage_source", None)
    if not isinstance(store, dict):
        return
    store[target.id] = getattr(source, "id", None)


def clear_damage_source(state, player) -> None:
    """失去体力等非伤害来源会覆盖死亡归属，防止旧伤害来源被错误计为击杀。"""
    store = getattr(state, "last_damage_source", None)
    if not isinstance(store, dict):
        return
    store[player.id] = None


def pop_kill_credit(state, player) -> Optional[int]:
    """玩家死亡时取出击杀来源 id；自伤/无来源返回 None。"""
    store = getattr(state, "last_damage_source", None)
    if not isinstance(store, dict):
        return None
    killer_id = store.pop(player.id, None)
    if not isinstance(killer_id, int) or killer_id == player.id:
        return None
    return killer_id


__all__ = [
    "STAT_KEYS", "MVP_WEIGHTS", "GameStats", "record_stat",
    "mark_damage_source", "clear_damage_source", "pop_kill_credit",
]
