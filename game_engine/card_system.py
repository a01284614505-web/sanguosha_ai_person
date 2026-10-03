#!/usr/bin/env python3
"""
卡牌系统 - 基于无名杀架构完整实现
"""

import asyncio
import logging
from typing import List, Callable

from .card_table import CARD_TABLE, NO_EXTERNAL_TARGET
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
    card = option.get("card")
    if card is None:
        return "不响应"
    base = f"{SUIT_SYMBOLS.get(getattr(card, 'suit', ''), '')}{getattr(card, 'rank', '')} {card.name}"
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
    
    async def notify_card_to_discard(self, actor, card, reason="use", card_index=None, message=None):
        if not self.ui_notifier:
            return
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
            message=message or f"{actor.name}{'打出' if reason == 'respond' else '弃置'}【{card.name}】",
        )

    async def use_card(self, player, card: Card, targets: List = None):
        """使用卡牌（统一入口）。分发由 CARD_TABLE 的 resolver/usage 驱动。"""
        spec = CARD_TABLE.get(card.name)

        # 锦囊结算前统一走无懈链；无懈本身只作为响应牌进入 ask_wuxie。
        if spec and spec.wuxie_targetable:
            wuxie_targets = targets or []
            if await self.ask_wuxie(card, player, wuxie_targets):
                logger.info(f"  → 【{card.name}】被无懈可击抵消")
                return True

        if spec and spec.usage == "response":
            logger.info(f"{card.name}只能响应使用")
            return False

        resolver_name = spec.resolver if spec else None
        if resolver_name:
            method = getattr(self, resolver_name)
            if resolver_name in ("use_tiesuo", "use_jiedao"):
                return await method(player, card, targets if targets else [])
            # 无显式目标的牌（桃/酒/无中生有等，NO_EXTERNAL_TARGET）不传 target 参数；其余单目标。
            if spec.target_rule.get("type") in NO_EXTERNAL_TARGET:
                return await method(player, card)
            return await method(player, card, targets[0] if targets else None)

        logger.info(f"未实现的卡牌: {card.name}")
        return False
    
    async def use_sha(self, player, card: Card, target):
        """使用杀（完整流程）"""
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
        if player.sha_count >= player.max_sha:
            logger.info(f"本回合已使用{player.sha_count}次杀")
            return False
        
        # 3. 技能可转移目标（如流离）。
        target = await self.trigger_manager.before_card_target(player, target, card)
        if not target:
            return False
        event = {
            'name': 'useCard',
            'card': card,
            'player': player,
            'target': target,
            'baseDamage': 1,
            'shanRequired': 1,
            'nature': card.effect if hasattr(card, 'nature') else None
        }
        
        # 5. 技能修正目标、响应数和伤害后执行杀的效果
        await self.trigger_manager.before_sha(player, target, card, event)
        success = await self._sha_effect(event)
        
        # 6. 增加出杀计数
        if success:
            player.sha_count += 1
        
        return success
    
    async def _sha_effect(self, event):
        """杀的效果（参考无名杀）"""
        player = event['player']
        target = event['target']
        base_damage = event['baseDamage']
        # 酒杀：伤害+1
        if hasattr(player, 'jiu_buff') and player.jiu_buff:
            base_damage += 1
            player.jiu_buff = False
            logger.info(f"  → 酒杀！伤害+1，总计{base_damage}点")
        shan_required = event['shanRequired']
        
    #     logger.info(f"  → 目标: {target.name}")
        
        # 1. 要求打出闪
        shaned = False
        for i in range(shan_required):
            logger.info(f"  → 要求出闪 ({i+1}/{shan_required})")
            
            result = await self.choose_to_respond(
                target,
                f"请使用第{i+1}张闪响应杀",
                card_filter=lambda c: c.name == '闪',
                requested_name='闪',
                context={'source': player, 'target': target, 'card': event['card']}
            )
            
            if result and result.get('bool'):
                response_card = result.get('card')
                logger.info(f"  → {target.name} 打出 {response_card}")
                
                # 从实际提供者手牌移除（护驾等技能可由队友提供）。
                owner = result.get('owner') or target
                if response_card in owner.hand:
                    response_index = owner.hand.index(response_card)
                    owner.hand.remove(response_card)
                    self.game_state.discard_pile.append(response_card)
                    await self.notify_card_to_discard(
                        owner, response_card, reason="respond", card_index=response_index,
                        message=f"{owner.name}打出【{result.get('as_name', response_card.name)}】响应"
                    )
                    await self.trigger_manager.on_cards_lost(owner, [response_card], "respond")
                    self._record_played(owner)
                    await self.trigger_manager.on_card_discarded(owner, response_card, "respond")
                    await self.trigger_manager.on_card_responded(
                        target, response_card, result.get('as_name', response_card.name),
                        {'source': player, 'target': target, 'card': event['card'], 'owner': owner}
                    )
                
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
            return True
        else:
            # 造成伤害
        #     logger.info(f"  ✗ 造成 {base_damage} 点伤害")
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

    REGION_SLOTS = ("weapon", "armor", "plus_horse", "minus_horse")

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
            context={"target": target, "reason": reason},
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
        if chosen is None:
            chosen = self._fallback_region_card(target)
        if chosen is None:
            logger.info("目标没有可弃置的牌")
            return False
        discarded, zone = chosen
        if zone == "equipment" and self.trigger_manager.protect_card(target, discarded, "other_discard_equipment"):
            logger.info(f"  → {target.name}的装备受技能保护，不能被弃置")
            return True
        removed, discarded_index = self._region_remove(target, discarded, zone)
        if not removed:
            logger.info(f"  ❌ 过河拆桥复核失败：【{discarded.name}】已不在{target.name}的区域")
            return False
        self.game_state.discard_pile.append(discarded)
        logger.info(f"  → {target.name} 弃置 {discarded}（{zone}）")
        await self.notify_card_to_discard(
            target, discarded, reason="discard", card_index=discarded_index,
            message=f"{target.name}因【过河拆桥】弃置【{discarded.name}】"
        )
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
        if chosen is None:
            chosen = self._fallback_region_card(target)
        if chosen is None:
            return False
        gained, zone = chosen
        removed, _index = self._region_remove(target, gained, zone)
        if not removed:
            logger.info(f"  ❌ 顺手牵羊复核失败：【{gained.name}】已不在{target.name}的区域")
            return False
        player.hand.append(gained)
        logger.info(f"  → {player.name} 获得 {target.name} 的{gained}（{zone}）")
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
            })

        if not options:
            return []
        options.append(make_pass_option())
        return options

    async def choose_to_respond(self, player, prompt: str, card_filter: Callable,
                                requested_name=None, context=None, kind="respond"):
        """选择响应（核心方法）：引擎算候选 → 真人或AI从候选里挑 → 引擎复核后返回。"""
        options = self.build_response_options(player, card_filter, requested_name)
        if not options:
            logger.info(f"  → {player.name} 没有符合条件的牌")
            return {'bool': False}
        if self.responder is None:
            return {'bool': False}

        return await self.responder(player, {
            "kind": kind,
            "prompt": prompt,
            "requested_name": requested_name,
            "options": options,
            "context": context or {},
        })

    async def ask_wuxie(self, card, source, targets=None) -> bool:
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
                    context={"source": current_source, "targets": targets or [], "card": card},
                    kind="wuxie",
                )
                if not (result and result.get("bool")):
                    continue
                owner = result.get("owner") or responder
                response_card = result.get("card")
                if response_card is None or response_card not in owner.hand:
                    raise AssertionError("无懈响应已确认，但响应牌未在提供者手牌中")
                response_index = owner.hand.index(response_card)
                owner.hand.remove(response_card)
                self.game_state.discard_pile.append(response_card)
                await self.notify_card_to_discard(
                    owner, response_card, reason="respond", card_index=response_index,
                    message=f"{owner.name}使用【无懈可击】响应第{layer}层"
                )
                await self.trigger_manager.on_cards_lost(owner, [response_card], "wuxie")
                self._record_played(owner)
                await self.trigger_manager.on_card_discarded(owner, response_card, "wuxie")
                await self.trigger_manager.on_card_responded(
                    responder, response_card, result.get("as_name", response_card.name),
                    {"source": current_source, "targets": targets or [], "card": card, "owner": owner, "wuxie_layer": layer}
                )
                if response_card in owner.hand:
                    raise AssertionError("无懈响应消费后仍留在手牌")
                responded = True
                current_source = responder
                canceled = not canceled
                break
            if not responded:
                return canceled

    async def damage(self, source, target, amount: int, card=None, context=None):
        """造成伤害"""
        damage_info = {
            'source': source,
            'target': target,
            'amount': amount,
            'prevented': False
        }
        
        # 技能可修正伤害值。
        amount = await self.trigger_manager.modify_damage(source, target, amount, card, context)
        damage_info['amount'] = amount
        # 造成伤害
        if not damage_info['prevented'] and amount > 0:
            target.hp -= amount
            # 统计按修正后的最终伤害值计；自伤（如闪电）只记受到伤害，不记造成伤害。
            record_stat(self.engine, target, "damage_taken", amount)
            if source is not None and source is not target:
                record_stat(self.engine, source, "damage_dealt", amount)
            mark_damage_source(self.game_state, target, source)
            logger.info(f"  → {target.name} 体力: {target.hp}/{target.max_hp}")
            
            await self.trigger_manager.after_damage(source, target, amount, card, context)
            
            # 检查濒死
            if target.hp <= 0:
                await self.enter_dying(target)
    
    async def enter_dying(self, player):
        """濒死求桃：按座次逐个询问存活角色，每人都可以拒绝。"""
        logger.info(f"  ⚠️ {player.name} 进入濒死状态！HP:{player.hp}")
        while player.hp <= 0:
            rescued = False
            rescuers = [player] + [p for p in self.game_state.players if p.alive and p is not player]
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
                if not (result and result.get('bool')):
                    continue
                card = result.get('card')
                owner = result.get('owner') or rescuer
                if not card or card not in owner.hand:
                    continue
                index = owner.hand.index(card)
                owner.hand.remove(card)
                self.game_state.discard_pile.append(card)
                as_name = result.get('as_name') or card.name
                await self.notify_card_to_discard(owner, card, 'respond', index, f"{owner.name}使用【{as_name}】救援{player.name}")
                await self.trigger_manager.on_cards_lost(owner, [card], 'dying_rescue')
                self._record_played(owner)
                await self.trigger_manager.on_card_discarded(owner, card, 'dying_rescue')
                await self.trigger_manager.on_card_responded(rescuer, card, as_name, {'target': player, 'owner': owner})
                player.hp += 1
                record_stat(self.engine, owner, "healing", 1)
                await self.trigger_manager.on_recover(player, 1, rescuer, 'dying_rescue')
                logger.info(f"  🍑 {owner.name}救援{player.name}，体力回复至{player.hp}")
                rescued = True
                break
            if not rescued:
                break
        if player.hp <= 0:
            player.alive = False
            player.identity_revealed = True
            killer_id = pop_kill_credit(self.game_state, player)
            killer = next((p for p in self.game_state.players if p.id == killer_id), None)
            if killer is not None:
                record_stat(self.engine, killer, "kills")
            logger.info(f"  💀 {player.name} 阵亡，身份揭示为 {player.identity}")

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

        # 放入目标判定区
        if not hasattr(target, 'judge_area'):
            target.judge_area = []

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
        drawn = []
        for _ in range(2):
            if self.game_state.deck:
                drawn_card = self.game_state.deck.pop(0)
                player.hand.append(drawn_card)
                drawn.append(drawn_card)

        if drawn:
            logger.info(f"  → {player.name} 摸了{len(drawn)}张牌")
            await self.trigger_manager.on_card_gained(player, drawn, "无中生有")

        return True

    async def use_juedou(self, player, card: Card, target):
        """决斗：轮流出杀，先不出者受1点伤害。"""
        if not target:
            return False
        target = await self.trigger_manager.before_card_target(player, target, card)
        if not target:
            return False
        current, other = target, player
        while True:
            result = await self.choose_to_respond(
                current,
                f"【决斗】：请出一张【杀】",
                card_filter=lambda c: c.name == "杀",
                requested_name="杀",
                context={"source": other, "target": current, "card": card},
            )
            if not (result and result.get("bool")):
                await self.damage(other, current, 1, card=card, context={"reason": "决斗"})
                return True
            response = result.get("card")
            owner = result.get("owner") or current
            if response and response in owner.hand:
                idx = owner.hand.index(response)
                owner.hand.remove(response)
                self.game_state.discard_pile.append(response)
                await self.notify_card_to_discard(owner, response, "respond", idx,
                                                   f"{owner.name}打出【杀】响应决斗")
                await self.trigger_manager.on_cards_lost(owner, [response], "决斗")
                self._record_played(owner)
                await self.trigger_manager.on_card_discarded(owner, response, "决斗")
            current, other = other, current

    async def use_nanman(self, player, card: Card):
        """南蛮入侵：其他角色各出一张杀，否则受1点伤害。"""
        others = [p for p in self.game_state.players if p.alive and p is not player]
        for victim in list(others):
            result = await self.choose_to_respond(
                victim,
                "【南蛮入侵】：请出一张【杀】",
                card_filter=lambda c: c.name == "杀",
                requested_name="杀",
                context={"source": player, "target": victim, "card": card},
            )
            if result and result.get("bool"):
                response = result.get("card")
                owner = result.get("owner") or victim
                if response and response in owner.hand:
                    idx = owner.hand.index(response)
                    owner.hand.remove(response)
                    self.game_state.discard_pile.append(response)
                    await self.notify_card_to_discard(owner, response, "respond", idx,
                                                       f"{owner.name}打出【杀】响应南蛮入侵")
                    await self.trigger_manager.on_cards_lost(owner, [response], "南蛮入侵")
                    self._record_played(owner)
                    await self.trigger_manager.on_card_discarded(owner, response, "南蛮入侵")
            else:
                await self.damage(player, victim, 1, card=card, context={"reason": "南蛮入侵"})
        return True

    async def use_wanjian(self, player, card: Card):
        """万箭齐发：其他角色各出一张闪，否则受1点伤害。"""
        others = [p for p in self.game_state.players if p.alive and p is not player]
        for victim in list(others):
            result = await self.choose_to_respond(
                victim,
                "【万箭齐发】：请出一张【闪】",
                card_filter=lambda c: c.name == "闪",
                requested_name="闪",
                context={"source": player, "target": victim, "card": card},
            )
            if result and result.get("bool"):
                response = result.get("card")
                owner = result.get("owner") or victim
                if response and response in owner.hand:
                    idx = owner.hand.index(response)
                    owner.hand.remove(response)
                    self.game_state.discard_pile.append(response)
                    await self.notify_card_to_discard(owner, response, "respond", idx,
                                                       f"{owner.name}打出【闪】响应万箭齐发")
                    await self.trigger_manager.on_cards_lost(owner, [response], "万箭齐发")
                    self._record_played(owner)
                    await self.trigger_manager.on_card_discarded(owner, response, "万箭齐发")
            else:
                await self.damage(player, victim, 1, card=card, context={"reason": "万箭齐发"})
        return True

    async def use_taoyuan(self, player, card: Card):
        """桃园结义：所有角色各回复1点体力。"""
        for p in self.game_state.players:
            if not p.alive:
                continue
            if p.hp < p.max_hp:
                p.hp += 1
                record_stat(self.engine, player, "healing", 1)
                await self.trigger_manager.on_recover(p, 1, player, "桃园结义")
                logger.info(f"  → {p.name} 回复1点体力，当前{p.hp}/{p.max_hp}")
        return True

    async def use_wugu(self, player, card: Card):
        """五谷丰登：翻开顶牌，各角色从中取一张。"""
        alive = [p for p in self.game_state.players if p.alive]
        revealed = []
        for _ in alive:
            if self.game_state.deck:
                revealed.append(self.game_state.deck.pop(0))
        if not revealed:
            return True
        remaining = list(revealed)
        for p in alive:
            if not remaining:
                break
            chosen = None
            if self.engine and not p.is_ai:
                chosen_list = await self.engine.ask_choose_cards(
                    p, "【五谷丰登】：请选择一张牌",
                    candidates=remaining, min_n=1, max_n=1,
                    zone="shown", cancelable=False,
                )
                chosen = chosen_list[0] if chosen_list else None
                if chosen is not None and chosen not in remaining:
                    # 复核后仍须核对临时展示池；状态变化时落回确定性命中。
                    chosen = None
            if chosen is None:
                # AI/托管：取分值最高的牌
                from .card_table import CARD_TABLE
                chosen = max(remaining, key=lambda c: CARD_TABLE.get(c.name, CARD_TABLE.get("杀")).discard_keep_score
                             if CARD_TABLE.get(c.name) else 20)
            remaining.remove(chosen)
            p.hand.append(chosen)
            await self.trigger_manager.on_card_gained(p, [chosen], "五谷丰登")
            logger.info(f"  → {p.name} 获得【{chosen.name}】")
        for leftover in remaining:
            self.game_state.discard_pile.append(leftover)
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
        player.judge_area.append(card)
        logger.info(f"  → {player.name} 判定区增加【闪电】")
        return True

    async def use_huogong(self, player, card: Card, target):
        """火攻：目标亮一张手牌，若与出牌者弃置同花色的牌，造成1点伤害。"""
        if not target or not target.hand:
            return False
        target = await self.trigger_manager.before_card_target(player, target, card)
        if not target or not target.hand:
            return False
        shown = target.hand[0]
        logger.info(f"  → {target.name} 亮出【{shown}】")
        # 玩家选择弃置一张同花色的手牌
        same_suit = [c for c in player.hand if c.suit == shown.suit]
        if not same_suit:
            logger.info("  → 没有同花色的牌，火攻无效")
            return False
        discarded = None
        if self.engine and not player.is_ai:
            chosen = await self.engine.ask_choose_cards(
                player, f"【火攻】：请弃置一张与【{shown}】同花色的牌",
                candidates=same_suit, min_n=1, max_n=1,
                zone="hand", cancelable=True,
            )
            discarded = chosen[0] if chosen else None
        if discarded is None:
            discarded = same_suit[0]
        if discarded in player.hand:
            idx = player.hand.index(discarded)
            player.hand.remove(discarded)
            self.game_state.discard_pile.append(discarded)
            await self.notify_card_to_discard(player, discarded, "discard", idx,
                                               f"{player.name}弃置【{discarded.name}】发动火攻")
            await self.trigger_manager.on_cards_lost(player, [discarded], "火攻")
            await self.trigger_manager.on_card_discarded(player, discarded, "火攻")
            await self.damage(player, target, 1, card=card, context={"reason": "火攻"})
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
            player.equipment.pop(slot)
            self.game_state.discard_pile.append(old)
            await self.notify_card_to_discard(player, old, "discard",
                                               message=f"{player.name}弃置旧装备【{old.name}】")
            await self.trigger_manager.on_cards_lost(player, [old], "装备替换")
            await self.trigger_manager.on_card_discarded(player, old, "装备替换")
        player.equipment[slot] = card
        logger.info(f"  → {player.name} 装备【{card.name}】（{slot}槽）")
        return True
