#!/usr/bin/env python3
"""
卡牌系统 - 基于无名杀架构完整实现
"""

import asyncio
import logging
from typing import List, Callable

from . import card_flow
from .card_table import CARD_TABLE, NO_EXTERNAL_TARGET, card_label, damage_text
from .game_stats import mark_damage_source, pop_kill_credit, record_stat
from .state_manager import Card, card_to_dict


logger = logging.getLogger(__name__)

# 可被无懈可击响应的锦囊（单一来源：CARD_TABLE.wuxie_targetable）。
WUXIEABLE = frozenset(name for name, spec in CARD_TABLE.items() if spec.wuxie_targetable)


def make_pass_option() -> dict:
    """「不响应」候选。任何响应请求的候选列表末项恒为它（唯一定义处）。"""
    return {
        "card": None, "card_index": None, "owner": None,
        "as_name": None, "skill_name": None, "label": "不响应",
    }


SUIT_SYMBOLS = {"spade": "♠", "heart": "♥", "club": "♣", "diamond": "♦"}


def option_label(option: dict) -> str:
    """候选项的可读文案（唯一定义处）：前端面板、AI提示词、托管日志共用。"""
    if option.get("label"):
        return option["label"]
    if option.get("hidden"):
        owner = option.get("owner")
        return f"{getattr(owner, 'name', '其他角色')}可提供【{option.get('as_name') or '响应牌'}】"
    card = option.get("card")
    if card is None:
        return "不响应"
    # 属性杀写成 火【杀】/雷【杀】，AI 与真人都能看出响应牌的属性；普通牌保持原样。
    name_text = card_label(card) if getattr(card, "nature", None) else card.name
    base = f"{SUIT_SYMBOLS.get(getattr(card, 'suit', ''), '')}{getattr(card, 'rank', '')} {name_text}"
    skill = option.get("skill_name")
    if skill:
        return f"{base} →（{skill}）当{option.get('as_name') or card.name}"
    return base


