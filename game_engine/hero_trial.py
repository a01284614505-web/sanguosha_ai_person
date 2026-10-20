"""Run a validated draft hero in deterministic, in-memory real-engine scenes."""
from __future__ import annotations

import asyncio
import copy
import random
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .hero_package_store import FACTIONS, PACKAGE_ID, HeroImportError, HeroPackageStore
from .main_engine import MainEngine
from .protocol import ENGINE_EVENT
from .skill_dsl import SkillDSLRuntimeLimitError
from .skills_generated import get_all_skills
from .state_manager import Card, Phase


SCENARIO_IDS = frozenset({
    "active_choose_target",
    "damage_received",
    "phase_draw",
    "cancel_activation",
})
OUTCOMES = frozenset({
    "success", "declined", "not_triggered", "compile_error",
    "runtime_error", "budget_exhausted", "aborted",
})


class HeroTrialError(ValueError):
    def __init__(self, message: str, *, code="invalid_request", outcome="compile_error",
                 scenario_id=None, seed=None):
        super().__init__(message)
        self.code = code
        self.outcome = outcome
        self.scenario_id = scenario_id
        self.seed = seed


def empty_trial(outcome: str, summary: str, *, scenario_id=None, seed=None,
                diagnostics=None) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "scenario_id": scenario_id,
        "seed": seed,
        "outcome": outcome,
        "summary": summary,
        "diagnostics": list(diagnostics or []),
        "trace": [],
        "choices": [],
        "card_moves": [],
        "state_diff": [],
        "final_state": None,
    }


def error_trial(exc: Exception, *, scenario_id=None, seed=None) -> Dict[str, Any]:
    outcome = getattr(exc, "outcome", "runtime_error")
    if outcome not in OUTCOMES:
        outcome = "runtime_error"
    message = str(exc) or "试运行失败"
    return empty_trial(
        outcome,
        message,
        scenario_id=getattr(exc, "scenario_id", None) or scenario_id,
        seed=getattr(exc, "seed", None) if getattr(exc, "seed", None) is not None else seed,
        diagnostics=[{
            "level": "error",
            "code": getattr(exc, "code", "runtime_error"),
            "message": message,
        }],
    )


def _validate_request(payload: Any, project_root=None):
    if not isinstance(payload, dict):
        raise HeroTrialError("请求体必须是 JSON 对象")
    allowed = {"package", "hero", "scenario_id", "seed"}
    extra = set(payload) - allowed
    if extra:
        raise HeroTrialError("请求体含未知字段: " + ", ".join(sorted(map(str, extra))))
    scenario_id = payload.get("scenario_id")
    seed = payload.get("seed")
    if scenario_id not in SCENARIO_IDS:
        raise HeroTrialError("scenario_id 无效", scenario_id=scenario_id, seed=seed)
    if type(seed) is not int or not 0 <= seed <= 2_147_483_647:
        raise HeroTrialError("seed 必须是 0..2147483647 的整数", scenario_id=scenario_id)
    package = payload.get("package")
    if not isinstance(package, dict) or set(package) - {"id", "name", "version"}:
        raise HeroTrialError("package 只允许 id/name/version", scenario_id=scenario_id, seed=seed)
    package_id = str(package.get("id") or "").strip()
    package_name = str(package.get("name") or "").strip()
    version = str(package.get("version") or "1.0")
    if not PACKAGE_ID.fullmatch(package_id):
        raise HeroTrialError("package.id 格式无效", scenario_id=scenario_id, seed=seed)
    if not package_name or len(package_name) > 80 or len(version) > 32:
        raise HeroTrialError("package.name/version 无效", scenario_id=scenario_id, seed=seed)
    store = HeroPackageStore(project_root)
    try:
        hero = store._validate_hero(payload.get("hero"))
        current = store._read_current()
        base = store._base_data()
    except (HeroImportError, TypeError, ValueError) as exc:
        raise HeroTrialError(str(exc), code="compile_error", scenario_id=scenario_id, seed=seed) from exc
    except (OSError, RuntimeError) as exc:
        raise HeroTrialError("武将包存储损坏，无法完成与正式导入相同的冲突检查",
                             code="package_store_error", scenario_id=scenario_id, seed=seed) from exc
    if hero["faction"] not in FACTIONS:
        raise HeroTrialError("hero.faction 无效", scenario_id=scenario_id, seed=seed)
    existing_package = next((item for item in current["packages"] if item["id"] == package_id), None)
    if existing_package is not None and (existing_package["name"], existing_package["version"]) != (package_name, version):
        raise HeroTrialError("同一 package.id 的 name/version 不可修改",
                             code="package_conflict", scenario_id=scenario_id, seed=seed)
    existing_heroes = {item.get("id") for item in base}
    existing_heroes.update(item.get("id") for row in current["packages"] for item in row.get("heroes", []))
    if hero["id"] in existing_heroes:
        raise HeroTrialError("hero.id 已存在，正式导入会冲突",
                             code="hero_conflict", scenario_id=scenario_id, seed=seed)
    existing_skills = {skill.name for skill in get_all_skills()}
    existing_skills.update(skill["name"] for row in current["packages"]
                           for item in row.get("heroes", []) for skill in item.get("skills", []))
    conflict = next((skill["name"] for skill in hero["skills"] if skill["name"] in existing_skills), None)
    if conflict:
        raise HeroTrialError(f"技能名冲突: {conflict}", code="skill_conflict",
                             scenario_id=scenario_id, seed=seed)
    return {"id": package_id, "name": package_name, "version": version}, hero, scenario_id, seed


