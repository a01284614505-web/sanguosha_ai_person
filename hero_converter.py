#!/usr/bin/env python3
"""
武将数据转换器 - 自动将贴吧格式转为JSON
支持手动转换和AI自动转换
"""

import json
import re
import sys
import httpx
import asyncio

class HeroConverter:
    """武将数据转换器"""
    
    def __init__(self, use_ai=False, api_config=None):
        self.use_ai = use_ai
        self.api_config = api_config or {}
    
    def parse_tieba_text(self, text):
        """解析贴吧格式文本"""
        lines = text.strip().split('\n')
        hero_data = {
            "id": "",
            "name": "",
            "faction": "",
            "title": "",
            "code": "",
            "max_hp": 4,
            "artist": "",
            "image": "",
            "skills": [],
            "worldbook": {
                "summary": "",
                "skill_details": "",
                "usage_tips": "",
                "combos": [],
                "counters": []
            }
        }
        
        current_skill = None
        
        for line in lines:
            line = line.strip()
            if not line or line == '————':
                continue
            
            # 第一行：名字 势力
            if not hero_data['name'] and ' ' in line:
                parts = line.split()
                hero_data['name'] = parts[0]
                hero_data['faction'] = parts[1] if len(parts) > 1 else ''
                hero_data['id'] = self.name_to_id(hero_data['name'])
                hero_data['image'] = f"{hero_data['id']}.png"
                continue
            
            # 称号
            if line.startswith('称号:') or line.startswith('称号：'):
                hero_data['title'] = line.split(':', 1)[1].strip() if ':' in line else line.split('：', 1)[1].strip()
            
            # 编号
            elif line.startswith('编号:') or line.startswith('编号：'):
                hero_data['code'] = line.split(':', 1)[1].strip() if ':' in line else line.split('：', 1)[1].strip()
            
            # 体力
            elif line.startswith('体力:') or line.startswith('体力：'):
                try:
                    hp_text = line.split(':', 1)[1].strip() if ':' in line else line.split('：', 1)[1].strip()
                    hero_data['max_hp'] = int(hp_text)
                except:
                    pass
            
            # 画师
            elif line.startswith('画师:') or line.startswith('画师：'):
                hero_data['artist'] = line.split(':', 1)[1].strip() if ':' in line else line.split('：', 1)[1].strip()
            
            # 技能开始
            elif line.startswith('技能:') or line.startswith('技能：'):
                continue
            
            # 技能内容（格式：技能名：描述）
            elif '：' in line or ':' in line:
                if current_skill:
                    hero_data['skills'].append(current_skill)
                
                parts = line.split('：', 1) if '：' in line else line.split(':', 1)
                skill_name = parts[0].strip()
                skill_desc = parts[1].strip() if len(parts) > 1 else ''
                
                current_skill = {
                    "name": skill_name,
                    "description": skill_desc,
                    "type": self.detect_skill_type(skill_desc),
                    "trigger": "UNKNOWN"
                }
        
        # 添加最后一个技能
        if current_skill:
            hero_data['skills'].append(current_skill)
        
        # 生成世界书
        hero_data['worldbook'] = self.generate_worldbook(hero_data)
        
        return hero_data
    
    def name_to_id(self, name):
        """中文名转ID"""
        name_map = {
            '刘备': 'liubei', '关羽': 'guanyu', '张飞': 'zhangfei',
            '诸葛亮': 'zhugeliang', '赵云': 'zhaoyun', '马超': 'machao',
            '黄月英': 'huangyueying',
            '曹操': 'caocao', '司马懿': 'simayi', '夏侯惇': 'xiahoudun',
            '张辽': 'zhangliao', '许褚': 'xuchu', '郭嘉': 'guojia',
            '甄姬': 'zhenji',
            '孙权': 'sunquan', '甘宁': 'ganning', '吕蒙': 'lvmeng',
            '黄盖': 'huanggai', '周瑜': 'zhouyu', '大乔': 'daqiao',
            '陆逊': 'luxun',
            '华佗': 'huatuo', '吕布': 'lvbu', '貂蝉': 'diaochan',
            '华雄': 'huaxiong', '袁绍': 'yuanshao', '张角': 'zhangjiao'
        }
        return name_map.get(name, name.lower())
    
    def detect_skill_type(self, description):
        """检测技能类型"""
        if '主公技' in description:
            return 'lord'
        elif '锁定技' in description:
            return 'forced'
        elif '限定技' in description:
            return 'limited'
        elif '觉醒技' in description:
            return 'awaken'
        else:
            return 'active'
    
    def generate_worldbook(self, hero_data):
        """生成世界书内容"""
        skills_text = '\n'.join([
            f"【{s['name']}】{s['description']}" 
            for s in hero_data['skills']
        ])
        
        return {
            "summary": f"{hero_data['name']}，{hero_data['faction']}势力武将，{hero_data['title']}。体力值{hero_data['max_hp']}点。",
            "skill_details": f"技能详解：\n{skills_text}",
            "usage_tips": f"使用{hero_data['name']}时，注意灵活运用技能配合。",
            "combos": [],
            "counters": []
        }
    
    async def convert_with_ai(self, text):
        """使用AI转换（备用方案）"""
        if not self.api_config.get('apiKey'):
            return None
        
        prompt = f"""请将以下三国杀武将数据转换为JSON格式：

{text}

要求JSON格式：
{{
  "id": "武将拼音id",
  "name": "武将名",
  "faction": "势力",
  "title": "称号",
  "code": "编号",
  "max_hp": 体力数字,
  "artist": "画师",
  "skills": [
    {{
      "name": "技能名",
      "description": "技能描述",
      "type": "技能类型"
    }}
  ]
}}

只返回JSON，不要其他内容。"""
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.api_config['apiUrl']}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_config['apiKey']}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.api_config['model'],
                        "messages": [
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.3
                    }
                )
                
                if response.status_code == 200:
                    result = response.json()
                    json_text = result['choices'][0]['message']['content']
                    # 提取JSON
                    json_match = re.search(r'\{.*\}', json_text, re.DOTALL)
                    if json_match:
                        hero_data = json.loads(json_match.group())
                        hero_data['worldbook'] = self.generate_worldbook(hero_data)
                        return hero_data
        except Exception as e:
            print(f"AI转换失败: {e}")
        
        return None
    
    async def convert(self, text):
        """转换主函数"""
        # 先尝试规则解析
        try:
            hero_data = self.parse_tieba_text(text)
            if hero_data['name']:
                return hero_data
        except Exception as e:
            print(f"规则解析失败: {e}")
        
        # 如果启用AI且规则解析失败，使用AI
        if self.use_ai:
            print("使用AI进行转换...")
            return await self.convert_with_ai(text)
        
        return None

