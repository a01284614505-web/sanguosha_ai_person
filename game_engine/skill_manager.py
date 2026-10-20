#!/usr/bin/env python3
"""54技能统一注册、合法操作和事件分发。"""

import inspect
import logging
from importlib import import_module
from typing import Dict, List

from . import card_flow
from .game_stats import clear_damage_source, record_stat
from .skill_runtime_core import card_color, hero_id, reset_turn_flags
from .skill_runtime_state import SkillStateStore
from .skill_runtime_core import RuntimeSkill
from .skill_dsl import (SkillDSLRuntime, compile_skill, evaluate_condition,
                        _resolve_value, _resolve_bounds, _matches_card_filter)
from .skills_generated import get_all_skills, get_hero_skills


logger = logging.getLogger(__name__)


class SkillManager:
    _BENEFIT_TARGET_SKILLS = frozenset({"遗计", "清俭", "连营", "涯角"})
    _HARM_TARGET_SKILLS = frozenset({"雷击", "流离", "利驭", "奋威", "铁骑"})
    _FREE_BENEFIT_SKILLS = frozenset({"闭月", "奸雄", "天妒", "遗计", "集智"})

    def __init__(self, engine=None):
        self.engine = engine
        self.registered_skills: Dict[int, List] = {}
        self.handlers = []
        self.activation_log: List[Dict] = []
        self.skill_state = SkillStateStore()
        self._loss_batches = {}
        self.dsl_runtime = SkillDSLRuntime(self)
        self.dsl_programs = {}
        self._dsl_actor_usage = {}
        if engine is not None:
            self.bind_engine(engine)

    def bind_engine(self, engine):
        self.engine = engine
        self.dsl_runtime.engine = engine
        self.registered_skills.clear()
        self.skill_state = SkillStateStore()
        self._loss_batches.clear()
        self.dsl_programs.clear()
        self._dsl_actor_usage.clear()
        self.dsl_runtime.diagnostics.clear()
        for player in engine.game_state.players:
            skills = get_hero_skills(hero_id(player))
            by_name = {skill.name: skill for skill in skills}
            for definition in (player.hero or {}).get("skills", []):
                if not isinstance(definition, dict) or not isinstance(definition.get("dsl"), dict):
                    continue
                try:
                    compiled = compile_skill(definition["dsl"])
                except ValueError as exc:
                    logger.warning("拒绝无效技能 DSL %s/%s: %s", hero_id(player), definition.get("name"), exc)
                    continue
                name = str(definition.get("name") or "").strip()
                status = definition.get("implementation_status", "partial")
                if not name or status not in ("active", "partial", "data_only"):
                    continue
                # Keep metadata-only declarations out of every executable DSL
                # lookup, including overrides of names backed by native skills.
                if status == "active":
                    self.dsl_programs[(player.id, name)] = compiled
                runtime = by_name.get(name)
                if runtime is None:
                    runtime = RuntimeSkill(
                        skill_id=f"{hero_id(player)}_{name}", name=name,
                        owner_hero_id=hero_id(player), skill_type=definition.get("type", "trigger"),
                        trigger_event=compiled.program["trigger"],
                        description=str(definition.get("description") or ""),
                        implementation_status=status,
                    )
                    skills.append(runtime)
                    by_name[name] = runtime
            self.registered_skills[player.id] = skills
            for skill in self.registered_skills[player.id]:
                dsl_program = self.dsl_programs.get((player.id, skill.name))
                usage = dsl_program.program.get("usage", {}) if dsl_program is not None else {}
                scope = usage.get("scope", "current_turn") if usage else ("current_turn" if skill.name == "制衡" else "game")
                if scope == "actor_turn":
                    # Delegated actions keep their donor-specific counter separately.
                    scope = "current_turn"
                charges = usage.get("charges") if usage else (1 if skill.name == "替身" else None)
                state = {"awakened": False} if skill.name == "勤学" else None
                self.skill_state.register(
                    player.id, skill.skill_id, version_id=getattr(skill, "version_id", None),
                    source=hero_id(player) or "native", charges=charges,
                    usage_scope=scope, state=state,
                )
        self._load_handlers()
        return self

    async def _run_dsl(self, trigger, owners, event):
        if self.engine is None or self.engine.game_aborted:
            return False
        event["trigger"] = trigger
        skip_default = False
        for owner in owners:
            if owner is None or not owner.alive:
                continue
            for skill in self.player_skills(owner, active_only=True):
                compiled = self.dsl_programs.get((owner.id, skill.name))
                if (compiled is not None and trigger in compiled.program.get("triggers", [compiled.program["trigger"]])
                        and self.has_skill(owner, skill.name)):
                    executed = await self.dsl_runtime.run(compiled, owner, event, skill.name)
                    skip_default = skip_default or bool(executed and compiled.program.get("skip_default"))
        return skip_default

    def _load_handlers(self):
        self.handlers = []
        shu_module = import_module(".skills_shu", __package__)
        self.handlers.append(shu_module.ShuSkillHandler(self))
        # 其他势力处理器在蜀国试点验证后注册。
        for module_name, class_name in [
            ("skills_wei", "WeiSkillHandler"),
            ("skills_wu", "WuSkillHandler"),
            ("skills_qun", "QunSkillHandler"),
        ]:
            module = import_module(f".{module_name}", __package__)
            self.handlers.append(getattr(module, class_name)(self))

    def all_definitions(self):
        return get_all_skills()

    def player_skills(self, player, active_only=False):
        skills = self.registered_skills.get(player.id, [])
        if active_only:
            return [s for s in skills if s.implementation_status == "active"]
        return list(skills)

    def public_player_skills(self, player):
        by_name = {s.name: s for s in self.player_skills(player)}
        raw = (player.hero or {}).get("skills", [])
        result = []
        for item in raw:
            item = dict(item) if isinstance(item, dict) else {"name": str(item)}
            runtime = by_name.get(item.get("name"))
            if runtime:
                item.update(runtime.public_dict())
            else:
                item["implementation_status"] = "data_only"
            result.append(item)
        return result

    def has_skill(self, player, name, active_only=True):
        matches = [skill for skill in self.player_skills(player)
                   if skill.name == name and (not active_only or skill.implementation_status == "active")]
        if not matches:
            return False
        if getattr(player, "flags", {}).get("nonlocked_disabled") and all(
            skill.skill_type not in ("locked",) for skill in matches
        ):
            return False
        return any(self.skill_state.has_enabled(player.id, skill.skill_id) for skill in matches)

    def dsl_overrides_native(self, player, name):
        """An active imported declaration is the single implementation for this named skill."""
        compiled = self.dsl_programs.get((player.id, name))
        skill = next((item for item in self.player_skills(player) if item.name == name), None)
        return bool(compiled is not None and skill is not None and skill.implementation_status == "active"
                    and self.has_skill(player, name))

    def dsl_actor_skill_available(self, skill_owner, actor, name, limit=1):
        turn_id = getattr(self.engine, "completed_turns", None)
        return self._dsl_actor_usage.get((skill_owner.id, actor.id, name, turn_id), 0) < limit

    def consume_dsl_actor_skill_use(self, skill_owner, actor, name, limit=1):
        if not self.dsl_actor_skill_available(skill_owner, actor, name, limit):
            return False
        turn_id = getattr(self.engine, "completed_turns", None)
        key = (skill_owner.id, actor.id, name, turn_id)
        self._dsl_actor_usage[key] = self._dsl_actor_usage.get(key, 0) + 1
        return True

    @staticmethod
    def _action_actor_allowed(selector, actor):
        faction = (actor.hero or {}).get("faction")
        return selector in {"faction:qun", "faction:群"} and faction in {"qun", "群"}

    def _skill_instance(self, player, name):
        skill = next((item for item in self.player_skills(player) if item.name == name), None)
        return None if skill is None else self.skill_state.get(
            player.id, skill.skill_id, version_id=getattr(skill, "version_id", None)
        )

    def skill_state_value(self, player, name, key, default=None):
        instance = self._skill_instance(player, name)
        return default if instance is None else instance.state.get(key, default)

    def set_skill_state(self, player, name, key, value):
        skill = next((item for item in self.player_skills(player) if item.name == name), None)
        if skill is None:
            return 0
        return self.skill_state.set_state(
            player.id, skill.skill_id, key, value,
            version_id=getattr(skill, "version_id", None),
        )

    def skill_available(self, player, name, *, phase=None, limit=1):
        instance = self._skill_instance(player, name)
        if instance is None:
            return False
        state = self.engine.game_state
        current = state.current_player
        for source in self.skill_state.find(player.id, instance.skill_id):
            if source.version_id != instance.version_id or not source.enabled:
                continue
            if (source.usage_scope == "current_turn" and current is not player):
                continue
            key = source.scope_key(
                phase=getattr(phase, "value", phase),
                current_player_id=getattr(current, "id", None),
                turn_id=getattr(self.engine, "completed_turns", None),
                round_number=state.round_number,
                turn_policy="owner",
            )
            if source.usage_counts.get(key, 0) < limit and (source.charges is None or source.charges > 0):
                return True
        return False

    def consume_skill_use(self, player, name, *, phase=None, charges=0, limit=1):
        instance = self._skill_instance(player, name)
        if instance is None:
            return False
        state = self.engine.game_state
        current = state.current_player
        return self.skill_state.consume(
            player.id, instance.skill_id, version_id=instance.version_id,
            phase=getattr(phase, "value", phase),
            current_player_id=getattr(current, "id", None),
            turn_id=getattr(self.engine, "completed_turns", None),
            round_number=state.round_number, turn_policy="owner",
            limit=limit, charges=charges,
        )

    def gain_skill(self, player, skill_id, *, source, version_id=None, **options):
        """Register an additional source; identical sources use reference counts."""
        return self.skill_state.add_source(
            player.id, skill_id, source, version_id=version_id, **options
        )

    def lose_skill_source(self, player, skill_id, *, source, version_id=None):
        return self.skill_state.remove_source(
            player.id, skill_id, source, version_id=version_id
        )

    def disable_skill(self, player, skill_id, *, source=None):
        return self.skill_state.disable(player.id, skill_id, source=source)

    def restore_skill(self, player, skill_id, *, source=None):
        return self.skill_state.restore(player.id, skill_id, source=source)

    def registration_stats(self):
        all_skills = self.all_definitions()
        return {
            "total_classes": len(all_skills),
            "active_classes": sum(s.implementation_status == "active" for s in all_skills),
            "registered_players": len(self.registered_skills),
            "registered_instances": sum(len(v) for v in self.registered_skills.values()),
        }

    def record(self, player, skill_name, event, **details):
        if self.engine is not None and self.engine.game_aborted:
            return None
        entry = {
            "player_id": player.id,
            "player_name": player.name,
            "hero_id": hero_id(player),
            "skill_name": skill_name,
            "event": event,
            **details,
        }
        self.activation_log.append(entry)
        if event == "activate":
            record_stat(self.engine, player, "skill_activations")
        logger.info(f"  [技能] {player.name}发动【{skill_name}】({event})")
        return entry

    async def draw_cards(self, player, count, reason="skill"):
        drawer = getattr(self.engine, "draw_cards", None)
        if callable(drawer) and getattr(self.engine, "game_state", None) is not None and hasattr(self.engine, "move_card"):
            cards = await drawer(player, count, reason)
        else:
            cards = self.engine.game_state.draw_card(player, count)
        await self.on_card_gained(player, cards, reason)
        return cards

    async def discard_card(self, player, card, reason="skill"):
        if self.engine is None or card not in player.hand or self.engine.game_aborted:
            return False
        index = player.hand.index(card)
        move = await self.engine.move_card(
            card, "hand", "discard", from_owner=player,
            reason=reason, actor_id=player.id,
        )
        if move is None:
            return False
        await self.engine.card_system.notify_card_to_discard(
            player, card, "discard", index, f"{player.name}因{reason}弃置【{card.name}】"
        )
        await self.on_card_discarded(player, card, reason)
        return True

    def ledger_kind(self, skill_name) -> str:
        """技能在行为账本里的类型（取自 RuntimeSkill 元数据，默认 none）。"""
        kinds = getattr(self, "_ledger_kinds", None)
        if kinds is None:
            kinds = self._ledger_kinds = {s.name: s.ledger_kind for s in get_all_skills()}
        return kinds.get(skill_name, "none")

    def ledger_record(self, skill_name, source, target, *, label=None, weight=None):
        """技能结算确定目标时记账；类型取自技能元数据。没有账本或类型为 none 时什么也不做。"""
        ledger = getattr(self.engine, "ledger", None)
        kind = self.ledger_kind(skill_name)
        if ledger is None or kind == "none" or source is None or target is None:
            return None
        return ledger.record(self.engine.game_state.round_number, source.id, target.id,
                             kind, label or skill_name, weight)

    async def transfer_card(self, source, target, card, reason="skill"):
        if self.engine is None or self.engine.game_aborted or card not in source.hand:
            return False
        move = await self.engine.move_card(
            card, "hand", "hand", from_owner=source, to_owner=target,
            reason=reason, actor_id=source.id, visibility="owner",
        )
        if move is None:
            return False
        if not self.engine.game_aborted:
            await self.on_card_gained(target, [card], reason)
        return True

    async def ask_confirm(self, player, prompt, **kwargs):
        context = dict(kwargs.get("context") or {})
        skill_name = kwargs.get("skill_name")
        if skill_name:
            context.setdefault("skill_name", skill_name)
            context.setdefault("actual_chooser_id", player.id)
            context.setdefault("intent", "benefit" if skill_name in self._FREE_BENEFIT_SKILLS else "conditional")
            context.setdefault("cost", "none" if skill_name in self._FREE_BENEFIT_SKILLS else "skill_specific")
            kwargs["context"] = context
        return await self.engine.ask_confirm(player, prompt, **kwargs)

    async def ask_choose_players(self, player, prompt, candidates, **kwargs):
        context = dict(kwargs.get("context") or {})
        skill_name = kwargs.get("skill_name")
        if skill_name:
            context.setdefault("skill_name", skill_name)
            context.setdefault("actual_chooser_id", player.id)
            if skill_name in self._BENEFIT_TARGET_SKILLS:
                context.setdefault("intent", "benefit")
            elif skill_name in self._HARM_TARGET_SKILLS:
                context.setdefault("intent", "harm")
            context.setdefault("cost", "target_selection")
            kwargs["context"] = context
        return await self.engine.ask_choose_players(player, prompt, candidates, **kwargs)

    async def ask_choose_cards(self, player, prompt, candidates, **kwargs):
        context = dict(kwargs.get("context") or {})
        skill_name = kwargs.get("skill_name")
        if skill_name:
            context.setdefault("skill_name", skill_name)
            context.setdefault("actual_chooser_id", player.id)
            context.setdefault("cost", "card_selection")
            kwargs["context"] = context
        return await self.engine.ask_choose_cards(player, prompt, candidates, **kwargs)

    async def ask_choose_cards_result(self, player, prompt, candidates, **kwargs):
        context = dict(kwargs.get("context") or {})
        skill_name = kwargs.get("skill_name")
        if skill_name:
            context.setdefault("skill_name", skill_name)
            context.setdefault("actual_chooser_id", player.id)
            context.setdefault("cost", "card_selection")
            kwargs["context"] = context
        return await self.engine.ask_choose_cards_result(player, prompt, candidates, **kwargs)

    async def ask_choose_option(self, player, prompt, choices, **kwargs):
        context = dict(kwargs.get("context") or {})
        skill_name = kwargs.get("skill_name")
        if skill_name:
            context.setdefault("skill_name", skill_name)
            context.setdefault("actual_chooser_id", player.id)
            context.setdefault("cost", "option_selection")
            kwargs["context"] = context
        return await self.engine.ask_choose_option(player, prompt, choices, **kwargs)

    async def lose_hp(self, player, amount=1, reason="skill", source=None):
        amount = max(0, int(amount))
        if not amount:
            return
        player.hp -= amount
        # 失去体力不是伤害：清掉旧伤害来源，死亡时不得把击杀记到早前的伤害上。
        if self.engine is not None:
            clear_damage_source(self.engine.game_state, player)
        await self.on_hp_lost(player, amount, reason, source)
        if player.hp <= 0:
            await self.engine.card_system.enter_dying(player)

    async def recover(self, player, amount=1, source=None, reason="skill"):
        before = player.hp
        player.hp = min(player.max_hp, player.hp + max(0, int(amount)))
        recovered = player.hp - before
        if recovered:
            record_stat(self.engine, source or player, "healing", recovered)
            await self.on_recover(player, recovered, source, reason)
        return recovered

    async def judge(self, player, reason="skill"):
        state = self.engine.game_state
        judge_reason = f"判定【{reason}】"
        revealed = await card_flow.reveal_top(self.engine, state, player, 1, reason=judge_reason)
        if not revealed:
            return None
        card = revealed[0]
        card = await self.before_judge(player, card, {"reason": reason})
        # 技能判定（洛神、刚烈、雷击等）也走判定框；是否“生效”由各技能自行解读，这里不下结论。
        announce = getattr(self.engine, "announce_judge", None)
        if announce is not None:
            pending = announce(player, card, reason)
            if inspect.isawaitable(pending):
                await pending
        claimed = await self.after_judge(player, card, {"reason": reason})
        if not claimed:
            await card_flow.release_shown(self.engine, state, card, "discard",
                                          reason=f"{judge_reason}结算", actor_id=player.id)
            await self.on_card_discarded(player, card, "judge")
        return card

    async def duel(self, source, target, reason="决斗"):
        if self.target_error(source, target, "决斗"):
            return False
        from .state_manager import Card
        card = Card(f"virtual_duel:{source.id}:{target.id}:{reason}", "决斗", "spade", 1, "trick")
        context = self.engine._new_effect_context(
            source, card, skill_source=reason, card_cost_ids=[], target=target,
        )
        return await self.engine.card_system.resolve_duel(
            source, target, card, effect_context=context, reason=reason,
        )

    async def announce(self, player, skill_name, message=None):
        self.record(player, skill_name, "activate")
        if self.engine:
            await self.engine.log_event(
                message or f"{player.name}发动【{skill_name}】",
                event_kind="skill_activation",
                actor_id=player.id,
                actor_name=player.name,
                skill_name=skill_name,
                system_text=f"[‘{player.name}’发动‘{skill_name}’]",
            )

    def get_actions(self, player):
        actions = []
        for handler in self.handlers:
            actions.extend(handler.get_actions(player))
        for skill in self.player_skills(player, active_only=True):
            compiled = self.dsl_programs.get((player.id, skill.name))
            if (compiled is not None and not compiled.program.get("action_actors")
                    and compiled.program["trigger"] == "play_action"
                    and self.has_skill(player, skill.name)):
                event = {"action": "play_action", "_skill_name": skill.name, "_locals": {}}
                if not evaluate_condition(compiled.program.get("condition", True), self.dsl_runtime._scope(player, event)):
                    continue
                usage = compiled.program.get("usage")
                if usage and not self.skill_available(
                        player, skill.name, phase=self.engine.game_state.current_phase,
                        limit=usage.get("limit", 1)):
                    continue
                can_pay = True
                scope = self.dsl_runtime._scope(player, event)
                for cost in compiled.program.get("cost", []):
                    if cost["interaction"] == "ask_choose_cards":
                        filt = cost.get("filter", {})
                        card_owner = self.dsl_runtime._card_owner(player, cost, event)
                        available = self.dsl_runtime._card_candidates(card_owner, cost, event) if card_owner else []
                        available = [c for c in available if _matches_card_filter(c, filt)]
                        bounds = _resolve_bounds(cost, scope)
                        if bounds is None or len(available) < bounds[0]:
                            can_pay = False
                            break
                        if filt.get("same_suit") and max((sum(1 for c in available if c.suit == suit) for suit in {c.suit for c in available}), default=0) < bounds[0]:
                            can_pay = False
                            break
                targets = compiled.program.get("targets", {"selector": "self", "min": 1, "max": 1})
                if can_pay and targets.get("selector") == "chosen_players":
                    candidates = self.dsl_runtime._candidates(targets.get("candidates", "alive_others"), player, event,
                                                              targets.get("exclude_state"))
                    bounds = _resolve_bounds(targets, scope)
                    if bounds is None or len(candidates) < bounds[0]:
                        can_pay = False
                if not can_pay:
                    continue
                actions.append({"type": "use_skill", "skill_name": skill.name,
                                "variant": "dsl", "requires_target": False,
                                "valid_targets": [], "text": f"发动【{skill.name}】"})
        for skill_owner in self.engine.game_state.players:
            if skill_owner is player or not skill_owner.alive:
                continue
            for skill in self.player_skills(skill_owner, active_only=True):
                compiled = self.dsl_programs.get((skill_owner.id, skill.name))
                if (compiled is None or compiled.program["trigger"] != "play_action"
                        or not self.has_skill(skill_owner, skill.name)
                        or not self._action_actor_allowed(compiled.program.get("action_actors"), player)):
                    continue
                event = {"action": "play_action", "target": skill_owner,
                         "_skill_name": skill.name, "_dsl_state_owner": skill_owner, "_locals": {}}
                if not evaluate_condition(compiled.program.get("condition", True), self.dsl_runtime._scope(player, event)):
                    continue
                usage = compiled.program.get("usage")
                if usage and (usage.get("scope") != "actor_turn" or not self.dsl_actor_skill_available(
                        skill_owner, player, skill.name, usage.get("limit", 1))):
                    continue
                can_pay = True
                for cost in compiled.program.get("cost", []):
                    if cost["interaction"] == "ask_choose_cards":
                        bounds = _resolve_bounds(cost, self.dsl_runtime._scope(player, event))
                        card_owner = self.dsl_runtime._card_owner(player, cost, event)
                        available = self.dsl_runtime._card_candidates(card_owner, cost, event) if card_owner else []
                        if bounds is None or len(available) < bounds[0]:
                            can_pay = False
                            break
                if can_pay:
                    actions.append({"type": "use_skill", "skill_name": skill.name,
                                    "variant": "dsl", "dsl_owner_id": skill_owner.id,
                                    "requires_target": False, "valid_targets": [],
                                    "text": f"响应【{skill.name}】"})
        return actions

    async def execute(self, player, action, targets):
        if action.get("variant") == "dsl":
            skill_owner = next((p for p in self.engine.game_state.players
                                if p.id == action.get("dsl_owner_id")), player)
            skill_name = action.get("skill_name")
            compiled = self.dsl_programs.get((skill_owner.id, skill_name))
            delegated = skill_owner is not player
            if (compiled is None or compiled.program["trigger"] != "play_action"
                    or not self.has_skill(skill_owner, skill_name)
                    or (delegated and not self._action_actor_allowed(compiled.program.get("action_actors"), player))
                    or self.engine is None
                    or self.engine.game_state.current_phase.value != "play"
                    or self.engine.game_state.current_player is not player):
                return False
            event = {"action": "play_action", "target": skill_owner if delegated else None,
                     "_dsl_state_owner": skill_owner, "_locals": {}}
            return await self.dsl_runtime.run(compiled, player, event, skill_name)
        for handler in self.handlers:
            if await handler.execute(player, action, targets):
                return True
        return False

    def reset_turn_scope(self, player):
        """Open a fresh per-turn scope without dispatching any skill trigger."""
        reset_turn_flags(player)
        for other in self.engine.game_state.players:
            used = getattr(other, "flags", {}).get("skill_used", {})
            used.pop("护驾摸牌", None)
            used.pop("激将摸牌", None)
        player.max_sha = 1

    async def on_turn_start(self, player):
        self.reset_turn_scope(player)
        self._apply_turn_modifiers(player)
        await self._run_dsl("turn_start", [player], {"player": player})
        for handler in self.handlers:
            await handler.on_turn_start(player)

    async def before_phase(self, player, phase):
        result = {"skip_default": False}
        result["skip_default"] = await self._run_dsl(
            "phase_start", [player], {"player": player, "phase": getattr(phase, "value", phase)}
        )
        for handler in self.handlers:
            value = await handler.before_phase(player, phase)
            if isinstance(value, dict):
                result.update(value)
        return result

    async def after_phase(self, player, phase):
        await self._run_dsl("phase_end", [player], {"player": player, "phase": getattr(phase, "value", phase)})
        for handler in self.handlers:
            await handler.after_phase(player, phase)

    async def before_sha(self, source, target, card, event):
        for skill in self.player_skills(source, active_only=True):
            compiled = self.dsl_programs.get((source.id, skill.name))
            if compiled is None or not self.has_skill(source, skill.name):
                continue
            scope = self.dsl_runtime._scope(source, {"target": target, "card_name": getattr(card, "name", None), "_skill_name": skill.name})
            for modifier in compiled.program.get("modifiers", []):
                if modifier["stat"] == "response_count" and evaluate_condition(modifier.get("when", True), scope):
                    value = _resolve_value(modifier["value"], scope)
                    if type(value) is int:
                        event["shanRequired"] = max(event.get("shanRequired", 1), value)
        for handler in self.handlers:
            await handler.before_sha(source, target, card, event)

    async def on_sha_dodged(self, source, target, card, event):
        await self._run_dsl("sha_dodged", [source], {"source": source, "target": target,
                                                       "card_name": getattr(card, "name", None)})
        for handler in self.handlers:
            await handler.on_sha_dodged(source, target, card, event)

    async def modify_damage(self, source, target, amount, card=None, context=None):
        for handler in self.handlers:
            amount = await handler.modify_damage(source, target, amount, card, context)
        return max(0, int(amount))

    async def after_damage(self, source, target, amount, card=None, context=None):
        event = {"source": source, "target": target, "amount": amount,
                 "card": card,
                 "card_name": getattr(card, "name", None),
                 "card_color": card_color(card) if card is not None else None,
                 "card_available": bool(card is not None and card in self.engine.game_state.discard_pile)}
        await self._run_dsl("damage_received", [target], event)
        await self._run_dsl("damage_dealt", [source], event)
        for handler in self.handlers:
            await handler.after_damage(source, target, amount, card, context)

    async def after_card_used(self, player, card, targets, success):
        await self._run_dsl("card_used", [player], {"card": card, "card_name": getattr(card, "name", None),
                                                        "card_type": getattr(card, "card_type", None),
                                                        "targets": targets, "success": bool(success)})
        for handler in self.handlers:
            await handler.after_card_used(player, card, targets, success)

    async def on_card_responded(self, player, card, as_name, context=None):
        await self._run_dsl("card_responded", [player], {"card_name": getattr(card, "name", None), "as_name": as_name})
        for handler in self.handlers:
            await handler.on_card_responded(player, card, as_name, context)

    def response_options(self, player, requested_name):
        options = []
        for handler in self.handlers:
            options.extend(handler.response_options(player, requested_name))
        for skill in self.player_skills(player, active_only=True):
            compiled = self.dsl_programs.get((player.id, skill.name))
            if compiled is None or not self.has_skill(player, skill.name):
                continue
            for conversion in compiled.program.get("conversions", []):
                if conversion["as"] != requested_name:
                    continue
                scope = self.dsl_runtime._scope(player, {"requested_name": requested_name, "_skill_name": skill.name})
                if not evaluate_condition(conversion.get("when", True), scope):
                    continue
                entries = self.handlers[0].response_card_entries(player) if self.handlers else []
                for card, index, zone in entries:
                    color = card_color(card)
                    if conversion.get("names") and card.name not in conversion["names"]:
                        continue
                    if conversion.get("color") and color != conversion["color"]:
                        continue
                    if conversion.get("suits") and card.suit not in conversion["suits"]:
                        continue
                    options.append({"card": card, "card_index": index, "owner": player,
                                    "as_name": requested_name, "skill_name": skill.name,
                                    "source_zone": zone})
        return options

    def required_response_count(self, player, requested_name, base_count=1, context=None):
        count = base_count
        for skill in self.player_skills(player, active_only=True):
            compiled = self.dsl_programs.get((player.id, skill.name))
            if compiled is None or not self.has_skill(player, skill.name):
                continue
            scope = self.dsl_runtime._scope(player, {"requested_name": requested_name, "_skill_name": skill.name, **(context or {})})
            for modifier in compiled.program.get("modifiers", []):
                if modifier["stat"] == "response_count" and evaluate_condition(modifier.get("when", True), scope):
                    value = _resolve_value(modifier["value"], scope)
                    if type(value) is int:
                        count = max(count, value)
        return count

    async def request_lord_sha(self, player, first_donor):
        for handler in self.handlers:
            request = getattr(handler, "request_jijiang_response", None)
            if request is not None:
                return await request(player, first_donor)
        return None

    def target_error(self, source, target, card_name):
        for handler in self.handlers:
            error = handler.can_target(source, target, card_name)
            if error:
                return error
        for skill in self.player_skills(target, active_only=True):
            compiled = self.dsl_programs.get((target.id, skill.name))
            if compiled is None or not self.has_skill(target, skill.name):
                continue
            scope = self.dsl_runtime._scope(target, {"source": source, "card_name": card_name, "_skill_name": skill.name})
            for modifier in compiled.program.get("modifiers", []):
                if (modifier["stat"] == "target_protection"
                        and evaluate_condition(modifier.get("when", True), scope)):
                    return f"{target.name}的技能【{skill.name}】禁止成为此牌目标"
        return None

    def modify_distance(self, source, target, distance):
        for handler in self.handlers:
            distance = handler.modify_distance(source, target, distance)
        for skill in self.player_skills(source, active_only=True):
            compiled = self.dsl_programs.get((source.id, skill.name))
            if compiled is None or not self.has_skill(source, skill.name):
                continue
            scope = self.dsl_runtime._scope(source, {"target": target, "_skill_name": skill.name})
            for modifier in compiled.program.get("modifiers", []):
                if modifier["stat"] != "distance" or not evaluate_condition(modifier.get("when", True), scope):
                    continue
                value = _resolve_value(modifier["value"], scope)
                if type(value) is int:
                    distance += value if modifier["op"] == "add" else -value
        return max(1, distance)

    def _apply_turn_modifiers(self, player):
        for skill in self.player_skills(player, active_only=True):
            compiled = self.dsl_programs.get((player.id, skill.name))
            if compiled is None or not self.has_skill(player, skill.name):
                continue
            scope = self.dsl_runtime._scope(player, {"_skill_name": skill.name})
            for modifier in compiled.program.get("modifiers", []):
                if modifier["stat"] != "max_sha" or not evaluate_condition(modifier.get("when", True), scope):
                    continue
                value = _resolve_value(modifier["value"], scope)
                if type(value) is int:
                    player.max_sha = max(player.max_sha, value)

    def ignore_distance(self, source, card):
        if any(handler.ignore_distance(source, card) for handler in self.handlers):
            return True
        for skill in self.player_skills(source, active_only=True):
            compiled = self.dsl_programs.get((source.id, skill.name))
            if compiled is None or not self.has_skill(source, skill.name):
                continue
            scope = self.dsl_runtime._scope(source, {"_skill_name": skill.name, "card_name": getattr(card, "name", None),
                                                     "card_suit": getattr(card, "suit", None),
                                                     "card_type": getattr(card, "card_type", None)})
            if any(modifier["stat"] == "ignore_distance"
                   and evaluate_condition(modifier.get("when", True), scope)
                   for modifier in compiled.program.get("modifiers", [])):
                return True
        return False

    def hand_limit(self, player, current):
        for handler in self.handlers:
            current = handler.hand_limit(player, current)
        for skill in self.player_skills(player, active_only=True):
            compiled = self.dsl_programs.get((player.id, skill.name))
            if compiled is None or not self.has_skill(player, skill.name):
                continue
            scope = self.dsl_runtime._scope(player, {"_skill_name": skill.name})
            for modifier in compiled.program.get("modifiers", []):
                if modifier["stat"] != "hand_limit" or not evaluate_condition(modifier.get("when", True), scope):
                    continue
                value = _resolve_value(modifier["value"], scope)
                if type(value) is not int:
                    continue
                if modifier["op"] == "add":
                    current += value
                else:
                    current = max(current, value)
        return max(0, current)

    def protect_card(self, owner, card, reason):
        if any(handler.protect_card(owner, card, reason) for handler in self.handlers):
            return True
        for skill in self.player_skills(owner, active_only=True):
            compiled = self.dsl_programs.get((owner.id, skill.name))
            if compiled is None or not self.has_skill(owner, skill.name):
                continue
            scope = self.dsl_runtime._scope(owner, {"card_name": getattr(card, "name", None), "reason": reason})
            if any(modifier["stat"] == "protect_card"
                   and evaluate_condition(modifier.get("when", True), scope)
                   for modifier in compiled.program.get("modifiers", [])):
                return True
        return False

    async def before_judge(self, player, card, context=None):
        event = {"card": card, "target": player, "card_name": getattr(card, "name", None),
                 "card_color": card_color(card), "card_suit": getattr(card, "suit", None),
                 "card_rank": getattr(card, "rank", None), "judged_color": card_color(card),
                 "judged_suit": getattr(card, "suit", None), "judged_rank": getattr(card, "rank", None),
                 "context": context or {}}
        await self._run_dsl("judge_before", list(self.engine.game_state.players), event)
        if event.get("_replacement") is not None:
            return event["_replacement"]
        for handler in self.handlers:
            card = await handler.before_judge(player, card, context)
        return card

    async def after_judge(self, player, card, context=None):
        event = {"card": card, "target": player, "card_name": getattr(card, "name", None),
                 "card_color": card_color(card), "card_suit": getattr(card, "suit", None),
                 "card_rank": getattr(card, "rank", None), "context": context or {}}
        await self._run_dsl("judge_after", [player], event)
        claimed = bool(event.get("_claimed"))
        for handler in self.handlers:
            claimed = bool(await handler.after_judge(player, card, context)) or claimed
        return claimed

    async def on_card_gained(self, player, cards, reason="unknown"):
        if not cards:
            return
        await self._run_dsl("card_gained", [player], {"count": len(cards), "reason": reason})
        for handler in self.handlers:
            await handler.on_card_gained(player, cards, reason)

    @staticmethod
    def _is_counted_loss(event):
        return (
            event.from_owner is not None
            and event.from_zone in ("hand", "equipment")
            and event.to_zone != "temporary"
            and (event.from_owner != event.to_owner or event.from_zone != event.to_zone)
        )

    def record_card_move_stats(self, event):
        """Record an already committed move before any awaited event publication."""
        player = next((p for p in self.engine.game_state.players if p.id == event.from_owner), None)
        if event.reason == "use_card":
            # 终结对局的杀仍是已提交用牌；投影不能被 game_over 拦掉。
            self.engine.stats.add(player, "cards_played")
        if self._is_counted_loss(event):
            self.engine.stats.add(player, "cards_lost")

    def begin_loss_batch(self, player, reason):
        """Group cards lost in one declared action for X-card skill triggers."""
        if player.id in self._loss_batches:
            raise RuntimeError(f"loss batch already active for player {player.id}")
        self._loss_batches[player.id] = {"reason": reason, "cards": []}

    async def finish_loss_batch(self, player):
        batch = self._loss_batches.pop(player.id, None)
        if batch and batch["cards"]:
            await self.on_cards_lost(
                player, batch["cards"], batch["reason"], record=False,
            )

    async def on_card_move(self, card, event, *, stats_recorded=False):
        """Project statistics and skill hooks from one committed movement fact."""
        if not stats_recorded:
            self.record_card_move_stats(event)
        if self.engine is not None and self.engine.game_aborted:
            return
        for handler in self.handlers:
            await handler.on_card_move(card, event)
        if not self._is_counted_loss(event):
            return
        player = next((p for p in self.engine.game_state.players if p.id == event.from_owner), None)
        if player is None:
            return
        batch = self._loss_batches.get(player.id)
        if batch is not None and event.reason == batch["reason"]:
            batch["cards"].append(card)
            return
        await self.on_cards_lost(player, [card], event.reason, record=False, event=event)

    async def on_cards_lost(self, player, cards, reason="unknown", *, record=True, event=None):
        if not cards or (self.engine is not None and self.engine.game_aborted):
            return
        if record:
            record_stat(self.engine, player, "cards_lost", len(cards))
        if self.engine is not None:
            recipient_count = sum(1 for p in self.engine.game_state.players if p.alive)
            await self._run_dsl("cards_lost", [player], {
                "count": min(len(cards), recipient_count), "lost_count": len(cards),
                "hand_empty": not player.hand, "reason": reason,
                "from_zone": getattr(event, "from_zone", None),
                "to_zone": getattr(event, "to_zone", None),
            })
        for handler in self.handlers:
            await handler.on_cards_lost(player, cards, reason, event=event)

    async def on_card_discarded(self, player, card, reason="unknown"):
        if self.engine is not None and self.engine.game_aborted:
            return
        current = self.engine.game_state.current_player if self.engine else None
        if current:
            ensure = getattr(current, "flags", {})
            ensure.setdefault("turn_discard_suits", set()).add(card.suit)
        for handler in self.handlers:
            await handler.on_card_discarded(player, card, reason)

    async def on_hp_lost(self, player, amount, reason="unknown", source=None):
        if self.engine is not None and self.engine.game_aborted:
            return
        await self._run_dsl("hp_lost", [player], {
            "amount": amount, "reason": reason, "source": source,
        })
        for handler in self.handlers:
            await handler.on_hp_lost(player, amount, reason, source)

    async def on_recover(self, player, amount, source=None, reason="unknown"):
        if self.engine is not None and self.engine.game_aborted:
            return
        await self._run_dsl("recover", [player], {
            "amount": amount, "source": source, "reason": reason,
        })
        for handler in self.handlers:
            await handler.on_recover(player, amount, source, reason)

    async def before_card_target(self, source, target, card):
        for handler in self.handlers:
            updated = await handler.before_card_target(source, target, card)
            if updated is not None:
                target = updated
        return target

    async def before_multi_target_trick(self, source, card, targets):
        event = {"source": source, "card": card, "card_name": getattr(card, "name", None),
                 "card_type": getattr(card, "card_type", None),
                 "targets": list(targets), "target_count": len(targets)}
        await self._run_dsl("multi_target_trick", list(self.engine.game_state.players), event)
        targets = event.get("_targets", targets)
        for handler in self.handlers:
            targets = await handler.before_multi_target_trick(source, card, targets)
        return targets


# 兼容旧MainEngine导入名。
TriggerManager = SkillManager

__all__ = ["SkillManager", "TriggerManager"]