def _fixture_card(index: int) -> Card:
    specs = [
        ("杀", "spade", 7, "basic"), ("闪", "heart", 2, "basic"),
        ("桃", "diamond", 3, "basic"), ("酒", "club", 9, "basic"),
        ("过河拆桥", "spade", 4, "trick"), ("无中生有", "heart", 8, "trick"),
    ]
    name, suit, rank, kind = specs[index % len(specs)]
    return Card(f"trial_{index}", name, suit, rank, kind)


def _public_state(engine: MainEngine) -> Dict[str, Any]:
    state = engine.game_state

    def card_summary(card: Card) -> Dict[str, Any]:
        # The trial runs entirely in a disposable sandbox.  These are public
        # zones, so exposing card identity here helps an author understand the
        # effect without revealing any player's hidden hand or Ox contents.
        return {"id": card.id, "name": card.name}

    def public_marks(player) -> Dict[str, Any]:
        flags = player.flags or {}
        marks: Dict[str, Any] = {}
        for key in ("hand_limit_bonus", "cannot_use_hand", "nonlocked_disabled",
                    "pao_tokens", "rende_count", "sha_used_this_turn",
                    "trick_used_this_turn"):
            value = flags.get(key)
            if isinstance(value, (bool, int, float, str)) and value not in (False, 0, ""):
                marks[key] = value
        used = flags.get("skill_used")
        if isinstance(used, dict):
            marks["skill_used"] = {
                str(key): _safe(value) for key, value in sorted(used.items(), key=lambda row: str(row[0]))
            }
        return marks

    return {
        "players": [{
            "id": p.id, "name": p.name, "hp": p.hp, "max_hp": p.max_hp,
            "alive": bool(p.alive), "hand_count": len(p.hand),
            "status": getattr(p.status, "value", str(p.status)),
            "chained": bool(getattr(p, "chained", False)),
            "sha_count": int(getattr(p, "sha_count", 0)),
            "max_sha": int(getattr(p, "max_sha", 1)),
            "jiu_used_this_turn": bool(getattr(p, "jiu_used_this_turn", False)),
            "equipment": {
                str(slot): card_summary(card)
                for slot, card in sorted(p.equipment.items())
            },
            "judge_area": [card_summary(card) for card in p.judge_area],
            "shown": [card_summary(card) for card in p.shown],
            # 木牛流马牌与 temporary 区可能含暗牌；只公布数量。
            "treasure_count": len(p.treasure_cards),
            "temporary_count": len(p.temporary),
            "marks": public_marks(p),
            "skill_state": [
                _safe(instance.to_dict())
                for instance in engine.skill_manager.skill_state.for_owner(p.id)
            ],
        } for p in state.players],
        "deck_count": len(state.deck),
        "discard_count": len(state.discard_pile),
        "discard": [card_summary(card) for card in state.discard_pile],
        "round": state.round_number,
        "phase": getattr(state.current_phase, "value", None),
        "current_player_id": getattr(state.current_player, "id", None),
    }


