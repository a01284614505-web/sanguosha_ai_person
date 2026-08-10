#!/usr/bin/env python3
"""54技能统一注册、合法操作和事件分发。"""

from importlib import import_module
from typing import Dict, List

from .skill_runtime_core import hero_id, reset_turn_flags
from .skills_generated import get_all_skills, get_hero_skills


class SkillManager:
    def __init__(self, engine=None):
        self.engine = engine
        self.registered_skills: Dict[int, List] = {}
        self.handlers = []
        self.activation_log: List[Dict] = []
        if engine is not None:
            self.bind_engine(engine)

    def bind_engine(self, engine):
        self.engine = engine
        self.registered_skills.clear()
        for player in engine.game_state.players:
            self.registered_skills[player.id] = get_hero_skills(hero_id(player))
        self._load_handlers()
        return self

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
        for skill in self.player_skills(player):
            if skill.name != name or (active_only and skill.implementation_status != "active"):
                continue
            if getattr(player, "flags", {}).get("nonlocked_disabled") and skill.skill_type not in ("locked",):
                return False
            return True
        return False

    def registration_stats(self):
        all_skills = self.all_definitions()
        return {
            "total_classes": len(all_skills),
            "active_classes": sum(s.implementation_status == "active" for s in all_skills),
            "registered_players": len(self.registered_skills),
            "registered_instances": sum(len(v) for v in self.registered_skills.values()),
        }

    def record(self, player, skill_name, event, **details):
        entry = {
            "player_id": player.id,
            "player_name": player.name,
            "hero_id": hero_id(player),
            "skill_name": skill_name,
            "event": event,
            **details,
        }
        self.activation_log.append(entry)
        print(f"  [技能] {player.name}发动【{skill_name}】({event})")
        return entry

    async def draw_cards(self, player, count, reason="skill"):
        cards = self.engine.game_state.draw_card(player, count)
        await self.on_card_gained(player, cards, reason)
        return cards

    async def discard_card(self, player, card, reason="skill"):
        if card not in player.hand:
            return False
        index = player.hand.index(card)
        player.hand.remove(card)
        self.engine.game_state.discard_pile.append(card)
        await self.engine.card_system.notify_card_to_discard(
            player, card, "discard", index, f"{player.name}因{reason}弃置【{card.name}】"
        )
        await self.on_cards_lost(player, [card], reason)
        await self.on_card_discarded(player, card, reason)
        return True

    async def transfer_card(self, source, target, card, reason="skill"):
        if card not in source.hand:
            return False
        source.hand.remove(card)
        target.hand.append(card)
        await self.on_cards_lost(source, [card], reason)
        await self.on_card_gained(target, [card], reason)
        return True

    async def lose_hp(self, player, amount=1, reason="skill", source=None):
        amount = max(0, int(amount))
        if not amount:
            return
        player.hp -= amount
        await self.on_hp_lost(player, amount, reason, source)
        if player.hp <= 0:
            await self.engine.card_system.enter_dying(player)

    async def recover(self, player, amount=1, source=None, reason="skill"):
        before = player.hp
        player.hp = min(player.max_hp, player.hp + max(0, int(amount)))
        recovered = player.hp - before
        if recovered:
            await self.on_recover(player, recovered, source, reason)
        return recovered

    async def judge(self, player, reason="skill"):
        state = self.engine.game_state
        if not state.deck:
            state.draw_card(player, 0)
        if not state.deck:
            return None
        card = state.deck.pop(0)
        card = await self.before_judge(player, card, {"reason": reason})
        claimed = await self.after_judge(player, card, {"reason": reason})
        if not claimed:
            state.discard_pile.append(card)
            await self.on_card_discarded(player, card, "judge")
        return card

    async def duel(self, source, target, reason="决斗"):
        if self.target_error(source, target, "决斗"):
            return False
        current, other = target, source
        while source.alive and target.alive:
            required = 2 if self.has_skill(other, "无双") else 1
            responded = True
            for _ in range(required):
                direct = next((c for c in current.hand if c.name == "杀"), None)
                option = None if direct else next(iter(self.response_options(current, "杀")), None)
                response = direct or (option or {}).get("card")
                owner = (option or {}).get("owner") or current
                if not response or response not in owner.hand:
                    responded = False
                    break
                await self.discard_card(owner, response, f"响应{reason}")
                await self.on_card_responded(current, response, (option or {}).get("as_name", "杀"), {"source": other, "owner": owner})
            if not responded:
                await self.engine.card_system.damage(other, current, 1, card=None, context={"reason": reason})
                return True
            current, other = other, current
        return True

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
        return actions

    async def execute(self, player, action, targets):
        for handler in self.handlers:
            if await handler.execute(player, action, targets):
                return True
        return False

    async def on_turn_start(self, player):
        reset_turn_flags(player)
        for other in self.engine.game_state.players:
            used = getattr(other, "flags", {}).get("skill_used", {})
            used.pop("护驾摸牌", None)
            used.pop("激将摸牌", None)
        player.max_sha = 1
        for handler in self.handlers:
            await handler.on_turn_start(player)

    async def before_phase(self, player, phase):
        result = {"skip_default": False}
        for handler in self.handlers:
            value = await handler.before_phase(player, phase)
            if isinstance(value, dict):
                result.update(value)
        return result

    async def after_phase(self, player, phase):
        for handler in self.handlers:
            await handler.after_phase(player, phase)

    async def before_sha(self, source, target, card, event):
        for handler in self.handlers:
            await handler.before_sha(source, target, card, event)

    async def on_sha_dodged(self, source, target, card, event):
        for handler in self.handlers:
            await handler.on_sha_dodged(source, target, card, event)

    async def modify_damage(self, source, target, amount, card=None, context=None):
        for handler in self.handlers:
            amount = await handler.modify_damage(source, target, amount, card, context)
        return max(0, int(amount))

    async def after_damage(self, source, target, amount, card=None, context=None):
        for handler in self.handlers:
            await handler.after_damage(source, target, amount, card, context)

    async def after_card_used(self, player, card, targets, success):
        for handler in self.handlers:
            await handler.after_card_used(player, card, targets, success)

    async def on_card_responded(self, player, card, as_name, context=None):
        for handler in self.handlers:
            await handler.on_card_responded(player, card, as_name, context)

    def response_options(self, player, requested_name):
        options = []
        for handler in self.handlers:
            options.extend(handler.response_options(player, requested_name))
        return options

    def target_error(self, source, target, card_name):
        for handler in self.handlers:
            error = handler.can_target(source, target, card_name)
            if error:
                return error
        return None

    def modify_distance(self, source, target, distance):
        for handler in self.handlers:
            distance = handler.modify_distance(source, target, distance)
        return max(1, distance)

    def ignore_distance(self, source, card):
        return any(handler.ignore_distance(source, card) for handler in self.handlers)

    def hand_limit(self, player, current):
        for handler in self.handlers:
            current = handler.hand_limit(player, current)
        return max(0, current)

    def protect_card(self, owner, card, reason):
        return any(handler.protect_card(owner, card, reason) for handler in self.handlers)

    async def before_judge(self, player, card, context=None):
        for handler in self.handlers:
            card = await handler.before_judge(player, card, context)
        return card

    async def after_judge(self, player, card, context=None):
        claimed = False
        for handler in self.handlers:
            claimed = bool(await handler.after_judge(player, card, context)) or claimed
        return claimed

    async def on_card_gained(self, player, cards, reason="unknown"):
        if not cards:
            return
        for handler in self.handlers:
            await handler.on_card_gained(player, cards, reason)

    async def on_cards_lost(self, player, cards, reason="unknown"):
        if not cards:
            return
        for handler in self.handlers:
            await handler.on_cards_lost(player, cards, reason)

    async def on_card_discarded(self, player, card, reason="unknown"):
        current = self.engine.game_state.current_player if self.engine else None
        if current:
            ensure = getattr(current, "flags", {})
            ensure.setdefault("turn_discard_suits", set()).add(card.suit)
        for handler in self.handlers:
            await handler.on_card_discarded(player, card, reason)

    async def on_hp_lost(self, player, amount, reason="unknown", source=None):
        for handler in self.handlers:
            await handler.on_hp_lost(player, amount, reason, source)

    async def on_recover(self, player, amount, source=None, reason="unknown"):
        for handler in self.handlers:
            await handler.on_recover(player, amount, source, reason)

    async def before_card_target(self, source, target, card):
        for handler in self.handlers:
            updated = await handler.before_card_target(source, target, card)
            if updated is not None:
                target = updated
        return target

    async def before_multi_target_trick(self, source, card, targets):
        for handler in self.handlers:
            targets = await handler.before_multi_target_trick(source, card, targets)
        return targets


# 兼容旧MainEngine导入名。
TriggerManager = SkillManager

__all__ = ["SkillManager", "TriggerManager"]
