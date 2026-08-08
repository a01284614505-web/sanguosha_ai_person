#!/usr/bin/env python3
"""
卡牌系统 - 基于无名杀架构完整实现
"""

import asyncio
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass

@dataclass
class Card:
    """卡牌"""
    id: str
    name: str
    suit: str
    rank: int
    card_type: str
    effect: Optional[str] = None
    
    def __repr__(self):
        suit_symbol = {'spade': '♠', 'heart': '♥', 'club': '♣', 'diamond': '♦'}[self.suit]
        return f"{suit_symbol}{self.rank} {self.name}"

class CardSystem:
    """卡牌系统"""
    
    def __init__(self, game_state, event_bus, trigger_manager, ui_notifier=None):
        self.game_state = game_state
        self.event_bus = event_bus
        self.trigger_manager = trigger_manager
        self.ui_notifier = ui_notifier
    
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
            card={
                "id": card.id, "name": card.name, "suit": card.suit,
                "rank": card.rank, "card_type": card.card_type,
            },
            reason=reason,
            discard_count=len(self.game_state.discard_pile),
            message=message or f"{actor.name}{'打出' if reason == 'respond' else '弃置'}【{card.name}】",
        )

    async def use_card(self, player, card: Card, targets: List = None):
        """使用卡牌（统一入口）"""
    #     print(f"\n[出牌] {player.name} 使用 {card}")
        
        # 根据卡牌类型分发
        if card.name == '杀':
            return await self.use_sha(player, card, targets[0] if targets else None)
        elif card.name == '闪':
            print("闪只能响应使用")
            return False
        elif card.name == '桃':
            return await self.use_tao(player, card)
        elif card.name == '过河拆桥':
            return await self.use_guohe(player, card, targets[0] if targets else None)
        elif card.name == '无懈可击':
            print("无懈只能响应使用")
            return False
        else:
            print(f"未实现的卡牌: {card.name}")
            return False
    
    async def use_sha(self, player, card: Card, target):
        """使用杀（完整流程）"""
        if not target:
            print("杀需要指定目标")
            return False
        
        # 1. 检查距离
        distance = self.game_state.get_distance(player, target)
        weapon_range = player.get_equipment_range()
        
        if distance > weapon_range:
            print(f"距离不够：{distance} > {weapon_range}")
            return False
        
        # 2. 检查出杀次数
        if player.sha_count >= player.max_sha:
            print(f"本回合已使用{player.sha_count}次杀")
            return False
        
        # 3. 创建使用事件
        event = {
            'name': 'useCard',
            'card': card,
            'player': player,
            'target': target,
            'baseDamage': 1,
            'shanRequired': 1,
            'nature': card.effect if hasattr(card, 'nature') else None
        }
        
        # 4. 触发使用前事件
        from event_bus import EventType
        self.event_bus.trigger(EventType.CARD_USE, player=player, card=card, target=target)
        
        # 5. 执行杀的效果
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
        shan_required = event['shanRequired']
        
    #     print(f"  → 目标: {target.name}")
        
        # 1. 要求打出闪
        shaned = False
        for i in range(shan_required):
            print(f"  → 要求出闪 ({i+1}/{shan_required})")
            
            result = await self.choose_to_respond(
                target,
                f"请使用第{i+1}张闪响应杀",
                card_filter=lambda c: c.name == '闪'
            )
            
            if result and result.get('bool'):
                response_card = result.get('card')
                print(f"  → {target.name} 打出 {response_card}")
                
                # 从手牌移除
                if response_card in target.hand:
                    response_index = target.hand.index(response_card)
                    target.hand.remove(response_card)
                    self.game_state.discard_pile.append(response_card)
                    await self.notify_card_to_discard(
                        target, response_card, reason="respond", card_index=response_index,
                        message=f"{target.name}打出【{response_card.name}】响应"
                    )
                
                shaned = True
            else:
                print(f"  → {target.name} 没有闪")
                shaned = False
                break
        
        # 2. 判断结果
        if shaned:
            # 闪避成功
        #     print(f"  ✓ 闪避成功")
            from event_bus import EventType
            self.event_bus.trigger(EventType.CARD_RESPOND, player=target)
            return True
        else:
            # 造成伤害
        #     print(f"  ✗ 造成 {base_damage} 点伤害")
            await self.damage(player, target, base_damage)
            return True
    
    async def use_tao(self, player, card: Card):
        """使用桃"""
        if player.hp >= player.max_hp:
            print("体力已满")
            return False
        
        print(f"  → {player.name} 回复1点体力")
        player.hp = min(player.hp + 1, player.max_hp)
        
        from event_bus import EventType
        self.event_bus.trigger(EventType.HP_RECOVER, player=player, num=1)
        
        return True
    
    async def use_guohe(self, player, card: Card, target):
        """使用过河拆桥"""
        if not target:
            print("过河拆桥需要指定目标")
            return False
        
        if not target.hand and not target.equipment:
            print("目标没有牌")
            return False
        
        # 简化版：随机弃置一张手牌
        if target.hand:
            import random
            discarded = random.choice(target.hand)
            discarded_index = target.hand.index(discarded)
            target.hand.remove(discarded)
            self.game_state.discard_pile.append(discarded)
            print(f"  → {target.name} 弃置 {discarded}")
            await self.notify_card_to_discard(
                target, discarded, reason="discard", card_index=discarded_index,
                message=f"{target.name}因【过河拆桥】弃置【{discarded.name}】"
            )
        
        return True
    
    async def choose_to_respond(self, player, prompt: str, card_filter: Callable):
        """选择响应（核心方法）"""
    #     print(f"  [响应] {prompt}")
        
        # 找到符合条件的牌
        valid_cards = [c for c in player.hand if card_filter(c)]
        
        if not valid_cards:
            print(f"  → {player.name} 没有符合条件的牌")
            return {'bool': False}
        
        # TODO: 这里应该等待前端或AI决策
        # 现在暂时用简单逻辑
        if player.id == 0:
            # 玩家：默认打出第一张（后续接前端）
            return {'bool': True, 'card': valid_cards[0]}
        else:
            # AI：简单决策（后续接AI API）
            return await self.ai_respond(player, valid_cards, prompt)
    
    async def ai_respond(self, player, valid_cards: List[Card], prompt: str):
        """AI响应决策"""
        # 简单AI：有闪就出
        if any(c.name == '闪' for c in valid_cards):
            shan = next(c for c in valid_cards if c.name == '闪')
            print(f"  → AI决定打出 {shan}")
            return {'bool': True, 'card': shan}
        
        return {'bool': False}
    
    async def damage(self, source, target, amount: int):
        """造成伤害"""
        damage_info = {
            'source': source,
            'target': target,
            'amount': amount,
            'prevented': False
        }
        
        # 触发伤害前事件
        from event_bus import EventType
        self.event_bus.trigger(EventType.DAMAGE_BEGIN, **damage_info)
        
        # 造成伤害
        if not damage_info['prevented']:
            target.hp -= amount
            print(f"  → {target.name} 体力: {target.hp}/{target.max_hp}")
            
            # 触发伤害后事件
            self.event_bus.trigger(EventType.DAMAGE, **damage_info)
            
            # 检查濒死
            if target.hp <= 0:
                await self.enter_dying(target)
    
    async def enter_dying(self, player):
        """进入濒死状态（带求桃）"""
        print(f"  ⚠️ {player.name} 进入濒死状态！HP:{player.hp}")
        
        # 简化版求桃：检查自己是否有桃
        while player.hp <= 0:
            has_tao = any(c.name == '桃' for c in player.hand)
            
            if has_tao:
                # 自动用桃
                tao = next((c for c in player.hand if c.name == '桃'), None)
                if tao:
                    tao_index = player.hand.index(tao)
                    player.hand.remove(tao)
                    self.game_state.discard_pile.append(tao)
                    await self.notify_card_to_discard(
                        player, tao, reason="use", card_index=tao_index,
                        message=f"{player.name}在濒死时使用【桃】"
                    )
                    player.hp += 1
                    print(f"  🍑 {player.name} 使用【桃】，体力回复至{player.hp}")
                    if player.hp > 0:
                        break
            else:
                # 无桃，死亡
                break
        
        if player.hp <= 0:
            player.alive = False
            print(f"  💀 {player.name} 阵亡")