def _card_names(engine: MainEngine) -> Dict[str, str]:
    state = engine.game_state
    cards = list(state.deck) + list(state.discard_pile)
    for player in state.players:
        cards.extend(player.hand)
        cards.extend(player.judge_area)
        cards.extend(player.shown)
        cards.extend(player.temporary)
        cards.extend(player.treasure_cards)
        cards.extend(player.equipment.values())
    return {card.id: card.name for card in cards}


def _diff(before: Any, after: Any, path="") -> List[Dict[str, Any]]:
    if type(before) is not type(after):
        return [{"path": path or "$", "before": before, "after": after}]
    if isinstance(before, dict):
        rows = []
        for key in sorted(set(before) | set(after)):
            rows.extend(_diff(before.get(key), after.get(key), f"{path}.{key}" if path else key))
        return rows
    if isinstance(before, list):
        rows = []
        for index in range(max(len(before), len(after))):
            left = before[index] if index < len(before) else None
            right = after[index] if index < len(after) else None
            rows.extend(_diff(left, right, f"{path}[{index}]"))
        return rows
    return [] if before == after else [{"path": path or "$", "before": before, "after": after}]


def _safe(value: Any):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()
                if not str(key).startswith("_")}
    if hasattr(value, "id"):
        return {"id": getattr(value, "id", None), "name": getattr(value, "name", None)}
    return str(value)


