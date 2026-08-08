#!/usr/bin/env python3
"""同步技能实现状态到运行时武将、技能索引和AI世界书。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENGINE = ROOT / "game_engine"
sys.path.insert(0, str(ENGINE))

from skills_generated import get_all_skills


def atomic_write(path: Path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main():
    definitions = get_all_skills()
    by_owner_name = {(s.owner_hero_id, s.name): s for s in definitions}
    by_id = {s.skill_id: s for s in definitions}

    skills_path = ROOT / "data/skills.json"
    skills = json.loads(skills_path.read_text(encoding="utf-8"))
    for item in skills:
        runtime = by_id[item["id"]]
        item["implementation_status"] = runtime.implementation_status
        item["runtime_class"] = type(runtime).__name__
        item["engine_authority"] = "技能仅通过引擎合法操作和事件钩子执行"
    atomic_write(skills_path, skills)

    heroes_path = ROOT / "data/heroes.json"
    heroes = json.loads(heroes_path.read_text(encoding="utf-8"))
    for hero in heroes:
        for item in hero.get("skills", []):
            runtime = by_owner_name[(hero["id"], item["name"])]
            item["implementation_status"] = runtime.implementation_status
            item["runtime_class"] = type(runtime).__name__
        hero.setdefault("worldbook", {})["runtime_status"] = {
            "active_skills": [x["name"] for x in hero.get("skills", []) if x["implementation_status"] == "active"],
            "data_only_skills": [x["name"] for x in hero.get("skills", []) if x["implementation_status"] != "active"],
        }
    atomic_write(heroes_path, heroes)

    wb_path = ROOT / "worldbook_generated/heroes/heroes_27_complete.json"
    wb = json.loads(wb_path.read_text(encoding="utf-8"))
    for hero in wb["heroes"]:
        for item in hero.get("skills", []):
            runtime = by_owner_name[(hero["id"], item["name"])]
            status = runtime.implementation_status
            item["implementation_status"] = status
            item["runtime_class"] = type(runtime).__name__
            base = item.get("worldbook", item.get("description", ""))
            if status == "active":
                note = "运行状态：已接入游戏引擎。AI只能在引擎提供该技能的合法操作时发动，目标和成本必须来自合法列表。"
            else:
                note = "运行状态：仅知识数据，当前不可发动；AI不得自行构造此技能操作。"
            item["worldbook"] = base.split("\n运行状态：", 1)[0] + "\n" + note
    wb.setdefault("meta", {})["runtime_skill_classes"] = len(definitions)
    wb["meta"]["active_skill_classes"] = sum(s.implementation_status == "active" for s in definitions)
    atomic_write(wb_path, wb)

    print(json.dumps({
        "runtime_classes": len(definitions),
        "active": sum(s.implementation_status == "active" for s in definitions),
        "heroes": len(heroes),
        "worldbook_heroes": len(wb["heroes"]),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
