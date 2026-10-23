"""Content-bound machine-readable summary for Python/DSL parity evidence.

Parity means that two implementations agreed in listed scenarios. It does not
certify that either implementation matches a particular rules client/version.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "data" / "skill_parity_certification.json"
ENGINE_INPUTS = (
    "game_engine/main_engine.py",
    "game_engine/state_manager.py",
    "game_engine/card_flow.py",
    "game_engine/skill_dsl.py",
    "game_engine/skill_runtime_core.py",
    "game_engine/skill_runtime_state.py",
    "game_engine/skill_manager.py",
    "game_engine/skills_wei.py",
    "game_engine/skills_qun.py",
    "game_engine/skills_wu.py",
)
DSL_SOURCE = "data/skill_dsl_coverage.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_fingerprints(root: Path = ROOT) -> dict:
    dsl_manifest = root / DSL_SOURCE
    definitions = json.loads(dsl_manifest.read_text(encoding="utf-8"))["definitions"]
    skill_hashes = {
        item["skill"]: hashlib.sha256(
            json.dumps(item["dsl"], ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        for item in definitions if item.get("skill") in SKILL_SCOPES
    }
    engine_inputs = {name: _sha256(root / name) for name in ENGINE_INPUTS}
    engine_version = hashlib.sha256(json.dumps(
        engine_inputs, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    return {
        "dsl_manifest_sha256": _sha256(dsl_manifest),
        "dsl_sha256_by_skill": skill_hashes,
        "engine_version": engine_version,
        "engine_inputs_sha256": engine_inputs,
    }


SKILL_SCOPES = {
    "英姿": "draw phase; 3-card draw, skip-default and hand-limit modifier",
    "闭月": "end phase; empty/non-empty hand branch and accepted/declined prompt",
    "克己": "discard phase; Sha-used condition and accepted/declined prompt",
    "替身": "limited recovery/draw; accepted/declined prompt",
    "连营": "empty-hand trigger; target selection and draw",
    "天妒": "post-judgment accepted claim",
    "鬼才": "pre-judgment replacement using hand card",
    "鬼道": "black-card replacement; old-card claim and spade 2-9 draw",
    "奸雄": "damage-card claim and draw",
    "反馈": "per-damage-point transfer; accept then decline",
}

EVIDENCE = {
    "英姿": "tests/test_skill_dsl_parity.py::test_yingzi_dsl_matches_native_draw_and_skip_default_behavior",
    "闭月": "tests/test_skill_dsl_parity.py::test_biyue_dsl_matches_native_prompt_branch_draw_and_cost_decline",
    "克己": "tests/test_skill_dsl_parity.py::test_keji_dsl_matches_native_prompt_skip_and_sha_condition",
    "替身": "tests/test_skill_dsl_parity.py::test_tishen_dsl_matches_native_limited_recover_draw_and_decline",
    "连营": "tests/test_skill_dsl_parity.py::test_lianying_dsl_matches_native_empty_hand_selection_and_draws",
    "天妒": "tests/test_plan_b_parity.py::test_tiandu_dsl_matches_native_claim_of_judgment_card",
    "鬼才": "tests/test_plan_b_parity.py::test_guicai_dsl_matches_native_judgment_replacement_and_discard",
    "鬼道": "tests/test_plan_b_parity.py::test_guidao_dsl_matches_native_black_replacement_claim_and_spade_draw",
    "奸雄": "tests/test_plan_b_parity.py::test_jianxiong_dsl_matches_native_gain_damage_card_and_draw",
    "反馈": "tests/test_plan_b_parity.py::test_fankui_dsl_matches_native_card_transfer_per_damage_point_and_decline",
}


def build_report(root: Path = ROOT) -> dict:
    fingerprints = current_fingerprints(root)
    definitions = json.loads((root / DSL_SOURCE).read_text(encoding="utf-8"))["definitions"]
    by_name = {item["skill"]: item["dsl"] for item in definitions}
    return {
        "schema_version": 1,
        "evidence_type": "python_dsl_behavioral_parity",
        "generated_from": "data/skill_dsl_coverage.json",
        **fingerprints,
        "rules_version_verified": False,
        "interpretation": "Parity only: agreement does not establish correctness against a client/rules version.",
        "skills": [
            {
                "skill": name,
                "dsl_sha256": fingerprints["dsl_sha256_by_skill"].get(name),
                "status": "scenario_parity",
                "scenarios": [EVIDENCE[name]],
                "scope": SKILL_SCOPES[name],
                "branch_gaps": branch_gaps(name),
                "test_count": 1,
                "dsl_present": name in by_name,
            }
            for name in SKILL_SCOPES
        ],
        "supplemental_scenarios": [
            {
                "id": "decline_unmet_cancelled_selection",
                "status": "parity",
                "covers": ["declined confirm", "condition unmet without source card", "cancelled card selection"],
                "skills_covered": ["反馈"],
                "test": "tests/test_plan_b_certification.py::test_decline_unmet_and_cancelled_selection_match_native_and_dsl",
            },
            {
                "id": "engine_abort_during_interaction",
                "status": "parity",
                "covers": ["game ends during optional prompt", "pending effect does not commit"],
                "skills_covered": ["天妒"],
                "test": "tests/test_plan_b_certification.py::test_abort_during_optional_prompt_matches_native_and_dsl",
            },
            {
                "id": "dead_owner_dispatch",
                "status": "parity",
                "covers": ["dead owner while match continues", "terminal state after death", "no card movement"],
                "skills_covered": ["奸雄"],
                "test": "tests/test_plan_b_certification.py::test_dead_owner_and_multi_skill_cross_trigger_match_native_and_dsl",
            },
            {
                "id": "multi_skill_cross_trigger",
                "status": "parity",
                "covers": ["奸雄 then 反馈 on one damage event"],
                "skills_covered": ["奸雄", "反馈"],
                "test": "tests/test_plan_b_certification.py::test_dead_owner_and_multi_skill_cross_trigger_match_native_and_dsl",
            },
        ],
        "observed_divergences": [],
        "overall_status": "listed_scenarios_parity_with_branch_gaps",
    }


def branch_gaps(name: str) -> list[str]:
    gaps = {
        "英姿": ["no explicit dead/abort or multi-skill cross scene"],
        "闭月": ["no explicit engine-abort during interaction scene"],
        "克己": ["no explicit cancelled interaction result scene"],
        "替身": ["no explicit death during interaction scene"],
        "连营": ["no explicit cancelled target selection or multi-skill cross scene"],
        "天妒": ["decline and dead-owner branches not covered; abort during prompt is covered by supplemental scenario"],
        "鬼才": ["decline, cancelled card selection and dead-owner branches not covered by original test"],
        "鬼道": ["decline, no eligible black card and cancelled selection branches not covered by original test"],
        "奸雄": ["decline and unavailable event-card branches remain untested; dead-owner dispatch parity is covered by supplemental scenario"],
        "反馈": ["no source card and cancelled selection are covered by supplemental scenarios; zero-damage condition remains untested"],
    }
    return gaps[name]


def report_is_current(report: dict, root: Path = ROOT) -> bool:
    """False when either the catalog DSL or bound execution implementation changed."""
    expected = current_fingerprints(root)
    return all(report.get(key) == expected[key] for key in expected)


def write_report(path: Path = REPORT_PATH, root: Path = ROOT) -> dict:
    report = build_report(root)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    write_report()