class _TrialHarness:
    def __init__(self, hero, scenario_id: str, seed: int):
        self.scenario_id = scenario_id
        self.rng = random.Random(seed)
        self.choices: List[Dict[str, Any]] = []
        self.trace: List[Dict[str, Any]] = []
        self.runtime_runs: List[Dict[str, Any]] = []
        self.engine = MainEngine({
            "mode": "5人身份局",
            "player": {"name": hero["name"], "hero": copy.deepcopy(hero), "is_ai": True,
                       "ai_config": {"api_key": "test_key"}},
            "ais": [{"name": f"试验对手{i}", "hero": {"id": f"trial_dummy_{i}",
                     "name": f"试验对手{i}", "faction": "群", "max_hp": 4,
                     "skills": []}}
                    for i in range(1, 5)],
            "phase_delay": 0, "turn_delay": 0, "_rng": self.rng,
        })
        self.owner = self.engine.game_state.players[0]
        self._prepare_state()
        self._install_trace()
        self._install_choices()
        self._install_runtime_trace()

    def _prepare_state(self):
        state = self.engine.game_state
        for player in state.players:
            player.hand.clear()
            player.equipment.clear()
            player.judge_area.clear()
            player.shown.clear()
            player.temporary.clear()
            player.treasure_cards.clear()
            player.alive = True
            player.hp = player.max_hp
        self.owner.hand.extend([_fixture_card(20), _fixture_card(21), _fixture_card(22)])
        for offset, player in enumerate(state.players[1:], start=1):
            player.hand.append(_fixture_card(30 + offset))
        state.deck[:] = [_fixture_card(index) for index in range(12)]
        state.discard_pile.clear()
        state.card_move_events.clear()
        state.current_player = self.owner
        state.current_player_index = 0
        state.current_phase = Phase.PLAY
        identities = ["lord", "rebel", "loyalist", "spy", "rebel"]
        for player, identity in zip(state.players, identities):
            player.identity = identity
            player.identity_revealed = player is self.owner
        self.engine.skill_manager.bind_engine(self.engine)

    def _append_trace(self, event: str, **detail):
        self.trace.append({"seq": len(self.trace) + 1, "event": event, **_safe(detail)})

    def _install_trace(self):
        async def handler_factory(event_name, **data):
            kept = {key: value for key, value in data.items()
                    if key in {"event_kind", "message", "phase", "skipped", "status",
                               "player_id", "actor_id", "skill_name"}}
            self._append_trace(event_name, detail=kept)
        for event_name in (ENGINE_EVENT.EVENT_NOTIFICATION, ENGINE_EVENT.SELECTION_RESULT,
                           ENGINE_EVENT.CARD_MOVE, ENGINE_EVENT.DECISION_TRACE):
            async def handler(_event=event_name, **data):
                await handler_factory(_event, **data)
            self.engine.on(event_name, handler)

    def _script_choice(self, _player, request):
        kind = request.get("kind")
        cancelling = self.scenario_id == "cancel_activation"
        if kind == "confirm":
            return [1] if cancelling else [0]
        if cancelling:
            return []
        count = max(0, int(request.get("min_n", 1)))
        options = request.get("options") or []
        if not options or count == 0:
            return []
        start = self.rng.randrange(len(options))
        order = list(range(start, len(options))) + list(range(0, start))
        return order[:count]

    def _install_choices(self):
        self.engine.ai_decision.simple_choice_decision = self._script_choice
        original = self.engine.request_choice

        async def request_choice(player, request):
            result = await original(player, request)
            selected = []
            for key in ("players", "cards"):
                selected.extend(_safe(result.get(key) or []))
            if result.get("choice") is not None:
                selected.append(_safe(result["choice"]))
            if "confirmed" in result:
                selected.append(bool(result["confirmed"]))
            cancelled = result.get("status") in {"cancelled", "invalid"} or (
                request.get("kind") == "confirm" and result.get("confirmed") is False)
            self.choices.append({
                "prompt": str(request.get("prompt") or ""),
                "kind": str(request.get("kind") or ""),
                "selected": selected,
                "cancelled": bool(cancelled),
            })
            return result
        self.engine.request_choice = request_choice

    def _install_runtime_trace(self):
        runtime = self.engine.skill_manager.dsl_runtime
        original = runtime.run

        async def run(compiled, owner, event, skill_name=None):
            self._append_trace("skill_trigger", skill_name=skill_name, actor_id=owner.id,
                               detail={"trigger": compiled.program.get("trigger")})
            result = await original(compiled, owner, event, skill_name)
            row = {"skill_name": skill_name, "trigger": event.get("trigger") or compiled.program.get("trigger"),
                   "executed": bool(result)}
            self.runtime_runs.append(row)
            self._append_trace("skill_result", skill_name=skill_name, actor_id=owner.id,
                               detail={"executed": bool(result)})
            return result
        runtime.run = run

    def _active_programs(self):
        return [(skill["name"], skill["dsl"]) for skill in (self.owner.hero or {}).get("skills", [])
                if skill.get("implementation_status") == "active" and isinstance(skill.get("dsl"), dict)]

    @staticmethod
    def _is_interactive(program):
        if program.get("cost"):
            return True
        if (program.get("targets") or {}).get("selector") == "chosen_players":
            return True
        return any(effect.get("type") == "interact" for effect in program.get("effects", []))

    async def execute(self):
        scenario = self.scenario_id
        programs = self._active_programs()
        relevant: List[str] = []
        if scenario in {"active_choose_target", "cancel_activation"}:
            candidates = [(name, program) for name, program in programs
                          if program.get("trigger") == "play_action"
                          and (scenario != "active_choose_target" or self._is_interactive(program))
                          and (scenario != "cancel_activation" or self._is_interactive(program))]
            if not candidates:
                return relevant
            name, _program = candidates[0]
            relevant = [name]
            action = next((item for item in self.engine.skill_manager.get_actions(self.owner)
                           if item.get("variant") == "dsl" and item.get("skill_name") == name), None)
            if action is not None:
                await self.engine.skill_manager.execute(self.owner, action, [])
        elif scenario == "damage_received":
            relevant = [name for name, program in programs
                        if "damage_received" in program.get("triggers", [program.get("trigger")])]
            source = self.engine.game_state.players[1]
            damage_card = Card("trial_damage", "杀", "heart", 7, "basic")
            await self.engine.card_system.damage(source, self.owner, 1, damage_card,
                                                 {"reason": "skill_trial"})
        elif scenario == "phase_draw":
            relevant = [name for name, program in programs
                        if "phase_start" in program.get("triggers", [program.get("trigger")])]
            self.engine.skill_manager.reset_turn_scope(self.owner)
            await self.engine._enter_phase(self.owner, Phase.DRAW)
            await self.engine._execute_phase_with_ui(Phase.DRAW)
        return relevant


