#!/usr/bin/env python3
"""
卡牌系统 - 基于无名杀架构完整实现
"""

import logging
from typing import List, Callable

from .card_table import CARD_TABLE, NO_EXTERNAL_TARGET
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

    def __init__(self, game_state, _event_bus, trigger_manager, ui_notifier=None, responder=None):
        self.game_state = game_state
        self.trigger_manager = trigger_manager
        self.ui_notifier = ui_notifier
        # 场外响应决策器，由引擎注入。为 None 时一律视为「不响应」，老调用点不会崩。
        self.responder = responder
    
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
            if resolver_name == "use_tiesuo":
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
            await self.trigger_manager.on_recover(player, player.hp - before_hp, player, "桃")
        
        return True

    async def use_guohe(self, player, card: Card, target):
        """使用过河拆桥"""
        if not target:
            logger.info("过河拆桥需要指定目标")
            return False
        
        target = await self.trigger_manager.before_card_target(player, target, card)
        if target and getattr(target, "flags", {}).pop("qianxun_cancelled_card", None) == card.id:
            return True
        if not target or (not target.hand and not target.equipment):
            logger.info("目标没有牌")
            return False
        
        # 当前交互层未提供选牌时，确定性优先弃置手牌；只有无手牌才处理装备。
        discarded = None
        discarded_index = None
        if target.hand:
            discarded = target.hand[0]
            discarded_index = 0
            target.hand.remove(discarded)
        elif target.equipment:
            candidate = next(iter(target.equipment.values()))
            if self.trigger_manager.protect_card(target, candidate, "other_discard_equipment"):
                logger.info(f"  → {target.name}的装备受技能保护，不能被弃置")
                return True
            slot = next(k for k, v in target.equipment.items() if v is candidate)
            discarded = target.equipment.pop(slot)
        if discarded:
            self.game_state.discard_pile.append(discarded)
            logger.info(f"  → {target.name} 弃置 {discarded}")
            await self.notify_card_to_discard(
                target, discarded, reason="discard", card_index=discarded_index,
                message=f"{target.name}因【过河拆桥】弃置【{discarded.name}】"
            )
            await self.trigger_manager.on_cards_lost(target, [discarded], "过河拆桥")
            await self.trigger_manager.on_card_discarded(target, discarded, "过河拆桥")
        return True

    async def use_shunshou(self, player, card: Card, target):
        """顺手牵羊：获得目标一张手牌。"""
        if not target or not target.hand:
            return False
        target = await self.trigger_manager.before_card_target(player, target, card)
        if target and getattr(target, "flags", {}).pop("qianxun_cancelled_card", None) == card.id:
            return True
        if not target or not target.hand:
            return False
        gained = target.hand[0]
        target.hand.remove(gained)
        player.hand.append(gained)
        await self.trigger_manager.on_cards_lost(target, [gained], "顺手牵羊")
        await self.trigger_manager.on_card_gained(player, [gained], "顺手牵羊")
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
                await self.trigger_manager.on_card_discarded(owner, card, 'dying_rescue')
                await self.trigger_manager.on_card_responded(rescuer, card, as_name, {'target': player, 'owner': owner})
                player.hp += 1
                await self.trigger_manager.on_recover(player, 1, rescuer, 'dying_rescue')
                logger.info(f"  🍑 {owner.name}救援{player.name}，体力回复至{player.hp}")
                rescued = True
                break
            if not rescued:
                break
        if player.hp <= 0:
            player.alive = False
            player.identity_revealed = True
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
