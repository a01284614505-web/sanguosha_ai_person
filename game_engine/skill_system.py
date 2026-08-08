#!/usr/bin/env python3
"""兼容入口：项目技能真相源为SkillManager与54个运行时技能类。

旧版Skill/SkillConfig/TODO触发框架已停用。新代码应直接导入skill_manager。
"""

from skill_manager import SkillManager, TriggerManager
from skill_runtime_core import RuntimeSkill
from skills_generated import SKILL_REGISTRY, get_all_skills, get_hero_skills

Skill = RuntimeSkill


def create_skill_from_data(skill_data):
    """按技能ID或“武将ID+技能名”解析真实运行时技能；找不到时不创建伪技能。"""
    if not isinstance(skill_data, dict):
        return None
    skill_id = skill_data.get("id")
    if skill_id in SKILL_REGISTRY:
        return SKILL_REGISTRY[skill_id]()
    owner = skill_data.get("owner_hero_id")
    name = skill_data.get("name")
    for skill in get_all_skills():
        if skill.name == name and (not owner or skill.owner_hero_id == owner):
            return skill
    return None


__all__ = [
    "Skill", "RuntimeSkill", "SkillManager", "TriggerManager",
    "SKILL_REGISTRY", "get_all_skills", "get_hero_skills", "create_skill_from_data",
]