async def _run(payload: Any, project_root=None) -> Dict[str, Any]:
    package, hero, scenario_id, seed = _validate_request(payload, project_root)
    diagnostics = [{
        "level": "info", "code": "draft_validated",
        "message": f"草稿包 {package['id']} 已在内存中校验；未写入正式包存储。",
    }]
    for skill in hero.get("skills", []):
        if skill.get("implementation_status") == "active":
            diagnostics.append({
                "level": "info", "code": "compiled",
                "message": "DSL 编译通过", "skill_name": skill["name"],
            })
    harness = _TrialHarness(hero, scenario_id, seed)
    before = _public_state(harness.engine)
    try:
        relevant = await harness.execute()
    except SkillDSLRuntimeLimitError as exc:
        raise HeroTrialError(str(exc), code="budget_exhausted", outcome="budget_exhausted",
                             scenario_id=scenario_id, seed=seed) from exc
    after = _public_state(harness.engine)
    executed = {row["skill_name"] for row in harness.runtime_runs if row["executed"]}
    cancelled = any(row["cancelled"] for row in harness.choices)
    runtime_diagnostics = [row for row in harness.engine.skill_manager.dsl_runtime.diagnostics
                           if not relevant or row.get("skill_name") in relevant]
    for row in runtime_diagnostics:
        status = row.get("status", "runtime_rejected")
        diagnostics.append({
            "level": "error" if status in {"budget_exhausted", "effect_rejected"} else
                     "warning" if status != "success" else "info",
            "code": status,
            "message": {
                "success": "技能运行并完成结算",
                "condition_false": "技能条件不满足",
                "declined": "预设选择取消了技能",
                "budget_exhausted": "技能运行预算耗尽，已由运行时禁用",
                "usage_unavailable": "技能使用次数或充能不足",
            }.get(status, "技能运行被引擎拒绝"),
            "skill_name": row.get("skill_name"),
        })
    budget_exhausted = any(row.get("status") == "budget_exhausted"
                           for row in runtime_diagnostics)
    runtime_declined = any(row.get("status") == "declined" for row in runtime_diagnostics)
    if harness.engine.game_aborted:
        outcome, summary = "aborted", "试验局被引擎中止"
    elif budget_exhausted:
        outcome, summary = "budget_exhausted", "技能运行预算耗尽，运行时已停止并禁用该技能"
    elif scenario_id == "cancel_activation" and cancelled:
        outcome, summary = "declined", "已按预设取消发动，未提交技能效果"
    elif executed.intersection(relevant):
        outcome, summary = "success", "预设场景中的技能已通过真实引擎触发并结算"
    elif not relevant:
        outcome, summary = "not_triggered", "草稿中没有与此预设场景匹配的 active DSL 技能"
        diagnostics.append({"level": "warning", "code": "scenario_not_supported",
                            "message": summary})
    elif cancelled or runtime_declined:
        outcome, summary = "declined", "预设选择取消了技能发动"
    else:
        outcome, summary = "not_triggered", "技能已进入触发检查，但条件或候选不满足"
        diagnostics.append({"level": "warning", "code": "condition_or_candidates_rejected",
                            "message": summary, "skill_name": relevant[0]})
    names = _card_names(harness.engine)
    moves = [{
        "card_id": event.card_id,
        "card_name": names.get(event.card_id, ""),
        "from": event.from_zone,
        "to": event.to_zone,
        "owner_id": event.from_owner,
        "target_id": event.to_owner,
        "reason": event.reason,
    } for event in harness.engine.game_state.card_move_events]
    return {
        "schema_version": 1,
        "scenario_id": scenario_id,
        "seed": seed,
        "outcome": outcome,
        "summary": summary,
        "diagnostics": diagnostics,
        "trace": harness.trace,
        "choices": harness.choices,
        "card_moves": moves,
        "state_diff": _diff(before, after),
        "final_state": after,
    }


def run_hero_trial(payload: Any, project_root: Path | str | None = None) -> Dict[str, Any]:
    """Synchronous HTTP boundary for the isolated async engine scene."""
    return asyncio.run(_run(payload, project_root))
