#!/usr/bin/env python3
"""
规则引擎 - 游戏规则和合法性检查
"""

from typing import List, Optional, Tuple
from dataclasses import dataclass

class RulesEngine:
    """规则引擎：检查所有操作的合法性"""
    
    def __init__(self, game_state):
        self.game_state = game_state
    
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
        
        # 4. 根据卡牌类型检查
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
        
        # 4. 检查距离
        distance = self.get_distance(player, target)
        weapon_range = player.get_equipment_range()
        
        if distance > weapon_range:
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
        
        # 检查距离（顺手需要距离1）
        distance = self.get_distance(player, target)
        if distance > 1:
            return False, f"距离太远：{distance} > 1"
        
        if not target.hand and not target.equipment:
            return False, "目标没有牌"
        
        return True, "OK"
    
    def get_distance(self, from_player, to_player) -> int:
        """统一委托给GameState，避免两套距离算法。"""
        return self.game_state.get_distance(from_player, to_player)

    def can_use_skill(self, player, skill_name: str) -> Tuple[bool, str]:
        """检查是否可以使用技能"""
        if not player.hero or not hasattr(player.hero, 'skills'):
            return False, "没有技能"
        
        # 查找技能
        skill = None
        for s in player.hero['skills']:
            if s['name'] == skill_name:
                skill = s
                break
        
        if not skill:
            return False, f"没有技能【{skill_name}】"
        
        # TODO: 根据技能类型检查发动条件
        # 主动技：检查阶段
        # 锁定技：自动触发
        # 限定技：检查是否已使用
        
        return True, "OK"
    
    def can_respond(self, player, card, request_type: str) -> Tuple[bool, str]:
        """检查是否可以响应"""
        if card not in player.hand:
            return False, "卡牌不在手中"
        
        if request_type == 'sha' and card.name == '闪':
            return True, "OK"
        
        if request_type == 'jinang' and card.name == '无懈可击':
            return True, "OK"
        
        return False, "响应类型不匹配"

# 导出
__all__ = ['RulesEngine']

if __name__ == "__main__":
    print("规则引擎模块加载成功")
