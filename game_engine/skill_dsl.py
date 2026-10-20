"""受限的、声明式技能 DSL。只接受 JSON 数据，执行能力由白名单 Runtime 提供。"""
from __future__ import annotations

from copy import deepcopy
from contextvars import ContextVar
from dataclasses import dataclass
import logging
from typing import Any, Dict, Iterable, List, Mapping

from . import card_flow
from .skill_runtime_core import card_color

logger = logging.getLogger(__name__)

MAX_STEPS = 100
TRIGGERS = {
    "turn_start", "phase_start", "phase_end", "damage_received", "damage_dealt", "recover", "hp_lost",
    "card_gained", "card_used", "card_responded", "judge_before", "judge_after",
    "play_action", "cards_lost", "sha_dodged", "multi_target_trick",
}
INTERACTIONS = {"ask_confirm", "ask_choose_players", "ask_choose_cards", "ask_choose_option"}
EFFECTS = {"draw_cards", "transfer_card", "discard_card", "judge", "damage", "recover", "lose_hp", "announce", "gain_judged_card", "replace_judgment", "gain_event_card", "duel", "exclude_targets", "interact", "repeat", "set_state", "set_local"}
CONDITION_OPS = {"all", "any", "not", "eq", "ne", "gt", "gte", "lt", "lte", "in", "exists"}
ROOTS = {"owner", "event", "game", "locals", "state"}
TOP_KEYS = {"version", "trigger", "triggers", "condition", "cost", "targets", "effects", "description", "skip_default", "usage", "modifiers", "conversions", "action_actors"}
_ACTIVE_BUDGET = ContextVar("skill_dsl_budget", default=None)
_ACTIVE_SKILLS = ContextVar("skill_dsl_active", default=frozenset())


class SkillDSLValidationError(ValueError):
    pass


class SkillDSLRuntimeLimitError(RuntimeError):
    pass


@dataclass(frozen=True)
class CompiledSkill:
    program: Mapping[str, Any]
    steps: int


def _require_object(value, where):
    if not isinstance(value, dict):
        raise SkillDSLValidationError(f"{where} 必须是对象")


def _path(value, where):
    if not isinstance(value, str) or not value or len(value) > 120:
        raise SkillDSLValidationError(f"{where} 路径无效")
    parts = value.split(".")
    if parts[0] not in ROOTS or any(
        (not part.isidentifier() and not part.isdigit()) or part.startswith("_") for part in parts
    ):
        raise SkillDSLValidationError(f"{where} 路径根必须为 owner/event/game/locals/state")


def _validate_condition(node, depth=0):
    if depth > 12:
        raise SkillDSLValidationError("条件嵌套过深")
    if isinstance(node, bool) or node is None:
        return 1
    _require_object(node, "condition")
    if set(node) - {"op", "args", "path", "value", "values"}:
        raise SkillDSLValidationError("condition 含未知字段")
    op = node.get("op")
    if not isinstance(op, str) or op not in CONDITION_OPS:
        raise SkillDSLValidationError(f"不支持的条件操作: {op}")
    if op in ("all", "any"):
        args = node.get("args")
        if not isinstance(args, list) or not args:
            raise SkillDSLValidationError(f"{op} 需要非空 args")
        return 1 + sum(_validate_condition(x, depth + 1) for x in args)
    if op == "not":
        return 1 + _validate_condition(node.get("args"), depth + 1)
    _path(node.get("path"), "condition")
    if op == "in" and not isinstance(node.get("values"), list):
        raise SkillDSLValidationError("in 需要 values 数组")
    if op == "in" and (len(node["values"]) > 20 or any(not isinstance(x, (str, int, bool, type(None))) for x in node["values"])):
        raise SkillDSLValidationError("in values 只允许最多20个标量")
    if op not in ("exists", "in") and "value" not in node:
        raise SkillDSLValidationError(f"{op} 需要 value")
    if isinstance(node.get("value"), dict):
        _validate_value(node["value"], "condition value")
    return 1


