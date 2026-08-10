#!/usr/bin/env python3
"""界限突破群雄6将13技能运行实现。"""

from itertools import combinations

from state_manager import Card, Phase
from skill_runtime_core import (
    FactionSkillHandler, alive_others, card_color, ensure_flags, hero_faction,
    mark_once_per_turn, once_per_turn,
)

FEMALE_HEROES = {"zhenji", "huangyueying", "daqiao", "diaochan"}


def is_male(player):
    hero = player.hero or {}
    return hero.get("sex", "female" if hero.get("id") in FEMALE_HEROES else "male") == "male"


class QunSkillHandler(FactionSkillHandler):
    faction = "qun"

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
            targets_all = await self.manager.before_multi_target_trick(player, Card("luanji", "万箭齐发", cards[0].suit, cards[0].rank, "trick"), alive_others(self.state, player))
            for victim in list(targets_all):
                result = await self.engine.card_system.choose_to_respond(
                    victim, "请使用【闪】响应万箭齐发", lambda c: c.name == "闪",
                    requested_name="闪", context={"source": player, "target": victim}
                )
                if result.get("bool"):
                    owner = result.get("owner") or victim
                    response = result["card"]
                    if response in owner.hand:
                        index = owner.hand.index(response)
                        owner.hand.remove(response)
                        self.state.discard_pile.append(response)
                        await self.engine.card_system.notify_card_to_discard(owner, response, "respond", index, f"{owner.name}打出【闪】响应【万箭齐发】")
                        await self.manager.on_cards_lost(owner, [response], "万箭齐发")
                        await self.manager.on_card_discarded(owner, response, "万箭齐发")
                        await self.manager.on_card_responded(victim, response, result.get("as_name", response.name), {"source": player, "owner": owner})
                else:
                    await self.engine.card_system.damage(player, victim, 1, card=Card("luanji", "万箭齐发", cards[0].suit, cards[0].rank, "trick"), context={"reason": "乱击"})
            return True

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
            await self.manager.draw_cards(player, count, "闭月")
            await self.manager.announce(player, "闭月", f"{player.name}发动【闭月】摸{count}张牌")

    async def before_sha(self, source, target, card, event):
        if self.has(source, "无双"):
            event["shanRequired"] = max(2, event.get("shanRequired", 1))

    async def after_damage(self, source, target, amount, card=None, context=None):
        if amount <= 0:
            return
        if self.has(source, "利驭") and source is not target and card and card.name == "杀":
            gained = target.hand[0] if target.hand else next(iter(target.equipment.values()), None)
            if gained:
                is_equipment = gained in target.equipment.values()
                if gained in target.hand:
                    target.hand.remove(gained)
                else:
                    slot = next(k for k, v in target.equipment.items() if v is gained)
                    target.equipment.pop(slot)
                source.hand.append(gained)
                await self.manager.on_cards_lost(target, [gained], "利驭")
                await self.manager.on_card_gained(source, [gained], "利驭")
                await self.manager.announce(source, "利驭", f"{source.name}发动【利驭】获得{target.name}一张牌")
                if is_equipment:
                    other = next((p for p in self.state.players if p.alive and p not in (source, target)), None)
                    if other:
                        await self.manager.duel(source, other, "利驭")
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
        owner = next((p for p in self.state.players if p.alive and self.has(p, "鬼道") and any(card_color(c) == "black" for c in p.hand)), None)
        if not owner:
            return card
        replacement = next(c for c in owner.hand if card_color(c) == "black")
        owner.hand.remove(replacement)
        owner.hand.append(card)
        await self.manager.on_cards_lost(owner, [replacement], "鬼道")
        await self.manager.on_card_gained(owner, [card], "鬼道")
        if replacement.suit == "spade" and 2 <= replacement.rank <= 9:
            await self.manager.draw_cards(owner, 1, "鬼道")
        await self.manager.announce(owner, "鬼道", f"{owner.name}发动【鬼道】替换判定牌并获得原判定牌")
        return replacement

    async def on_card_responded(self, player, card, as_name, context=None):
        if as_name == "桃" and card.name != "桃" and self.has(player, "急救"):
            await self.manager.announce(player, "急救", f"{player.name}发动【急救】，将红色牌当【桃】")
        if as_name != "闪" or not self.has(player, "雷击"):
            return
        result = await self.manager.judge(player, "雷击")
        if not result:
            return
        candidates = [p for p in self.state.players if p.alive and p is not player]
        if not candidates:
            return
        target = sorted(candidates, key=lambda p: (p.hp, p.id))[0]
        if result.suit == "spade":
            await self.manager.announce(player, "雷击", f"{player.name}发动【雷击】对{target.name}造成2点雷电伤害")
            await self.engine.card_system.damage(player, target, 2, context={"reason": "雷击"})
        elif result.suit == "club":
            await self.manager.recover(player, 1, player, "雷击")
            await self.manager.announce(player, "雷击", f"{player.name}发动【雷击】回复1点体力并对{target.name}造成1点伤害")
            await self.engine.card_system.damage(player, target, 1, context={"reason": "雷击"})

    def response_options(self, player, requested_name):
        if requested_name == "桃" and self.has(player, "急救") and self.state.current_player is not player:
            for index, card in enumerate(player.hand):
                if card_color(card) == "red":
                    return [{"card": card, "card_index": index, "as_name": "桃", "skill_name": "急救", "owner": player}]
        return []


    def hand_limit(self, player, current):
        if self.has(player, "血裔") and player.identity == "lord":
            current += 2 * sum(1 for p in self.state.players if p.alive and p is not player and hero_faction(p) == "qun")
        return current
