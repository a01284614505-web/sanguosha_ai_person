#!/usr/bin/env python3
"""
规则引擎 - 游戏规则和合法性检查
"""

import logging
from typing import List, Optional, Tuple
from dataclasses import dataclass

from .card_table import CARD_TABLE, NO_EXTERNAL_TARGET


logger = logging.getLogger(__name__)


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
        
        # 4. 根据卡牌类型检查（单一来源：CARD_TABLE 的 card_type/usage/resolver）
        spec = CARD_TABLE.get(card.name)
        if spec and spec.usage == "response":
            return False, "该牌只能响应使用"
        can_play_fn = getattr(self, f"can_play_{spec.resolver[4:]}", None) if spec and spec.resolver else None
        if can_play_fn:
            # 与 use_card 分发链对称（单一来源 NO_EXTERNAL_TARGET）：无外部目标不传 targets
            if spec.target_rule.get("type") in NO_EXTERNAL_TARGET:
                return can_play_fn(player, card)
            return can_play_fn(player, card, targets)

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
    
    def can_play_jiedao(self, player, card, targets: List) -> Tuple[bool, str]:
        """检查借刀杀人的两个有序目标：有武器者、被攻击者。"""
        if not targets or len(targets) != 2:
            return False, "借刀杀人需要指定两名角色"

        weapon_owner, victim = targets
        if weapon_owner == victim:
            return False, "借刀杀人的两个目标不能相同"
        if weapon_owner == player or victim == player:
            return False, "借刀杀人不能指定自己"
        if not weapon_owner.alive or not victim.alive:
            return False, "目标已死亡"
        if "weapon" not in weapon_owner.equipment:
            return False, "第一目标没有武器"

        distance = self.get_distance(weapon_owner, victim)
        if self.skill_manager:
            distance = self.skill_manager.modify_distance(weapon_owner, victim, distance)
        weapon_range = weapon_owner.get_equipment_range()
        if distance > weapon_range:
            return False, f"借刀目标距离不够：{distance} > {weapon_range}"
        return True, "OK"

    def get_distance(self, from_player, to_player) -> int:
        """统一委托给GameState，避免两套距离算法。"""
        return self.game_state.get_distance(from_player, to_player)


# 导出
__all__ = ['RulesEngine']

if __name__ == "__main__":
    logger.info("规则引擎模块加载成功")