def _validate_filter_any(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 6:
        raise SkillDSLValidationError("filter.any 需要 1..6 个分支")
    for branch in value:
        _require_object(branch, "filter.any branch")
        if not branch or set(branch) - {"names", "suits", "color"}:
            raise SkillDSLValidationError("filter.any 分支字段无效")
        for key, allowed in (("names", None), ("suits", {"spade", "heart", "club", "diamond"})):
            if key in branch and (not isinstance(branch[key], list) or not 1 <= len(branch[key]) <= 12
                                  or any(not isinstance(x, str) or (allowed is not None and x not in allowed) or len(x) > 30 for x in branch[key])):
                raise SkillDSLValidationError(f"filter.any.{key} 无效")
        if "color" in branch and (not isinstance(branch["color"], str) or branch["color"] not in {"red", "black"}):
            raise SkillDSLValidationError("filter.any.color 无效")


def _matches_card_filter(card, filt):
    if filt.get("color") and card_color(card) != filt["color"]: return False
    if filt.get("names") and card.name not in filt["names"]: return False
    if filt.get("suits") and card.suit not in filt["suits"]: return False
    branches = filt.get("any", [])
    if branches and not any((not branch.get("names") or card.name in branch["names"])
                            and (not branch.get("suits") or card.suit in branch["suits"])
                            and (not branch.get("color") or card_color(card) == branch["color"])
                            for branch in branches):
        return False
    return True


def _validate_effect_list(effects, depth=0):
    if depth > 8 or not isinstance(effects, list) or not effects or len(effects) > 32:
        raise SkillDSLValidationError("effect/repeat effects 必须是 1..32 项的浅层数组")
    steps = 0
    for effect in effects:
        _require_object(effect, "effect")
        kind = effect.get("type")
        if not isinstance(kind, str) or kind not in EFFECTS | {"card_as"}:
            raise SkillDSLValidationError(f"不支持的效果: {kind}")
        common = {"type", "target", "amount", "reason", "prompt", "source", "card", "count", "text", "damage_type", "when", "duel_source", "duel_target", "store_as", "cards_from", "card_owner", "actor", "zone", "interaction", "min", "max", "candidates", "choices", "filter", "optional", "effects", "key", "op", "value", "claim_old", "scope"}
        if set(effect) - common:
            raise SkillDSLValidationError("effect 含未知字段")
        if kind == "repeat":
            if set(effect) - {"type", "count", "effects", "when"}:
                raise SkillDSLValidationError("repeat 只接受 count/effects")
            _validate_value(effect.get("count"), "repeat.count", limit=52)
            if "when" in effect:
                steps += _validate_condition(effect["when"])
            steps += 1 + _validate_effect_list(effect.get("effects"), depth + 1)
            continue
        if kind == "interact":
            if (not isinstance(effect.get("interaction"), str) or effect["interaction"] not in INTERACTIONS
                    or not isinstance(effect.get("store_as"), str) or not effect["store_as"].isidentifier()
                    or effect["store_as"].startswith("_")):
                raise SkillDSLValidationError("interact 需合法交互原语及 store_as")
            if set(effect) - {"type", "interaction", "store_as", "prompt", "min", "max", "zone", "card_owner", "actor", "candidates", "choices", "filter", "optional", "when", "exclude_state"}:
                raise SkillDSLValidationError("interact 含未知字段")
            if "actor" in effect and (not isinstance(effect["actor"], str) or effect["actor"] not in {"owner", "source", "target"}):
                raise SkillDSLValidationError("interact.actor 无效")
            if effect.get("optional", False) not in (True, False) or type(effect.get("optional", False)) is not bool:
                raise SkillDSLValidationError("interact.optional 必须为布尔值")
            for key in ("min", "max"):
                if key in effect: _validate_value(effect[key], f"interact.{key}", limit=52)
            if effect.get("interaction") == "ask_choose_cards":
                if effect.get("zone", "hand") not in {"hand", "equipment", "hand_or_equipment"} and not (isinstance(effect.get("zone"), str) and effect["zone"].startswith("local:") and effect["zone"][6:].isidentifier()):
                    raise SkillDSLValidationError("interact zone 无效")
                if effect.get("card_owner", "owner") not in {"owner", "source", "target"}:
                    raise SkillDSLValidationError("interact card_owner 无效")
                if "filter" in effect:
                    _require_object(effect["filter"], "interact.filter")
                    if set(effect["filter"]) - {"color", "names", "suits", "same_suit", "any"}:
                        raise SkillDSLValidationError("interact.filter 含未知字段")
                    if "any" in effect["filter"]: _validate_filter_any(effect["filter"]["any"])
            candidates = effect.get("candidates", "alive_others")
            if effect.get("interaction") == "ask_choose_players" and (not isinstance(candidates, str) or candidates not in {"alive_others", "injured_alive", "all_alive", "event.source", "event.target", "event.targets", "male_others"}):
                raise SkillDSLValidationError("interact candidates 无效")
            if "exclude_state" in effect and (not isinstance(effect["exclude_state"], str) or not effect["exclude_state"].isidentifier() or effect["exclude_state"].startswith("_")):
                raise SkillDSLValidationError("interact.exclude_state 无效")
            if effect.get("interaction") == "ask_choose_option" and (not isinstance(effect.get("choices"), list) or not 1 <= len(effect["choices"]) <= 10):
                raise SkillDSLValidationError("interact choices 无效")
            if "when" in effect:
                steps += _validate_condition(effect["when"])
            steps += 1
            continue
        if kind == "set_state":
            if set(effect) - {"type", "key", "op", "value", "scope", "when"}:
                raise SkillDSLValidationError("set_state 含未知字段")
            key, operation = effect.get("key"), effect.get("op", "set")
            if not isinstance(key, str) or not key.isidentifier() or key.startswith("_") or operation not in {"set", "add", "append"} or effect.get("scope", "game") not in {"game", "current_turn"} or "value" not in effect:
                raise SkillDSLValidationError("set_state key/op/value 无效")
            value = effect["value"]
            if not isinstance(value, (str, bool, type(None))):
                _validate_value(value, "set_state.value", limit=52)
            if "when" in effect:
                steps += _validate_condition(effect["when"])
            steps += 1
            continue
        if kind == "set_local":
            if set(effect) - {"type", "key", "op", "value", "when"}:
                raise SkillDSLValidationError("set_local 含未知字段")
            key, operation = effect.get("key"), effect.get("op", "set")
            if not isinstance(key, str) or not key.isidentifier() or key.startswith("_") or operation not in {"set", "add", "append"} or "value" not in effect:
                raise SkillDSLValidationError("set_local key/op/value 无效")
            value = effect["value"]
            if not isinstance(value, (str, bool, type(None))):
                _validate_value(value, "set_local.value", limit=52)
            if "when" in effect:
                steps += _validate_condition(effect["when"])
            steps += 1
            continue
        target_value = effect.get("target", "targets")
        if not isinstance(target_value, str) or (target_value not in {"owner", "source", "target", "targets"} and not target_value.startswith("locals.")):
            raise SkillDSLValidationError("effect target 无效")
        if kind == "card_as" and (not isinstance(effect.get("card"), str) or effect["card"] not in {"杀", "桃", "酒", "过河拆桥", "决斗", "万箭齐发", "无中生有"}):
            raise SkillDSLValidationError("card_as 牌名无效")
        if "damage_type" in effect and (kind != "damage" or not isinstance(effect["damage_type"], str) or effect["damage_type"] not in {"normal", "fire", "thunder"}):
            raise SkillDSLValidationError("damage_type 只支持 normal/fire/thunder 伤害")
        if "source" in effect and (kind != "damage" or not isinstance(effect["source"], str) or effect["source"] not in {"owner", "source", "target"}):
            raise SkillDSLValidationError("damage.source 只支持 owner/source/target")
        for role in ("duel_source", "duel_target"):
            if role in effect and (not isinstance(effect[role], str) or effect[role] not in {"owner", "source", "target", "targets.0", "targets.1"}):
                raise SkillDSLValidationError(f"{role} 无效")
        amount = effect.get("amount", effect.get("count", 1))
        _validate_value(amount, "effect amount/count", limit=52)
        if "when" in effect:
            steps += _validate_condition(effect["when"])
        if "store_as" in effect and (not isinstance(effect["store_as"], str) or not effect["store_as"].isidentifier() or effect["store_as"].startswith("_")):
            raise SkillDSLValidationError("effect.store_as 无效")
        if "cards_from" in effect:
            _path(effect["cards_from"], "effect.cards_from")
        if kind in {"discard_card", "transfer_card"}:
            zone = effect.get("zone", "hand")
            if not isinstance(zone, str) or zone not in {"hand", "equipment", "hand_or_equipment"} and not (zone.startswith("local:") and zone[6:].isidentifier()):
                raise SkillDSLValidationError("牌移动 zone 无效")
            if effect.get("card_owner", "owner") not in {"owner", "source", "target"}:
                raise SkillDSLValidationError("牌移动 card_owner 无效")
        if "claim_old" in effect and type(effect["claim_old"]) is not bool:
            raise SkillDSLValidationError("claim_old 必须为布尔值")
        steps += 1
    return steps


def compile_skill(program: Mapping[str, Any]) -> CompiledSkill:
    """验证 DSL 结构并复制为不可受输入引用修改的编译产物。"""
    _require_object(program, "skill")
    if set(program) - TOP_KEYS:
        raise SkillDSLValidationError("skill 含未知字段")
    if program.get("version") != 1:
        raise SkillDSLValidationError("仅支持 DSL version=1")
    if "skip_default" in program and type(program["skip_default"]) is not bool:
        raise SkillDSLValidationError("skip_default 必须是布尔值")
    usage = program.get("usage")
    if usage is not None:
        _require_object(usage, "usage")
        if set(usage) - {"scope", "limit", "charges"}:
            raise SkillDSLValidationError("usage 含未知字段")
        if not isinstance(usage.get("scope", "current_turn"), str) or usage.get("scope", "current_turn") not in {"phase", "current_turn", "round", "game", "actor_turn"}:
            raise SkillDSLValidationError("usage.scope 无效")
        for field in ("limit", "charges"):
            if field in usage and (type(usage[field]) is not int or not 1 <= usage[field] <= 99):
                raise SkillDSLValidationError(f"usage.{field} 必须在 1..99")
    trigger = program.get("trigger")
    if not isinstance(trigger, str) or trigger not in TRIGGERS:
        raise SkillDSLValidationError(f"不支持的触发时机: {trigger}")
    triggers = program.get("triggers", [trigger])
    if (not isinstance(triggers, list) or not 1 <= len(triggers) <= 4
            or any(not isinstance(item, str) or item not in TRIGGERS for item in triggers)
            or len(set(triggers)) != len(triggers) or trigger not in triggers):
        raise SkillDSLValidationError("triggers 必须是包含 trigger 的 1..4 个不同触发时机")
    action_actors = program.get("action_actors")
    if action_actors is not None and (trigger != "play_action" or not isinstance(action_actors, str) or action_actors not in {"faction:qun", "faction:群"}):
        raise SkillDSLValidationError("action_actors 仅支持 play_action 的群势力委托动作")
    if action_actors is not None and (usage is None or usage.get("scope") != "actor_turn"):
        raise SkillDSLValidationError("委托动作必须使用 actor_turn 限次")
    condition = program.get("condition", True)
    steps = _validate_condition(condition)
    costs = program.get("cost", [])
    if not isinstance(costs, list):
        raise SkillDSLValidationError("cost 必须是数组")
    for cost in costs:
        _require_object(cost, "cost item")
        if not isinstance(cost.get("interaction"), str) or cost.get("interaction") not in INTERACTIONS:
            raise SkillDSLValidationError("cost 必须使用四种交互原语之一")
        if set(cost) - {"interaction", "prompt", "min", "max", "zone", "choices", "candidates", "filter", "card_owner", "exclude_state"}:
            raise SkillDSLValidationError("cost 含未知字段")
        if len(str(cost.get("prompt", ""))) > 200:
            raise SkillDSLValidationError("cost prompt 过长")
        for bound in ("min", "max"):
            if bound in cost:
                _validate_value(cost[bound], f"cost.{bound}", limit=52)
        if type(cost.get("min", 1)) is int and type(cost.get("max", 1)) is int and cost.get("min", 1) > cost.get("max", 1):
            raise SkillDSLValidationError("cost.min 不能大于 cost.max")
        if cost.get("interaction") == "ask_choose_players" and (not isinstance(cost.get("candidates", "alive_others"), str) or cost.get("candidates", "alive_others") not in {"alive_others", "injured_alive", "all_alive", "event.source", "event.target", "event.targets", "male_others"}):
            raise SkillDSLValidationError("cost candidates selector 无效")
        if "exclude_state" in cost and (not isinstance(cost["exclude_state"], str) or not cost["exclude_state"].isidentifier() or cost["exclude_state"].startswith("_")):
            raise SkillDSLValidationError("cost.exclude_state 无效")
        if cost.get("interaction") == "ask_choose_cards" and cost.get("zone", "hand") not in {"hand", "equipment", "hand_or_equipment"}:
            raise SkillDSLValidationError("cost.zone 仅支持 hand/equipment/hand_or_equipment")
        if cost.get("interaction") == "ask_choose_cards" and cost.get("card_owner", "owner") not in {"owner", "source", "target"}:
            raise SkillDSLValidationError("cost.card_owner 无效")
        if "filter" in cost:
            filt = cost["filter"]
            _require_object(filt, "cost.filter")
            if set(filt) - {"color", "names", "suits", "same_suit", "any"}:
                raise SkillDSLValidationError("cost.filter 含未知字段")
            if "same_suit" in filt and type(filt["same_suit"]) is not bool:
                raise SkillDSLValidationError("cost.filter.same_suit 必须是布尔值")
            if "color" in filt and (not isinstance(filt["color"], str) or filt["color"] not in {"red", "black"}):
                raise SkillDSLValidationError("cost.filter.color 无效")
            for key, allowed in (("names", None), ("suits", {"spade", "heart", "club", "diamond"})):
                if key in filt and (not isinstance(filt[key], list) or not 1 <= len(filt[key]) <= 12 or any(not isinstance(x, str) or (allowed is not None and x not in allowed) or len(x) > 30 for x in filt[key])):
                    raise SkillDSLValidationError(f"cost.filter.{key} 无效")
            if "any" in filt:
                _validate_filter_any(filt["any"])
        if cost.get("interaction") == "ask_choose_option":
            choices = cost.get("choices")
            if not isinstance(choices, list) or not 1 <= len(choices) <= 10 or any(not isinstance(x, (str, int, bool, dict)) for x in choices):
                raise SkillDSLValidationError("ask_choose_option choices 必须是 1..10 项的标量/对象数组")
        steps += 1
    targets = program.get("targets", {"selector": "self", "min": 1, "max": 1})
    _require_object(targets, "targets")
    if set(targets) - {"selector", "min", "max", "interaction", "prompt", "candidates", "exclude_state"}:
        raise SkillDSLValidationError("targets 含未知字段")
    if not isinstance(targets.get("selector"), str) or targets.get("selector") not in {"self", "event.source", "event.target", "alive_others", "chosen_players"}:
        raise SkillDSLValidationError("targets selector 无效")
    for key in ("min", "max"):
        if key in targets:
            _validate_value(targets[key], f"targets.{key}", limit=52)
    if type(targets.get("min", 1)) is int and type(targets.get("max", 1)) is int and targets.get("min", 1) > targets.get("max", 1):
        raise SkillDSLValidationError("targets.min 不能大于 targets.max")
    if targets.get("selector") == "chosen_players" and targets.get("interaction", "ask_choose_players") != "ask_choose_players":
        raise SkillDSLValidationError("chosen_players 只能映射 ask_choose_players")
    if "candidates" in targets and (not isinstance(targets["candidates"], str) or targets["candidates"] not in {"alive_others", "injured_alive", "all_alive", "event.source", "event.target", "event.targets", "male_others"}):
        raise SkillDSLValidationError("targets.candidates selector 无效")
    if "exclude_state" in targets and (not isinstance(targets["exclude_state"], str) or not targets["exclude_state"].isidentifier() or targets["exclude_state"].startswith("_")):
        raise SkillDSLValidationError("targets.exclude_state 无效")
    if targets["selector"] == "chosen_players":
        steps += 1
    effects = program.get("effects", [])
    modifiers = program.get("modifiers", [])
    if not isinstance(modifiers, list) or len(modifiers) > 8:
        raise SkillDSLValidationError("modifiers 必须是最多8项的数组")
    for modifier in modifiers:
        _require_object(modifier, "modifier")
        stat = modifier.get("stat")
        operation = modifier.get("op")
        allowed = {"hand_limit": {"add", "max"}, "distance": {"add", "subtract"},
                   "max_sha": {"max"}, "response_count": {"max"}, "ignore_distance": {"allow"},
                   "protect_card": {"deny"}}
        if stat == "target_protection":
            allowed[stat] = {"deny"}
        if (set(modifier) - {"when"} != {"stat", "op", "value"}
                or set(modifier) - {"stat", "op", "value", "when"}
                or not isinstance(stat, str) or stat not in allowed
                or not isinstance(operation, str) or operation not in allowed[stat]):
            raise SkillDSLValidationError("modifier stat/op 不在白名单")
        _validate_value(modifier["value"], "modifier.value", limit=52)
        if "when" in modifier:
            steps += _validate_condition(modifier["when"])
        steps += 1
    conversions = program.get("conversions", [])
    if not isinstance(conversions, list) or len(conversions) > 10:
        raise SkillDSLValidationError("conversions 必须是最多10项的数组")
    for conversion in conversions:
        _require_object(conversion, "conversion")
        if set(conversion) - {"names", "color", "suits", "as", "when"} or not isinstance(conversion.get("as"), str) or conversion["as"] not in {"杀", "闪", "桃", "酒", "过河拆桥", "无中生有", "万箭齐发"}:
            raise SkillDSLValidationError("牌转化字段或目标牌名无效")
        if not any(key in conversion for key in ("names", "color", "suits")):
            raise SkillDSLValidationError("牌转化必须限制来源牌")
        if "names" in conversion and (not isinstance(conversion["names"], list) or not 1 <= len(conversion["names"]) <= 12 or any(not isinstance(x, str) or len(x) > 30 for x in conversion["names"])):
            raise SkillDSLValidationError("conversion.names 无效")
        if "color" in conversion and (not isinstance(conversion["color"], str) or conversion["color"] not in {"red", "black"}):
            raise SkillDSLValidationError("conversion.color 无效")
        if "suits" in conversion and (not isinstance(conversion["suits"], list) or not 1 <= len(conversion["suits"]) <= 4 or any(not isinstance(x, str) or x not in {"spade", "heart", "club", "diamond"} for x in conversion["suits"])):
            raise SkillDSLValidationError("conversion.suits 无效")
        if "when" in conversion:
            steps += _validate_condition(conversion["when"])
        steps += 1
    if not isinstance(effects, list) or (not effects and not modifiers and not conversions):
        raise SkillDSLValidationError("effects 必须非空，除非声明了 modifiers/conversions")
    if effects:
        steps += _validate_effect_list(effects)
    if steps > MAX_STEPS:
        raise SkillDSLValidationError(f"技能步数超过上限 {MAX_STEPS}")
    return CompiledSkill(deepcopy(dict(program)), steps)


def _lookup(path, scope):
    value = scope
    for part in path.split("."):
        if isinstance(value, Mapping):
            if part not in value:
                return None
            value = value[part]
        elif isinstance(value, (list, tuple)) and part.isdigit():
            index = int(part)
            if index >= len(value):
                return None
            value = value[index]
        elif part in {"id", "name", "suit", "rank", "card_type", "hp", "max_hp", "alive", "identity", "color"}:
            if part == "color" and hasattr(value, "suit"):
                value = card_color(value)
            else:
                value = getattr(value, part, None)
        else:
            return None
    return value


def _validate_value(value, where, limit=10):
    if type(value) is int and 0 <= value <= limit:
        return
    if not isinstance(value, dict):
        raise SkillDSLValidationError(f"{where} 必须是 0..10 整数或受限表达式")
    if set(value) == {"path"}:
        _path(value["path"], where)
        return
    if set(value) == {"op", "args"} and value["op"] in {"add", "sub", "mul", "min", "max"}:
        args = value["args"]
        if not isinstance(args, list) or not 2 <= len(args) <= 4:
            raise SkillDSLValidationError(f"{where} 算术表达式参数无效")
        for arg in args: _validate_value(arg, where, limit)
        return
    raise SkillDSLValidationError(f"{where} 表达式操作无效")


def _resolve_value(value, scope, limit=10):
    if type(value) is int:
        return value if 0 <= value <= limit else None
    if isinstance(value, dict) and set(value) == {"path"}:
        return _lookup(value["path"], scope)
    op, args = value["op"], [_resolve_value(x, scope, limit) for x in value["args"]]
    if any(type(x) is not int for x in args): return None
    if op == "add": result = sum(args)
    elif op == "sub": result = args[0] - sum(args[1:])
    elif op == "mul":
        result = 1
        for arg in args: result *= arg
    elif op == "min": result = min(args)
    else: result = max(args)
    return result if 0 <= result <= limit else None


def _resolve_bounds(item, scope, *, default_min=1, default_max=1):
    """Resolve an interaction's bounds without passing invalid values to the engine."""
    minimum = _resolve_value(item.get("min", default_min), scope, limit=52)
    maximum = _resolve_value(item.get("max", default_max), scope, limit=52)
    if (type(minimum) is not int or type(maximum) is not int
            or minimum < 0 or maximum < minimum or maximum > 52):
        return None
    return minimum, maximum


def _canonical_players(selected, candidates, bounds):
    """Accept only distinct members of the current candidate set, by object or id."""
    if bounds is None or not isinstance(selected, list):
        return None
    by_id = {player.id: player for player in candidates}
    result = []
    for value in selected:
        player = value if any(value is candidate for candidate in candidates) else (
            by_id.get(value) if type(value) in (int, str) else None
        )
        if player is None or not player.alive or any(player is prior for prior in result):
            return None
        result.append(player)
    minimum, maximum = bounds
    if not minimum <= len(result) <= maximum:
        return None
    return result


def evaluate_condition(node, scope):
    if isinstance(node, bool) or node is None:
        return bool(node)
    op = node["op"]
    if op == "all":
        return all(evaluate_condition(x, scope) for x in node["args"])
    if op == "any":
        return any(evaluate_condition(x, scope) for x in node["args"])
    if op == "not":
        return not evaluate_condition(node["args"], scope)
    value = _lookup(node["path"], scope)
    if op == "exists": return value is not None
    expected = _resolve_value(node.get("value"), scope) if isinstance(node.get("value"), dict) else node.get("value")
    if op == "eq": return value == expected
    if op == "ne": return value != expected
    if op == "in": return value in node["values"]
    if value is None: return False
    try:
        return {"gt": lambda: value > expected, "gte": lambda: value >= expected,
                "lt": lambda: value < expected, "lte": lambda: value <= expected}[op]()
    except (TypeError, KeyError):
        return False


def _condition_steps(node):
    if isinstance(node, dict) and node.get("op") in ("all", "any"):
        return 1 + sum(_condition_steps(x) for x in node.get("args", []))
    if isinstance(node, dict) and node.get("op") == "not":
        return 1 + _condition_steps(node.get("args"))
    return 1


def _tick(budget, amount=1):
    budget[0] += amount
    if budget[0] > MAX_STEPS:
        raise SkillDSLRuntimeLimitError("DSL runtime step limit exceeded")


class SkillDSLRuntime:
    """运行时只持有引擎提供的显式能力；没有 import/eval/文件/网络入口。"""
    def __init__(self, manager):
        self.manager = manager
        self.engine = manager.engine
        self.diagnostics = []

    def _diagnostic(self, owner, skill_name, trigger):
        row = {"player_id": owner.id, "skill_name": skill_name,
               "trigger": trigger, "status": "runtime_rejected"}
        self.diagnostics.append(row)
        if len(self.diagnostics) > 200:
            del self.diagnostics[:-200]
        return row

    def _scope(self, owner, event):
        state = self.engine.game_state
        event_scope = dict(event)
        source_player = event.get("source")
        if source_player is not None:
            event_scope["source_hand_count"] = len(getattr(source_player, "hand", []))
            event_scope["source_equipment_count"] = sum(1 for c in getattr(source_player, "equipment", {}).values() if c is not None)
        event_scope.setdefault("missing_hp", max(0, owner.max_hp - owner.hp))
        event_scope.setdefault("hand_count_before", len(owner.hand))
        event_scope.setdefault("sha_used_this_turn", bool(owner.flags.get("sha_used_this_turn")))
        faction = (owner.hero or {}).get("faction")
        skill_name = event.get("_skill_name")
        state_owner = event.get("_dsl_state_owner", owner)
        instance = self.manager._skill_instance(state_owner, skill_name) if skill_name else None
        locals_scope = event.get("_locals", {})
        return {"owner": {"id": owner.id, "hp": owner.hp, "max_hp": owner.max_hp,
                          "missing_hp": max(0, owner.max_hp - owner.hp),
                          "faction": faction, "identity": owner.identity, "hand_count": len(owner.hand)},
                "event": event_scope,
                "game": {"round": state.round_number, "phase": getattr(state.current_phase, "value", state.current_phase),
                         "alive_other_faction_count": sum(1 for p in state.players if p.alive and p is not owner and (p.hero or {}).get("faction") == faction),
                         "alive_count": sum(1 for p in state.players if p.alive),
                         "is_owner_turn": state.current_player is owner},
                "locals": locals_scope,
                "state": self._state_view(owner, instance)}

    def _state_view(self, owner, instance):
        if instance is None:
            return {}
        result = {}
        turn_id = getattr(self.engine, "completed_turns", None)
        for key, value in instance.state.items():
            if isinstance(value, dict) and value.get("__dsl_scope__") == "current_turn":
                result[key] = value.get("value") if value.get("turn_id") == turn_id else value.get("default")
            else:
                result[key] = value
        return result

    async def run(self, compiled: CompiledSkill, owner, event: Dict[str, Any], skill_name=None):
        p = compiled.program
        caller_event = event
        event = dict(event)
        event.setdefault("_locals", {})
        event.setdefault("missing_hp", max(0, owner.max_hp - owner.hp))
        event.setdefault("hand_count_before", len(owner.hand))
        event.setdefault("sha_used_this_turn", bool(owner.flags.get("sha_used_this_turn")))
        event["_skill_name"] = skill_name
        state_owner = event.get("_dsl_state_owner", owner)
        diagnostic = self._diagnostic(owner, skill_name, p.get("trigger"))
        skill_key = (state_owner.id, skill_name or id(compiled), owner.id)
        active = _ACTIVE_SKILLS.get()
        if skill_key in active:
            diagnostic["status"] = "reentrant_blocked"
            return False
        token_skills = _ACTIVE_SKILLS.set(active | {skill_key})
        parent_budget = _ACTIVE_BUDGET.get()
        token_budget = None
        if parent_budget is None:
            token_budget = _ACTIVE_BUDGET.set([0])
        try:
            usage = p.get("usage")
            if usage:
                if usage.get("scope") == "actor_turn":
                    available = self.manager.dsl_actor_skill_available(state_owner, owner, skill_name, usage.get("limit", 1))
                else:
                    available = self.manager.skill_available(
                        state_owner, skill_name, phase=self.engine.game_state.current_phase,
                        limit=usage.get("limit", 1))
                if not available:
                    diagnostic["status"] = "usage_unavailable"
                    return False
            budget = _ACTIVE_BUDGET.get()
            _tick(budget, _condition_steps(p.get("condition", True)))
            if not evaluate_condition(p.get("condition", True), self._scope(owner, event)):
                diagnostic["status"] = "condition_false"
                return False
            chosen = []
            for cost in p.get("cost", []):
                _tick(budget)
                value = await self._interact(owner, cost, event)
                if owner not in self.engine.game_state.players or not owner.alive or self.engine.game_aborted:
                    return False
                if value is None or value is False or value == []:
                    diagnostic["status"] = "declined"
                    return False
                if cost["interaction"] == "ask_confirm":
                    if value is not True:
                        return False
                elif cost["interaction"] == "ask_choose_option":
                    choices = cost.get("choices", [])
                    if not any(type(value) is type(choice) and value == choice for choice in choices):
                        return False
                elif cost["interaction"] == "ask_choose_players":
                    bounds = _resolve_bounds(cost, self._scope(owner, event))
                    candidates = self._candidates(
                        cost.get("candidates", "alive_others"), owner, event,
                        cost.get("exclude_state"),
                    )
                    value = _canonical_players(value, candidates, bounds)
                    if value is None:
                        return False
                if cost["interaction"] == "ask_choose_cards":
                    filt = cost.get("filter", {})
                    card_owner = self._card_owner(owner, cost, event)
                    candidates = self._card_candidates(card_owner, cost, event) if card_owner else []
                    bounds = _resolve_bounds(cost, self._scope(owner, event))
                    if bounds is None:
                        return False
                    min_n, max_n = bounds
                    if (not isinstance(value, list) or len(value) != len({id(c) for c in value})
                            or len(value) < min_n or len(value) > max_n
                            or any(not any(c is candidate for candidate in candidates) for c in value)
                            or (filt.get("same_suit") and len({c.suit for c in value}) > 1)):
                        return False
                chosen.append(value)
            target_rule = p.get("targets", {"selector": "self"})
            if target_rule.get("selector") == "chosen_players":
                _tick(budget)
            targets = await self._resolve_targets(owner, target_rule, event)
            if targets is None:
                diagnostic["status"] = "declined"
                return False
            event["_locals"].update({"targets": targets})
            if targets:
                event["_locals"]["target"] = targets[0]
            if owner not in self.engine.game_state.players or not owner.alive or self.engine.game_aborted:
                return False
            selected_cards = next((value for cost, value in zip(p.get("cost", []), chosen)
                                   if cost["interaction"] == "ask_choose_cards"), [])
            event["_chosen_players"] = next((value for cost, value in zip(p.get("cost", []), chosen)
                                              if cost["interaction"] == "ask_choose_players"), [])
            if selected_cards:
                card_cost = next((c for c in p.get("cost", []) if c["interaction"] == "ask_choose_cards"), {})
                card_owner = self._card_owner(owner, card_cost, event)
                valid_cost_cards = self._card_candidates(card_owner, card_cost, event) if card_owner else []
                if any(not any(c is candidate for candidate in valid_cost_cards) for c in selected_cards):
                    return False
                event["_selected_zone"] = card_cost.get("zone", "hand")
                event["_selected_card_owner"] = card_owner
            event["_selected_cards"] = selected_cards
            event["selected_card_color"] = card_color(selected_cards[0]) if selected_cards else None
            event["selected_card_name"] = selected_cards[0].name if selected_cards else None
            event.setdefault("selected_count", len(selected_cards))
            event.setdefault("selected_all_hand", event.get("_selected_zone", "hand") == "hand"
                             and bool(owner.hand) and len(selected_cards) == len(owner.hand))
            for effect in p.get("effects", []):
                if effect.get("type") != "card_as":
                    continue
                if not selected_cards or event.get("_selected_card_owner", owner) is not owner:
                    return False
                from .state_manager import Card
                card_name = effect["card"]
                card_type = "basic" if card_name in {"杀", "桃", "酒"} else "trick"
                recipients = {"owner": [owner], "source": [event.get("source")],
                              "target": [event.get("target")], "targets": targets}[effect.get("target", "targets")]
                probe = selected_cards[0]
                original_name, original_type = probe.name, probe.card_type
                try:
                    probe.name, probe.card_type = card_name, card_type
                    legal, _reason = self.engine.rules.can_play_card(owner, probe, [p for p in recipients if p is not None])
                finally:
                    probe.name, probe.card_type = original_name, original_type
                if not legal:
                    return False
            for effect in p.get("effects", []):
                result = await self._effect(effect, owner, targets, event, chosen, budget)
                if result is False:
                    diagnostic["status"] = "effect_rejected"
                    return False
            if usage:
                if usage.get("scope") == "actor_turn":
                    consumed = self.manager.consume_dsl_actor_skill_use(
                        state_owner, owner, skill_name, usage.get("limit", 1))
                else:
                    consumed = self.manager.consume_skill_use(
                        state_owner, skill_name, phase=self.engine.game_state.current_phase,
                        charges=usage.get("charges", 0), limit=usage.get("limit", 1))
                if not consumed:
                    diagnostic["status"] = "usage_race"
                    return False
            # Judge hooks need a narrow result channel back to their caller so
            # the engine can consume a replacement or honor a claimed card.
            caller_event.update({key: value for key, value in event.items()
                                 if key in {"_replacement", "_claimed", "_targets"}})
            diagnostic["status"] = "success"
            return True
        except SkillDSLRuntimeLimitError:
            diagnostic["status"] = "budget_exhausted"
            logger.warning("DSL技能运行步数超限并已禁用: hero=%s skill=%s", (state_owner.hero or {}).get("id"), skill_name)
            if skill_name:
                instance = self.manager._skill_instance(state_owner, skill_name)
                if instance is not None:
                    self.manager.disable_skill(state_owner, instance.skill_id)
            return False
        finally:
            _ACTIVE_SKILLS.reset(token_skills)
            if token_budget is not None:
                _ACTIVE_BUDGET.reset(token_budget)

    async def _interact(self, owner, item, event):
        method = item["interaction"]
        actor = owner if item.get("actor", "owner") == "owner" else event.get(item["actor"])
        if actor is None or actor not in self.engine.game_state.players or not actor.alive:
            return None
        prompt = item.get("prompt", "是否发动技能？")
        skill_name = event.get("_skill_name")
        if method == "ask_confirm":
            return await self.manager.ask_confirm(actor, prompt, skill_name=skill_name)
        if method == "ask_choose_players":
            bounds = _resolve_bounds(item, self._scope(owner, event))
            if bounds is None:
                return None
            candidates = self._candidates(item.get("candidates", "alive_others"), owner, event,
                                          item.get("exclude_state"))
            return await self.manager.ask_choose_players(actor, prompt, candidates,
                min_n=bounds[0], max_n=bounds[1], skill_name=skill_name)
        if method == "ask_choose_cards":
            bounds = _resolve_bounds(item, self._scope(owner, event))
            if bounds is None:
                return None
            card_owner = self._card_owner(owner, item, event)
            if isinstance(item.get("zone", "hand"), str) and item.get("zone", "hand").startswith("local:"):
                candidates = self._card_candidates(actor, item, event)
            else:
                if card_owner is None or card_owner not in self.engine.game_state.players or not card_owner.alive:
                    return None
                candidates = self._card_candidates(card_owner, item, event)
            filt = item.get("filter", {})
            candidates = [c for c in candidates if _matches_card_filter(c, filt)]
            return await self.manager.ask_choose_cards(actor, prompt, candidates,
                min_n=bounds[0], max_n=bounds[1], zone=item.get("zone", "hand"),
                skill_name=skill_name)
        if method == "ask_choose_option":
            return await self.manager.ask_choose_option(
                actor, prompt, item.get("choices", []), skill_name=skill_name,
            )
        return None

    @staticmethod
    def _card_owner(owner, item, event):
        role = item.get("card_owner", "owner")
        return owner if role == "owner" else event.get(role)

    def _card_candidates(self, owner, item, event):
        zone = item.get("zone", "hand")
        if isinstance(zone, str) and zone.startswith("local:"):
            values = event.get("_locals", {}).get(zone[6:], [])
            candidates = [c for c in values if any(c is held for held in owner.hand)
                          or any(c is held for held in owner.equipment.values())] if isinstance(values, (list, tuple)) else []
        elif zone == "hand":
            candidates = list(owner.hand)
        elif zone == "equipment":
            candidates = [c for c in owner.equipment.values() if c is not None]
        else:
            candidates = list(owner.hand) + [c for c in owner.equipment.values() if c is not None]
        filt = item.get("filter", {})
        candidates = [c for c in candidates if _matches_card_filter(c, filt)]
        return candidates

    def _candidates(self, selector, owner, event, exclude_state=None):
        players = self.engine.game_state.players
        if selector == "alive_others": candidates = [p for p in players if p.alive and p is not owner]
        elif selector == "injured_alive": candidates = [p for p in players if p.alive and p.hp < p.max_hp]
        elif selector == "all_alive": candidates = [p for p in players if p.alive]
        elif selector == "event.targets": candidates = [p for p in event.get("targets", []) if p is not None]
        elif selector == "male_others":
            female = {"zhenji", "huangyueying", "daqiao", "diaochan"}
            candidates = [p for p in players if p.alive and p is not owner
                          and (p.hero or {}).get("sex", "female" if (p.hero or {}).get("id") in female else "male") == "male"]
        elif selector == "event.source": candidates = [event.get("source")] if event.get("source") else []
        elif selector == "event.target": candidates = [event.get("target")] if event.get("target") else []
        else: candidates = []
        if exclude_state:
            excluded = self._scope(owner, event)["state"].get(exclude_state, [])
            if isinstance(excluded, list):
                candidates = [p for p in candidates if p.id not in excluded]
        return candidates

    async def _resolve_targets(self, owner, rule, event):
        selector = rule.get("selector", "self")
        scope = self._scope(owner, event)
        default_min, default_max = ((1, 1) if selector == "chosen_players" else (0, 52))
        bounds = _resolve_bounds(rule, scope, default_min=default_min,
                                  default_max=default_max)
        if bounds is None:
            return None
        if selector == "self": result = [owner]
        elif selector == "event.source": result = [event["source"]] if event.get("source") else []
        elif selector == "event.target": result = [event["target"]] if event.get("target") else []
        elif selector == "alive_others": result = [p for p in self.engine.game_state.players if p.alive and p is not owner]
        elif selector == "injured_alive": result = [p for p in self.engine.game_state.players if p.alive and p.hp < p.max_hp]
        else:
            selected = await self._interact(owner, {"interaction": rule.get("interaction", "ask_choose_players"),
                "prompt": rule.get("prompt", "選擇目標"), "candidates": rule.get("candidates", "alive_others"),
                "min": bounds[0], "max": bounds[1],
                "exclude_state": rule.get("exclude_state")}, event)
            allowed = self._candidates(rule.get("candidates", "alive_others"), owner, event,
                                       rule.get("exclude_state"))
            result = _canonical_players(selected, allowed, bounds)
            if result is None:
                return None
        if not isinstance(result, list): result = [result] if result else []
        min_count, max_count = bounds
        if len(result) < min_count or len(result) > max_count: return None
        if len({p.id for p in result}) != len(result): return None
        if any(p not in self.engine.game_state.players or not p.alive for p in result): return None
        return result

    async def _effect(self, effect, owner, targets, event, chosen, budget):
        _tick(budget)
        selected_cards = event.get("_selected_cards", [])
        condition_event = dict(event)
        condition_event.setdefault("selected_count", len(selected_cards))
        condition_event.setdefault("selected_all_hand", bool(owner.hand) and len(selected_cards) == len(owner.hand))
        if "when" in effect:
            _tick(budget, _condition_steps(effect["when"]))
            if not evaluate_condition(effect["when"], self._scope(owner, condition_event)):
                return
        kind = effect["type"]
        target_rule = effect.get("target", "targets")
        if target_rule.startswith("locals."):
            value = _lookup(target_rule, self._scope(owner, condition_event))
            recipient = value if isinstance(value, list) else [value]
        else:
            recipient = {"owner": [owner], "source": [event.get("source")],
                         "target": [event.get("target")], "targets": targets}[target_rule]
        recipient = [p for p in recipient if p is not None]
        amount = _resolve_value(effect.get("amount", effect.get("count", 1)), self._scope(owner, condition_event), limit=52)
        if type(amount) is not int or not 0 <= amount <= 52:
            return False
        if kind in {"damage", "recover", "lose_hp"} and amount > 10:
            return False
        if kind in {"judge", "gain_judged_card", "replace_judgment"} and amount > 1:
            return False
        reason = effect.get("reason", "skill_dsl")
        if kind == "draw_cards":
            drawn_all = []
            for p in recipient:
                _tick(budget, max(1, amount))
                drawn = await self.manager.draw_cards(p, int(amount), reason)
                if p is owner:
                    drawn_all.extend(drawn or [])
            if effect.get("store_as"):
                event.setdefault("_locals", {})[effect["store_as"]] = drawn_all
        elif kind == "damage":
            for p in recipient:
                _tick(budget, max(1, amount))
                context = {"nature": effect.get("damage_type")} if effect.get("damage_type") not in (None, "normal") else None
                damage_source = {"owner": owner, "source": event.get("source"),
                                 "target": event.get("target")}.get(effect.get("source", "owner"))
                await self.engine.card_system.damage(damage_source, p, int(amount), context=context)
        elif kind == "recover":
            for p in recipient:
                _tick(budget, max(1, amount))
                await self.manager.recover(p, int(amount), source=owner, reason=reason)
        elif kind == "lose_hp":
            for p in recipient:
                _tick(budget, max(1, amount))
                await self.manager.lose_hp(p, int(amount), reason=reason, source=owner)
        elif kind == "announce":
            await self.manager.announce(owner, event.get("_skill_name") or "DSL", effect.get("text") or None)
        elif kind == "judge":
            for p in recipient:
                _tick(budget)
                judged = await self.manager.judge(p, reason=reason)
                if judged is not None:
                    event["judged_color"] = card_color(judged)
                    event["judged_card_name"] = judged.name
                    event["judged_suit"] = judged.suit
                    event["judged_rank"] = judged.rank
        elif kind == "gain_judged_card":
            card = event.get("card")
            if card is None or not any(card is c for c in owner.shown):
                return False
            await card_flow.release_shown(self.engine, self.engine.game_state, card, "hand",
                                          to_owner=owner, reason=reason, actor_id=owner.id)
            await self.manager.on_card_gained(owner, [card], reason)
            event["_claimed"] = True
        elif kind == "gain_event_card":
            card = event.get("card")
            if card is None or card not in self.engine.game_state.discard_pile:
                return False
            moved = await self.engine.move_card(card, "discard", "hand", to_owner=owner,
                                                 reason=reason, actor_id=owner.id, visibility="owner")
            if moved is None:
                return False
            await self.manager.on_card_gained(owner, [card], reason)
        elif kind == "interact":
            value = await self._interact(owner, effect, event)
            interaction_actor = owner if effect.get("actor", "owner") == "owner" else event.get(effect["actor"])
            if owner not in self.engine.game_state.players or not owner.alive or self.engine.game_aborted:
                return False
            if interaction_actor not in self.engine.game_state.players or not interaction_actor.alive:
                return False
            if (value is None or value is False or value == []) and not effect.get("optional", False):
                return False
            if effect["interaction"] == "ask_confirm" and value not in (None, False) and type(value) is not bool:
                return False
            if effect["interaction"] == "ask_choose_option" and value not in (None, False, []) and not any(
                    type(value) is type(choice) and value == choice for choice in effect.get("choices", [])):
                return False
            if effect.get("interaction") == "ask_choose_cards":
                if value not in (None, False, []):
                    bounds = _resolve_bounds(effect, self._scope(owner, event))
                    local_zone = str(effect.get("zone", "hand")).startswith("local:")
                    card_owner = interaction_actor if local_zone else self._card_owner(owner, effect, event)
                    candidates = self._card_candidates(card_owner, effect, event) if card_owner else []
                    if (bounds is None or not isinstance(value, list)
                            or len(value) != len({id(c) for c in value})
                            or not bounds[0] <= len(value) <= bounds[1]
                            or any(not any(c is candidate for candidate in candidates) for c in value)
                            or (effect.get("filter", {}).get("same_suit")
                                and len({c.suit for c in value}) > 1)):
                        return False
            if effect.get("interaction") == "ask_choose_players":
                if value not in (None, False, []):
                    bounds = _resolve_bounds(effect, self._scope(owner, event))
                    allowed = self._candidates(effect.get("candidates", "alive_others"), owner, event,
                                               effect.get("exclude_state"))
                    value = _canonical_players(value, allowed, bounds)
                    if value is None:
                        return False
            event.setdefault("_locals", {})[effect["store_as"]] = value
        elif kind == "repeat":
            count = _resolve_value(effect["count"], self._scope(owner, event), limit=52)
            if type(count) is not int:
                return False
            for _ in range(count):
                event["repeat_index"] = _
                _tick(budget)
                for nested in effect["effects"]:
                    result = await self._effect(nested, owner, targets, event, chosen, budget)
                    if result is False:
                        return False
        elif kind == "set_state":
            key, operation = effect["key"], effect.get("op", "set")
            current = self._scope(owner, event)["state"].get(key)
            value = effect["value"]
            if isinstance(value, dict):
                value = _resolve_value(value, self._scope(owner, event), limit=52)
            if operation == "add":
                if current is None: current = 0
                if type(current) is not int or type(value) is not int:
                    return False
                value = current + value
            elif operation == "append":
                if current is None: current = []
                if not isinstance(current, list) or value is None:
                    return False
                value = [*current, value]
            if effect.get("scope", "game") == "current_turn":
                default = [] if operation == "append" else 0 if operation == "add" else None
                value = {"__dsl_scope__": "current_turn", "turn_id": getattr(self.engine, "completed_turns", None),
                         "default": default, "value": value}
            self.manager.set_skill_state(owner, event.get("_skill_name"), key, value)
        elif kind == "set_local":
            key, operation = effect["key"], effect.get("op", "set")
            current = event.setdefault("_locals", {}).get(key)
            value = effect["value"]
            if isinstance(value, dict):
                value = _resolve_value(value, self._scope(owner, event), limit=52)
            if operation == "add":
                if current is None: current = 0
                if type(current) is not int or type(value) is not int:
                    return False
                value = current + value
            elif operation == "append":
                if current is None: current = []
                if not isinstance(current, list) or value is None:
                    return False
                value = [*current, value]
            event["_locals"][key] = value
        elif kind == "duel":
            def role(name):
                if name == "owner": return owner
                if name == "source": return event.get("source")
                if name == "target": return event.get("target")
                if name == "targets.0": return targets[0] if len(targets) > 0 else None
                if name == "targets.1": return targets[1] if len(targets) > 1 else None
                return None
            first = role(effect.get("duel_source", "owner"))
            second = role(effect.get("duel_target", "targets.0"))
            if first is None or second is None or first is second or not first.alive or not second.alive:
                return False
            if not await self.manager.duel(first, second, reason):
                return False
        elif kind == "exclude_targets":
            current = list(event.get("targets", []))
            chosen_players = event.get("_chosen_players", [])
            excluded = [p for p in chosen_players if any(p is candidate for candidate in current)]
            if not excluded:
                return False
            event["_targets"] = [p for p in current if p not in excluded]
        elif kind == "replace_judgment":
            card, judged = event.get("card"), event.get("target")
            if card is None or judged is None or not selected_cards:
                return False
            replacement = selected_cards[0]
            zone = "equipment" if any(replacement is c for c in owner.equipment.values()) else "hand"
            taken = await card_flow.take_judge_replacement(
                self.engine, self.engine.game_state, owner, judged, replacement, zone, reason=reason,
            )
            if taken is None:
                return False
            claim_old = bool(effect.get("claim_old", False))
            await card_flow.release_shown(self.engine, self.engine.game_state, card,
                                          "hand" if claim_old else "discard",
                                          to_owner=owner if claim_old else None,
                                          reason=reason if claim_old else "判定替换",
                                          actor_id=owner.id)
            if taken == "legacy":
                await self.manager.on_cards_lost(owner, [replacement], reason)
            event["_replacement"] = replacement
            event["replacement_suit"] = replacement.suit
            event["replacement_rank"] = replacement.rank
            if claim_old:
                await self.manager.on_card_gained(owner, [card], reason)
            else:
                await self.manager.on_card_discarded(judged, card, "判定替换")
        elif kind == "discard_card":
            cards = _lookup(effect["cards_from"], self._scope(owner, event)) if effect.get("cards_from") else selected_cards
            if effect.get("cards_from") and cards is not None and not isinstance(cards, list):
                cards = [cards]
            card_owner = self._card_owner(owner, effect, event) if effect.get("cards_from") else event.get("_selected_card_owner", owner)
            zone = effect.get("zone", event.get("_selected_zone", "hand"))
            if not isinstance(cards, list):
                return False
            for card in cards:
                _tick(budget)
                if not any(card is c for c in self._card_candidates(card_owner, {"zone": zone}, event)):
                    return False
                if not await self._discard_card(card_owner, card, zone, reason):
                    return False
        elif kind == "transfer_card":
            cards = _lookup(effect["cards_from"], self._scope(owner, event)) if effect.get("cards_from") else selected_cards
            if effect.get("cards_from") and cards is not None and not isinstance(cards, list):
                cards = [cards]
            card_owner = self._card_owner(owner, effect, event) if effect.get("cards_from") else event.get("_selected_card_owner", owner)
            zone = effect.get("zone", event.get("_selected_zone", "hand"))
            if not isinstance(cards, list):
                return False
            if recipient:
                for card in cards:
                    _tick(budget)
                    if not any(card is c for c in self._card_candidates(card_owner, {"zone": zone}, event)):
                        return False
                    if not await self._transfer_card(card_owner, recipient[0], card, zone, reason):
                        return False
        elif kind == "card_as":
            if not selected_cards:
                return False
            from .state_manager import Card
            card_name = effect["card"]
            card_type = "basic" if card_name in {"杀", "桃", "酒"} else "trick"
            targets_for_card = recipient if effect.get("target", "targets") == "targets" else recipient
            virtual = Card(f"dsl:{owner.id}:{event.get('_skill_name', 'skill')}:{selected_cards[0].id}", card_name,
                           selected_cards[0].suit, selected_cards[0].rank, card_type)
            probe = selected_cards[0]
            original_name, original_type = probe.name, probe.card_type
            try:
                probe.name, probe.card_type = card_name, card_type
                legal, _reason = self.engine.rules.can_play_card(owner, probe, targets_for_card)
            finally:
                probe.name, probe.card_type = original_name, original_type
            if not legal:
                return False
            for selected in selected_cards:
                if not await self.manager.discard_card(owner, selected, reason):
                    return False
                if self.engine.game_aborted or not owner.alive:
                    return False
            success = await self.engine.card_system.use_card(owner, virtual, targets_for_card)
            await self.manager.after_card_used(owner, virtual, targets_for_card, success)
            return bool(success)
        return True

    async def _discard_card(self, owner, card, zone, reason):
        if zone == "hand" or (isinstance(zone, str) and zone.startswith("local:")):
            return await self.manager.discard_card(owner, card, reason)
        if zone == "hand_or_equipment":
            zone = "equipment" if any(card is c for c in owner.equipment.values()) else "hand"
            if zone == "hand":
                return await self.manager.discard_card(owner, card, reason)
        move = await self.engine.move_card(card, zone, "discard", from_owner=owner,
                                           reason=reason, actor_id=owner.id)
        if move is None:
            return False
        await self.engine.card_system.notify_card_to_discard(owner, card, "discard", None,
                                                             f"{owner.name}因{reason}弃置【{card.name}】")
        return True

    async def _transfer_card(self, source, target, card, zone, reason):
        if zone == "hand" or (isinstance(zone, str) and zone.startswith("local:")):
            return await self.manager.transfer_card(source, target, card, reason)
        if zone == "hand_or_equipment":
            zone = "equipment" if any(card is c for c in source.equipment.values()) else "hand"
            if zone == "hand":
                return await self.manager.transfer_card(source, target, card, reason)
        move = await self.engine.move_card(card, zone, "hand", from_owner=source, to_owner=target,
                                           reason=reason, actor_id=source.id, visibility="owner")
        if move is None:
            return False
        await self.manager.on_cards_lost(source, [card], reason)
        await self.manager.on_card_gained(target, [card], reason)
        return True


__all__ = ["CompiledSkill", "SkillDSLRuntime", "SkillDSLValidationError", "SkillDSLRuntimeLimitError", "compile_skill", "evaluate_condition"]
