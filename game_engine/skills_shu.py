#!/usr/bin/env python3
"""界限突破蜀国7将14技能运行实现。"""

from .state_manager import Card, Phase, card_to_dict
from .skill_runtime_core import (
    FactionSkillHandler, alive_others, card_color, card_type_group, ensure_flags,
    hero_faction, mark_once_per_turn, once_per_turn, player_by_id,
)


class ShuSkillHandler(FactionSkillHandler):
    faction = "shu"

    def _target_ids(self, player, require_hand=False):
        return [p.id for p in alive_others(self.state, player) if not require_hand or p.hand]

    def _sha_targets(self, player, ignore_distance=False):
        result = []
        for target in alive_others(self.state, player):
            if self.manager.target_error(player, target, "杀"):
                continue
            distance = self.manager.modify_distance(player, target, self.state.get_distance(player, target))
            if ignore_distance or distance <= player.get_equipment_range():
                result.append(target.id)
        return result

    def get_actions(self, player):
        actions = []
        flags = ensure_flags(player)

        # 仁德：每次交一张牌，同一阶段不能重复同一目标；累计两张后可视为基本牌。
        if self.has(player, "仁德") and player.hand:
            used_targets = set(flags.get("rende_targets", []))
            valid = [pid for pid in self._target_ids(player) if pid not in used_targets]
            for index in range(len(player.hand)):
                if valid:
                    actions.append(self._action("仁德", "give", [index], valid, True, "交给其他角色一张手牌"))
            if flags.get("rende_basic_available"):
                if player.hp < player.max_hp:
                    actions.append(self._action("仁德", "basic_tao", [], [], False, "视为使用【桃】"))
                sha_targets = self._sha_targets(player)
                if sha_targets and player.sha_count < player.max_sha:
                    actions.append(self._action("仁德", "basic_sha", [], sha_targets, True, "视为使用【杀】"))

        # 激将：主公向其他蜀势力角色征用一张杀。
        if self.has(player, "激将") and player.identity == "lord":
            donors = [p for p in alive_others(self.state, player) if hero_faction(p) == "shu" and any(c.name == "杀" for c in p.hand)]
            targets = self._sha_targets(player)
            if donors and targets and player.sha_count < player.max_sha:
                actions.append(self._action("激将", "borrow_sha", [], targets, True, "令蜀势力角色打出【杀】"))

        # 武圣：红色牌当杀；方片无距离限制。
        if self.has(player, "武圣") and player.sha_count < player.max_sha:
            for index, card in enumerate(player.hand):
                if card_color(card) == "red" and card.name != "杀":
                    targets = self._sha_targets(player, ignore_distance=card.suit == "diamond")
                    if targets:
                        actions.append(self._action("武圣", "as_sha", [index], targets, True, f"将{card.name}当【杀】"))

        # 义绝：弃一张牌，令目标展示一张手牌。
        if self.has(player, "义绝") and player.hand and not once_per_turn(player, "义绝"):
            valid = self._target_ids(player, require_hand=True)
            for index in range(len(player.hand)):
                if valid:
                    actions.append(self._action("义绝", "reveal", [index], valid, True, "弃牌并令目标展示手牌"))

        # 龙胆：闪当杀（酒/桃互换在当前牌堆出现酒后自动由同一分支扩展）。
        if self.has(player, "龙胆") and player.sha_count < player.max_sha:
            for index, card in enumerate(player.hand):
                if card.name == "闪":
                    targets = self._sha_targets(player)
                    if targets:
                        actions.append(self._action("龙胆", "shan_as_sha", [index], targets, True, "将【闪】当【杀】"))

        return actions

    @staticmethod
    def _action(name, variant, card_indices, valid_targets, requires_target, text):
        return {
            "type": "use_skill", "skill_name": name, "variant": variant,
            "card_indices": card_indices, "requires_target": requires_target,
            "valid_targets": valid_targets, "description": text,
        }

    async def execute(self, player, action, targets):
        name, variant = action.get("skill_name"), action.get("variant")
        target = targets[0] if targets else None
        indices = action.get("card_indices") or []

        if name == "仁德" and variant == "give":
            if not indices or not target or not player.hand:
                return False
            card = player.hand[indices[0]] if 0 <= indices[0] < len(player.hand) else None
            if not card:
                return False
            await self.manager.announce(player, "仁德", f"{player.name}发动【仁德】，交给{target.name}一张牌")
            await self.manager.transfer_card(player, target, card, "仁德")
            flags = ensure_flags(player)
            flags.setdefault("rende_targets", []).append(target.id)
            flags["rende_count"] = flags.get("rende_count", 0) + 1
            if flags["rende_count"] >= 2 and not flags.get("rende_basic_used"):
                flags["rende_basic_available"] = True
            return True

        if name == "仁德" and variant in ("basic_tao", "basic_sha"):
            flags = ensure_flags(player)
            if not flags.get("rende_basic_available"):
                return False
            flags["rende_basic_available"] = False
            flags["rende_basic_used"] = True
            await self.manager.announce(player, "仁德", f"{player.name}以【仁德】视为使用基本牌")
            if variant == "basic_tao":
                if player.hp >= player.max_hp:
                    return False
                player.hp += 1
                return True
            virtual = Card(f"skill_rende_sha_{player.id}", "杀", "heart", 1, "basic")
            return await self.engine.card_system.use_sha(player, virtual, target)

        if name == "激将" and variant == "borrow_sha":
            donor = next((p for p in alive_others(self.state, player) if hero_faction(p) == "shu" and any(c.name == "杀" for c in p.hand)), None)
            if not donor or not target:
                return False
            card = next(c for c in donor.hand if c.name == "杀")
            donor.hand.remove(card)
            self.state.discard_pile.append(card)
            await self.manager.announce(player, "激将", f"{player.name}发动【激将】，{donor.name}打出【杀】")
            await self.engine.card_system.notify_card_to_discard(donor, card, "respond", message=f"{donor.name}响应【激将】打出【杀】")
            virtual = Card(f"skill_jijiang_sha_{player.id}", "杀", card.suit, card.rank, "basic")
            return await self.engine.card_system.use_sha(player, virtual, target)

        if name in ("武圣", "龙胆") and variant in ("as_sha", "shan_as_sha"):
            if not indices or not target or not 0 <= indices[0] < len(player.hand):
                return False
            source = player.hand[indices[0]]
            expected = name == "武圣" and card_color(source) == "red" or name == "龙胆" and source.name == "闪"
            if not expected:
                return False
            await self._consume_conversion(player, source, name, "杀")
            virtual = Card(f"skill_{name}_{source.id}", "杀", source.suit, source.rank, "basic")
            if name == "武圣" and source.suit == "diamond":
                virtual.ignore_distance = True
            return await self.engine.card_system.use_sha(player, virtual, target)

        if name == "义绝" and variant == "reveal":
            if not indices or not target or not target.hand or not 0 <= indices[0] < len(player.hand):
                return False
            cost = player.hand[indices[0]]
            await self._discard_cost(player, cost, "义绝")
            mark_once_per_turn(player, "义绝")
            shown = target.hand[0]
            await self.manager.announce(player, "义绝", f"{target.name}因【义绝】展示{shown.suit}{shown.rank}【{shown.name}】")
            if card_color(shown) == "black":
                flags = ensure_flags(target)
                flags["cannot_use_hand"] = True
                flags["nonlocked_disabled"] = True
                flags["yijue_heart_source"] = player.id
                ensure_flags(player).setdefault("yijue_targets", []).append(target.id)
            else:
                await self.manager.transfer_card(target, player, shown, "义绝")
                if target.hp < target.max_hp:
                    await self.manager.recover(target, 1, player, "义绝")
            return True

        return False

    async def _discard_cost(self, player, card, skill_name):
        index = player.hand.index(card)
        player.hand.remove(card)
        self.state.discard_pile.append(card)
        await self.engine.card_system.notify_card_to_discard(
            player, card, "discard", index, f"{player.name}发动【{skill_name}】弃置【{card.name}】"
        )

    async def _consume_conversion(self, player, card, skill_name, as_name):
        index = player.hand.index(card)
        await self.manager.announce(player, skill_name, f"{player.name}发动【{skill_name}】，将【{card.name}】当【{as_name}】")
        await self.engine._notify_card_ui(
            message=f"{player.name}以【{skill_name}】将【{card.name}】当【{as_name}】",
            system_text=f"[‘{player.name}’{skill_name}·{as_name}！]",
            actor_id=player.id, actor_name=player.name, source_name=player.name,
            target_name="", card_name=as_name, card_index=index,
            card=card_to_dict(card, name=as_name),
            reason="skill_conversion", discard_count=len(self.state.discard_pile) + 1,
        )
        player.hand.remove(card)
        self.state.discard_pile.append(card)

    async def on_turn_start(self, player):
        flags = ensure_flags(player)
        flags.pop("rende_targets", None)
        flags.pop("rende_count", None)
        flags.pop("rende_basic_available", None)
        flags.pop("rende_basic_used", None)
        if self.has(player, "咆哮"):
            player.max_sha = 999
            self.manager.record(player, "咆哮", "turn_rule", max_sha=999)

    async def before_phase(self, player, phase):
        if phase == Phase.PREPARE:
            # 替身限定技：受伤时自动发动，回复值等量摸牌。
            flags = ensure_flags(player)
            if self.has(player, "替身") and player.hp < player.max_hp and "替身" not in flags.setdefault("limited_skills", set()):
                recovered = player.max_hp - player.hp
                flags["limited_skills"].add("替身")
                player.hp = player.max_hp
                self.state.draw_card(player, recovered)
                await self.manager.announce(player, "替身", f"{player.name}发动【替身】，回复{recovered}点体力并摸{recovered}张牌")
                # 观星：自动把当前最需要的牌置于牌堆顶。
                # 评分保留现值（桃在掉血时100否则40，闪80，杀60，过河拆桥55，其余20）——
                # 观星是"预测下一张可用牌"的战术评分，与弃牌托管保留分（phase_controller
                # KEEP_SCORE，防弃牌）目的不同，刻意不与 CARD_TABLE 共用一套分值。
                if self.has(player, "观星") and self.state.deck:
                    count = 3 if len([p for p in self.state.players if p.alive]) < 4 else 5
                    cards = self.state.deck[:count]
                    score = {"桃": 100 if player.hp < player.max_hp else 40, "闪": 80, "杀": 60, "过河拆桥": 55}
                cards.sort(key=lambda c: (score.get(c.name, 20), -c.rank), reverse=True)
                self.state.deck[:count] = cards
                await self.manager.announce(player, "观星", f"{player.name}发动【观星】，调整牌堆顶{len(cards)}张牌")
        return None

    async def after_phase(self, player, phase):
        if phase != Phase.END:
            return
        flags = ensure_flags(player)
        for key in ("yijue_targets", "tieqi_targets"):
            for target_id in flags.pop(key, []):
                target = player_by_id(self.state, target_id)
                if target:
                    tflags = ensure_flags(target)
                    tflags.pop("cannot_use_hand", None)
                    tflags.pop("nonlocked_disabled", None)
                    tflags.pop("yijue_heart_source", None)
        flags.pop("pao_tokens", None)

    async def before_sha(self, source, target, card, event):
        # 铁骑：判定；目标若不能交同花色牌，则不可闪且伤害+1。
        if self.has(source, "铁骑") and self.state.deck:
            judge = self.state.deck.pop(0)
            self.state.discard_pile.append(judge)
            ensure_flags(target)["nonlocked_disabled"] = True
            matching = next((c for c in target.hand if c.suit == judge.suit), None)
            if matching:
                await self.manager.transfer_card(target, source, matching, "铁骑")
                await self.manager.announce(source, "铁骑", f"{target.name}交出同花色牌响应【铁骑】")
            else:
                event["shanRequired"] = 0
                event["baseDamage"] += 1
                await self.manager.announce(source, "铁骑", f"{target.name}未能响应【铁骑】，此杀不可闪且伤害+1")

    async def on_sha_dodged(self, source, target, card, event):
        if self.has(source, "咆哮"):
            flags = ensure_flags(source)
            flags["pao_tokens"] = flags.get("pao_tokens", 0) + 1
            self.manager.record(source, "咆哮", "sha_dodged", tokens=flags["pao_tokens"])

    async def modify_damage(self, source, target, amount, card=None, context=None):
        if source and self.has(source, "咆哮") and card and card.name == "杀":
            flags = ensure_flags(source)
            tokens = flags.pop("pao_tokens", 0)
            if tokens:
                amount += tokens
                await self.manager.announce(source, "咆哮", f"{source.name}弃置{tokens}枚“咆”，伤害+{tokens}")
        if source and target and ensure_flags(target).get("yijue_heart_source") == source.id and card and card.name == "杀" and card.suit == "heart":
            amount += 1
        return amount

    async def after_card_used(self, player, card, targets, success):
        if not success:
            return
        flags = ensure_flags(player)
        if card.name == "杀":
            flags["sha_used_this_turn"] = True
        if card_type_group(card) == "trick":
            flags["trick_used_this_turn"] = True
            if self.has(player, "集智"):
                drawn = self.state.draw_card(player, 1)
                if drawn:
                    await self.manager.announce(player, "集智", f"{player.name}发动【集智】摸一张牌")
                    card_drawn = drawn[0]
                    if card_type_group(card_drawn) == "basic" and len(player.hand) > player.hp:
                        player.hand.remove(card_drawn)
                        self.state.discard_pile.append(card_drawn)
                        flags["hand_limit_bonus"] = flags.get("hand_limit_bonus", 0) + 1
                        await self.engine.card_system.notify_card_to_discard(player, card_drawn, "discard", message=f"{player.name}因【集智】弃置摸到的基本牌")

    def response_options(self, player, requested_name):
        if ensure_flags(player).get("cannot_use_hand"):
            return []
        options = []
        if requested_name == "闪" and self.has(player, "龙胆"):
            for index, card in enumerate(player.hand):
                if card.name == "杀":
                    options.append({"card": card, "card_index": index, "as_name": "闪", "skill_name": "龙胆", "owner": player})
        if requested_name == "杀":
            if self.has(player, "武圣"):
                for index, card in enumerate(player.hand):
                    if card.name != "杀" and card_color(card) == "red":
                        options.append({"card": card, "card_index": index, "as_name": "杀", "skill_name": "武圣", "owner": player})
            if self.has(player, "龙胆"):
                for index, card in enumerate(player.hand):
                    if card.name == "闪":
                        options.append({"card": card, "card_index": index, "as_name": "杀", "skill_name": "龙胆", "owner": player})
            if self.has(player, "激将") and player.identity == "lord":
                donor = next((p for p in alive_others(self.state, player) if hero_faction(p) == "shu" and any(c.name == "杀" for c in p.hand)), None)
                if donor:
                    card = next(c for c in donor.hand if c.name == "杀")
                    options.append({"card": card, "card_index": donor.hand.index(card), "as_name": "杀", "skill_name": "激将", "owner": donor})
        if requested_name == "桃" and self.has(player, "龙胆"):
            for index, card in enumerate(player.hand):
                if card.name == "酒":
                    options.append({"card": card, "card_index": index, "as_name": "桃", "skill_name": "龙胆", "owner": player})
        if requested_name == "酒" and self.has(player, "龙胆"):
            for index, card in enumerate(player.hand):
                if card.name == "桃":
                    options.append({"card": card, "card_index": index, "as_name": "酒", "skill_name": "龙胆", "owner": player})
        return options

    async def on_card_responded(self, player, card, as_name, context=None):
        owner = (context or {}).get("owner")
        if owner and owner is not player and self.has(player, "激将") and as_name == "杀":
            await self.manager.announce(player, "激将", f"{player.name}发动【激将】，由{owner.name}打出【杀】")
        if self.has(player, "武圣") and as_name == "杀" and card.name != "杀" and card_color(card) == "red":
            await self.manager.announce(player, "武圣", f"{player.name}发动【武圣】，将红色牌当【杀】")
        if self.has(player, "龙胆") and card.name != as_name:
            await self.manager.announce(player, "龙胆", f"{player.name}发动【龙胆】，将【{card.name}】当【{as_name}】")
        responder = owner or player
        if hero_faction(responder) == "shu" and responder is not self.state.current_player and as_name == "杀":
            lord = next((p for p in self.state.players if p.alive and p.identity == "lord" and self.has(p, "激将") and not once_per_turn(p, "激将摸牌")), None)
            if lord:
                mark_once_per_turn(lord, "激将摸牌")
                await self.manager.draw_cards(lord, 1, "激将")
                await self.manager.announce(lord, "激将", f"{responder.name}于回合外打出【杀】，{lord.name}因【激将】摸一张牌")
        if self.has(player, "涯角") and player is not self.state.current_player and self.state.deck:
            revealed = self.state.deck.pop(0)
            if card_type_group(revealed) == card_type_group(card):
                player.hand.append(revealed)
                await self.manager.announce(player, "涯角", f"{player.name}发动【涯角】并获得展示牌【{revealed.name}】")
            else:
                self.state.discard_pile.append(revealed)
                source = (context or {}).get("source")
                if source and source.hand:
                    removed = source.hand[0]
                    source.hand.remove(removed)
                    self.state.discard_pile.append(removed)
                    await self.manager.announce(player, "涯角", f"{player.name}发动【涯角】弃置{source.name}一张牌")

    def can_target(self, source, target, card_name):
        if self.has(target, "空城") and not target.hand and card_name in ("杀", "决斗"):
            return "目标处于【空城】状态"
        return None

    def modify_distance(self, source, target, distance):
        if self.has(source, "马术"):
            return distance - 1
        return distance

    def protect_card(self, owner, card, reason):
        protected = {"八卦阵", "仁王盾", "藤甲", "白银狮子", "木牛流马", "玉玺"}
        return bool(self.has(owner, "奇才") and reason == "other_discard_equipment" and card.name in protected)
