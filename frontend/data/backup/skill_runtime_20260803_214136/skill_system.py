#!/usr/bin/env python3
"""
技能系统 - 基于无名杀架构实现
"""

from typing import Callable, Dict, Any, Optional, List
from dataclasses import dataclass
import asyncio

@dataclass
class SkillConfig:
    """技能配置"""
    name: str
    audio: Optional[str] = None
    trigger: Dict[str, str] = None
    filter_func: Optional[Callable] = None
    cost_func: Optional[Callable] = None
    content_func: Optional[Callable] = None
    forced: bool = False
    zhu_skill: bool = False

class Skill:
    """技能类"""
    
    def __init__(self, config: SkillConfig):
        self.name = config.name
        self.audio = config.audio
        self.trigger = config.trigger or {}
        self.filter_func = config.filter_func
        self.cost_func = config.cost_func
        self.content_func = config.content_func
        self.forced = config.forced
        self.zhu_skill = config.zhu_skill
    
    async def check_trigger(self, event_name: str, event: Dict, player) -> bool:
        """检查是否应该触发"""
        # 检查触发时机
        triggered = False
        
        if 'player' in self.trigger:
            if self.trigger['player'] == event_name and event.get('player') == player:
                triggered = True
        
        if 'global' in self.trigger:
            if self.trigger['global'] == event_name:
                triggered = True
        
        if not triggered:
            return False
        
        # 检查过滤条件
        if self.filter_func:
            try:
                return await self.filter_func(event, player)
            except Exception as e:
                print(f"技能{self.name}的filter执行出错: {e}")
                return False
        
        return True
    
    async def execute(self, event: Dict, trigger: Dict, player) -> bool:
        """执行技能"""
        # 1. 强制技能直接执行
        if self.forced:
            if self.content_func:
                try:
                    await self.content_func(event, trigger, player)
                    return True
                except Exception as e:
                    print(f"技能{self.name}执行出错: {e}")
                    return False
        
        # 2. 询问成本（是否发动）
        if self.cost_func:
            try:
                result = await self.cost_func(event, trigger, player)
                if not result or not result.get('bool'):
                    return False
            except Exception as e:
                print(f"技能{self.name}的cost执行出错: {e}")
                return False
        
        # 3. 执行效果
        if self.content_func:
            try:
                await self.content_func(event, trigger, player)
                return True
            except Exception as e:
                print(f"技能{self.name}执行出错: {e}")
                return False
        
        return True

class TriggerManager:
    """触发管理器"""
    
    def __init__(self):
        self.registered_skills: Dict[int, List[Skill]] = {}
    
    def register_skill(self, player, skill: Skill):
        """注册技能"""
        player_id = id(player)
        if player_id not in self.registered_skills:
            self.registered_skills[player_id] = []
        self.registered_skills[player_id].append(skill)
        print(f"注册技能: {player.name} - {skill.name}")
    
    def register_all_player_skills(self, players):
        """注册所有玩家的技能"""
        for player in players:
            if player.hero and hasattr(player.hero, 'skills'):
                for skill_data in player.hero['skills']:
                    # 从技能定义创建Skill对象
                    skill = create_skill_from_data(skill_data)
                    if skill:
                        self.register_skill(player, skill)
    
    async def trigger(self, event_name: str, event: Dict, players: List = None):
        """触发事件"""
        if players is None:
            # 如果没有指定玩家，触发所有玩家
            players = [p for pid in self.registered_skills.keys() 
                      for p in self.get_player_by_id(pid)]
        
        triggered_skills = []
        
        for player in players:
            player_id = id(player)
            if player_id not in self.registered_skills:
                continue
            
            for skill in self.registered_skills[player_id]:
                if await skill.check_trigger(event_name, event, player):
                    triggered_skills.append((player, skill))
        
        # 按优先级执行（后续可以添加优先级系统）
        for player, skill in triggered_skills:
            print(f"触发技能: {player.name} - {skill.name}")
            await skill.execute(event, event, player)

def create_skill_from_data(skill_data: Dict) -> Optional[Skill]:
    """从JSON数据创建技能对象"""
    # 这里是简化版，实际需要根据技能名称映射到具体实现
    config = SkillConfig(
        name=skill_data.get('name'),
        trigger=skill_data.get('trigger'),
        forced=skill_data.get('forced', False)
    )
    
    # TODO: 根据技能名称映射到具体的filter/cost/content函数
    
    return Skill(config)

# ===== 具体技能实现示例 =====

async def rende_filter(event, player):
    """仁德的触发条件"""
    # 出牌阶段且有手牌
    return len(player.hand) > 0

async def rende_cost(event, trigger, player):
    """仁德的成本"""
    # 选择要给出的牌和目标
    # TODO: 前端交互或AI决策
    return {'bool': True, 'cards': [], 'target': None}

async def rende_content(event, trigger, player):
    """仁德的效果"""
    # 给牌，检查是否达到2张
    cards_given = event.get('cards_given_this_phase', 0)
    cards_given += len(event.get('cards', []))
    
    if cards_given >= 2 and not event.get('rende_recovered'):
        # 回复1点体力
        player.hp = min(player.hp + 1, player.max_hp)
        event['rende_recovered'] = True
        print(f"{player.name}发动仁德，回复1点体力")

# 创建仁德技能
RENDE_SKILL = Skill(SkillConfig(
    name="仁德",
    trigger={'player': 'phaseUse'},
    filter_func=rende_filter,
    cost_func=rende_cost,
    content_func=rende_content
))

# 导出
__all__ = ['Skill', 'SkillConfig', 'TriggerManager', 'create_skill_from_data']

if __name__ == "__main__":
    # 测试
    print("技能系统模块加载成功")
    print(f"仁德技能: {RENDE_SKILL.name}")
