#!/usr/bin/env python3
"""从data/skills.json生成54个运行时技能类，不生成TODO占位逻辑。"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FACTION_BY_HERO = {}
for hero in json.loads((ROOT / "data/heroes.json").read_text(encoding="utf-8")):
    FACTION_BY_HERO[hero["id"]] = {"魏": "wei", "蜀": "shu", "吴": "wu", "群": "qun"}.get(hero["faction"], hero["faction"])


def generate(active_factions):
    skills = json.loads((ROOT / "data/skills.json").read_text(encoding="utf-8"))
    lines = [
        "#!/usr/bin/env python3",
        '"""自动生成：27将54技能运行时元数据类。具体机制由势力处理器执行。"""',
        "",
        "from skill_runtime_core import RuntimeSkill",
        "",
    ]
    registry_lines = ["SKILL_REGISTRY = {"]
    hero_lines = ["HERO_SKILLS = {"]
    by_hero = {}
    for index, skill in enumerate(skills, start=1):
        faction = FACTION_BY_HERO[skill["owner_hero_id"]]
        status = "active" if faction in active_factions else "data_only"
        class_name = f"Skill_{skill['owner_hero_id']}_{index:02d}"
        lines.extend([
            f"class {class_name}(RuntimeSkill):",
            "    def __init__(self):",
            "        super().__init__(",
            f"            skill_id={skill['id']!r}, name={skill['name']!r},",
            f"            owner_hero_id={skill['owner_hero_id']!r}, skill_type={skill['type']!r},",
            f"            trigger_event={skill.get('trigger_event', 'PASSIVE')!r},",
            f"            forced={bool(skill.get('is_forced'))!r}, limited={bool(skill.get('is_limited'))!r},",
            f"            description={skill['description']!r}, faction={faction!r},",
            f"            implementation_status={status!r},",
            "        )",
            "",
        ])
        registry_lines.append(f"    {skill['id']!r}: {class_name},")
        by_hero.setdefault(skill["owner_hero_id"], []).append(skill["id"])
    registry_lines.extend(["}", ""])
    for hid, ids in by_hero.items():
        hero_lines.append(f"    {hid!r}: {ids!r},")
    hero_lines.extend(["}", ""])
    footer = [
        "def get_hero_skills(hero_id):",
        "    return [SKILL_REGISTRY[sid]() for sid in HERO_SKILLS.get(hero_id, [])]",
        "",
        "def get_all_skills():",
        "    return [cls() for cls in SKILL_REGISTRY.values()]",
        "",
        "__all__ = ['SKILL_REGISTRY', 'HERO_SKILLS', 'get_hero_skills', 'get_all_skills']",
        "",
    ]
    output = "\n".join(lines + registry_lines + hero_lines + footer)
    (ROOT / "game_engine/skills_generated.py").write_text(output, encoding="utf-8")
    return len(skills), sum(1 for s in skills if FACTION_BY_HERO[s["owner_hero_id"]] in active_factions)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--active-factions", default="shu", help="逗号分隔: wei,shu,wu,qun")
    args = parser.parse_args()
    active = {x.strip() for x in args.active_factions.split(",") if x.strip()}
    total, active_count = generate(active)
    print(f"生成完成：{total}技能类，active={active_count}，factions={sorted(active)}")
