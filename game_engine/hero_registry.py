#!/usr/bin/env python3
'''武将注册表：权威加载、校验和开局武将分配。'''
import json
from copy import deepcopy
from pathlib import Path
class HeroRegistry:
    '''从 data/heroes.json 提供武将运行数据。'''
    def __init__(self, project_root=None):
        self.project_root = Path(
            project_root or Path(__file__).resolve().parents[1]
        ).resolve()
        self.heroes = self._load()
    def _load(self):
        path = self.project_root / "data" / "heroes.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"武将数据加载失败: {path}: {exc}") from exc
        heroes = data if isinstance(data, list) else data.get("heroes", [])
        if not isinstance(heroes, list) or not heroes:
            raise ValueError(f"武将数据为空或格式错误: {path}")
        ids = [hero.get("id") for hero in heroes]
        if any(not hero_id for hero_id in ids) or len(ids) != len(set(ids)):
            raise ValueError(f"武将数据存在空ID或重复ID: {path}")
        return heroes
    def all_heroes(self):
        return deepcopy(self.heroes)
    def count(self):
        return len(self.heroes)
    def hero_for_seat(self, seat, excluded=None):
        excluded = excluded or set()
        available = [hero for hero in self.heroes if hero.get("id") not in excluded]
        source = available or self.heroes
        if source:
            return deepcopy(source[seat % len(source)])
        return {
            "id": f"default_{seat}",
            "name": "默认武将",
            "faction": "群",
            "max_hp": 4,
            "skills": [],
        }
    def canonical_hero(self, candidate, seat=0, excluded=None):
        '''只信任 hero_id；体力、势力和技能从权威数据重建。'''
        candidate = candidate or {}
        hero_id = candidate.get("id") if isinstance(candidate, dict) else str(candidate)
        canonical = next(
            (hero for hero in self.heroes if hero.get("id") == hero_id), None
        )
        return deepcopy(canonical) if canonical else self.hero_for_seat(seat, excluded)
__all__ = ["HeroRegistry"]
