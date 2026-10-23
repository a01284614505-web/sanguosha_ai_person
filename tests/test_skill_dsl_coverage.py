import json
from pathlib import Path

from game_engine.skill_dsl import compile_skill
from game_engine.skills_generated import get_all_skills


def test_coverage_manifest_contains_compilable_semantic_definitions_not_name_only_claims():
    manifest = json.loads((Path(__file__).resolve().parents[1] / "data" / "skill_dsl_coverage.json").read_text(encoding="utf-8"))
    definitions = manifest["definitions"]
    complete = [item for item in definitions if item.get("supported") is True]
    catalog = get_all_skills()
    catalog_names = {skill.name for skill in catalog}
    assert len(complete) == len({item["skill"] for item in complete})
    assert all(item["skill"] in catalog_names for item in complete)
    assert all(item.get("mapping") and compile_skill(item["dsl"]).steps > 0 for item in complete)
    assert len(catalog) == manifest["catalog_size"] == 54
    assert len(complete) / len(catalog) >= 0.6