def main():
    """命令行工具"""
    if len(sys.argv) < 2:
        print("用法: python hero_converter.py <贴吧文本文件>")
        print("或: python hero_converter.py --ai <文本文件> <api_key>")
        sys.exit(1)
    
    use_ai = '--ai' in sys.argv
    
    if use_ai:
        text_file = sys.argv[2]
        api_key = sys.argv[3] if len(sys.argv) > 3 else None
        api_config = {
            'apiUrl': 'https://api.deepseek.com/v1',
            'apiKey': api_key,
            'model': 'deepseek-chat'
        }
    else:
        text_file = sys.argv[1]
        api_config = None
    
    # 读取文本
    with open(text_file, 'r', encoding='utf-8') as f:
        text = f.read()
    
    # 转换
    converter = HeroConverter(use_ai=use_ai, api_config=api_config)
    hero_data = asyncio.run(converter.convert(text))
    
    if hero_data:
        # 输出JSON
        output_file = text_file.replace('.txt', '.json')
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(hero_data, f, ensure_ascii=False, indent=2)
        
        print(f"✅ 转换成功！")
        print(f"输出文件: {output_file}")
        print(f"武将: {hero_data['name']} ({hero_data['faction']})")
        print(f"技能数: {len(hero_data['skills'])}")
    else:
        print("❌ 转换失败")

if __name__ == '__main__':
    main()
