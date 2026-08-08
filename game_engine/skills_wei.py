#!/usr/bin/env python3
"""界限突破魏国7将11技能运行实现。"""

from state_manager import Phase
from skill_runtime_core import FactionSkillHandler, card_color, card_type_group, ensure_flags, hero_faction, mark_once_per_turn, once_per_turn


class WeiSkillHandler(FactionSkillHandler):
    faction = "wei"

    async def on_turn_start(self, player):
        ensure_flags(player).pop("luoyi_active", None)

    async def before_phase(self, player, phase):
        if phase == Phase.PREPARE and self.has(player, "洛神"):
            await self._luoshen(player)

        if phase == Phase.DRAW and self.has(player, "突袭"):
            victims = [p for p in self.state.players if p.alive and p is not player and p.hand][:2]
            if victims:
                gained = []
                for victim in victims:
                    card = victim.hand[0]
                    victim.hand.remove(card)
                    player.hand.append(card)
                    gained.append(card)
                    await self.manager.on_cards_lost(victim, [card], "突袭")
                await self.manager.on_card_gained(player, gained, "突袭")
                remaining = max(0, 2 - len(gained))
                if remaining:
                    await self.manager.draw_cards(player, remaining, "突袭补摸")
                await self.manager.announce(player, "突袭", f"{player.name}发动【突袭】，获得{len(gained)}名角色各一张手牌并补摸{remaining}张")
                return {"skip_default": True}

        if phase == Phase.DRAW and self.has(player, "裸衣") and len(self.state.deck) >= 3:
            shown = [self.state.deck.pop(0) for _ in range(3)]
            weapons = {"诸葛连弩", "青釭剑", "青龙偃月刀", "丈八蛇矛", "贯石斧", "方天画戟", "麒麟弓", "寒冰剑", "古锭刀"}
            gained = [c for c in shown if card_type_group(c) == "basic" or c.name in weapons or c.name == "决斗"]
            rejected = [c for c in shown if c not in gained]
            player.hand.extend(gained)
            self.state.discard_pile.extend(rejected)
            ensure_flags(player)["luoyi_active"] = True
            await self.manager.on_card_gained(player, gained, "裸衣")
            for card in rejected:
                await self.manager.on_card_discarded(player, card, "裸衣")
            await self.manager.announce(player, "裸衣", f"{player.name}发动【裸衣】，获得{len(gained)}张牌，本回合杀伤害+1")
            return {"skip_default": True}
        return None

    async def _luoshen(self, player):
        obtained = []
        for _ in range(12):
            if not self.state.deck:
                break
            card = self.state.deck.pop(0)
            card = await self.manager.before_judge(player, card, {"reason": "洛神"})
            if card_color(card) == "black":
                player.hand.append(card)
                obtained.append(card)
                await self.manager.on_card_gained(player, [card], "洛神")
            else:
                claimed = await self.manager.after_judge(player, card, {"reason": "洛神"})
                if not claimed:
                    self.state.discard_pile.append(card)
                    await self.manager.on_card_discarded(player, card, "洛神")
                break
        if obtained:
            ensure_flags(player)["luoshen_exempt"] = len(obtained)
            await self.manager.announce(player, "洛神", f"{player.name}发动【洛神】，获得{len(obtained)}张黑色判定牌")

    async def before_judge(self, player, card, context=None):
        # 场上任一拥有鬼才的角色可打出一张牌替换判定；确定性策略优先用低价值牌。
        owner = next((p for p in self.state.players if p.alive and self.has(p, "鬼才") and p.hand), None)
        if not owner:
            return card
        replacement = sorted(owner.hand, key=lambda c: (c.name == "桃", c.name == "闪", c.rank))[0]
        owner.hand.remove(replacement)
        self.state.discard_pile.append(card)
        await self.manager.on_cards_lost(owner, [replacement], "鬼才")
        await self.manager.on_card_discarded(player, card, "判定替换")
        await self.manager.announce(owner, "鬼才", f"{owner.name}发动【鬼才】替换{player.name}的判定牌")
        return replacement

    async def after_judge(self, player, card, context=None):
        if self.has(player, "天妒"):
            player.hand.append(card)
            await self.manager.on_card_gained(player, [card], "天妒")
            await self.manager.announce(player, "天妒", f"{player.name}发动【天妒】获得判定牌【{card.name}】")
            return True
        return False

    async def modify_damage(self, source, target, amount, card=None, context=None):
        if source and self.has(source, "裸衣") and ensure_flags(source).get("luoyi_active") and card and card.name in ("杀", "决斗"):
            amount += 1
        return amount

    async def after_damage(self, source, target, amount, card=None, context=None):
        if amount <= 0:
            return

        if self.has(target, "奸雄"):
            gained = []
            if card and card in self.state.discard_pile:
                self.state.discard_pile.remove(card)
                target.hand.append(card)
                gained.append(card)
            gained.extend(await self.manager.draw_cards(target, 1, "奸雄"))
            await self.manager.announce(target, "奸雄", f"{target.name}发动【奸雄】获得伤害牌并摸一张牌")

        for _ in range(amount):
            if self.has(target, "反馈") and source and source.alive:
                stolen = source.hand[0] if source.hand else next(iter(source.equipment.values()), None)
                if stolen:
                    if stolen in source.hand:
                        source.hand.remove(stolen)
                    else:
                        slot = next(k for k, v in source.equipment.items() if v is stolen)
                        source.equipment.pop(slot)
                    target.hand.append(stolen)
                    await self.manager.on_cards_lost(source, [stolen], "反馈")
                    await self.manager.on_card_gained(target, [stolen], "反馈")
                    await self.manager.announce(target, "反馈", f"{target.name}发动【反馈】获得{source.name}一张牌")

            if self.has(target, "刚烈") and source and source.alive:
                result = await self.manager.judge(target, "刚烈")
                if result and card_color(result) == "red":
                    await self.manager.announce(target, "刚烈", f"{target.name}发动【刚烈】对{source.name}造成1点伤害")
                    await self.engine.card_system.damage(target, source, 1, context={"reason": "刚烈"})
                elif result and (source.hand or source.equipment):
                    await self.manager.announce(target, "刚烈", f"{target.name}发动【刚烈】弃置{source.name}一张牌")
                    if source.hand:
                        await self.manager.discard_card(source, source.hand[0], "刚烈")

            if self.has(target, "遗计"):
                drawn = await self.manager.draw_cards(target, 2, "遗计")
                receiver = next((p for p in self.state.players if p.alive and p is not target), None)
                moved = 0
                if receiver:
                    for give in list(drawn[:2]):
                        if give in target.hand:
                            await self.manager.transfer_card(target, receiver, give, "遗计")
                            moved += 1
                await self.manager.announce(target, "遗计", f"{target.name}发动【遗计】摸两张并分配{moved}张牌")

    async def on_card_gained(self, player, cards, reason="unknown"):
        if not self.has(player, "清俭") or once_per_turn(player, "清俭") or reason in ("draw", "清俭"):
            return
        # 摸牌阶段外获得牌后，交出一张，并提升当前回合角色手牌上限。
        if player is self.state.current_player and self.state.current_phase == Phase.DRAW:
            return
        give = next((c for c in cards if c in player.hand), None)
        receiver = next((p for p in self.state.players if p.alive and p is not player), None)
        if not give or not receiver:
            return
        mark_once_per_turn(player, "清俭")
        await self.manager.transfer_card(player, receiver, give, "清俭")
        current = self.state.current_player
        if current:
            ensure_flags(current)["hand_limit_bonus"] = ensure_flags(current).get("hand_limit_bonus", 0) + 1
        await self.manager.announce(player, "清俭", f"{player.name}发动【清俭】交给{receiver.name}一张牌")

    def response_options(self, player, requested_name):
        options = []
        if requested_name == "闪" and self.has(player, "倾国"):
            for index, card in enumerate(player.hand):
                if card_color(card) == "black":
                    options.append({"card": card, "card_index": index, "as_name": "闪", "skill_name": "倾国", "owner": player})
        if requested_name == "闪" and self.has(player, "护驾") and player.identity == "lord" :
            donor = next((p for p in self.state.players if p.alive and p is not player and hero_faction(p) == "wei" and any(c.name == "闪" for c in p.hand)), None)
            if donor:
                card = next(c for c in donor.hand if c.name == "闪")
                options.append({"card": card, "card_index": donor.hand.index(card), "as_name": "闪", "skill_name": "护驾", "owner": donor})
        return options

    async def on_card_responded(self, player, card, as_name, context=None):
        if self.has(player, "倾国") and card.name != as_name:
            await self.manager.announce(player, "倾国", f"{player.name}发动【倾国】，将黑色牌当【闪】")
        owner = (context or {}).get("owner")
        if owner and owner is not player and self.has(player, "护驾"):
            await self.manager.announce(player, "护驾", f"{player.name}发动【护驾】，由{owner.name}打出【闪】")
        responder = owner or player
        if hero_faction(responder) == "wei" and responder is not self.state.current_player and as_name == "闪":
            lord = next((p for p in self.state.players if p.alive and p.identity == "lord" and self.has(p, "护驾") and not once_per_turn(p, "护驾摸牌")), None)
            if lord:
                mark_once_per_turn(lord, "护驾摸牌")
                await self.manager.draw_cards(lord, 1, "护驾")
                await self.manager.announce(lord, "护驾", f"{responder.name}于回合外打出【闪】，{lord.name}因【护驾】摸一张牌")

    def hand_limit(self, player, current):
        return current + int(ensure_flags(player).get("hand_limit_bonus", 0)) + int(ensure_flags(player).get("luoshen_exempt", 0))
