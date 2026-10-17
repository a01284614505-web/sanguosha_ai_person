#!/usr/bin/env python3
"""界限突破魏国7将11技能运行实现。"""

import inspect

from . import card_flow
from .state_manager import Phase
from .skill_runtime_core import FactionSkillHandler, card_color, card_type_group, ensure_flags, hero_faction, mark_once_per_turn, once_per_turn


class WeiSkillHandler(FactionSkillHandler):
    faction = "wei"

    def _finished(self):
        return bool(self.engine.game_aborted or self.state.game_over)

    async def _choose_owned_card(self, chooser, owner, skill_name, prompt, *, cancelable=True):
        """Ask against a frozen hand/equipment snapshot and return its real zone."""
        places = [(owner, "hand", card) for card in list(owner.hand)]
        places.extend((owner, "equipment", card) for card in list(owner.equipment.values()))
        if not places:
            return None
        result = await self.manager.ask_choose_cards_result(
            chooser, prompt, [card for _player, _zone, card in places],
            min_n=1, max_n=1, zone="mixed", skill_name=skill_name,
            cancelable=cancelable,
            hidden_indices=[i for i, (_player, zone, _card) in enumerate(places)
                            if zone == "hand" and chooser is not owner],
            places=[(player, zone) for player, zone, _card in places],
        )
        if self._finished() or result.get("status") not in ("resolved", "timeout"):
            return None
        # Use object identity: card names and ids are not selection authority.
        card = next(iter(result.get("cards") or []), None)
        if card is None:
            return None
        return next(((card, zone) for player, zone, candidate in places
                     if player is owner and candidate is card), None)

    async def _discard_region_card(self, owner, card, zone, reason):
        if self._finished():
            return False
        index = owner.hand.index(card) if zone == "hand" and card in owner.hand else None
        move = await self.engine.move_card(
            card, zone, "discard", from_owner=owner,
            reason=reason, actor_id=owner.id,
        )
        if move is None or self._finished():
            return False
        await self.engine.card_system.notify_card_to_discard(
            owner, card, "discard", index,
            f"{owner.name}因【{reason}】弃置【{card.name}】",
        )
        await self.manager.on_card_discarded(owner, card, reason)
        return not self._finished()

    async def on_turn_start(self, player):
        ensure_flags(player).pop("luoyi_active", None)

    async def before_phase(self, player, phase):
        if phase == Phase.PREPARE and self.has(player, "洛神"):
            await self._luoshen(player)

        if phase == Phase.DRAW and self.has(player, "突袭"):
            victims = [p for p in self.state.players if p.alive and p is not player and p.hand]
            if victims:
                use = await self.manager.ask_confirm(player, "是否发动【突袭】少摸牌并获得其他角色的手牌？", skill_name="突袭", default=False)
                if self._finished():
                    return {"skip_default": True}
                if use:
                    chosen = await self.manager.ask_choose_players(
                        player, "【突袭】：选择1至2名有手牌的角色", victims,
                        min_n=1, max_n=2, skill_name="突袭", cancelable=True,
                    )
                    if self._finished():
                        return {"skip_default": True}
                    if not chosen:
                        return None
                    steals = []
                    for victim in chosen[:2]:
                        if victim not in victims or not victim.alive or not victim.hand:
                            continue
                        selected = await self._choose_owned_card(
                            player, victim, "突袭", f"【突袭】：选择{victim.name}的一张手牌",
                            cancelable=False,
                        )
                        if self._finished():
                            return {"skip_default": True}
                        if selected:
                            steals.append((victim, *selected))
                    gained = []
                    for victim, stolen, zone in steals:
                        if stolen not in victim.hand or not victim.alive:
                            continue
                        moved = await self.engine.move_card(
                            stolen, zone, "hand", from_owner=victim, to_owner=player,
                            reason="突袭", actor_id=player.id, visibility="owner",
                        )
                        if moved is None or self._finished():
                            return {"skip_default": True}
                        await self.manager.on_cards_lost(victim, [stolen], "突袭")
                        gained.append(stolen)
                    if gained:
                        await self.manager.on_card_gained(player, gained, "突袭")
                    remaining = max(0, 2 - len(gained))
                    if remaining:
                        await self.manager.draw_cards(player, remaining, "突袭补摸")
                    await self.manager.announce(player, "突袭", f"{player.name}发动【突袭】，获得{len(gained)}张手牌并补摸{remaining}张")
                    return {"skip_default": True}

        if phase == Phase.DRAW and self.has(player, "裸衣") and len(self.state.deck) >= 3:
            shown = await card_flow.reveal_top(
                self.engine, self.state, player, 3, reason="裸衣亮牌", refill=False)
            weapons = {"诸葛连弩", "青釭剑", "青龙偃月刀", "丈八蛇矛", "贯石斧", "方天画戟", "麒麟弓", "寒冰剑", "古锭刀"}
            gained = [c for c in shown if card_type_group(c) == "basic" or c.name in weapons or c.name == "决斗"]
            rejected = [c for c in shown if c not in gained]
            for gained_card in gained:
                await card_flow.release_shown(self.engine, self.state, gained_card, "hand",
                                              to_owner=player, reason="裸衣", actor_id=player.id)
            for rejected_card in rejected:
                await card_flow.release_shown(self.engine, self.state, rejected_card, "discard",
                                              reason="裸衣", actor_id=player.id)
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
            revealed = await card_flow.reveal_top(
                self.engine, self.state, player, 1, reason="判定【洛神】")
            if not revealed:
                break
            card = revealed[0]
            card = await self.manager.before_judge(player, card, {"reason": "洛神"})
            # 每一次判定都在牌桌中央亮出（与官方一致）：黑色“获得”，红色“结束”。
            announce = getattr(self.engine, "announce_judge", None)
            if announce is not None:
                black = card_color(card) == "black"
                pending = announce(player, card, "洛神", effective=black,
                                   result_text="获得此牌" if black else "洛神结束")
                if inspect.isawaitable(pending):
                    await pending
                if self._finished():
                    return
            if card_color(card) == "black":
                await card_flow.release_shown(self.engine, self.state, card, "hand",
                                              to_owner=player, reason="洛神", actor_id=player.id)
                obtained.append(card)
                await self.manager.on_card_gained(player, [card], "洛神")
            else:
                claimed = await self.manager.after_judge(player, card, {"reason": "洛神"})
                if not claimed:
                    await card_flow.release_shown(self.engine, self.state, card, "discard",
                                                  reason="判定【洛神】结算", actor_id=player.id)
                    await self.manager.on_card_discarded(player, card, "洛神")
                break
        if obtained:
            ensure_flags(player)["luoshen_exempt"] = len(obtained)
            await self.manager.announce(player, "洛神", f"{player.name}发动【洛神】，获得{len(obtained)}张黑色判定牌")

    async def before_judge(self, player, card, context=None):
        # 场上任一拥有鬼才的角色可打出一张牌替换判定；确定性策略优先用低价值牌。
        owner = next((p for p in self.state.players if p.alive and self.has(p, "鬼才") and p.hand), None)
        if owner is None:
            owner = next((p for p in self.state.players if p.alive and self.has(p, "鬼才") and p.equipment), None)
        if not owner:
            return card
        use = await self.manager.ask_confirm(owner, f"是否发动【鬼才】替换{player.name}的判定牌？", skill_name="鬼才", default=False)
        if self._finished() or not use:
            return card
        selected = await self._choose_owned_card(owner, owner, "鬼才", "【鬼才】：选择一张牌替换判定牌")
        if self._finished() or not selected:
            return card
        replacement, zone = selected
        taken = await card_flow.take_judge_replacement(
            self.engine, self.state, owner, player, replacement, zone, reason="鬼才")
        if taken is None:
            return card
        await card_flow.release_shown(self.engine, self.state, card, "discard",
                                      reason="判定替换", actor_id=owner.id)
        if taken == "legacy":
            # 直接改牌区时没有牌移动事件，失去牌的技能钩子要自己触发。
            await self.manager.on_cards_lost(owner, [replacement], "鬼才")
        await self.manager.on_card_discarded(player, card, "判定替换")
        await self.manager.announce(owner, "鬼才", f"{owner.name}发动【鬼才】替换{player.name}的判定牌")
        return replacement

    async def after_judge(self, player, card, context=None):
        if self.has(player, "天妒"):
            use = await self.manager.ask_confirm(player, "是否发动【天妒】获得判定牌？", skill_name="天妒", default=False)
            if self._finished() or not use:
                return False
            await card_flow.release_shown(self.engine, self.state, card, "hand",
                                          to_owner=player, reason="天妒", actor_id=player.id)
            await self.manager.on_card_gained(player, [card], "天妒")
            await self.manager.announce(player, "天妒", f"{player.name}发动【天妒】获得判定牌【{card.name}】")
            return True
        return False

    async def modify_damage(self, source, target, amount, card=None, context=None):
        if source and self.has(source, "裸衣") and ensure_flags(source).get("luoyi_active") and card and card.name in ("杀", "决斗"):
            amount += 1
        return amount

    async def after_damage(self, source, target, amount, card=None, context=None):
        if amount <= 0 or self._finished():
            return

        # These are optional triggers: each asks its owner first, then commits effects.
        if self.has(target, "奸雄") and card and card in self.state.discard_pile:
            use = await self.manager.ask_confirm(
                target, "是否发动【奸雄】获得造成伤害的牌并摸一张牌？",
                skill_name="奸雄", context={"source": source, "card_name": card.name},
                default=False,
            )
            if self._finished():
                return
            if use and card in self.state.discard_pile:
                move = await self.engine.move_card(
                    card, "discard", "hand", to_owner=target,
                    reason="奸雄", actor_id=target.id, visibility="owner",
                )
                if move is not None:
                    await self.manager.on_card_gained(target, [card], "奸雄")
                    if self._finished():
                        return
                    await self.manager.draw_cards(target, 1, "奸雄")
                    await self.manager.announce(target, "奸雄", f"{target.name}发动【奸雄】获得伤害牌并摸一张牌")

        for _ in range(amount):
            if self._finished():
                return

            if self.has(target, "反馈") and source and source.alive and (source.hand or source.equipment):
                use = await self.manager.ask_confirm(
                    target, f"是否发动【反馈】获得{source.name}的一张牌？",
                    skill_name="反馈", context={"source": source}, default=False,
                )
                if self._finished():
                    return
                if use:
                    chosen = await self._choose_owned_card(
                        target, source, "反馈", f"【反馈】：选择{source.name}的一张牌获得",
                    )
                    if self._finished():
                        return
                    if chosen:
                        stolen, zone = chosen
                        move = await self.engine.move_card(
                            stolen, zone, "hand", from_owner=source, to_owner=target,
                            reason="反馈", actor_id=target.id, visibility="owner",
                        )
                        if move is not None:
                            await self.manager.on_card_gained(target, [stolen], "反馈")
                            await self.manager.announce(target, "反馈", f"{target.name}发动【反馈】获得{source.name}一张牌")

            if self._finished():
                return
            if self.has(target, "刚烈") and source and source.alive:
                use = await self.manager.ask_confirm(
                    target, "是否发动【刚烈】进行判定？",
                    skill_name="刚烈", context={"source": source}, default=False,
                )
                if self._finished():
                    return
                if use:
                    result = await self.manager.judge(target, "刚烈")
                    if self._finished():
                        return
                    if result and card_color(result) == "red":
                        await self.manager.announce(target, "刚烈", f"{target.name}发动【刚烈】对{source.name}造成1点伤害")
                        await self.engine.card_system.damage(target, source, 1, context={"reason": "刚烈"})
                    elif result and (source.hand or source.equipment):
                        chosen = await self._choose_owned_card(
                            source, source, "刚烈", f"【刚烈】：选择一张牌弃置",
                            cancelable=False,
                        )
                        if self._finished():
                            return
                        if chosen:
                            discarded, zone = chosen
                            if await self._discard_region_card(source, discarded, zone, "刚烈"):
                                await self.manager.announce(target, "刚烈", f"{target.name}发动【刚烈】，{source.name}弃置一张牌")

            if self.has(target, "遗计"):
                use = await self.manager.ask_confirm(target, "是否发动【遗计】摸两张并分配手牌？", skill_name="遗计", default=False)
                if self._finished():
                    return
                if not use:
                    continue
                drawn = await self.manager.draw_cards(target, 2, "遗计")
                candidates = [p for p in self.state.players if p.alive]
                assignments = []
                for give in list(drawn[:2]):
                    if self._finished():
                        return
                    if give not in target.hand or not candidates:
                        continue
                    chosen = await self.manager.ask_choose_players(
                        target, "【遗计】：选择这张牌的分配对象", candidates,
                        min_n=1, max_n=1, skill_name="遗计", cancelable=False,
                    )
                    if self._finished():
                        return
                    receiver = next((p for p in chosen if p in self.state.players and p.alive), None)
                    if receiver:
                        assignments.append((give, receiver))
                moved = 0
                for give, receiver in assignments:
                    if self._finished() or give not in target.hand or not receiver.alive:
                        return
                    if receiver is target:
                        continue
                    event = await self.engine.move_card(
                        give, "hand", "hand", from_owner=target, to_owner=receiver,
                        reason="遗计", actor_id=target.id, visibility="owner",
                    )
                    if event is None:
                        continue
                    await self.manager.on_cards_lost(target, [give], "遗计")
                    await self.manager.on_card_gained(receiver, [give], "遗计")
                    moved += 1
                await self.manager.announce(target, "遗计", f"{target.name}发动【遗计】摸两张并分配{moved}张牌")

    async def on_card_gained(self, player, cards, reason="unknown"):
        if not self.has(player, "清俭") or once_per_turn(player, "清俭") or reason in ("draw", "清俭"):
            return
        # 摸牌阶段外获得牌后，可展示并交出任意张手牌；手牌上限按不同类别增加。
        if player is self.state.current_player and self.state.current_phase == Phase.DRAW:
            return
        available = list(player.hand)
        receivers = [p for p in self.state.players if p.alive and p is not player]
        if not available or not receivers:
            return
        use = await self.manager.ask_confirm(player, "是否发动【清俭】交出一张刚获得的牌？", skill_name="清俭", default=False)
        if self._finished() or not use:
            return
        result = await self.manager.ask_choose_cards_result(
            player, "【清俭】：选择任意张手牌交给他人", available,
            min_n=1, max_n=len(available), zone="hand", skill_name="清俭",
        )
        if self._finished() or result.get("status") not in ("resolved", "timeout"):
            return
        selected = list(result.get("cards") or [])
        if not selected or any(give not in available or give not in player.hand for give in selected):
            return
        chosen = await self.manager.ask_choose_players(player, "【清俭】：选择收牌角色", receivers, skill_name="清俭")
        if self._finished() or not chosen or chosen[0] not in receivers:
            return
        receiver = chosen[0]
        mark_once_per_turn(player, "清俭")
        committed = []
        for give in selected:
            moved = await self.engine.move_card(
                give, "hand", "hand", from_owner=player, to_owner=receiver,
                reason="清俭", actor_id=player.id, visibility="owner",
            )
            if moved is None or self._finished():
                return
            committed.append(give)
        await self.manager.on_cards_lost(player, committed, "清俭")
        await self.manager.on_card_gained(receiver, committed, "清俭")
        current = self.state.current_player
        if current:
            categories = {card_type_group(card) for card in committed}
            ensure_flags(current)["hand_limit_bonus"] = ensure_flags(current).get("hand_limit_bonus", 0) + len(categories)
        await self.manager.announce(player, "清俭", f"{player.name}发动【清俭】交给{receiver.name}{len(committed)}张牌")

    def response_options(self, player, requested_name):
        options = []
        if requested_name == "闪" and self.has(player, "倾国"):
            for card, index, zone in self.response_card_entries(player):
                if card_color(card) == "black":
                    options.append({"card": card, "card_index": index, "as_name": "闪", "skill_name": "倾国", "owner": player, "source_zone": zone})
        if requested_name == "闪" and self.has(player, "护驾") and player.identity == "lord" :
            for donor in self.state.players:
                if not donor.alive or donor is player or hero_faction(donor) != "wei":
                    continue
                candidate = next(((card, index, zone) for card, index, zone in self.response_card_entries(donor)
                                  if card.name == "闪"), None)
                if candidate:
                    card, index, zone = candidate
                    options.append({"card": card, "card_index": index, "as_name": "闪", "skill_name": "护驾", "owner": donor, "source_zone": zone})
                    break
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
