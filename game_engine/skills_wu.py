#!/usr/bin/env python3
"""界限突破吴国7将12技能运行实现。"""

from .game_stats import record_stat
from .state_manager import Card, Phase
from .skill_runtime_core import (
    FactionSkillHandler, alive_others, card_color, ensure_flags, hero_faction,
    mark_once_per_turn, once_per_turn,
)


class WuSkillHandler(FactionSkillHandler):
    faction = "wu"

    def _finished(self):
        return bool(self.engine.game_aborted or self.state.game_over)

    async def _choose_region_card(self, chooser, owner, skill_name, prompt, *, cancelable=True):
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
        card = next(iter(result.get("cards") or []), None)
        return next(((card, zone) for player, zone, candidate in places
                     if player is owner and candidate is card), None)

    async def _discard_region_card(self, owner, card, zone, reason, actor):
        if self._finished():
            return False
        index = owner.hand.index(card) if zone == "hand" and card in owner.hand else None
        move = await self.engine.move_card(
            card, zone, "discard", from_owner=owner,
            reason=reason, actor_id=actor.id,
        )
        if move is None:
            return False
        await self.engine.card_system.notify_card_to_discard(
            owner, card, "discard", index,
            f"{owner.name}因【{reason}】弃置【{card.name}】",
        )
        await self.manager.on_card_discarded(owner, card, reason)
        return True

    @staticmethod
    def _action(name, variant, indices=None, targets=None, text=""):
        targets = targets or []
        return {
            "type": "use_skill", "skill_name": name, "variant": variant,
            "card_indices": indices or [], "requires_target": bool(targets),
            "valid_targets": targets, "description": text,
        }

    def get_actions(self, player):
        actions = []
        others = alive_others(self.state, player)

        if self.has(player, "制衡") and player.hand and self.manager.skill_available(player, "制衡"):
            actions.append(self._action("制衡", "choose_discard", text="弃置任意张手牌并摸等量牌；全弃多摸一张"))

        if self.has(player, "奇袭"):
            valid = [p.id for p in others if p.hand or p.equipment]
            for index, card in enumerate(player.hand):
                if card_color(card) == "black" and valid:
                    actions.append(self._action("奇袭", "as_guohe", [index], valid, "将黑色牌当【过河拆桥】"))

        if self.has(player, "苦肉") and player.hand and not once_per_turn(player, "苦肉"):
            for index in range(len(player.hand)):
                actions.append(self._action("苦肉", "lose_hp", [index], text="弃一张牌并失去1点体力"))

        if self.has(player, "反间") and player.hand and not once_per_turn(player, "反间"):
            valid = [p.id for p in others]
            for index in range(len(player.hand)):
                actions.append(self._action("反间", "give_reveal", [index], valid, "展示并交给目标一张牌"))

        if self.has(player, "国色") and not once_per_turn(player, "国色"):
            for index, card in enumerate(player.hand):
                if card.suit != "diamond":
                    continue
                valid = [p.id for p in others if not any(c.name == "乐不思蜀" for c in p.judge_area)]
                if valid:
                    actions.append(self._action("国色", "as_lebu", [index], valid, "将方片牌当【乐不思蜀】"))
                delayed_targets = [p.id for p in self.state.players if p.alive and any(c.name == "乐不思蜀" for c in p.judge_area)]
                if delayed_targets:
                    actions.append(self._action("国色", "remove_lebu", [index], delayed_targets, "弃方片牌并移除一张【乐不思蜀】"))

        if ensure_flags(player).get("gongxin") and not once_per_turn(player, "攻心"):
            valid = [p.id for p in others if any(c.suit == "heart" for c in p.hand)]
            if valid:
                actions.append(self._action("攻心", "take_heart", [], valid, "观看目标手牌并获得一张红桃牌"))
        return actions

    async def execute(self, player, action, targets):
        name, variant = action.get("skill_name"), action.get("variant")
        indices = action.get("card_indices") or []
        target = targets[0] if targets else None

        if name == "制衡" and variant == "choose_discard":
            hand_snapshot = list(player.hand)
            choice = await self.manager.ask_choose_cards_result(
                player, "制衡：请选择要弃置的手牌", hand_snapshot,
                min_n=1, max_n=len(hand_snapshot), zone="hand",
                skill_name="制衡", cancelable=True,
            )
            cards = choice.get("cards", [])
            if choice.get("status") not in ("resolved", "timeout") or not cards:
                return False
            if any(card not in player.hand for card in cards):
                return False
            all_hand = len(cards) == len(hand_snapshot)
            if not self.manager.consume_skill_use(player, "制衡", phase=Phase.PLAY, charges=0):
                return False
            await self.manager.announce(player, "制衡", f"{player.name}发动【制衡】弃置{len(cards)}张牌")
            self.manager.begin_loss_batch(player, "制衡")
            try:
                for card in list(cards):
                    if not await self.manager.discard_card(player, card, "制衡"):
                        return False
                    if self.engine.game_aborted:
                        return False
            finally:
                await self.manager.finish_loss_batch(player)
            await self.manager.draw_cards(player, len(cards) + (1 if all_hand else 0), "制衡")
            return True

        if name == "奇袭" and variant == "as_guohe" and target and indices:
            if not 0 <= indices[0] < len(player.hand):
                return False
            card = player.hand[indices[0]]
            if card_color(card) != "black":
                return False
            await self.manager.announce(player, "奇袭", f"{player.name}发动【奇袭】，将黑色牌当【过河拆桥】")
            await self.manager.discard_card(player, card, "奇袭")
            record_stat(self.engine, player, "cards_played")
            virtual = Card(f"qixi_{card.id}", "过河拆桥", card.suit, card.rank, "trick")
            success = await self.engine.card_system.use_guohe(player, virtual, target)
            await self.manager.after_card_used(player, virtual, [target], success)
            return success

        if name == "苦肉" and variant == "lose_hp" and indices:
            if not 0 <= indices[0] < len(player.hand):
                return False
            mark_once_per_turn(player, "苦肉")
            await self.manager.announce(player, "苦肉", f"{player.name}发动【苦肉】弃牌并失去1点体力")
            await self.manager.discard_card(player, player.hand[indices[0]], "苦肉")
            await self.manager.lose_hp(player, 1, "苦肉")
            return True

        if name == "反间" and variant == "give_reveal" and target and indices:
            if not 0 <= indices[0] < len(player.hand):
                return False
            card = player.hand[indices[0]]
            mark_once_per_turn(player, "反间")
            await self.manager.announce(player, "反间", f"{player.name}发动【反间】，展示并交给{target.name}【{card.name}】")
            await self.manager.transfer_card(player, target, card, "反间")
            same_suit = [c for c in target.hand if c.suit == card.suit]
            if len(same_suit) <= 1:
                for lose in list(same_suit):
                    await self.manager.discard_card(target, lose, "反间")
            else:
                await self.manager.lose_hp(target, 1, "反间", player)
            return True

        if name == "国色" and target and indices:
            if not 0 <= indices[0] < len(player.hand):
                return False
            card = player.hand[indices[0]]
            if card.suit != "diamond":
                return False
            mark_once_per_turn(player, "国色")
            if variant == "as_lebu":
                player.hand.remove(card)
                card.name = "乐不思蜀"
                card.card_type = "delayed_trick"
                target.judge_area.append(card)
                record_stat(self.engine, player, "cards_played")
                await self.manager.on_cards_lost(player, [card], "国色")
                await self.manager.announce(player, "国色", f"{player.name}发动【国色】，对{target.name}使用【乐不思蜀】")
            elif variant == "remove_lebu":
                await self.manager.discard_card(player, card, "国色")
                delayed = next((c for c in target.judge_area if c.name == "乐不思蜀"), None)
                if not delayed:
                    return False
                target.judge_area.remove(delayed)
                self.state.discard_pile.append(delayed)
                await self.manager.on_card_discarded(target, delayed, "国色")
                await self.manager.announce(player, "国色", f"{player.name}发动【国色】移除{target.name}的【乐不思蜀】")
            else:
                return False
            await self.manager.draw_cards(player, 1, "国色")
            return True

        if name == "攻心" and target:
            hearts = [c for c in target.hand if c.suit == "heart"]
            if not hearts:
                return False
            result = await self.manager.ask_choose_cards_result(
                player, f"【攻心】：请选择获得{target.name}的一张红桃手牌",
                hearts, min_n=1, max_n=1, zone="hand", skill_name="攻心",
                context={"target": target}, cancelable=True,
                places=[(target, "hand")] * len(hearts),
            )
            if self._finished() or result.get("status") not in ("resolved", "timeout"):
                return False
            heart = next(iter(result.get("cards") or []), None)
            if not heart or heart not in target.hand:
                return False
            move = await self.engine.move_card(
                heart, "hand", "hand", from_owner=target, to_owner=player,
                reason="攻心", actor_id=player.id, visibility="owner",
            )
            if move is None:
                return False
            mark_once_per_turn(player, "攻心")
            await self.manager.on_card_gained(player, [heart], "攻心")
            await self.manager.announce(player, "攻心", f"{player.name}发动【攻心】获得{target.name}一张红桃牌")
            return True
        return False

    async def before_phase(self, player, phase):
        if phase == Phase.JUDGE and self.has(player, "谦逊") and player.hand and player.judge_area:
            use = await self.manager.ask_confirm(
                player, "是否发动【谦逊】暂存所有手牌？", skill_name="谦逊",
                context={"delayed_tricks": [card.name for card in player.judge_area]},
            )
            if use and not self.engine.game_aborted:
                for card in list(player.hand):
                    move = await self.engine.move_card(
                        card, "hand", "temporary", from_owner=player, to_owner=player,
                        reason="谦逊", actor_id=player.id, visibility="owner",
                    )
                    if move is None:
                        break
                if player.temporary:
                    await self.manager.announce(player, "谦逊", f"{player.name}发动【谦逊】暂存所有手牌")
        if phase == Phase.PREPARE and self.has(player, "勤学"):
            await self._try_qinxue(player)

        if phase == Phase.DRAW and self.has(player, "英姿"):
            cards = await self.manager.draw_cards(player, 3, "英姿")
            await self.manager.announce(player, "英姿", f"{player.name}发动【英姿】摸{len(cards)}张牌")
            return {"skip_default": True}

        if phase == Phase.DISCARD and self.has(player, "克己") and not ensure_flags(player).get("sha_used_this_turn"):
            use = await self.manager.ask_confirm(player, "是否发动【克己】跳过弃牌阶段？", skill_name="克己", default=False)
            if use and not self._finished():
                await self.manager.announce(player, "克己", f"{player.name}发动【克己】跳过弃牌阶段")
                return {"skip_default": True}
        return None

    async def after_phase(self, player, phase):
        if phase != Phase.END:
            return
        if self.has(player, "勤学"):
            await self._try_qinxue(player)
        if self.has(player, "博图"):
            suits = ensure_flags(player).get("turn_discard_suits", set())
            round_key = f"botu_round_{self.state.round_number}"
            used = ensure_flags(player).get(round_key, 0)
            limit = min(3, len([p for p in self.state.players if p.alive]))
            if len(suits) >= 4 and used < limit:
                use = await self.manager.ask_confirm(player, "是否发动【博图】获得额外回合？", skill_name="博图", default=False)
                if use and not self._finished():
                    ensure_flags(player)[round_key] = used + 1
                    ensure_flags(player)["extra_turn"] = True
                    await self.manager.announce(player, "博图", f"{player.name}发动【博图】获得额外回合")
        # 谦逊暂存牌在当前回合结束时归还。
        for owner in self.state.players:
            stored = list(owner.temporary)
            if stored:
                moved = []
                for card in stored:
                    event = await self.engine.move_card(
                        card, "temporary", "hand", from_owner=owner, to_owner=owner,
                        reason="谦逊归还", actor_id=owner.id, visibility="owner",
                    )
                    if event is not None:
                        moved.append(card)
                stored = moved
                await self.manager.on_card_gained(owner, stored, "谦逊")
                await self.manager.announce(owner, "谦逊", f"{owner.name}收回因【谦逊】暂存的{len(stored)}张牌")

    async def _try_qinxue(self, player):
        if self.manager.skill_state_value(player, "勤学", "awakened", False) or len(player.hand) - player.hp <= 1:
            return
        flags = ensure_flags(player)
        self.manager.set_skill_state(player, "勤学", "awakened", True)
        flags["qinxue_awakened"] = True
        player.max_hp = max(1, player.max_hp - 1)
        player.hp = min(player.hp, player.max_hp)
        choice = await self.manager.ask_choose_option(
            player, "勤学觉醒后选择一项",
            [{"key": "recover", "label": "回复1点体力"}, {"key": "draw", "label": "摸两张牌"}],
            skill_name="勤学",
        )
        if self._finished():
            return
        key = choice.get("key") if isinstance(choice, dict) else choice
        if key == "recover" and player.hp < player.max_hp:
            await self.manager.recover(player, 1, player, "勤学")
        elif key == "draw":
            await self.manager.draw_cards(player, 2, "勤学")
        flags["gongxin"] = True
        await self.manager.announce(player, "勤学", f"{player.name}觉醒【勤学】，获得【攻心】")

    async def before_multi_target_trick(self, source, card, targets):
        owner = next((p for p in self.state.players if p.alive and self.has(p, "奋威") and "奋威" not in ensure_flags(p).setdefault("limited_skills", set())), None)
        if not owner or len(targets) < 2:
            return targets
        use = await self.manager.ask_confirm(
            owner, "是否发动限定技【奋威】令此锦囊对目标角色无效？",
            skill_name="奋威", context={"source": source, "card_name": card.name,
                                         "target_ids": [p.id for p in targets]},
            default=False,
        )
        if self._finished() or not use:
            return targets
        chosen = await self.manager.ask_choose_players(
            owner, "【奋威】：选择令此锦囊对其无效的目标",
            [p for p in targets if p.alive], min_n=1, max_n=len(targets),
            skill_name="奋威", context={"card_name": card.name}, cancelable=True,
        )
        if self._finished() or not chosen:
            return targets
        protected = [p for p in chosen if p in targets and p.alive]
        if not protected:
            return targets
        ensure_flags(owner)["limited_skills"].add("奋威")
        await self.manager.announce(owner, "奋威", f"{owner.name}发动【奋威】，令{len(protected)}名角色不受锦囊影响")
        return [p for p in targets if p not in protected]

    async def before_card_target(self, source, target, card):
        # 流离：先确认，再由目标本人选成本和新目标；所有选择完成前不移动牌。
        if card and card.name == "杀" and self.has(target, "流离") and (target.hand or target.equipment):
            alternatives = [
                p for p in self.state.players
                if p.alive and p not in (source, target)
                and self.manager.modify_distance(target, p, self.state.get_distance(target, p))
                    <= target.get_equipment_range()
            ]
            if alternatives:
                use = await self.manager.ask_confirm(
                    target, "是否发动【流离】弃置一张牌并转移此【杀】？",
                    skill_name="流离", context={"source": source}, default=False,
                )
                if self._finished():
                    return None
                if use:
                    cost = await self._choose_region_card(
                        target, target, "流离", "【流离】：选择一张手牌或装备作为弃置牌",
                    )
                    if self._finished():
                        return None
                    new_targets = [p for p in alternatives if p.alive]
                    chosen_targets = await self.manager.ask_choose_players(
                        target, "【流离】：选择此【杀】的新目标", new_targets,
                        min_n=1, max_n=1, skill_name="流离",
                        context={"source": source}, cancelable=True,
                    ) if cost and new_targets else []
                    if self._finished():
                        return None
                    new_target = chosen_targets[0] if chosen_targets else None
                    if cost and new_target in new_targets:
                        cost_card, zone = cost
                        if await self._discard_region_card(target, cost_card, zone, "流离", target):
                            # 原杀来源→大乔的敌意已由 use_sha 在指定目标时记下；这里只记大乔的转移选择。
                            self.manager.ledger_record("流离", target, new_target)
                            await self.manager.announce(target, "流离", f"{target.name}发动【流离】，将【杀】转移给{new_target.name}")
                            return new_target
        # 谦逊：成为其他角色普通锦囊唯一目标时暂存所有手牌。
        if card and card.card_type == "trick" and source is not target and self.has(target, "谦逊") and target.hand:
            use = await self.manager.ask_confirm(
                target, "是否发动【谦逊】暂存所有手牌并抵消此牌？",
                skill_name="谦逊", context={"source": source, "card_name": card.name},
            )
            if use and not self.engine.game_aborted:
                for held in list(target.hand):
                    move = await self.engine.move_card(
                        held, "hand", "temporary", from_owner=target, to_owner=target,
                        reason="谦逊", actor_id=target.id,
                        visibility="owner",
                    )
                    if move is None:
                        return None
                ensure_flags(target)["qianxun_cancelled_card"] = card.id
                await self.manager.announce(target, "谦逊", f"{target.name}发动【谦逊】暂存所有手牌")
        return target

    async def on_cards_lost(self, player, cards, reason="unknown", *, event=None):
        if event is not None and (event.from_zone != "hand" or event.to_zone == "temporary"):
            return
        if self.has(player, "连营") and not player.hand and cards:
            recipients = [player] + [p for p in self.state.players if p.alive and p is not player]
            count = min(len(cards), len(recipients))
            use = await self.manager.ask_confirm(player, "是否发动【连营】令角色摸牌？", skill_name="连营", default=False)
            if not use or self._finished():
                return
            selected = await self.manager.ask_choose_players(
                player, "选择因【连营】摸牌的角色", recipients,
                min_n=1, max_n=count, skill_name="连营", cancelable=False,
            )
            if self._finished():
                return
            for target in selected:
                await self.manager.draw_cards(target, 1, "连营")
            if selected:
                await self.manager.announce(player, "连营", f"{player.name}发动【连营】，令{len(selected)}名角色各摸一张牌")

    async def on_hp_lost(self, player, amount, reason="unknown", source=None):
        if not self.has(player, "诈降"):
            return
        await self.manager.draw_cards(player, 3 * amount, "诈降")
        if self.state.current_player is player and self.state.current_phase == Phase.PLAY:
            player.max_sha += amount
            ensure_flags(player)["zaxiang_active"] = True
        await self.manager.announce(player, "诈降", f"{player.name}发动【诈降】摸{3 * amount}张牌")

    async def before_sha(self, source, target, card, event):
        if self.has(source, "诈降") and ensure_flags(source).get("zaxiang_active") and card_color(card) == "red":
            event["shanRequired"] = 0
            card.ignore_distance = True

    async def on_recover(self, player, amount, source=None, reason="unknown"):
        # 救援：吴势力角色自己回合内回复时可改为主公回复，自己摸牌。
        if player.identity == "lord" or hero_faction(player) != "wu" or self.state.current_player is not player:
            return
        lord = next((p for p in self.state.players if p.alive and p.identity == "lord" and self.has(p, "救援")), None)
        if not lord or player.hp < lord.hp or lord.hp >= lord.max_hp:
            return
        use = await self.manager.ask_confirm(player, f"是否发动【救援】改为令主公{lord.name}回复？", skill_name="救援", default=False)
        if not use or self._finished():
            return
        before_player = player.hp
        player.hp = max(0, player.hp - amount)
        # 冲销必须落在正向治疗所记的那一行（source or player），否则提供者账目虚高。
        record_stat(self.engine, source or player, "healing", -(before_player - player.hp))
        before = lord.hp
        lord.hp = min(lord.max_hp, lord.hp + 1)
        record_stat(self.engine, lord, "healing", lord.hp - before)
        await self.manager.draw_cards(player, 1, "救援")
        await self.manager.announce(lord, "救援", f"{player.name}响应【救援】，改为令{lord.name}回复{lord.hp - before}点体力并摸一张牌")

    def ignore_distance(self, source, card):
        return bool(self.has(source, "诈降") and ensure_flags(source).get("zaxiang_active") and card.name == "杀" and card_color(card) == "red")

    def hand_limit(self, player, current):
        if self.has(player, "英姿"):
            current = max(current, player.max_hp)
        return current
