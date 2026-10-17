#!/usr/bin/env python3
"""界限突破群雄6将13技能运行实现。"""

from itertools import combinations

from .game_stats import record_stat
from .state_manager import Card, Phase
from .skill_runtime_core import (
    FactionSkillHandler, alive_others, card_color, ensure_flags, hero_faction,
    mark_once_per_turn, once_per_turn,
)

FEMALE_HEROES = {"zhenji", "huangyueying", "daqiao", "diaochan"}


def is_male(player):
    hero = player.hero or {}
    return hero.get("sex", "female" if hero.get("id") in FEMALE_HEROES else "male") == "male"


class QunSkillHandler(FactionSkillHandler):
    faction = "qun"

    def _finished(self):
        return bool(self.engine.game_aborted or self.state.game_over)

    async def _choose_region_card(self, chooser, owner, skill_name, prompt, *, predicate=lambda card: True):
        places = [(owner, "hand", card) for card in list(owner.hand) if predicate(card)]
        places.extend((owner, "equipment", card) for card in list(owner.equipment.values()) if predicate(card))
        if not places:
            return None
        result = await self.manager.ask_choose_cards_result(
            chooser, prompt, [card for _p, _z, card in places], min_n=1, max_n=1,
            zone="mixed", skill_name=skill_name,
            hidden_indices=[i for i, (_p, zone, _c) in enumerate(places)
                            if zone == "hand" and chooser is not owner],
            places=[(p, zone) for p, zone, _c in places],
        )
        if self._finished() or result.get("status") not in ("resolved", "timeout"):
            return None
        selected = next(iter(result.get("cards") or []), None)
        return next(((card, zone) for p, zone, card in places
                     if p is owner and card is selected), None)

    @staticmethod
    def _action(name, variant, indices=None, targets=None, text="", fixed_targets=None):
        targets = targets or []
        return {
            "type": "use_skill", "skill_name": name, "variant": variant,
            "card_indices": indices or [], "requires_target": bool(targets),
            "valid_targets": targets, "fixed_target_ids": fixed_targets or [],
            "description": text,
        }

    def get_actions(self, player):
        actions = []
        others = alive_others(self.state, player)

        if self.has(player, "青囊") and player.hand and not ensure_flags(player).get("qingnang_locked"):
            used = set(ensure_flags(player).get("qingnang_targets", []))
            valid = [p.id for p in self.state.players if p.alive and p.hp < p.max_hp and p.id not in used]
            for index in range(len(player.hand)):
                if valid:
                    actions.append(self._action("青囊", "heal", [index], valid, "弃一张手牌令目标回复1点体力"))

        if self.has(player, "离间") and player.hand and not once_per_turn(player, "离间"):
            males = [p for p in others if is_male(p)]
            for first, second in list(combinations(males, 2))[:12]:
                for index in range(min(len(player.hand), 3)):
                    actions.append(self._action("离间", "duel_pair", [index], text=f"令{first.name}对{second.name}决斗", fixed_targets=[first.id, second.id]))

        if self.has(player, "势斩") and ensure_flags(player).get("shizhan_count", 0) < 2:
            valid = [p.id for p in others]
            if valid:
                actions.append(self._action("势斩", "target_duel_self", [], valid, "令目标视为对你使用【决斗】"))

        if self.has(player, "乱击") and len(player.hand) >= 2:
            by_suit = {}
            for index, card in enumerate(player.hand):
                by_suit.setdefault(card.suit, []).append(index)
            for indices in by_suit.values():
                for pair in list(combinations(indices, 2))[:6]:
                    actions.append(self._action("乱击", "as_wanjian", list(pair), text="两张同花色牌当【万箭齐发】"))

        # 黄天由其他群势力角色主动交给拥有黄天的主公。
        lord = next((p for p in self.state.players if p.alive and p.identity == "lord" and self.has(p, "黄天")), None)
        if lord and lord is not player and hero_faction(player) == "qun" and not once_per_turn(player, "黄天进献"):
            for index, card in enumerate(player.hand):
                if card.name == "闪" or card.suit == "spade":
                    actions.append(self._action("黄天", "tribute", [index], text=f"交给主公{lord.name}一张【闪】或黑桃牌", fixed_targets=[lord.id]))
        return actions

    async def execute(self, player, action, targets):
        name, variant = action.get("skill_name"), action.get("variant")
        indices = action.get("card_indices") or []
        target = targets[0] if targets else None

        if name == "青囊" and target and indices:
            if not 0 <= indices[0] < len(player.hand) or target.hp >= target.max_hp:
                return False
            card = player.hand[indices[0]]
            await self.manager.discard_card(player, card, "青囊")
            ensure_flags(player).setdefault("qingnang_targets", []).append(target.id)
            await self.manager.recover(target, 1, player, "青囊")
            if card_color(card) == "black":
                ensure_flags(player)["qingnang_locked"] = True
            await self.manager.announce(player, "青囊", f"{player.name}发动【青囊】，令{target.name}回复1点体力")
            return True

        if name == "离间" and variant == "duel_pair" and indices:
            fixed = action.get("fixed_target_ids") or []
            if len(fixed) != 2 or not 0 <= indices[0] < len(player.hand):
                return False
            first = next((p for p in self.state.players if p.id == fixed[0] and p.alive), None)
            second = next((p for p in self.state.players if p.id == fixed[1] and p.alive), None)
            if not first or not second or not is_male(first) or not is_male(second):
                return False
            mark_once_per_turn(player, "离间")
            await self.manager.discard_card(player, player.hand[indices[0]], "离间")
            await self.manager.announce(player, "离间", f"{player.name}发动【离间】，令{first.name}对{second.name}使用【决斗】")
            return await self.manager.duel(first, second, "离间")

        if name == "势斩" and target:
            flags = ensure_flags(player)
            if flags.get("shizhan_count", 0) >= 2:
                return False
            flags["shizhan_count"] = flags.get("shizhan_count", 0) + 1
            await self.manager.announce(player, "势斩", f"{player.name}发动【势斩】，令{target.name}对其使用【决斗】")
            return await self.manager.duel(target, player, "势斩")

        if name == "乱击" and variant == "as_wanjian" and len(indices) == 2:
            if any(not 0 <= i < len(player.hand) for i in indices):
                return False
            cards = [player.hand[i] for i in indices]
            if cards[0].suit != cards[1].suit:
                return False
            await self.manager.announce(player, "乱击", f"{player.name}发动【乱击】，将两张{cards[0].suit}牌当【万箭齐发】")
            for card in sorted(cards, key=lambda c: player.hand.index(c), reverse=True):
                await self.manager.discard_card(player, card, "乱击")
            record_stat(self.engine, player, "cards_played", 2)
            virtual = Card(f"luanji:{cards[0].id}:{cards[1].id}", "万箭齐发",
                           cards[0].suit, cards[0].rank, "trick")
            context = self.engine._new_effect_context(
                player, virtual, skill_source="乱击",
                card_cost_ids=[card.id for card in cards],
            )
            return await self.engine.card_system.use_wanjian(
                player, virtual, effect_context=context,
            )

        if name == "黄天" and variant == "tribute" and indices:
            fixed = action.get("fixed_target_ids") or []
            lord = next((p for p in self.state.players if p.id in fixed and p.alive and self.has(p, "黄天")), None)
            if not lord or not 0 <= indices[0] < len(player.hand):
                return False
            card = player.hand[indices[0]]
            if card.name != "闪" and card.suit != "spade":
                return False
            mark_once_per_turn(player, "黄天进献")
            await self.manager.transfer_card(player, lord, card, "黄天")
            await self.manager.announce(lord, "黄天", f"{player.name}响应【黄天】，交给{lord.name}一张牌")
            return True
        return False

    async def on_turn_start(self, player):
        flags = ensure_flags(player)
        flags.pop("qingnang_targets", None)
        flags.pop("qingnang_locked", None)
        flags.pop("shizhan_count", None)

    async def after_phase(self, player, phase):
        if phase == Phase.END and self.has(player, "闭月"):
            count = 2 if not player.hand else 1
            use = await self.manager.ask_confirm(player, "是否发动【闭月】摸牌？", skill_name="闭月", default=False)
            if use and not self._finished():
                await self.manager.draw_cards(player, count, "闭月")
                await self.manager.announce(player, "闭月", f"{player.name}发动【闭月】摸{count}张牌")

    async def before_sha(self, source, target, card, event):
        if self.has(source, "无双"):
            event["shanRequired"] = max(2, event.get("shanRequired", 1))

    async def after_damage(self, source, target, amount, card=None, context=None):
        if amount <= 0 or self._finished():
            return
        if self.has(source, "利驭") and source is not target and card and card.name == "杀" and (target.hand or target.equipment):
            # 官方 FAQ：是否发动由受伤角色决定；吕布选择并获得其区域内的牌。
            use = await self.manager.ask_confirm(target, f"是否发动【利驭】令{source.name}获得你的一张牌？", skill_name="利驭", context={"source": source}, default=False)
            if self._finished():
                return
            if use:
                selected = await self._choose_region_card(source, target, "利驭", "选择获得的一张牌")
                if self._finished():
                    return
                if selected:
                    gained, zone = selected
                    is_equipment = zone == "equipment"
                    moved = await self.engine.move_card(
                        gained, zone, "hand", from_owner=target, to_owner=source,
                        reason="利驭", actor_id=source.id,
                    )
                    if moved and not self._finished():
                        await self.manager.on_cards_lost(target, [gained], "利驭")
                        await self.manager.on_card_gained(source, [gained], "利驭")
                        await self.manager.announce(source, "利驭", f"{source.name}发动【利驭】，获得{target.name}一张牌")
                        if is_equipment:
                            candidates = [p for p in self.state.players if p.alive and p not in (source, target)]
                            chosen = await self.manager.ask_choose_players(target, "【利驭】：选择吕布决斗的另一名角色", candidates, skill_name="利驭", context={"source": source}) if candidates else []
                            if self._finished():
                                return
                            if chosen:
                                await self.manager.duel(source, chosen[0], "利驭")
                        else:
                            await self.manager.draw_cards(target, 1, "利驭")

        if self.has(target, "耀武") and card:
            if card_color(card) == "red" and source and source.alive:
                await self.manager.draw_cards(source, 1, "耀武")
                await self.manager.announce(target, "耀武", f"{target.name}触发【耀武】，{source.name}摸一张牌")
            else:
                await self.manager.draw_cards(target, 1, "耀武")
                await self.manager.announce(target, "耀武", f"{target.name}触发【耀武】摸一张牌")

    async def before_judge(self, player, card, context=None):
        owner = next((p for p in self.state.players if p.alive and self.has(p, "鬼道") and
                      any(card_color(c) == "black" for c in list(p.hand) + list(p.equipment.values()))), None)
        if not owner:
            return card
        use = await self.manager.ask_confirm(owner, f"是否发动【鬼道】替换{player.name}的判定牌？", skill_name="鬼道", default=False)
        if self._finished() or not use:
            return card
        selected = await self._choose_region_card(owner, owner, "鬼道", "选择一张黑色手牌或装备牌替换判定牌", predicate=lambda c: card_color(c) == "black")
        if self._finished() or not selected:
            return card
        replacement, zone = selected
        if zone == "hand" and replacement in owner.hand:
            owner.hand.remove(replacement)
        elif zone == "equipment":
            slot = next((k for k, value in owner.equipment.items() if value is replacement), None)
            if slot is None:
                return card
            owner.equipment.pop(slot)
        else:
            return card
        self.state.discard_pile.append(card)
        await self.manager.on_cards_lost(owner, [replacement], "鬼道")
        await self.manager.on_card_discarded(player, card, "判定替换")
        owner.hand.append(card)
        await self.manager.on_card_gained(owner, [card], "鬼道")
        if replacement.suit == "spade" and 2 <= replacement.rank <= 9:
            await self.manager.draw_cards(owner, 1, "鬼道")
        await self.manager.announce(owner, "鬼道", f"{owner.name}发动【鬼道】替换判定牌并获得原判定牌")
        return replacement

    async def _resolve_leiji(self, player):
        if not self.has(player, "雷击"):
            return
        use = await self.manager.ask_confirm(player, "是否发动【雷击】进行判定？", skill_name="雷击", default=False)
        if self._finished() or not use:
            return
        result = await self.manager.judge(player, "雷击")
        if self._finished() or not result:
            return
        candidates = [p for p in self.state.players if p.alive and p is not player]
        if not candidates:
            return
        chosen = await self.manager.ask_choose_players(player, "选择【雷击】伤害目标", candidates, skill_name="雷击")
        if self._finished() or not chosen or not chosen[0].alive:
            return
        target = chosen[0]
        if result.suit == "spade":
            await self.manager.announce(player, "雷击", f"{player.name}发动【雷击】对{target.name}造成2点雷电伤害")
            await self.engine.card_system.damage(player, target, 2, context={"reason": "雷击"})
        elif result.suit == "club":
            await self.manager.recover(player, 1, player, "雷击")
            await self.manager.announce(player, "雷击", f"{player.name}发动【雷击】回复1点体力并对{target.name}造成1点伤害")
            await self.engine.card_system.damage(player, target, 1, context={"reason": "雷击"})

    async def after_card_used(self, player, card, targets, success):
        if success and card and card.name == "闪电":
            await self._resolve_leiji(player)

    async def on_card_responded(self, player, card, as_name, context=None):
        if as_name == "桃" and card.name != "桃" and self.has(player, "急救"):
            await self.manager.announce(player, "急救", f"{player.name}发动【急救】，将红色牌当【桃】")
        if as_name == "闪":
            await self._resolve_leiji(player)

    def response_options(self, player, requested_name):
        if requested_name == "桃" and self.has(player, "急救") and self.state.current_player is not player:
            for card, index, zone in self.response_card_entries(player):
                if card_color(card) == "red":
                    return [{"card": card, "card_index": index, "as_name": "桃", "skill_name": "急救", "owner": player, "source_zone": zone}]
        return []


    def hand_limit(self, player, current):
        if self.has(player, "血裔") and player.identity == "lord":
            current += 2 * sum(1 for p in self.state.players if p.alive and p is not player and hero_faction(p) == "qun")
        return current
