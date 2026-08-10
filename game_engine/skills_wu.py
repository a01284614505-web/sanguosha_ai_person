#!/usr/bin/env python3
"""界限突破吴国7将12技能运行实现。"""

from .state_manager import Card, Phase
from .skill_runtime_core import (
    FactionSkillHandler, alive_others, card_color, ensure_flags, hero_faction,
    mark_once_per_turn, once_per_turn,
)


class WuSkillHandler(FactionSkillHandler):
    faction = "wu"

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

        if self.has(player, "制衡") and player.hand and not once_per_turn(player, "制衡"):
            for index in range(len(player.hand)):
                actions.append(self._action("制衡", "discard_draw", [index], text="弃置一张牌并摸一张牌"))
            if len(player.hand) > 1:
                actions.append(self._action("制衡", "discard_all", list(range(len(player.hand))), text="弃置所有手牌并多摸一张"))

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

        if name == "制衡" and variant in ("discard_draw", "discard_all"):
            cards = [player.hand[i] for i in indices if 0 <= i < len(player.hand)]
            if not cards:
                return False
            all_hand = len(cards) == len(player.hand)
            mark_once_per_turn(player, "制衡")
            await self.manager.announce(player, "制衡", f"{player.name}发动【制衡】弃置{len(cards)}张牌")
            for card in list(cards):
                await self.manager.discard_card(player, card, "制衡")
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
            heart = next((c for c in target.hand if c.suit == "heart"), None)
            if not heart:
                return False
            mark_once_per_turn(player, "攻心")
            await self.manager.transfer_card(target, player, heart, "攻心")
            await self.manager.announce(player, "攻心", f"{player.name}发动【攻心】获得{target.name}一张红桃牌")
            return True
        return False

    async def before_phase(self, player, phase):
        if phase == Phase.JUDGE and self.has(player, "谦逊") and player.hand and player.judge_area:
            stored = list(player.hand)
            player.hand.clear()
            ensure_flags(player)["qianxun_cards"] = ensure_flags(player).get("qianxun_cards", []) + stored
            await self.manager.on_cards_lost(player, stored, "谦逊")
            await self.manager.announce(player, "谦逊", f"{player.name}因延时锦囊发动【谦逊】暂存所有手牌")
        if phase == Phase.PREPARE and self.has(player, "勤学"):
            await self._try_qinxue(player)

        if phase == Phase.DRAW and self.has(player, "英姿"):
            cards = await self.manager.draw_cards(player, 3, "英姿")
            await self.manager.announce(player, "英姿", f"{player.name}发动【英姿】摸{len(cards)}张牌")
            return {"skip_default": True}

        if phase == Phase.DISCARD and self.has(player, "克己") and not ensure_flags(player).get("sha_used_this_turn"):
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
                ensure_flags(player)[round_key] = used + 1
                ensure_flags(player)["extra_turn"] = True
                await self.manager.announce(player, "博图", f"{player.name}发动【博图】获得额外回合")
        # 谦逊暂存牌在当前回合结束时归还。
        for owner in self.state.players:
            stored = ensure_flags(owner).pop("qianxun_cards", [])
            if stored:
                owner.hand.extend(stored)
                await self.manager.on_card_gained(owner, stored, "谦逊")
                await self.manager.announce(owner, "谦逊", f"{owner.name}收回因【谦逊】暂存的{len(stored)}张牌")

    async def _try_qinxue(self, player):
        flags = ensure_flags(player)
        if flags.get("qinxue_awakened") or len(player.hand) - player.hp <= 1:
            return
        flags["qinxue_awakened"] = True
        player.max_hp = max(1, player.max_hp - 1)
        player.hp = min(player.hp, player.max_hp)
        if player.hp < player.max_hp:
            await self.manager.recover(player, 1, player, "勤学")
        else:
            await self.manager.draw_cards(player, 2, "勤学")
        flags["gongxin"] = True
        await self.manager.announce(player, "勤学", f"{player.name}觉醒【勤学】，获得【攻心】")

    async def before_multi_target_trick(self, source, card, targets):
        owner = next((p for p in self.state.players if p.alive and self.has(p, "奋威") and "奋威" not in ensure_flags(p).setdefault("limited_skills", set())), None)
        if not owner or len(targets) < 2:
            return targets
        ensure_flags(owner)["limited_skills"].add("奋威")
        protected = [p for p in targets if p is owner or p.identity == owner.identity]
        if not protected:
            protected = [owner] if owner in targets else []
        result = [p for p in targets if p not in protected]
        await self.manager.announce(owner, "奋威", f"{owner.name}发动【奋威】，令{len(protected)}名角色不受锦囊影响")
        return result

    async def before_card_target(self, source, target, card):
        # 流离：弃一张牌，将杀转给攻击范围内另一名角色。
        if card and card.name == "杀" and self.has(target, "流离") and target.hand:
            alternatives = [p for p in self.state.players if p.alive and p not in (source, target) and self.state.get_distance(target, p) <= target.get_equipment_range()]
            if alternatives:
                await self.manager.discard_card(target, target.hand[0], "流离")
                new_target = sorted(alternatives, key=lambda p: (p.hp, p.id))[0]
                await self.manager.announce(target, "流离", f"{target.name}发动【流离】，将【杀】转移给{new_target.name}")
                return new_target
        # 谦逊：成为其他角色普通锦囊唯一目标时暂存所有手牌。
        if card and card.card_type == "trick" and source is not target and self.has(target, "谦逊") and target.hand:
            stored = list(target.hand)
            target.hand.clear()
            flags = ensure_flags(target)
            flags["qianxun_cards"] = stored
            flags["qianxun_cancelled_card"] = card.id
            await self.manager.on_cards_lost(target, stored, "谦逊")
            await self.manager.announce(target, "谦逊", f"{target.name}发动【谦逊】暂存所有手牌")
        return target

    async def on_cards_lost(self, player, cards, reason="unknown"):
        if self.has(player, "连营") and not player.hand and cards:
            recipients = [player] + [p for p in self.state.players if p.alive and p is not player]
            count = min(len(cards), len(recipients))
            for target in recipients[:count]:
                await self.manager.draw_cards(target, 1, "连营")
            await self.manager.announce(player, "连营", f"{player.name}发动【连营】，令{count}名角色各摸一张牌")

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
        player.hp = max(0, player.hp - amount)
        before = lord.hp
        lord.hp = min(lord.max_hp, lord.hp + 1)
        await self.manager.draw_cards(player, 1, "救援")
        await self.manager.announce(lord, "救援", f"{player.name}响应【救援】，改为令{lord.name}回复{lord.hp - before}点体力并摸一张牌")

    def ignore_distance(self, source, card):
        return bool(self.has(source, "诈降") and ensure_flags(source).get("zaxiang_active") and card.name == "杀" and card_color(card) == "red")

    def hand_limit(self, player, current):
        if self.has(player, "英姿"):
            current = max(current, player.max_hp)
        return current