class CardSystem:
    """卡牌系统"""

    def __init__(self, game_state, _event_bus, trigger_manager, ui_notifier=None, responder=None, engine=None):
        self.game_state = game_state
        self.trigger_manager = trigger_manager
        self.ui_notifier = ui_notifier
        # 场外响应决策器，由引擎注入。为 None 时一律视为「不响应」，老调用点不会崩。
        self.responder = responder
        self.engine = engine

    async def on_equipment_left(self, owner, card, move):
        """装备离区后结算白银狮子；死亡清牌不再恢复已死亡角色。"""
        if card.name == "木牛流马":
            # 只有宝物从装备区直接进入另一人的装备区，扣置牌才随之移动。
            recipient = next((p for p in self.game_state.players
                              if p.id == move.to_owner), None) if move.to_zone == "equipment" else None
            for stored in list(owner.treasure_cards):
                await self.engine.move_card(
                    stored, "treasure", "treasure" if recipient else "discard",
                    from_owner=owner, to_owner=recipient,
                    reason="muniu_transfer" if recipient else "muniu_lost",
                    actor_id=owner.id, visibility="owner" if recipient else "public",
                )
        if card.name == "白银狮子" and owner.alive and owner.hp < owner.max_hp:
            owner.hp += 1
            record_stat(self.engine, owner, "healing", 1)
            await self.trigger_manager.on_recover(owner, 1, owner, "白银狮子")

    async def _weapon_confirm(self, player, prompt):
        """可选武器效果由真人决定；AI 在条件成立时使用。"""
        if self.engine is None:
            return False
        return player.is_ai or await self.engine.ask_confirm(player, prompt, default=False)

    async def _weapon_discard_one(self, chooser, owner, reason, *, hand_only=False):
        """从手牌/装备区选择并弃置一张实体牌，供武器代价与寒冰剑共用。"""
        places = [(owner, "hand", card) for card in owner.hand]
        if not hand_only:
            places.extend((owner, "equipment", card) for card in owner.equipment.values())
        if not places:
            return False
        chosen_card = places[0][2]
        if self.engine is not None:
            chosen = await self.engine.ask_choose_cards(
                chooser, f"【{reason}】：选择{owner.name}的一张牌弃置",
                [entry[2] for entry in places], min_n=1, max_n=1,
                zone="mixed", cancelable=False,
                hidden_indices=[i for i, entry in enumerate(places) if entry[1] == "hand" and chooser is not owner],
                places=[(entry[0], entry[1]) for entry in places],
                context={"intent": "discard"},
            )
            if self.engine.game_aborted:
                return False
            if chosen and chosen[0] in [entry[2] for entry in places]:
                chosen_card = chosen[0]
        zone = next(entry[1] for entry in places if entry[2] is chosen_card)
        if self.engine is not None:
            return await self.engine.move_card(
                chosen_card, zone, "discard", from_owner=owner,
                reason=reason, actor_id=chooser.id,
            ) is not None
        if zone == "hand":
            owner.hand.remove(chosen_card)
        else:
            owner.equipment.pop(next(k for k, v in owner.equipment.items() if v is chosen_card))
        self.game_state.discard_pile.append(chosen_card)
        return True

    async def _cixiong_effect(self, source, target):
        """雌雄双股剑在指定异性目标时令其弃手牌或让使用者摸牌。"""
        from .skills_qun import is_male
        if is_male(source) == is_male(target) or not await self._weapon_confirm(
            source, "是否发动【雌雄双股剑】？",
        ):
            return
        discard = bool(target.hand) and (target.is_ai or await self.engine.ask_confirm(
            target, "是否弃一张手牌响应【雌雄双股剑】？否则使用者摸一张牌", default=False,
        ))
        if discard and await self._weapon_discard_one(target, target, "雌雄双股剑", hand_only=True):
            return
        if self.engine is not None and not self.engine.game_aborted:
            await self.trigger_manager.draw_cards(source, 1, "雌雄双股剑")

    async def _follow_up_weapon_on_dodge(self, event):
        """杀被闪抵消后处理贯石斧强制命中与青龙刀追杀。"""
        source, target = event["player"], event["target"]
        if not source.alive or not target.alive or (self.engine and self.engine.game_aborted):
            return
        weapon = getattr(source.equipment.get("weapon"), "name", None)
        if weapon == "贯石斧" and len(source.hand) + len(source.equipment) >= 2:
            if not await self._weapon_confirm(source, "是否弃两张牌发动【贯石斧】？"):
                return
            if (await self._weapon_discard_one(source, source, "贯石斧")
                    and await self._weapon_discard_one(source, source, "贯石斧")):
                await self.damage(source, target, event.get("resolved_base_damage", 1),
                                  card=event["card"], context=event)
        elif weapon == "青龙偃月刀" and await self._weapon_confirm(
            source, "是否发动【青龙偃月刀】再对同一目标使用一张杀？",
        ):
            result = await self.choose_to_respond(
                source, "【青龙偃月刀】：请选择追加的【杀】",
                card_filter=lambda c: c.name == "杀", requested_name="杀",
                context={"source": source, "target": target, "card": event["card"]},
            )
            if await self._consume_response(source, result, "青龙偃月刀", {"target": target}):
                follow = {**event, "card": result["card"], "baseDamage": 1,
                          "nature": getattr(result["card"], "nature", None)}
                await self.trigger_manager.before_sha(source, target, result["card"], follow)
                await self._sha_effect(follow)
                source.sha_count += 1
    
    async def notify_card_to_discard(self, actor, card, reason="use", card_index=None, message=None):
        if not self.ui_notifier:
            return
        shown = card_label(card)
        action_text = {
            "respond": f"[‘{actor.name}’{card.name}！]",
            "discard": f"[‘{actor.name}’弃置‘{card.name}’]",
            "use": f"[‘{actor.name}’{card.name}！]",
            "hand_limit": f"[‘{actor.name}’因手牌上限弃置‘{card.name}’]",
        }.get(reason, f"[‘{actor.name}’{card.name}]")
        await self.ui_notifier(
            actor_id=actor.id,
            actor_name=actor.name,
            source_name=actor.name,
            card_name=card.name,
            card_index=card_index,
            system_text=action_text,
            card=card_to_dict(card),
            reason=reason,
            discard_count=len(self.game_state.discard_pile),
            message=message or f"{actor.name}{'打出' if reason == 'respond' else '弃置'}{shown}",
        )

    # ---------- 行为账本（Stage T · T1）----------

    def _ledger_record(self, source, target, kind, label, weight=None):
        """向 engine.ledger 记一条公开行为；没有引擎 / 账本（单测桩）时什么也不做。"""
        ledger = getattr(self.engine, "ledger", None)
        if ledger is None or source is None or (target is None and kind != "group"):
            return None
        return ledger.record(self.game_state.round_number, source.id,
                             None if target is None else target.id, kind, label, weight)

    def _ledger_record_card(self, player, card, spec, targets) -> List:
        """牌指定目标时按 CARD_TABLE.ledger_kind 记账，返回已记条目（出牌失败时撤销）。

        杀由 use_sha 在目标确定处自己记（要区分流离转移），这里跳过；
        群体牌只记一条不归属的 group；借刀杀人：指使者→最终目标敌意，取武器不带敌意（2026-10-18 用户裁定：可能是借队友的刀打敌人），不记指使者→被借刀者。
        """
        if spec is None or spec.ledger_kind == "none" or spec.resolver == "use_sha" or spec.usage == "response":
            return []
        kind, entries = spec.ledger_kind, []
        if kind == "group":
            entries.append(self._ledger_record(player, None, "group", card.name))
        elif kind == "borrow":
            if targets and len(targets) == 2:
                _weapon_owner, victim = targets  # 被借刀者不入账：取武器是中性的
                entries.append(self._ledger_record(player, victim, "hostile", "借刀"))
        elif kind in ("hostile", "friendly"):
            seen = set()
            for target in targets or []:
                if target.id in seen:
                    continue
                seen.add(target.id)
                entries.append(self._ledger_record(player, target, kind, card.name, spec.ledger_weight))
        return [e for e in entries if e is not None]

    async def use_card(self, player, card: Card, targets: List = None, *, effect_context=None):
        """使用卡牌（统一入口）。分发由 CARD_TABLE 的 resolver/usage 驱动。"""
        if self.engine is not None and self.engine.game_aborted:
            return False
        spec = CARD_TABLE.get(card.name)
        entries = self._ledger_record_card(player, card, spec, targets)
        success = await self._use_card_resolve(player, card, targets, spec, effect_context)
        if not success and entries:
            # 出牌失败时牌会退回手牌，不能留下一条没发生的行为。
            self.engine.ledger.remove(entries)
        return success

    async def _use_card_resolve(self, player, card, targets, spec, effect_context):
        # 延时锦囊先进入判定区，判定阶段生效前才询问无懈。
        group_trick = bool(spec and spec.target_rule.get("type") in ("all", "all_others"))
        delayed_trick = bool(spec and spec.resolver in ("use_bingliang", "use_lebu", "use_shandian"))
        if spec and spec.wuxie_targetable and not group_trick and not delayed_trick:
            wuxie_targets = targets or []
            if await self.ask_wuxie(card, player, wuxie_targets):
                logger.info(f"  → 【{card.name}】被无懈可击抵消")
                return True
            if self.engine is not None and self.engine.game_aborted:
                return False

        if spec and spec.usage == "response":
            logger.info(f"{card.name}只能响应使用")
            return False

        resolver_name = spec.resolver if spec else None
        if resolver_name:
            method = getattr(self, resolver_name)
            if resolver_name == "use_sha":
                return await method(player, card, targets or [],
                                    effect_context=effect_context)
            if resolver_name in ("use_juedou", "use_nanman", "use_wanjian", "use_taoyuan", "use_wugu"):
                if group_trick:
                    return await method(player, card, effect_context=effect_context)
                return await method(player, card, targets[0] if targets else None,
                                    effect_context=effect_context)
            if resolver_name in ("use_tiesuo", "use_jiedao"):
                return await method(player, card, targets if targets else [])
            # 无显式目标的牌（桃/酒/无中生有等，NO_EXTERNAL_TARGET）不传 target 参数；其余单目标。
            if spec.target_rule.get("type") in NO_EXTERNAL_TARGET:
                return await method(player, card)
            return await method(player, card, targets[0] if targets else None)

        logger.info(f"未实现的卡牌: {card.name}")
        return False
    
    async def use_sha(self, player, card: Card, target, *, effect_context=None,
                      _multi_part=False, _wine_bonus=False):
        """使用杀（完整流程）"""
        if isinstance(target, list):
            if len(target) == 1:
                target = target[0]
            elif (not 2 <= len(target) <= 3
                  or getattr(player.equipment.get("weapon"), "name", None) != "方天画戟"
                  or not getattr(effect_context, "last_hand_card", False)
                  or len({p.id for p in target}) != len(target)):
                return False
            else:
                # 同一张杀按目标顺序结算；酒增伤覆盖所有目标，次数只计一次。
                wine_bonus = bool(getattr(player, "jiu_buff", False))
                player.jiu_buff = False
                for victim in target:
                    # 第一名目标可能触发即时胜负；对局结束后不可继续结算后续目标。
                    if self.game_state.game_over:
                        break
                    if self.engine is not None and self.engine.game_aborted:
                        return False
                    await self.use_sha(player, card, victim, effect_context=effect_context,
                                       _multi_part=True, _wine_bonus=wine_bonus)
                player.sha_count += 1
                return True
        if not target:
            logger.info("杀需要指定目标")
            return False
        
        # 1. 检查距离
        distance = self.game_state.get_distance(player, target)
        weapon_range = player.get_equipment_range()
        
        distance = self.trigger_manager.modify_distance(player, target, distance)
        if not (getattr(card, "ignore_distance", False) or self.trigger_manager.ignore_distance(player, card)) and distance > weapon_range:
            logger.info(f"距离不够：{distance} > {weapon_range}")
            return False
        
        # 2. 检查出杀次数
        unlimited = getattr(player.equipment.get("weapon"), "name", None) == "诸葛连弩"
        if not _multi_part and not unlimited and player.sha_count >= player.max_sha:
            logger.info(f"本回合已使用{player.sha_count}次杀")
            return False
        
        # 3. 技能可转移目标（如流离）。指定目标即记敌意（对流离，记的是原杀来源→大乔）。
        self._ledger_record(player, target, "hostile", "杀")
        target = await self.trigger_manager.before_card_target(player, target, card)
        if not target:
            return False
        weapon_name = getattr(player.equipment.get("weapon"), "name", None)
        if weapon_name == "雌雄双股剑":
            await self._cixiong_effect(player, target)
            if self.engine is not None and self.engine.game_aborted:
                return False
        if effect_context is None and self.engine is not None:
            effect_context = self.engine._new_effect_context(player, card, target=target)
        if effect_context is not None:
            effect_context.current_target_id = target.id
            effect_context.damage_nature = card.nature
        event = {
            'name': 'useCard',
            'card': card,
            'player': player,
            'target': target,
            'baseDamage': 1,
            'shanRequired': 1,
            'nature': card.nature,
            'effect_context': effect_context,
            'wine_bonus': _wine_bonus,
        }
        # 青釭剑只在本次杀的目标结算中忽略防具；朱雀羽扇转化普通杀的属性。
        event["ignore_armor"] = weapon_name == "青釭剑"
        if weapon_name == "朱雀羽扇" and not event["nature"] and card.name == "杀":
            event["nature"] = "fire"
            await self._notify_gain(f"{player.name}的【朱雀羽扇】发动：普通【杀】视为火【杀】")
        
        # 5. 技能修正目标、响应数和伤害后执行杀的效果
        await self.trigger_manager.before_sha(player, target, card, event)
        success = await self._sha_effect(event)
        
        # 6. 增加出杀计数
        if success and not _multi_part:
            player.sha_count += 1
        
        return success
    
    async def _sha_effect(self, event):
        """杀的效果（参考无名杀）"""
        player = event['player']
        target = event['target']
        base_damage = event['baseDamage']
        # 酒杀：伤害+1
        if event.get("wine_bonus") or (hasattr(player, 'jiu_buff') and player.jiu_buff):
            base_damage += 1
            player.jiu_buff = False
            logger.info(f"  → 酒杀！伤害+1，总计{base_damage}点")
        event["resolved_base_damage"] = base_damage
        shan_required = event['shanRequired']
        armor = None if event.get("ignore_armor") else getattr(target.equipment.get("armor"), "name", None)
        if armor == "仁王盾" and event["card"].suit in ("spade", "club"):
            return True
        if armor == "藤甲" and not event.get("nature"):
            return True
        
    #     logger.info(f"  → 目标: {target.name}")
        
        # 1. 要求打出闪
        shaned = False
        for i in range(shan_required):
            logger.info(f"  → 要求出闪 ({i+1}/{shan_required})")
            
            result = await self.choose_to_respond(
                target,
                (f"{player.name}对你使用【杀】，请打出【闪】（共需 {shan_required} 张，第 {i+1} 张）"
                 if shan_required > 1 else f"{player.name}对你使用【杀】，是否打出【闪】？"),
                card_filter=lambda c: c.name == '闪',
                requested_name='闪',
                context={'source': player, 'target': target, 'card': event['card'],
                         'ignore_armor': event.get('ignore_armor', False)}
            )
            if self.engine is not None and self.engine.game_aborted:
                return False
            
            # 杀/决斗/群体锦囊共用实体响应消费，失效候选不能算成功闪避。
            if await self._consume_response(
                target, result, "杀",
                {"source": player, "target": target, "card": event["card"],
                 "effect_context": event.get("effect_context")},
            ):
                shaned = True
            else:
                logger.info(f"  → {target.name} 没有闪")
                shaned = False
                break
        
        # 2. 判断结果
        if shaned:
            # 闪避成功
        #     logger.info(f"  ✓ 闪避成功")
            await self.trigger_manager.on_sha_dodged(player, target, event['card'], event)
            await self._follow_up_weapon_on_dodge(event)
            return True
        else:
            # 造成伤害
        #     logger.info(f"  ✗ 造成 {base_damage} 点伤害")
            effect_context = event.get("effect_context")
            if effect_context is not None:
                effect_context.current_target_id = target.id
                effect_context.next_sequence()
                event["sequence"] = effect_context.sequence
                event["effect"] = effect_context.to_dict()
            # 古锭刀在目标没有手牌的伤害结算点增加伤害。
            if getattr(player.equipment.get("weapon"), "name", None) == "古锭刀" and not target.hand:
                base_damage += 1
            await self.damage(player, target, base_damage, card=event['card'], context=event)
            return True
    
    async def use_tao(self, player, card: Card):
        """使用桃"""
        if player.hp >= player.max_hp:
            logger.info("体力已满")
            return False
        
        logger.info(f"  → {player.name} 回复1点体力")
        before_hp = player.hp
        player.hp = min(player.hp + 1, player.max_hp)
        if player.hp > before_hp:
            record_stat(self.engine, player, "healing", player.hp - before_hp)
            await self.trigger_manager.on_recover(player, player.hp - before_hp, player, "桃")
        
        return True

    # ---------- 区域选牌（过河拆桥 / 顺手牵羊共用） ----------

    REGION_SLOTS = ("weapon", "armor", "plus_horse", "minus_horse", "treasure")

    def _region_card_entries(self, target, exclude_protected=False) -> List:
        """目标区域的候选清单：(牌, 区域, 是否对选择者隐藏)。

        与数据世界书口径一致：手牌、装备、判定区；手牌隐藏身份，其余明牌。
        """
        entries = [(card, "hand", True) for card in target.hand]
        for slot in self.REGION_SLOTS:
            card = target.equipment.get(slot)
            if not card:
                continue
            if exclude_protected and self.trigger_manager.protect_card(target, card, "other_discard_equipment"):
                continue
            entries.append((card, "equipment", False))
        for card in list(getattr(target, "judge_area", [])):
            entries.append((card, "judge", False))
        return entries

    def _fallback_region_card(self, target):
        """无引擎（老调用点）/候选为空时的确定性兜底：手牌 → 装备 → 判定区。"""
        entries = self._region_card_entries(target)
        if not entries:
            return None
        card, zone, _hidden = entries[0]
        return card, zone

    async def _choose_region_card(self, chooser, target, prompt, *, reason, exclude_protected=False):
        """真人/AI 共用的区域选牌：不可取消，超时/离席落规则托管，复核由引擎完成。"""
        if self.engine is None:
            return None
        entries = self._region_card_entries(target, exclude_protected=exclude_protected)
        if not entries:
            return None
        candidates = [card for card, _zone, _hidden in entries]
        hidden = [i for i, (_card, _zone, is_hidden) in enumerate(entries) if is_hidden]
        places = [(target, zone) for _card, zone, _hidden in entries]
        chosen = await self.engine.ask_choose_cards(
            chooser, prompt, candidates, min_n=1, max_n=1, zone="mixed",
            cancelable=False, hidden_indices=hidden, places=places,
            context={"target": target, "reason": reason,
                     "intent": "gain" if reason == "顺手牵羊" else "discard"},
        )
        if not chosen:
            return None
        card = chosen[0]
        zone = next((zone for entry_card, zone, _hidden in entries if entry_card is card), None)
        if zone is None:
            return None
        return card, zone

    def _region_remove(self, target, card, zone):
        """从声明牌区移除一张牌；返回 (是否移除, 手牌原位置)。"""
        if zone == "hand":
            if card not in target.hand:
                return False, None
            index = target.hand.index(card)
            target.hand.remove(card)
            return True, index
        if zone == "equipment":
            slot = next((s for s, value in target.equipment.items() if value is card), None)
            if slot is None:
                return False, None
            target.equipment.pop(slot)
            return True, None
        if zone == "judge":
            if card not in getattr(target, "judge_area", []):
                return False, None
            target.judge_area.remove(card)
            return True, None
        return False, None

    async def _notify_gain(self, message):
        """可选的引擎日志通知；测试替身与未注入引擎的调用点静默跳过。"""
        notifier = getattr(self.engine, "log_event", None)
        if notifier is None:
            return
        result = notifier(message)
        if asyncio.iscoroutine(result):
            await result

    def _record_played(self, player, count=1):
        record_stat(self.engine, player, "cards_played", count)

    async def use_guohe(self, player, card: Card, target):
        """使用过河拆桥：由使用者选择目标区域（手牌/装备/判定区）的一张牌弃置。"""
        if not target:
            logger.info("过河拆桥需要指定目标")
            return False
        
        target = await self.trigger_manager.before_card_target(player, target, card)
        if target and getattr(target, "flags", {}).pop("qianxun_cancelled_card", None) == card.id:
            return True
        if not target or (not target.hand and not target.equipment and not target.judge_area):
            logger.info("目标没有牌")
            return False

        chosen = await self._choose_region_card(
            player, target, f"【过河拆桥】：请选择弃置{target.name}的一张牌",
            reason="过河拆桥", exclude_protected=True,
        )
        if self.engine is not None and self.engine.game_aborted:
            return False
        if chosen is None:
            chosen = self._fallback_region_card(target)
        if chosen is None:
            logger.info("目标没有可弃置的牌")
            return False
        discarded, zone = chosen
        if zone == "equipment" and self.trigger_manager.protect_card(target, discarded, "other_discard_equipment"):
            logger.info(f"  → {target.name}的装备受技能保护，不能被弃置")
            return True
        discarded_index = target.hand.index(discarded) if zone == "hand" and discarded in target.hand else None
        if self.engine is not None:
            removed = await self.engine.move_card(
                discarded, zone, "discard", from_owner=target,
                reason="过河拆桥", actor_id=player.id,
            ) is not None
        else:
            removed, _ = self._region_remove(target, discarded, zone)
            if removed:
                self.game_state.discard_pile.append(discarded)
        if not removed:
            logger.info(f"  ❌ 过河拆桥复核失败：【{discarded.name}】已不在{target.name}的区域")
            return False
        logger.info(f"  → {target.name} 弃置 {discarded}（{zone}）")
        await self.notify_card_to_discard(
            target, discarded, reason="discard", card_index=discarded_index,
            message=f"{target.name}因【过河拆桥】弃置【{discarded.name}】"
        )
        # 判定区牌不是目标自己的资源：只走弃牌展示，不计失去牌。
        if zone != "judge" and self.engine is None:
            await self.trigger_manager.on_cards_lost(target, [discarded], "过河拆桥")
        await self.trigger_manager.on_card_discarded(target, discarded, "过河拆桥")
        return True

    async def use_shunshou(self, player, card: Card, target):
        """顺手牵羊：由使用者选择目标区域（手牌/装备/判定区）的一张牌获得。"""
        if not target or (not target.hand and not target.equipment and not target.judge_area):
            return False
        target = await self.trigger_manager.before_card_target(player, target, card)
        if target and getattr(target, "flags", {}).pop("qianxun_cancelled_card", None) == card.id:
            return True
        if not target or (not target.hand and not target.equipment and not target.judge_area):
            return False

        chosen = await self._choose_region_card(
            player, target, f"【顺手牵羊】：请选择获得{target.name}的一张牌", reason="顺手牵羊",
        )
        if self.engine is not None and self.engine.game_aborted:
            return False
        if chosen is None:
            chosen = self._fallback_region_card(target)
        if chosen is None:
            return False
        gained, zone = chosen
        if self.engine is not None:
            removed = await self.engine.move_card(
                gained, zone, "hand", from_owner=target, to_owner=player,
                reason="顺手牵羊", actor_id=player.id, visibility="owner",
            ) is not None
        else:
            removed, _index = self._region_remove(target, gained, zone)
            if removed:
                player.hand.append(gained)
        if not removed:
            logger.info(f"  ❌ 顺手牵羊复核失败：【{gained.name}】已不在{target.name}的区域")
            return False
        logger.info(f"  → {player.name} 获得 {target.name} 的{gained}（{zone}）")
        # 判定区牌不是目标自己的资源：不计失去牌。
        if zone != "judge" and self.engine is None:
            await self.trigger_manager.on_cards_lost(target, [gained], "顺手牵羊")
        await self.trigger_manager.on_card_gained(player, [gained], "顺手牵羊")
        # 真人参与时明牌告知获得的牌；纯 AI 之间保持隐藏信息不落地到日志。
        if not player.is_ai or not target.is_ai:
            await self._notify_gain(f"{player.name}对{target.name}使用【顺手牵羊】，获得一张【{gained.name}】")
        return True
    
    def build_response_options(self, player, card_filter: Callable, requested_name=None) -> List[dict]:
        """引擎侧算出全部合法响应候选：手牌直接打出 + 技能转化。末项恒为「不响应」。"""
        hand_blocked = bool(getattr(player, "flags", {}).get("cannot_use_hand"))
        options: List[dict] = []
        seen = set()

        if not hand_blocked:
            for index, card in enumerate(player.hand):
                if not card_filter(card):
                    continue
                key = (card.id, card.name, None)
                if key in seen:
                    continue
                seen.add(key)
                options.append({
                    "card": card, "card_index": index, "owner": player,
                    "as_name": card.name, "skill_name": None,
                })
        if getattr(player.equipment.get("treasure"), "name", None) == "木牛流马":
            for index, card in enumerate(player.treasure_cards):
                if card_filter(card):
                    options.append({
                        "card": card, "card_index": len(player.hand) + index,
                        "owner": player, "source_zone": "treasure",
                        "as_name": card.name, "skill_name": None,
                    })

        skill_options = self.trigger_manager.response_options(player, requested_name) if requested_name else []
        for option in skill_options:
            card = option.get("card")
            if card is None:
                continue
            owner = option.get("owner") or player
            as_name = option.get("as_name") or card.name
            # 同一张牌既能直接打出又能技能转化时两项都留，靠 skill_name 区分（R5）。
            key = (card.id, as_name, option.get("skill_name"))
            if key in seen:
                continue
            seen.add(key)
            card_index = option.get("card_index")
            if card_index is None and card in owner.hand:
                card_index = owner.hand.index(card)
            options.append({
                "card": card, "card_index": card_index, "owner": owner,
                "as_name": as_name, "skill_name": option.get("skill_name"),
                # 转化选项必须保留原牌区，消费时才能移动正确的实体牌。
                "source_zone": option.get("source_zone", "hand"),
                "hidden": owner is not player,
            })

        if not options:
            return []
        options.append(make_pass_option())
        return options

    async def choose_to_respond(self, player, prompt: str, card_filter: Callable,
                                requested_name=None, context=None, kind="respond"):
        """选择响应（核心方法）：引擎算候选 → 真人或AI从候选里挑 → 引擎复核后返回。"""
        if (requested_name == "闪" and self.engine is not None
                and not (context or {}).get("ignore_armor")
                and getattr(player.equipment.get("armor"), "name", None) == "八卦阵"
                and self.game_state.deck):
            # 八卦阵先判定；失败后仍可使用手牌中的闪。
            activate = player.is_ai or await self.engine.ask_confirm(
                player, "是否发动【八卦阵】判定？", default=False,
            )
            if activate:
                judged = await self.trigger_manager.judge(player, "八卦阵")
                if judged is not None and judged.suit in ("heart", "diamond"):
                    return {"bool": True, "virtual": True,
                            "card": Card(f"bagua:{judged.id}", "闪", judged.suit, judged.rank, "basic"),
                            "as_name": "闪", "owner": player}
        options = self.build_response_options(player, card_filter, requested_name)
        if not options:
            asked = f"【{requested_name}】" if requested_name else "符合条件的牌"
            logger.info(f"  → {player.name} 没有{asked}")
            return {'bool': False}
        if self.responder is None:
            return {'bool': False}

        request = {
            "kind": kind,
            "prompt": prompt,
            "requested_name": requested_name,
            "options": options,
            "context": context or {},
        }
        result = await self.responder(player, request)
        if result and result.get("bool") and result.get("skill_name") == "激将":
            offered = await self.trigger_manager.request_lord_sha(player, result.get("owner"))
            if offered and not (self.engine and self.engine.game_aborted):
                return offered
            # 供牌者都拒绝后，主公仍可选择自己的合法响应牌。
            own_options = [option for option in options if option.get("skill_name") != "激将"]
            if any(option.get("card") is not None for option in own_options):
                return await self.responder(player, {**request, "options": own_options})
            return {"bool": False}
        return result

    _USER_UNSET = object()

    async def ask_wuxie(self, card, source, targets=None, *, trick_user=_USER_UNSET) -> bool:
        """询问无懈可击链，返回 True 表示当前锦囊最终被无懈。

        不设人为深度上限：每层必须真实消耗一张无懈，标准牌堆总数保证终止。
        每层询问顺序从上一层响应者之后开始，允许无懈打无懈。
        """
        players = list(self.game_state.players)
        if source not in players:
            return False
        current_source = source
        canceled = False
        layer = 0
        while True:
            layer += 1
            start = players.index(current_source)
            responders = [players[(start + offset) % len(players)] for offset in range(1, len(players))]
            responded = False
            for responder in responders:
                if not responder.alive:
                    continue
                result = await self.choose_to_respond(
                    responder,
                    f"{current_source.name}使用【{card.name}】，是否使用【无懈可击】？",
                    card_filter=lambda c: c.name == '无懈可击',
                    requested_name='无懈可击',
                    # 被抵消的锦囊名、当前是第几层无懈都是公开信息，AI 据此判断该不该拦。
                    context={"source": current_source, "card_source": source, "targets": targets or [], "card": card,
                             "card_name": card.name, "layer": layer},
                    kind="wuxie",
                )
                if not (result and result.get("bool")):
                    continue
                owner = result.get("owner") or responder
                response_card = result.get("card")
                source_zone = result.get("source_zone", "hand")
                source_cards = owner.treasure_cards if source_zone == "treasure" else owner.hand
                if response_card is None or response_card not in source_cards:
                    raise AssertionError("无懈响应已确认，但响应牌未在提供者的合法牌区中")
                # 无懈链每层也只提交一条响应牌移动事实。
                consumed = await self._consume_response(
                    responder, result, "wuxie",
                    {"source": current_source, "targets": targets or [],
                     "card": card, "wuxie_layer": layer},
                )
                if not consumed:
                    return canceled
                if response_card in source_cards:
                    raise AssertionError("无懈响应消费后仍留在原牌区")
                responded = True
                # 无懈链逐层记受益者：奇数层抵消锦囊，保护原目标；偶数层抵消上一层无懈，等于帮锦囊使用者。
                # 无目标的锦囊（无中生有等）没有「被保护者」，不记。
                # 判定阶段的延时锦囊 source 是被判定者，偶数层的受益者要由调用方给出 trick_user
                # （查不到使用者就传 None：不记，不猜）。
                if layer % 2 == 1:
                    beneficiaries = targets or []
                elif trick_user is self._USER_UNSET:
                    beneficiaries = [source]
                else:
                    beneficiaries = [trick_user] if trick_user is not None else []
                for beneficiary in beneficiaries:
                    self._ledger_record(owner, beneficiary, "protect", "无懈保护")
                current_source = responder
                canceled = not canceled
                break
            if not responded:
                return canceled

    async def damage(self, source, target, amount: int, card=None, context=None):
        """造成伤害"""
        if (self.engine is not None and self.engine.game_aborted) or not target.alive:
            return
        context = context or {}
        nature = context.get("nature") or getattr(card, "nature", None)
        armor = None if context.get("ignore_armor") else getattr(target.equipment.get("armor"), "name", None)
        # 防具在伤害修正前结算，后续技能仍可对修正值继续处理。
        if armor == "藤甲" and nature == "fire":
            amount += 1
        if armor == "白银狮子":
            amount = min(amount, 1)
        if (source is not None and source is not target and card is not None
                and card.name == "杀" and not context.get("chain_transfer")
                and getattr(source.equipment.get("weapon"), "name", None) == "寒冰剑"
                and (target.hand or target.equipment)
                and await self._weapon_confirm(source, "是否发动【寒冰剑】防止伤害并弃置目标两张牌？")):
            for _ in range(2):
                if not await self._weapon_discard_one(source, target, "寒冰剑"):
                    break
            return
        # 同一次属性伤害共享已访问集合；每名横置角色最多承受一次传导。
        chain_visited = context.setdefault("_chain_visited", set()) if nature in ("fire", "thunder") else None
        if chain_visited is not None and target.id in chain_visited:
            return
        damage_info = {
            'source': source,
            'target': target,
            'amount': amount,
            'prevented': False
        }
        
        # 技能可修正伤害值。
        amount = await self.trigger_manager.modify_damage(source, target, amount, card, context)
        if self.engine is not None and self.engine.game_aborted:
            return
        damage_info['amount'] = amount
        # 造成伤害
        if not damage_info['prevented'] and amount > 0:
            if chain_visited is not None:
                chain_visited.add(target.id)
            # 先记录待传导座次再重置当前横置状态，防止伤害钩子重入形成环。
            propagate = bool(chain_visited is not None and target.chained)
            chain_targets = []
            if propagate:
                # 传导从当前回合角色起按座次依次结算（跳过原目标），而不是按玩家列表下标。
                seats = self.game_state.players
                current = self.game_state.current_player
                start = seats.index(current) if current in seats else 0
                chain_targets = [p for offset in range(len(seats))
                                 if (p := seats[(start + offset) % len(seats)]) is not target
                                 and p.alive and p.chained]
            if propagate:
                target.chained = False
            target.hp -= amount
            # 统计按修正后的最终伤害值计；自伤（如闪电）只记受到伤害，不记造成伤害。
            record_stat(self.engine, target, "damage_taken", amount)
            if source is not None and source is not target:
                record_stat(self.engine, source, "damage_dealt", amount)
            mark_damage_source(self.game_state, target, source)
            logger.info(f"  → {target.name} 体力: {target.hp}/{target.max_hp}")
            # 战报：写明属性与来源；铁索传导的伤害单独标注。
            dealer = f"（{source.name}造成）" if source is not None and source is not target else ""
            via = "（铁索连环传导）" if context.get("chain_transfer") else ""
            await self._notify_gain(f"{target.name}受到{damage_text(amount, nature)}{dealer}{via}，体力{target.hp}/{target.max_hp}")
            
            await self.trigger_manager.after_damage(source, target, amount, card, context)
            if self.engine is not None and self.engine.game_aborted:
                return
            if (source is not None and source is not target and card is not None
                    and card.name == "杀" and not context.get("chain_transfer")
                    and getattr(source.equipment.get("weapon"), "name", None) == "麒麟弓"):
                mounts = [target.equipment.get(slot) for slot in ("plus_horse", "minus_horse")
                          if target.equipment.get(slot) is not None]
                if mounts and await self._weapon_confirm(source, "是否发动【麒麟弓】弃置目标坐骑？"):
                    chosen = mounts[0]
                    if len(mounts) > 1 and self.engine is not None:
                        # 两匹马都在时由麒麟弓持有者选择弃哪一匹（坐骑是明牌）。
                        picked = await self.engine.ask_choose_cards(
                            source, f"【麒麟弓】：选择弃置{target.name}的一匹坐骑",
                            mounts, min_n=1, max_n=1, zone="equipment",
                            cancelable=False,
                            places=[(target, "equipment") for _ in mounts],
                            context={"intent": "discard"},
                        )
                        if self.engine.game_aborted:
                            return
                        if picked and picked[0] in mounts:
                            chosen = picked[0]
                    if self.engine is not None:
                        await self.engine.move_card(chosen, "equipment", "discard",
                                                    from_owner=target, reason="麒麟弓", actor_id=source.id)
                    else:
                        target.equipment.pop(next(k for k, v in target.equipment.items() if v is chosen))
                        self.game_state.discard_pile.append(chosen)
            
            # 检查濒死
            if target.hp <= 0:
                await self.enter_dying(target)
            # 传导的是已结算的伤害值；每个后续目标仍各自经过减伤/增伤钩子。
            for chained_target in chain_targets:
                if self.engine is not None and self.engine.game_aborted:
                    return
                if chained_target.alive and chained_target.chained:
                    await self.damage(
                        source, chained_target, amount, card=card,
                        context={**context, "nature": nature, "_chain_visited": chain_visited,
                                 "chain_transfer": True},
                    )
    
    async def enter_dying(self, player):
        """濒死求桃：按座次逐个询问存活角色，每人都可以拒绝。"""
        if self.engine is not None and self.engine.game_aborted:
            return
        logger.info(f"  ⚠️ {player.name} 进入濒死状态！HP:{player.hp}")
        on_dying = getattr(self.engine, "on_player_dying", None)
        if callable(on_dying):
            on_dying(player)
        while player.hp <= 0:
            if self.engine is not None and self.engine.game_aborted:
                return
            rescued = False
            # 从濒死者起按座次轮询，不能固定从玩家列表的 0 号位开始。
            seats = self.game_state.players
            start = seats.index(player)
            rescuers = [p for offset in range(len(seats))
                        if (p := seats[(start + offset) % len(seats)]).alive]
            for rescuer in rescuers:
                prompt = (
                    "你已濒死，是否使用【桃】自救？" if rescuer is player
                    else f"{player.name}濒死，是否使用【桃】救援？"
                )
                result = await self.choose_to_respond(
                    rescuer, prompt,
                    card_filter=lambda c: c.name == '桃',
                    requested_name='桃',
                    context={'target': player, 'source': rescuer},
                    kind='dying',
                )
                if self.engine is not None and self.engine.game_aborted:
                    return
                if not (result and result.get('bool')):
                    continue
                card = result.get('card')
                owner = result.get('owner') or rescuer
                source_zone = result.get("source_zone", "hand")
                source_cards = owner.treasure_cards if source_zone == "treasure" else owner.hand
                if not card or card not in source_cards:
                    continue
                if not await self._consume_response(
                    rescuer, result, "dying_rescue", {"target": player, "owner": owner},
                ):
                    continue
                if self.engine is not None and self.engine.game_aborted:
                    return
                player.hp += 1
                record_stat(self.engine, owner, "healing", 1)
                # 治疗归属与统计一致：记给实际提供桃的角色（owner），不是被询问者。
                await self.trigger_manager.on_recover(player, 1, owner, 'dying_rescue')
                logger.info(f"  🍑 {owner.name}救援{player.name}，体力回复至{player.hp}")
                # 救援是最强的站队信号（高权重）；自救不记，「没救」更不记。
                self._ledger_record(owner, player, "friendly", "救援", 3.0)
                rescued = True
                break
            if not rescued:
                break
        if player.hp <= 0:
            if self.engine is not None and self.engine.game_aborted:
                return
            player.alive = False
            # 官方规则阵亡亮明身份；开局选了“阵亡暗置”则保持隐藏（奖惩仍按真实身份结算）。
            if not getattr(self.engine, "hide_dead_identity", False):
                player.identity_revealed = True
            on_death = getattr(self.engine, "on_player_death", None)
            if callable(on_death):
                on_death(player)
                push = getattr(self.engine, "push_notes_after_death", None)
                if callable(push):
                    await push()
            killer_id = pop_kill_credit(self.game_state, player)
            killer = next((p for p in self.game_state.players if p.id == killer_id), None)
            if killer is not None:
                record_stat(self.engine, killer, "kills")
            logger.info(f"  💀 {player.name} 阵亡，身份揭示为 {player.identity}")
            await self._discard_player_zones(player, "death")
            if self.engine is not None and self.engine.game_aborted:
                return
            await self._settle_identity_death(player, killer)

    async def _discard_player_zones(self, player, reason, *, include_judge=True):
        """死亡/主公误杀惩罚共用清牌；每张实体只从其真实牌区移动一次。"""
        zones = [("hand", list(player.hand)), ("equipment", list(player.equipment.values()))]
        if include_judge:
            zones.extend((("judge", list(player.judge_area)),
                          ("shown", list(player.shown)), ("temporary", list(player.temporary)),
                          ("treasure", list(player.treasure_cards))))
        for zone, cards in zones:
            for card in cards:
                if self.engine is not None:
                    moved = await self.engine.move_card(
                        card, zone, "discard", from_owner=player,
                        reason=reason, actor_id=player.id,
                    )
                    if moved is None:
                        continue
                else:
                    container = player.equipment if zone == "equipment" else (
                        player.judge_area if zone == "judge" else (
                            player.treasure_cards if zone == "treasure" else getattr(player, zone))
                    )
                    if zone == "equipment":
                        slot = next((key for key, value in container.items() if value is card), None)
                        if slot is None:
                            continue
                        del container[slot]
                    else:
                        container.remove(card)
                    self.game_state.discard_pile.append(card)
                    if zone in ("hand", "equipment"):
                        await self.trigger_manager.on_cards_lost(player, [card], reason)

    async def _settle_identity_death(self, victim, killer):
        """身份奖惩在阵亡清牌之后结算，胜负紧接着检查。"""
        if killer is not None and killer.alive and victim.identity == "rebel":
            if self.engine is not None and hasattr(self.engine, "draw_cards"):
                drawn = await self.engine.draw_cards(killer, 3, "kill_rebel_reward")
            else:
                drawn = []
                for _ in range(3):
                    if not self.game_state.refill_deck_if_empty():
                        break
                    killer.hand.append(self.game_state.deck.pop(0))
                    drawn.append(killer.hand[-1])
            if drawn:
                await self.trigger_manager.on_card_gained(killer, drawn, "kill_rebel_reward")
            logger.info(f"  → {killer.name} 击杀反贼，摸 {len(drawn)} 张牌")
        elif killer is not None and killer.alive and killer.identity == "lord" and victim.identity == "loyalist":
            logger.info(f"  → {killer.name}误杀忠臣，弃置所有牌")
            await self._discard_player_zones(killer, "lord_killed_loyalist", include_judge=False)

        from .identity_system import IdentitySystem
        victory = IdentitySystem.check_victory(self.game_state.players)
        if victory.get("game_over"):
            self.game_state.game_over = True
            self.game_state.winner = victory["winner"]
            self.game_state.end_message = victory["message"]
            if self.engine is not None:
                await self.engine.log_event(victory["message"], important=True)

    async def use_jiu(self, player, card: Card):
        """使用酒"""
        # 检查本回合是否已经使用过酒（非濒死情况）
        if hasattr(player, 'jiu_used_this_turn') and player.jiu_used_this_turn:
            logger.info("本回合已使用过酒")
            return False
        
        # 标记酒效果：下一张杀伤害+1
        player.jiu_buff = True
        player.jiu_used_this_turn = True
        logger.info(f"  → {player.name} 使用【酒】，下一张杀伤害+1")
        
        return True
    
    async def use_tiesuo(self, player, card: Card, targets: List):
        """使用铁索连环"""
        if not targets or len(targets) == 0:
            logger.info("铁索连环需要指定1-2个目标")
            return False
        
        if len(targets) > 2:
            targets = targets[:2]
        
        for target in targets:
            # 切换横置状态
            target.chained = not getattr(target, 'chained', False)
            status = "横置" if target.chained else "重置"
            logger.info(f"  → {target.name} {status}")
        
        return True

    async def _use_delayed_trick(self, player, card: Card, target):
        """延时锦囊共用结算：放入目标判定区。"""
        if not target or target == player:
            logger.info(f"{card.name}需要指定其他角色")
            return False
        if any(existing.name == card.name for existing in target.judge_area):
            logger.info(f"{target.name}判定区已有【{card.name}】")
            return False

        # 放入目标判定区
        if not hasattr(target, 'judge_area'):
            target.judge_area = []

        # 实体牌在 execute_action 中先移到弃牌区，再原子移入判定区。
        if self.engine is not None and card in self.game_state.discard_pile:
            move = await self.engine.move_card(
                card, "discard", "judge", to_owner=target,
                reason="place_delayed_trick", actor_id=player.id,
            )
            if move is None:
                return False
        else:
            target.judge_area.append(card)
        logger.info(f"  → {target.name} 判定区增加【{card.name}】")

        return True

    async def use_bingliang(self, player, card: Card, target):
        """使用兵粮寸断（延时锦囊）"""
        return await self._use_delayed_trick(player, card, target)

    async def use_lebu(self, player, card: Card, target):
        """使用乐不思蜀（延时锦囊）"""
        return await self._use_delayed_trick(player, card, target)
    
    async def use_wuzhongshengyou(self, player, card: Card):
        """使用无中生有"""
        # 摸2张牌
        if self.engine is not None and hasattr(self.engine, "draw_cards"):
            drawn = await self.engine.draw_cards(player, 2, "无中生有")
        else:
            drawn = self.game_state.draw_card(player, 2)

        if drawn:
            logger.info(f"  → {player.name} 摸了{len(drawn)}张牌")
            await self.trigger_manager.on_card_gained(player, drawn, "无中生有")

        return True

    async def _consume_response(self, responder, result, reason, context):
        """Move one validated response card exactly once and notify its hooks."""
        if not result or not result.get("bool") or (self.engine and self.engine.game_aborted):
            return False
        if result.get("virtual"):
            # 八卦阵视为打出闪，判定牌本身已经处理，不再消费手牌实体。
            await self.trigger_manager.on_card_responded(
                responder, result["card"], result.get("as_name") or "闪",
                {**context, "owner": responder},
            )
            return True
        card = result.get("card")
        owner = result.get("owner") or responder
        source_zone = result.get("source_zone", "hand")
        source_cards = owner.treasure_cards if source_zone == "treasure" else owner.hand
        if card is None or card not in source_cards:
            return False
        index = source_cards.index(card)
        if self.engine is not None:
            move = await self.engine.move_card(
                card, source_zone, "discard", from_owner=owner,
                reason="respond", actor_id=owner.id,
                effect_id=getattr(context.get("effect_context"), "effect_id", None),
            )
            if move is None:
                return False
        else:
            source_cards.remove(card)
            self.game_state.discard_pile.append(card)
            await self.trigger_manager.on_cards_lost(owner, [card], reason)
        await self.notify_card_to_discard(owner, card, "respond", index,
                                          f"{owner.name}打出{card_label(card, name=result.get('as_name'))}响应{reason}")
        self._record_played(owner)
        await self.trigger_manager.on_card_discarded(owner, card, reason)
        await self.trigger_manager.on_card_responded(
            responder, card, result.get("as_name") or card.name,
            {**context, "owner": owner},
        )
        return True

    def _effect_context(self, source, card, target=None, existing=None):
        if existing is not None:
            return existing
        if self.engine is not None:
            return self.engine._new_effect_context(source, card, target=target)
        return None

    async def use_juedou(self, player, card: Card, target, *, effect_context=None):
        return await self.resolve_duel(player, target, card, effect_context=effect_context)

    async def resolve_duel(self, source, target, card: Card, *, effect_context=None, reason="决斗"):
        """One duel resolver for physical and skill-created duels."""
        if not target or not source.alive or not target.alive:
            return False
        target = await self.trigger_manager.before_card_target(source, target, card)
        if not target or not target.alive:
            return False
        effect_context = self._effect_context(source, card, target, effect_context)
        current, other = target, source
        while current.alive and other.alive:
            required = 2 if self.trigger_manager.has_skill(other, "无双") else 1
            for response_number in range(required):
                result = await self.choose_to_respond(
                    current, (f"【决斗】：请打出【杀】（共需 {required} 张，第 {response_number + 1} 张）"
                              if required > 1 else "【决斗】：是否打出【杀】？"),
                    card_filter=lambda c: c.name == "杀", requested_name="杀",
                    context={"source": other, "target": current, "card": card},
                )
                if self.engine is not None and self.engine.game_aborted:
                    return False
                context = {"source": other, "target": current, "card": card,
                           "effect_context": effect_context}
                if not await self._consume_response(current, result, reason, context):
                    if effect_context is not None:
                        effect_context.current_target_id = current.id
                        effect_context.next_sequence()
                    await self.damage(other, current, 1, card=card,
                                      context={"reason": reason, "effect_context": effect_context})
                    return True
                if effect_context is not None:
                    effect_context.next_sequence()
            current, other = other, current
        return True

    def _ordered_group_targets(self, source, include_source=False):
        players = list(self.game_state.players)
        if source not in players:
            return []
        start = players.index(source) + (0 if include_source else 1)
        return [p for offset in range(len(players))
                if (p := players[(start + offset) % len(players)]).alive
                and (include_source or p is not source)]

    async def _resolve_group_attack(self, source, card, requested_name, *, effect_context=None):
        targets = self._ordered_group_targets(source)
        targets = await self.trigger_manager.before_multi_target_trick(source, card, targets)
        effect_context = self._effect_context(source, card, existing=effect_context)
        for victim in list(targets):
            if self.engine is not None:
                if self.engine._abort_reason:
                    return False
                if self.game_state.game_over:
                    return True
            if not victim.alive:
                continue
            # 藤甲令南蛮与万箭对该目标无效，无需索取响应牌。
            if getattr(victim.equipment.get("armor"), "name", None) == "藤甲":
                continue
            if effect_context is not None:
                effect_context.current_target_id = victim.id
                effect_context.next_sequence()
            if await self.ask_wuxie(card, source, [victim]):
                if effect_context is not None:
                    effect_context.cancel_target(victim.id)
                continue
            if self.engine is not None:
                if self.engine._abort_reason:
                    return False
                if self.game_state.game_over:
                    return True
            result = await self.choose_to_respond(
                victim, f"【{card.name}】：请打出一张【{requested_name}】",
                card_filter=lambda c: c.name == requested_name,
                requested_name=requested_name,
                context={"source": source, "target": victim, "card": card},
            )
            if self.engine is not None:
                if self.engine._abort_reason:
                    return False
                if self.game_state.game_over:
                    return True
            context = {"source": source, "target": victim, "card": card,
                       "effect_context": effect_context}
            if await self._consume_response(victim, result, card.name, context):
                continue
            await self.damage(source, victim, 1, card=card,
                              context={"reason": card.name, "effect_context": effect_context})
        return True

    async def use_nanman(self, player, card: Card, *, effect_context=None):
        return await self._resolve_group_attack(player, card, "杀", effect_context=effect_context)

    async def use_wanjian(self, player, card: Card, *, effect_context=None):
        return await self._resolve_group_attack(player, card, "闪", effect_context=effect_context)

    async def use_taoyuan(self, player, card: Card, *, effect_context=None):
        """桃园结义：所有角色各回复1点体力。"""
        targets = await self.trigger_manager.before_multi_target_trick(
            player, card, self._ordered_group_targets(player, include_source=True),
        )
        effect_context = self._effect_context(player, card, existing=effect_context)
        for p in targets:
            if not p.alive or (self.engine is not None and self.engine.game_aborted):
                continue
            if effect_context is not None:
                effect_context.current_target_id = p.id
                effect_context.next_sequence()
            if await self.ask_wuxie(card, player, [p]):
                if effect_context is not None:
                    effect_context.cancel_target(p.id)
                continue
            if self.engine is not None and self.engine.game_aborted:
                return False
            if p.hp < p.max_hp:
                p.hp += 1
                record_stat(self.engine, player, "healing", 1)
                await self.trigger_manager.on_recover(p, 1, player, "桃园结义")
                logger.info(f"  → {p.name} 回复1点体力，当前{p.hp}/{p.max_hp}")
        return True

    async def _publish_shown_pool(self, pool):
        """把临时展示池（五谷丰登的亮牌）同步给引擎；没有真引擎（单测桩）时什么也不做。"""
        publish = getattr(self.engine, "set_shown_pool", None)
        if publish is not None and asyncio.iscoroutinefunction(publish):
            await publish(pool)

    async def use_wugu(self, player, card: Card, *, effect_context=None):
        """五谷丰登：翻开与角色数等量的牌，从使用者起按座次轮流各取一张。

        亮出的牌对全桌公开：每一步都把整池（谁取走了哪张、轮到谁）同步给引擎，
        界面据此显示，断线重连时也随状态快照恢复。
        """
        alive = await self.trigger_manager.before_multi_target_trick(
            player, card, self._ordered_group_targets(player, include_source=True),
        )
        effect_context = self._effect_context(player, card, existing=effect_context)
        # 亮出的牌先进使用者的展示区（公开），取走/弃置时再走牌移动；牌堆空了不洗牌。
        revealed = await card_flow.reveal_top(
            self.engine, self.game_state, player, len(alive),
            reason="五谷丰登亮牌", refill=False)
        if not revealed:
            return True
        pool = {
            "title": "五谷丰登",
            "source_id": player.id,
            "source_name": player.name,
            "order": [p.id for p in alive],
            "current_id": None,
            "cards": [
                {"slot": i, "card": card_to_dict(c, include_id=False),
                 "picked_by": None, "picked_name": ""}
                for i, c in enumerate(revealed)
            ],
        }
        slot_of = {id(c): i for i, c in enumerate(revealed)}
        await self._publish_shown_pool(pool)
        remaining = list(revealed)
        try:
            for p in alive:
                if not remaining:
                    break
                if not p.alive or (self.engine is not None and self.engine.game_aborted):
                    continue
                if effect_context is not None:
                    effect_context.current_target_id = p.id
                    effect_context.next_sequence()
                pool["current_id"] = p.id
                await self._publish_shown_pool(pool)
                if await self.ask_wuxie(card, player, [p]):
                    if effect_context is not None:
                        effect_context.cancel_target(p.id)
                    continue
                chosen = None
                if self.engine:
                    chosen_list = await self.engine.ask_choose_cards(
                        p, "【五谷丰登】：请选择一张牌",
                        candidates=remaining, min_n=1, max_n=1,
                        zone="shown", cancelable=False,
                        # pool_slots：每个候选对应展示池里的第几张，界面据此在五谷面板里直接点选。
                        context={"intent": "gain", "shown_pool": "五谷丰登",
                                 "pool_slots": [slot_of[id(c)] for c in remaining]},
                    )
                    chosen = chosen_list[0] if chosen_list else None
                    if chosen is not None and chosen not in remaining:
                        # 复核后仍须核对临时展示池；状态变化时落回确定性命中。
                        chosen = None
                if chosen is None:
                    if self.engine is not None and self.engine.game_aborted:
                        logger.info("  → 对局已收摊，五谷丰登停止分发")
                        break
                    # AI/托管：取分值最高的牌
                    chosen = max(remaining, key=lambda c: CARD_TABLE.get(c.name, CARD_TABLE.get("杀")).discard_keep_score
                                 if CARD_TABLE.get(c.name) else 20)
                remaining.remove(chosen)
                await card_flow.release_shown(
                    self.engine, self.game_state, chosen, "hand",
                    to_owner=p, reason="五谷丰登", actor_id=p.id)
                entry = pool["cards"][slot_of[id(chosen)]]
                entry["picked_by"] = p.id
                entry["picked_name"] = p.name
                await self._publish_shown_pool(pool)
                await self.trigger_manager.on_card_gained(p, [chosen], "五谷丰登")
                logger.info(f"  → {p.name} 获得【{chosen.name}】")
        finally:
            # 没被取走的牌（含中途收摊/异常）一律进弃牌堆，不能卡在展示区。
            for leftover in remaining:
                await card_flow.release_shown(
                    self.engine, self.game_state, leftover, "discard",
                    reason="五谷丰登剩余", actor_id=player.id)
            await self._publish_shown_pool(None)
        return True

    async def use_jiedao(self, player, card: Card, targets):
        """借刀杀人：令有武器的角色对另一角色使用杀，否则获得其武器。"""
        if not targets or len(targets) != 2:
            return False

        weapon_owner, victim = targets
        weapon = weapon_owner.equipment.get("weapon")
        if not weapon:
            return False

        result = await self.choose_to_respond(
            weapon_owner,
            f"【借刀杀人】：请对{victim.name}使用一张【杀】",
            card_filter=lambda c: c.name == "杀",
            requested_name="杀",
            context={"source": player, "target": victim, "card": card},
        )
        response = result.get("card") if result and result.get("bool") else None
        response_owner = (result.get("owner") or weapon_owner) if response else None
        if response and response_owner and response in response_owner.hand:
            response_index = response_owner.hand.index(response)
            response_owner.hand.remove(response)
            self.game_state.discard_pile.append(response)
            await self.notify_card_to_discard(
                response_owner, response, "respond", response_index,
                f"{response_owner.name}打出【杀】响应借刀杀人",
            )
            await self.trigger_manager.on_cards_lost(response_owner, [response], "借刀杀人")
            self._record_played(response_owner)
            await self.trigger_manager.on_card_discarded(response_owner, response, "借刀杀人")
            event = {
                "name": "useCard", "card": response, "player": weapon_owner,
                "target": victim, "baseDamage": 1, "shanRequired": 1,
                "nature": getattr(response, "nature", None),
                "borrowed_by": player,
            }
            await self.trigger_manager.before_sha(weapon_owner, victim, response, event)
            await self._sha_effect(event)
            return True

        if self.engine is not None:
            if await self.engine.move_card(
                weapon, "equipment", "hand", from_owner=weapon_owner,
                to_owner=player, reason="借刀杀人", actor_id=player.id,
                visibility="owner",
            ) is None:
                return False
        else:
            weapon_owner.equipment.pop("weapon")
            player.hand.append(weapon)
            await self.trigger_manager.on_cards_lost(weapon_owner, [weapon], "借刀杀人")
        await self.trigger_manager.on_card_gained(player, [weapon], "借刀杀人")
        return True

    async def use_shandian(self, player, card: Card):
        """闪电：延时锦囊，放入自己判定区。"""
        if not hasattr(player, 'judge_area'):
            player.judge_area = []
        # 若判定区已有闪电则不重复放
        if any(c.name == "闪电" for c in player.judge_area):
            logger.info("判定区已有闪电")
            return False
        if self.engine is not None and card in self.game_state.discard_pile:
            move = await self.engine.move_card(
                card, "discard", "judge", to_owner=player,
                reason="place_lightning", actor_id=player.id,
            )
            if move is None:
                return False
        else:
            player.judge_area.append(card)
        logger.info(f"  → {player.name} 判定区增加【闪电】")
        return True

    async def use_huogong(self, player, card: Card, target):
        """火攻：目标亮一张手牌，若与出牌者弃置同花色的牌，造成1点伤害。"""
        if not target:
            return False
        target = await self.trigger_manager.before_card_target(player, target, card)
        if not target:
            return False
        if not target.hand:
            # 出牌时目标有手牌，但无懈链中目标把最后一张手牌打出去了：火攻已使用，只是落空。
            # 返回 False 会把已消耗无懈的这张火攻退回手牌（既不合规则，也会被判成非法出牌）。
            logger.info(f"  → {target.name}已无手牌，火攻落空")
            return True
        if self.engine is not None:
            choice = await self.engine.ask_choose_cards(
                target, "【火攻】：请选择展示的一张手牌", list(target.hand),
                zone="hand", cancelable=False,
            )
            if self.engine.game_aborted:
                return False
            if not choice:
                return True
            shown = choice[0]
        else:
            shown = target.hand[0]
        logger.info(f"  → {target.name} 亮出【{shown}】")
        # 玩家选择弃置一张同花色的手牌
        same_suit = [c for c in player.hand if c.suit == shown.suit]
        if not same_suit:
            logger.info("  → 没有同花色的牌，火攻无效")
            return True
        discarded = None
        if self.engine:
            chosen = await self.engine.ask_choose_cards(
                player, f"【火攻】：请弃置一张与【{shown}】同花色的牌",
                candidates=same_suit, min_n=1, max_n=1,
                zone="hand", cancelable=True,
                context={"intent": "discard"},
            )
            discarded = chosen[0] if chosen else None
        if discarded is None:
            if self.engine is not None:
                logger.info("  → 火攻弃牌已取消或对局结束，不再造成伤害")
                return not self.engine.game_aborted
            discarded = same_suit[0]
        if discarded in player.hand:
            idx = player.hand.index(discarded)
            if self.engine is not None:
                if await self.engine.move_card(
                    discarded, "hand", "discard", from_owner=player,
                    reason="火攻", actor_id=player.id,
                ) is None:
                    return False
            else:
                player.hand.remove(discarded)
                self.game_state.discard_pile.append(discarded)
                await self.trigger_manager.on_cards_lost(player, [discarded], "火攻")
            await self.notify_card_to_discard(player, discarded, "discard", idx,
                                               f"{player.name}弃置【{discarded.name}】发动火攻")
            await self.trigger_manager.on_card_discarded(player, discarded, "火攻")
            await self.damage(player, target, 1, card=card, context={"reason": "火攻", "nature": "fire"})
        return True

    async def use_equipment(self, player, card: Card):
        """装备牌进入对应槽位，同槽旧装备弃置。"""
        from .card_table import CARD_TABLE
        spec = CARD_TABLE.get(card.name)
        slot = spec.equipment_slot if spec else None
        if not slot:
            logger.info(f"未知装备槽：{card.name}")
            return False
        old = player.equipment.get(slot)
        if old:
            if self.engine is not None:
                moved = await self.engine.move_card(
                    old, "equipment", "discard", from_owner=player,
                    reason="equipment_replaced", actor_id=player.id,
                )
                if moved is None:
                    return False
            else:
                player.equipment.pop(slot)
                self.game_state.discard_pile.append(old)
                await self.trigger_manager.on_cards_lost(player, [old], "装备替换")
            await self.notify_card_to_discard(player, old, "discard",
                                               message=f"{player.name}弃置旧装备【{old.name}】")
            await self.trigger_manager.on_card_discarded(player, old, "装备替换")
        # execute_action 先把所用实体牌送入弃牌区；装备成功后必须再次原子移动。
        if self.engine is not None and card in self.game_state.discard_pile:
            moved = await self.engine.move_card(
                card, "discard", "equipment", to_owner=player, to_slot=slot,
                reason="equip", actor_id=player.id,
            )
            if moved is None:
                return False
        else:
            player.equipment[slot] = card
        logger.info(f"  → {player.name} 装备【{card.name}】（{slot}槽）")
        return True

    async def store_muniu(self, player, card_index: int):
        """出牌阶段限一次扣置一张手牌，并可把宝物连同扣置牌交给别人。"""
        if (self.engine is None or self.engine.game_aborted
                or getattr(player.equipment.get("treasure"), "name", None) != "木牛流马"
                or player.flags.get("muniu_stored_this_turn")
                or not isinstance(card_index, int) or not 0 <= card_index < len(player.hand)):
            return False
        stored = player.hand[card_index]
        move = await self.engine.move_card(
            stored, "hand", "treasure", from_owner=player, to_owner=player,
            reason="muniu_store", actor_id=player.id, visibility="owner",
        )
        if move is None:
            return False
        player.flags["muniu_stored_this_turn"] = True
        recipients = [p for p in self.game_state.players if p.alive and p is not player
                      and "treasure" not in p.equipment]
        if not recipients or self.engine.game_aborted:
            return True
        chosen = await self.engine.ask_choose_players(
            player, "是否将【木牛流马】移动给另一名角色？", recipients,
            min_n=0, max_n=1, cancelable=True,
        )
        if self.engine.game_aborted:
            return True
        recipient = chosen[0] if chosen and chosen[0] in recipients else None
        if recipient is not None:
            await self.engine.move_card(
                player.equipment["treasure"], "equipment", "equipment",
                from_owner=player, to_owner=recipient, to_slot="treasure",
                reason="muniu_give", actor_id=player.id,
            )
        return True

    async def use_zhangba(self, player, indices, target):
        """丈八蛇矛将两张真实手牌作为一次虚拟杀的代价。"""
        if (self.engine is None or self.engine.game_aborted or target is None
                or getattr(player.equipment.get("weapon"), "name", None) != "丈八蛇矛"
                or len(indices) != 2 or indices[0] == indices[1]
                or any(not isinstance(i, int) or not 0 <= i < len(player.hand) for i in indices)):
            return False
        costs = [player.hand[i] for i in indices]
        colors = {"red" if card.suit in ("heart", "diamond") else "black" for card in costs}
        suit = costs[0].suit if len(colors) == 1 else "none"
        virtual = Card(f"zhangba:{costs[0].id}:{costs[1].id}", "杀", suit, 1, "basic")
        if not self.engine.rules.can_play_sha(player, virtual, [target])[0]:
            return False
        context = self.engine._new_effect_context(
            player, virtual, skill_source="丈八蛇矛",
            card_cost_ids=[cost.id for cost in costs], target=target,
        )
        for cost in costs:
            if await self.engine.move_card(cost, "hand", "discard", from_owner=player,
                                           reason="use_card", actor_id=player.id,
                                           effect_id=context.effect_id) is None:
                return False
        if self.engine.game_aborted:
            return False
        return await self.use_sha(player, virtual, target, effect_context=context)
