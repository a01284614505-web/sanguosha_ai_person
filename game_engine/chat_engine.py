#!/usr/bin/env python3
"""聊天引擎 - AI对话系统"""

import asyncio
import random
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

class ChatEngine:
    def __init__(self, ai_gateway):
        self.gateway = ai_gateway
        self.last_chat_time = {}
        self.chat_cooldown = 8  # 8秒冷却
    
    async def trigger_event_chat(self, event_type: str, player, context: Dict):
        """事件触发对话"""
        # 只对有API key的AI触发
        if not player.is_ai:
            return None
        
        api_key = player.ai_config.get('api_key', '')
        if not api_key or api_key == 'test_key' or len(api_key) < 10:
            return None
        
        # 冷却检查
        now = asyncio.get_event_loop().time()
        last = self.last_chat_time.get(player.id, 0)
        if now - last < self.chat_cooldown:
            return None
        
        # 构建对话prompt
        prompt = self.build_chat_prompt(event_type, player, context)
        
        try:
            response = await self.gateway.call_api(
                provider=player.ai_config.get('provider', 'deepseek'),
                model=player.ai_config.get('model', 'deepseek-chat'),
                api_key=api_key,
                messages=[
                    {"role": "system", "content": f"你是{player.hero.get('name', player.name)}，三国武将。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.9
            )
            
            # 提取对话（限制30字）
            msg = response.strip()[:30]
            self.last_chat_time[player.id] = now
            
            return msg
        except Exception:
            logger.warning("聊天AI调用失败", exc_info=True)
            return None
    
    def build_chat_prompt(self, event_type: str, player, context: Dict) -> str:
        """构建对话prompt"""
        prompts = {
            'damage_dealt': f"你刚对{context.get('target_name', '敌人')}造成了伤害。请说一句符合{player.hero.get('name', '你')}性格的话，不超过15字。",
            'damage_received': f"你受到了{context.get('damage', 1)}点伤害。请说一句符合{player.hero.get('name', '你')}性格的话，不超过15字。",
            'kill': f"你击杀了{context.get('target_name', '敌人')}。请说一句胜利宣言，不超过15字。",
            'turn_start': f"轮到你的回合。请说一句开场白，不超过15字。"
        }
        
        return prompts.get(event_type, "说一句话，不超过15字。")

__all__ = ['ChatEngine']
