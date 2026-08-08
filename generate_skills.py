#!/usr/bin/env python3
"""
技能代码生成器 - 根据世界书JSON自动生成27将技能实现代码
"""

import json
import os

class SkillCodeGenerator:
    """技能代码生成器"""
    
    def __init__(self, worldbook_dir='worldbook_generated'):
        self.worldbook_dir = worldbook_dir
        self.heroes = self.load_heroes()
    
    def load_heroes(self):
        """加载武将数据"""
        path = os.path.join(self.worldbook_dir, 'heroes', 'heroes_27_complete.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data['heroes']
    
    def generate_all_skills(self):
        """生成所有武将的技能代码"""
        code = []
        
        # 文件头
        code.append('#!/usr/bin/env python3')
        code.append('"""')
        code.append('武将技能实现 - 自动生成（基于世界书数据）')
        code.append('包含界限突破27将的所有技能')
        code.append('"""')
        code.append('')
        code.append('from typing import List, Dict, Optional')
        code.append('from dataclasses import dataclass')
        code.append('import asyncio')
        code.append('')
        code.append('# 导入游戏引擎')
        code.append('from event_bus import EventType')
        code.append('from skill_system import Skill, SkillConfig')
        code.append('')
        code.append('')
        
        # 按势力生成
        factions = {'魏': [], '蜀': [], '吴': [], '群': []}
        for hero in self.heroes:
            factions[hero['faction']].append(hero)
        
        for faction, heroes in factions.items():
            code.append(f'# {"=" * 60}')
            code.append(f'# {faction}势力武将技能')
            code.append(f'# {"=" * 60}')
            code.append('')
            
            for hero in heroes:
                code.extend(self.generate_hero_skills(hero))
                code.append('')
        
        # 生成技能注册表
        code.append('# ' + '=' * 60)
        code.append('# 技能注册表')
        code.append('# ' + '=' * 60)
        code.append('')
        code.append('SKILL_REGISTRY = {')
        
        for hero in self.heroes:
            for skill in hero['skills']:
                skill_id = f"{hero['id']}_{skill['name']}"
                skill_class = self.get_skill_class_name(hero['id'], skill['name'])
                code.append(f'    "{skill_id}": {skill_class},')
        
        code.append('}')
        code.append('')
        code.append('')
        code.append('def get_hero_skills(hero_id: str) -> List[Skill]:')
        code.append('    """获取武将的所有技能实例"""')
        code.append('    skills = []')
        code.append('    for skill_id, skill_class in SKILL_REGISTRY.items():')
        code.append('        if skill_id.startswith(hero_id + "_"):')
        code.append('            skills.append(skill_class())')
        code.append('    return skills')
        code.append('')
        
        return '\n'.join(code)
    
    def generate_hero_skills(self, hero: Dict) -> List[str]:
        """生成单个武将的所有技能"""
        code = []
        
        code.append(f'# {hero["name"]}')
        code.append(f'# {hero["max_hp"]}点体力，{hero["faction"]}势力')
        
        for skill in hero['skills']:
            code.append('')
            code.extend(self.generate_single_skill(hero, skill))
        
        return code
    
    def generate_single_skill(self, hero: Dict, skill: Dict) -> List[str]:
        """生成单个技能的代码"""
        code = []
        
        skill_class = self.get_skill_class_name(hero['id'], skill['name'])
        skill_type = skill.get('type', 'trigger')
        trigger_event = skill.get('trigger_event', 'TURN_START')
        
        code.append(f'class {skill_class}(Skill):')
        code.append(f'    """')
        code.append(f'    {skill["name"]} - {hero["name"]}')
        code.append(f'    {skill["description"]}')
        code.append(f'    """')
        code.append(f'    ')
        code.append(f'    def __init__(self):')
        code.append(f'        super().__init__(SkillConfig(')
        code.append(f'            name="{skill["name"]}",')
        code.append(f'            trigger={{"{trigger_event}": "player"}},')
        code.append(f'            forced={skill_type == "passive"},')
        code.append(f'            zhu_skill={skill_type == "lord"}')
        code.append(f'        ))')
        code.append(f'    ')
        code.append(f'    async def can_activate(self, event, player, game_state):')
        code.append(f'        """检查是否可以发动"""')
        
        # 根据技能类型生成条件
        if skill_type == 'lord':
            code.append(f'        # 主公技，需要是主公')
            code.append(f'        if player.identity != "lord":')
            code.append(f'            return False')
        
        code.append(f'        # TODO: 补充具体发动条件')
        code.append(f'        return True')
        code.append(f'    ')
        code.append(f'    async def execute(self, event, player, game_state):')
        code.append(f'        """执行技能效果"""')
        code.append(f'        print(f"{{player.name}} 发动技能【{skill["name"]}】")')
        code.append(f'        ')
        
        # 根据世界书生成提示性代码
        worldbook = skill.get('worldbook', '')
        if '受伤' in worldbook or '伤害' in worldbook:
            code.append(f'        # 伤害相关技能')
            code.append(f'        damage_info = event.get("damage_info")')
            code.append(f'        if damage_info:')
            code.append(f'            source = damage_info.get("source")')
            code.append(f'            amount = damage_info.get("amount", 1)')
            code.append(f'            # TODO: 实现具体效果')
        elif '摸牌' in worldbook:
            code.append(f'        # 摸牌相关技能')
            code.append(f'        cards = game_state.draw_card(player, 1)')
            code.append(f'        # TODO: 实现具体效果')
        elif '判定' in worldbook:
            code.append(f'        # 判定相关技能')
            code.append(f'        judge_card = game_state.judge(player)')
            code.append(f'        # TODO: 实现具体效果')
        else:
            code.append(f'        # TODO: 实现具体技能效果')
            code.append(f'        # 参考世界书: {worldbook[:50]}...')
        
        code.append(f'        ')
        code.append(f'        return True')
        code.append('')
        
        return code
    
    def get_skill_class_name(self, hero_id: str, skill_name: str) -> str:
        """生成技能类名"""
        # 驼峰命名
        hero_part = hero_id.capitalize()
        skill_part = skill_name
        return f'{hero_part}_{skill_part}_Skill'
    
    def save_to_file(self, filename='skills_generated.py'):
        """保存到文件"""
        code = self.generate_all_skills()
        
        path = os.path.join('game_engine', filename)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(code)
        
        print(f'✅ 技能代码已生成: {path}')
        print(f'   包含27将共{sum(len(h["skills"]) for h in self.heroes)}个技能')
        
        return path


if __name__ == '__main__':
    print('🔧 开始生成技能代码...\n')
    
    generator = SkillCodeGenerator()
    file_path = generator.save_to_file()
    
    print(f'\n📊 统计：')
    for faction in ['魏', '蜀', '吴', '群']:
        heroes = [h for h in generator.heroes if h['faction'] == faction]
        skill_count = sum(len(h['skills']) for h in heroes)
        print(f'   {faction}势力: {len(heroes)}将，{skill_count}个技能')
    
    print(f'\n💡 使用方法：')
    print(f'   1. 查看生成的文件: {file_path}')
    print(f'   2. 补充TODO部分的具体实现')
    print(f'   3. 在game_engine中导入: from skills_generated import get_hero_skills')
    print(f'\n✨ 技能代码生成完成！')
