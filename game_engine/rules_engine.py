#!/usr/bin/env python3
"""
规则引擎 - 游戏规则和合法性检查
"""

from typing import List, Optional, Tuple
from dataclasses import dataclass

class RulesEngine:
    """规则引擎：检查所有操作的合法性"""
    
    def __init__(self, game_state, skill_manager=None):
        self.game_state = game_state
        self.skill_manager = skill_manager
    
    def can_play_card(self, player, card, targets: List = None) -> Tuple[bool, str]:
        """检查是否可以出牌"""
        # 1. 检查阶段
        if self.game_state.current_phase.value != 'play':
            return False, "不在出牌阶段"
        
        # 2. 检查是否是当前玩家
        if player != self.game_state.current_player:
            return False, "不是你的回合"
        
        # 3. 检查卡牌是否在手牌中
        if card not in player.hand:
            return False, "卡牌不在手中"
        if getattr(player, "flags", {}).get("cannot_use_hand"):
            return False, "受技能影响，本回合不能使用或打出手牌"
        
        # 4. 根据卡牌类型检查
        if card.card_type == 'equipment':
            return False, "装备效果尚未接入，本批仅支持摸取和弃置"
        if card.name == '杀':
            return self.can_play_sha(player, card, targets)
        elif card.name == '桃':
            return self.can_play_tao(player, card)
        elif card.name == '过河拆桥':
            return self.can_play_guohe(player, card, targets)
        elif card.name == '顺手牵羊':
            return self.can_play_shunshou(player, card, targets)
        elif card.name == '无懈可击':
            return False, "无懈只能响应使用"
        
        return True, "OK"
    
    def can_play_sha(self, player, card, targets: List) -> Tuple[bool, str]:
        """检查是否可以出杀"""
        # 1. 检查出杀次数
        if player.sha_count >= player.max_sha:
            return False, f"本回合已使用{player.sha_count}次杀"
        
        # 2. 检查目标
        if not targets or len(targets) == 0:
            return False, "杀需要指定目标"
        
        if len(targets) > 1:
            return False, "杀只能指定1个目标"
        
        target = targets[0]
        
        # 3. 检查目标合法性
        if not target.alive:
            return False, "目标已死亡"
        
        if target == player:
            return False, "不能对自己使用"
        
        if self.skill_manager:
            error = self.skill_manager.target_error(player, target, "杀")
            if error:
                return False, error
        # 4. 检查距离
        distance = self.get_distance(player, target)
        weapon_range = player.get_equipment_range()
        if self.skill_manager:
            distance = self.skill_manager.modify_distance(player, target, distance)
        
        if not (getattr(card, "ignore_distance", False) or (self.skill_manager and self.skill_manager.ignore_distance(player, card))) and distance > weapon_range:
            return False, f"距离不够：{distance} > {weapon_range}"
        
        return True, "OK"
    
    def can_play_tao(self, player, card) -> Tuple[bool, str]:
        """检查是否可以用桃"""
        if player.hp >= player.max_hp:
            return False, "体力已满"
        return True, "OK"
    
    def can_play_guohe(self, player, card, targets: List) -> Tuple[bool, str]:
        """检查是否可以用过河拆桥"""
        if not targets or len(targets) == 0:
            return False, "过河拆桥需要指定目标"
        
        target = targets[0]
        
        if not target.alive:
            return False, "目标已死亡"
        
        if target == player:
            return False, "不能对自己使用"
        
        if not target.hand and not target.equipment:
            return False, "目标没有牌"
        
        return True, "OK"
    
    def can_play_shunshou(self, player, card, targets: List) -> Tuple[bool, str]:
        """检查是否可以用顺手牵羊"""
        if not targets or len(targets) == 0:
            return False, "顺手牵羊需要指定目标"
        
        target = targets[0]
        
        if not target.alive:
            return False, "目标已死亡"
        
        if target == player:
            return False, "不能对自己使用"
        
        # 检查距离（顺手需要距离1；奇才令锦囊无距离限制）
        distance = self.get_distance(player, target)
        if self.skill_manager:
            distance = self.skill_manager.modify_distance(player, target, distance)
        has_qicai = bool(self.skill_manager and self.skill_manager.has_skill(player, "奇才"))
        if distance > 1 and not has_qicai:
            return False, f"距离太远：{distance} > 1"
        
        if not target.hand and not target.equipment:
            return False, "目标没有牌"
        
        return True, "OK"
    
    def get_distance(self, from_player, to_player) -> int:
        """统一委托给GameState，避免两套距离算法。"""
        return self.game_state.get_distance(from_player, to_player)

# 导出
__all__ = ['RulesEngine']

if __name__ == "__main__":
    print("规则引擎模块加载成功")
