#!/usr/bin/env python3
"""界限突破蜀国7将14技能运行实现。"""

from .game_stats import record_stat
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
        if self.has(player, "仁德"):
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
            donors = [p for p in alive_others(self.state, player) if hero_faction(p) == "shu"
                      and any(card.name == "杀" for card, _index, _zone in self.response_card_entries(p))]
            targets = self._sha_targets(player)
            if donors and targets and player.sha_count < player.max_sha:
                actions.append(self._action("激将", "borrow_sha", [], targets, True, "令蜀势力角色打出【杀】"))

        # 武圣：红色牌当杀；方片无距离限制。
        if self.has(player, "武圣") and player.sha_count < player.max_sha:
            for card, index, _zone in self.response_card_entries(player):
                if card_color(card) == "red" and card.name != "杀":
                    targets = self._sha_targets(player, ignore_distance=card.suit == "diamond")
                    if targets:
                        actions.append(self._action("武圣", "as_sha", [index], targets, True, f"将{card.name}当【杀】"))

        # 义绝：弃一张牌，令目标展示一张手牌。
        if self.has(player, "义绝") and (player.hand or player.equipment) and not once_per_turn(player, "义绝"):
            valid = self._target_ids(player, require_hand=True)
            if valid:
                actions.append(self._action("义绝", "reveal", [], valid, True, "弃牌并令目标展示手牌"))

        # 龙胆：闪当杀（酒/桃互换在当前牌堆出现酒后自动由同一分支扩展）。
        if self.has(player, "龙胆") and player.sha_count < player.max_sha:
            for card, index, _zone in self.response_card_entries(player):
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
            if await self.manager.transfer_card(player, target, card, "仁德"):
                self.manager.ledger_record("仁德", player, target)   # 只记「给了谁」，不记牌名
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
            virtual = None
            if variant == "basic_tao" and player.hp >= player.max_hp:
                return False
            if variant == "basic_sha":
                if target is None:
                    return False
                virtual = Card(f"skill_rende_sha_{player.id}", "杀", "heart", 1, "basic")
                if not self.engine.rules.can_play_sha(player, virtual, [target])[0]:
                    return False
            flags["rende_basic_available"] = False
            flags["rende_basic_used"] = True
            await self.manager.announce(player, "仁德", f"{player.name}以【仁德】视为使用基本牌")
            if variant == "basic_tao":
                await self.manager.recover(player, 1, player, "仁德")
                return True
            return await self.engine.card_system.use_sha(player, virtual, target)

        if name == "激将" and variant == "borrow_sha":
            if not target:
                return False
            donor_entry = None
            for donor in alive_others(self.state, player):
                if hero_faction(donor) != "shu":
                    continue
                options = [(card, zone) for card, _index, zone in self.response_card_entries(donor)
                           if card.name == "杀"]
                if not options:
                    continue
                if not await self.manager.ask_confirm(
                    donor, f"是否响应{player.name}的【激将】，打出一张【杀】？",
                    skill_name="激将", default=False,
                ) or self.engine.game_aborted:
                    continue
                cards = await self.manager.ask_choose_cards(
                    donor, "请选择交给【激将】的一张【杀】", [item[0] for item in options],
                    skill_name="激将", cancelable=True,
                    places=[(donor, zone) for _card, zone in options],
                )
                if cards and not self.engine.game_aborted:
                    card = cards[0]
                    source_zone = next(zone for candidate, zone in options if candidate is card)
                    donor_entry = (donor, card, source_zone)
                    break
            if donor_entry is None:
                return False
            donor, card, source_zone = donor_entry
            virtual = Card(f"skill_jijiang_sha_{player.id}", "杀", card.suit, card.rank, "basic")
            context = self.engine._new_effect_context(
                player, virtual, skill_source="激将", card_cost_ids=[card.id], target=target,
            )
            move = await self.engine.move_card(
                card, source_zone, "discard", from_owner=donor,
                reason="激将", actor_id=player.id, effect_id=context.effect_id,
            )
            if move is None:
                return False
            record_stat(self.engine, donor, "cards_played")
            await self.manager.announce(player, "激将", f"{player.name}发动【激将】，{donor.name}打出【杀】")
            await self.engine.card_system.notify_card_to_discard(donor, card, "respond", message=f"{donor.name}响应【激将】打出【杀】")
            return await self.engine.card_system.use_sha(player, virtual, target, effect_context=context)

        if name in ("武圣", "龙胆") and variant in ("as_sha", "shan_as_sha"):
            if not indices or not target:
                return False
            candidate = next(((card, zone) for card, index, zone in self.response_card_entries(player)
                              if index == indices[0]), None)
            if candidate is None:
                return False
            source, _source_zone = candidate
            expected = (name == "武圣" and card_color(source) == "red" and source.name != "杀"
                        or name == "龙胆" and source.name == "闪")
            if not expected:
                return False
            virtual = Card(f"skill_{name}_{source.id}", "杀", source.suit, source.rank, "basic")
            context = self.engine._new_effect_context(
                player, virtual, skill_source=name, card_cost_ids=[source.id], target=target,
            )
            if not await self._consume_conversion(player, source, name, "杀", effect_id=context.effect_id):
                return False
            if name == "武圣" and source.suit == "diamond":
                virtual.ignore_distance = True
            return await self.engine.card_system.use_sha(player, virtual, target, effect_context=context)

        if name == "义绝" and variant == "reveal":
            if not target or not target.hand or once_per_turn(player, "义绝"):
                return False
            costs = [(card, "hand") for card in player.hand]
            costs.extend((card, "equipment") for card in player.equipment.values())
            if not costs:
                return False
            selected_cost = await self.manager.ask_choose_cards(
                player, "【义绝】：选择弃置的一张手牌或装备牌",
                [card for card, _zone in costs], skill_name="义绝", cancelable=True,
                places=[(player, zone) for _card, zone in costs],
            )
            if self.engine.game_aborted or not selected_cost:
                return False
            cost = selected_cost[0]
            cost_zone = next((zone for card, zone in costs if card is cost), None)
            if cost_zone is None or await self.engine.move_card(
                cost, cost_zone, "discard", from_owner=player,
                reason="义绝", actor_id=player.id,
            ) is None:
                return False
            mark_once_per_turn(player, "义绝")
            await self.engine.card_system.notify_card_to_discard(
                player, cost, "discard", message=f"{player.name}发动【义绝】弃置【{cost.name}】",
            )
            if not self.engine.game_aborted:
                await self.manager.on_card_discarded(player, cost, "义绝")
            if self.engine.game_aborted or not target.hand:
                return True
            shown_cards = await self.manager.ask_choose_cards(
                target, "【义绝】：请选择展示的一张手牌", list(target.hand),
                skill_name="义绝", cancelable=False,
            )
            if self.engine.game_aborted or not shown_cards:
                return True
            shown = shown_cards[0]
            if shown not in target.hand:
                return True
            await self.manager.announce(player, "义绝", f"{target.name}因【义绝】展示" + {"spade": "♠", "heart": "♥", "club": "♣", "diamond": "♦"}.get(shown.suit, "") + f"{shown.rank}【{shown.name}】")
            if card_color(shown) == "black":
                flags = ensure_flags(target)
                flags["cannot_use_hand"] = True
                flags["nonlocked_disabled"] = True
                sources = flags.setdefault("yijue_sources", [])
                if player.id not in sources:
                    sources.append(player.id)
                ensure_flags(player).setdefault("yijue_targets", []).append(target.id)
            else:
                if await self.manager.ask_confirm(
                    player, f"是否获得{target.name}展示的【{shown.name}】？",
                    skill_name="义绝", default=False,
                ) and not self.engine.game_aborted and shown in target.hand:
                    await self.manager.transfer_card(target, player, shown, "义绝")
                if (not self.engine.game_aborted and target.hp < target.max_hp
                        and await self.manager.ask_confirm(
                            player, f"是否令{target.name}回复1点体力？",
                            skill_name="义绝", default=False,
                        ) and not self.engine.game_aborted):
                    await self.manager.recover(target, 1, player, "义绝")
            return True

        return False

    async def _discard_cost(self, player, card, skill_name):
        index = player.hand.index(card)
        player.hand.remove(card)
        self.state.discard_pile.append(card)
        await self.manager.on_cards_lost(player, [card], skill_name)
        await self.engine.card_system.notify_card_to_discard(
            player, card, "discard", index, f"{player.name}发动【{skill_name}】弃置【{card.name}】"
        )

    async def _consume_conversion(self, player, card, skill_name, as_name, *, effect_id=None):
        # 木牛扣置牌使用与手牌相同的技能入口，但移动必须来自真实 treasure 牌区。
        entry = next(((index, zone) for candidate, index, zone in self.response_card_entries(player)
                      if candidate is card), None)
        if entry is None:
            return False
        index, source_zone = entry
        await self.manager.announce(player, skill_name, f"{player.name}发动【{skill_name}】，将【{card.name}】当【{as_name}】")
        await self.engine._notify_card_ui(
            message=f"{player.name}以【{skill_name}】将【{card.name}】当【{as_name}】",
            system_text=f"[‘{player.name}’{skill_name}·{as_name}！]",
            actor_id=player.id, actor_name=player.name, source_name=player.name,
            target_name="", card_name=as_name, card_index=index,
            card=card_to_dict(card, name=as_name),
            reason="skill_conversion", discard_count=len(self.state.discard_pile) + 1,
        )
        move = await self.engine.move_card(
            card, source_zone, "discard", from_owner=player,
            reason=skill_name, actor_id=player.id, effect_id=effect_id,
        )
        if move is None:
            return False
        record_stat(self.engine, player, "cards_played")
        return True

    async def on_turn_start(self, player):
        flags = ensure_flags(player)
        flags.pop("guanxing_bottomed", None)
        flags.pop("rende_targets", None)
        flags.pop("rende_count", None)
        flags.pop("rende_basic_available", None)
        flags.pop("rende_basic_used", None)
        if self.has(player, "咆哮"):
            player.max_sha = 999
            self.manager.record(player, "咆哮", "turn_rule", max_sha=999)

    async def before_phase(self, player, phase):
        if phase == Phase.PREPARE:
            # 限定技先由拥有者决定，确认后才消耗整局次数。
            if (self.has(player, "替身") and player.hp < player.max_hp
                    and self.manager.skill_available(player, "替身")
                    and await self.manager.ask_confirm(
                        player, "是否发动限定技【替身】？", skill_name="替身", default=False,
                    ) and not self.engine.game_aborted
                    and self.manager.consume_skill_use(player, "替身", charges=1)):
                recovered = player.max_hp - player.hp
                await self.manager.recover(player, recovered, player, "替身")
                if self.engine.game_aborted:
                    return None
                await self.manager.draw_cards(player, recovered, "替身")
                await self.manager.announce(player, "替身", f"{player.name}发动【替身】，回复{recovered}点体力并摸{recovered}张牌")
            if self.has(player, "观星") and self.state.deck:
                await self._guanxing(player)
        elif phase == Phase.END and ensure_flags(player).pop("guanxing_bottomed", False) and self.state.deck:
            if self.has(player, "观星"):
                await self._guanxing(player)
        return None

    async def _guanxing(self, player):
        if not await self.manager.ask_confirm(
            player, "是否发动【观星】？", skill_name="观星", default=False,
        ) or self.engine.game_aborted:
            return
        count = min(len(self.state.deck), 3 if sum(p.alive for p in self.state.players) < 4 else 5)
        revealed = list(self.state.deck[:count])
        if count == 1:
            choice = await self.manager.ask_choose_option(
                player, "将这张观星牌置于哪里？",
                [{"key": "top", "label": "牌堆顶"}, {"key": "bottom", "label": "牌堆底"}],
                skill_name="观星",
            )
            if self.engine.game_aborted or choice is None:
                return
            top_cards = revealed if choice.get("key") == "top" else []
        else:
            top = await self.manager.ask_choose_cards_result(
                player, "按点击顺序选择置于牌堆顶的牌；未选牌将置于牌堆底",
                revealed, min_n=0, max_n=count, zone="deck", skill_name="观星",
                cancelable=False, places=[(None, "deck")] * count,
            )
            if self.engine.game_aborted or not top.get("bool"):
                return
            top_cards = top["cards"]
        bottom = [card for card in revealed if card not in top_cards]
        if len(bottom) > 1:
            ordered = await self.manager.ask_choose_cards_result(
                player, "按点击顺序排列置于牌堆底的牌", bottom,
                min_n=len(bottom), max_n=len(bottom), zone="deck", skill_name="观星",
                cancelable=False, places=[(None, "deck")] * len(bottom),
            )
            if self.engine.game_aborted or not ordered.get("bool"):
                return
            bottom = ordered["cards"]
        if self.state.deck[:count] != revealed:
            return
        self.state.deck[:] = top_cards + self.state.deck[count:] + bottom
        if self.state.current_phase == Phase.PREPARE:
            ensure_flags(player)["guanxing_bottomed"] = not top_cards
        await self.manager.announce(player, "观星", f"{player.name}发动【观星】，调整牌堆顶{count}张牌")

    async def after_phase(self, player, phase):
        if phase != Phase.END:
            return
        flags = ensure_flags(player)
        for key, source_key in (("yijue_targets", "yijue_sources"),
                                ("tieqi_targets", "tieqi_sources")):
            for target_id in flags.pop(key, []):
                target = player_by_id(self.state, target_id)
                if target:
                    tflags = ensure_flags(target)
                    remaining = [source_id for source_id in tflags.get(source_key, [])
                                 if source_id != player.id]
                    if remaining:
                        tflags[source_key] = remaining
                    else:
                        tflags.pop(source_key, None)
                    if not tflags.get("yijue_sources"):
                        tflags.pop("cannot_use_hand", None)
                    if not (tflags.get("yijue_sources") or tflags.get("tieqi_sources")):
                        tflags.pop("nonlocked_disabled", None)
        flags.pop("pao_tokens", None)

    async def before_sha(self, source, target, card, event):
        # 铁骑：判定；目标若不能交同花色牌，则不可闪且伤害+1。
        if (self.has(source, "铁骑") and self.state.deck
                and await self.manager.ask_confirm(
                    source, f"是否对{target.name}发动【铁骑】？", skill_name="铁骑", default=False,
                ) and not self.engine.game_aborted):
            judge = await self.manager.judge(target, "铁骑")
            if judge is None or self.engine.game_aborted:
                return
            target_flags = ensure_flags(target)
            target_flags["nonlocked_disabled"] = True
            sources = target_flags.setdefault("tieqi_sources", [])
            if source.id not in sources:
                sources.append(source.id)
            ensure_flags(source).setdefault("tieqi_targets", []).append(target.id)
            candidates = [c for c in target.hand if c.suit == judge.suit]
            selected = await self.manager.ask_choose_cards(
                target, "可交给铁骑使用者一张与判定牌同花色的手牌",
                candidates, skill_name="铁骑", cancelable=True,
            ) if candidates else []
            if self.engine.game_aborted:
                return
            matching = selected[0] if selected else None
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
        if (source and target and source.id in ensure_flags(target).get("yijue_sources", [])
                and card and card.name == "杀" and card.suit == "heart"):
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
            if (self.has(player, "集智") and await self.manager.ask_confirm(
                    player, "是否发动【集智】摸一张牌？", skill_name="集智", default=False,
                ) and not self.engine.game_aborted):
                drawn = await self.manager.draw_cards(player, 1, "集智")
                if drawn:
                    await self.manager.announce(player, "集智", f"{player.name}发动【集智】摸一张牌")
                    card_drawn = drawn[0]
                    if (card_type_group(card_drawn) == "basic"
                            and await self.manager.ask_confirm(
                                player, f"是否弃置摸到的【{card_drawn.name}】使手牌上限+1？",
                                skill_name="集智", default=False,
                            ) and not self.engine.game_aborted
                            and await self.manager.discard_card(player, card_drawn, "集智")):
                        flags["hand_limit_bonus"] = flags.get("hand_limit_bonus", 0) + 1

    def response_options(self, player, requested_name):
        options = []
        if requested_name == "闪" and self.has(player, "龙胆"):
            for card, index, zone in self.response_card_entries(player):
                if card.name == "杀":
                    options.append({"card": card, "card_index": index, "as_name": "闪", "skill_name": "龙胆", "owner": player, "source_zone": zone})
        if requested_name == "杀":
            if self.has(player, "武圣"):
                for card, index, zone in self.response_card_entries(player):
                    if card.name != "杀" and card_color(card) == "red":
                        options.append({"card": card, "card_index": index, "as_name": "杀", "skill_name": "武圣", "owner": player, "source_zone": zone})
            if self.has(player, "龙胆"):
                for card, index, zone in self.response_card_entries(player):
                    if card.name == "闪":
                        options.append({"card": card, "card_index": index, "as_name": "杀", "skill_name": "龙胆", "owner": player, "source_zone": zone})
            if self.has(player, "激将") and player.identity == "lord":
                for donor in alive_others(self.state, player):
                    if hero_faction(donor) != "shu":
                        continue
                    candidate = next(((card, index, zone) for card, index, zone in self.response_card_entries(donor)
                                      if card.name == "杀"), None)
                    if candidate:
                        card, index, zone = candidate
                        options.append({"card": card, "card_index": index, "as_name": "杀", "skill_name": "激将", "owner": donor, "source_zone": zone})
        if requested_name == "桃" and self.has(player, "龙胆"):
            for card, index, zone in self.response_card_entries(player):
                if card.name == "酒":
                    options.append({"card": card, "card_index": index, "as_name": "桃", "skill_name": "龙胆", "owner": player, "source_zone": zone})
        if requested_name == "酒" and self.has(player, "龙胆"):
            for card, index, zone in self.response_card_entries(player):
                if card.name == "桃":
                    options.append({"card": card, "card_index": index, "as_name": "酒", "skill_name": "龙胆", "owner": player, "source_zone": zone})
        return options

    async def request_jijiang_response(self, lord, first_donor):
        """主公提出激将后，由蜀势力角色逐个自行决定是否供牌。"""
        if not self.has(lord, "激将") or lord.identity != "lord":
            return None
        donors = [p for p in alive_others(self.state, lord) if hero_faction(p) == "shu"]
        if first_donor in donors:
            donors = donors[donors.index(first_donor):] + donors[:donors.index(first_donor)]
        for donor in donors:
            entries = [(card, zone) for card, _index, zone in self.response_card_entries(donor)
                       if card.name == "杀"]
            if not entries:
                continue
            if not await self.manager.ask_confirm(
                donor, f"是否响应{lord.name}的【激将】打出【杀】？",
                skill_name="激将", default=False,
            ) or self.engine.game_aborted:
                continue
            selected = await self.manager.ask_choose_cards(
                donor, "【激将】：选择打出的一张【杀】", [card for card, _zone in entries],
                places=[(donor, zone) for _card, zone in entries],
                skill_name="激将", cancelable=True,
            )
            if self.engine.game_aborted:
                return None
            if selected:
                card = selected[0]
                zone = next((source_zone for candidate, source_zone in entries if candidate is card), None)
                if zone is not None:
                    return {"bool": True, "card": card, "owner": donor,
                            "source_zone": zone, "as_name": "杀", "skill_name": "激将"}
        return None

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
            if lord and await self.manager.ask_confirm(
                responder, f"是否令{lord.name}因【激将】摸一张牌？",
                skill_name="激将", default=False,
            ) and not self.engine.game_aborted:
                mark_once_per_turn(lord, "激将摸牌")
                await self.manager.draw_cards(lord, 1, "激将")
                await self.manager.announce(lord, "激将", f"{responder.name}于回合外打出【杀】，{lord.name}因【激将】摸一张牌")

    async def on_cards_lost(self, player, cards, reason="unknown", *, event=None):
        if (not self.has(player, "涯角") or player is self.state.current_player
                or not self.state.deck or event is None or event.from_zone != "hand"
                or reason not in {"use_card", "respond", "武圣", "龙胆"}):
            return
        if not await self.manager.ask_confirm(
            player, "是否发动【涯角】展示牌堆顶一张牌？",
            skill_name="涯角", default=False,
        ) or self.engine.game_aborted:
            return
        revealed = self.state.deck[0]
        moved = await self.engine.move_card(
            revealed, "deck", "discard", reason="涯角展示",
            actor_id=player.id, visibility="public",
        )
        if moved is None or self.engine.game_aborted:
            return
        await self.manager.announce(player, "涯角", f"{player.name}展示【{revealed.name}】")
        if card_type_group(revealed) == card_type_group(cards[0]):
            recipients = [p for p in self.state.players if p.alive]
            chosen = await self.manager.ask_choose_players(
                player, "【涯角】：选择获得展示牌的角色；可取消",
                recipients, skill_name="涯角", cancelable=True,
            )
            if chosen and not self.engine.game_aborted and revealed in self.state.discard_pile:
                receiver = chosen[0]
                gained = await self.engine.move_card(
                    revealed, "discard", "hand", to_owner=receiver,
                    reason="涯角", actor_id=player.id, visibility="public",
                )
                if gained is not None:
                    await self.manager.on_card_gained(receiver, [revealed], "涯角")
                    await self.manager.announce(player, "涯角", f"{receiver.name}获得【{revealed.name}】")
            return
        candidates = [p for p in self.state.players if p.alive and (p.hand or p.equipment or p.judge_area)
                      and self.manager.modify_distance(p, player, self.state.get_distance(p, player))
                      <= p.get_equipment_range()]
        if not candidates:
            return
        chosen = await self.manager.ask_choose_players(
            player, "【涯角】：选择弃置区域牌的角色；可取消",
            candidates, skill_name="涯角", cancelable=True,
        )
        if self.engine.game_aborted or not chosen:
            return
        target = chosen[0]
        selected = await self.engine.card_system._choose_region_card(
            player, target, f"【涯角】：选择弃置{target.name}区域内的一张牌",
            reason="涯角", exclude_protected=True,
        )
        if self.engine.game_aborted or selected is None:
            return
        card, zone = selected
        if await self.engine.move_card(card, zone, "discard", from_owner=target,
                                       reason="涯角", actor_id=player.id):
            await self.manager.announce(player, "涯角", f"{player.name}弃置{target.name}区域内一张牌")

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
