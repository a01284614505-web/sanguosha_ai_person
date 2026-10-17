#!/usr/bin/env python3
"""聊天引擎 - AI对话系统

过渡实现：Stage T 的 chat_director 落地后整体替换。
连接参数（Provider / 模型 / Key / 地址）与出牌决策共用 model_call_kwargs，
同一个 AI 只有一份配置。
"""

import asyncio
import logging
from typing import Dict, Set

import httpx

from .ai_decision import model_call_kwargs

logger = logging.getLogger(__name__)

# 这些状态码说明配置本身有问题（Key 无效、无权限、地址不对），重试也不会好。
_PERMANENT_STATUS = {401, 403, 404}


class ChatEngine:
    def __init__(self, ai_gateway):
        self.gateway = ai_gateway
        self.last_chat_time = {}
        self.chat_cooldown = 8  # 8秒冷却
        # 本局已因配置错误停用聊天的座位：只警告一次，之后不再发请求。
        self._muted: Set[int] = set()

    async def trigger_event_chat(self, event_type: str, player, context: Dict):
        """事件触发对话"""
        # 只对有API key的AI触发
        if not player.is_ai:
            return None

        api_key = player.ai_config.get('api_key', '')
        if not api_key or api_key == 'test_key' or len(api_key) < 10:
            return None
        if player.id in self._muted:
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
                **model_call_kwargs(player),
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
        except asyncio.CancelledError:
            raise
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in _PERMANENT_STATUS:
                self._muted.add(player.id)
                logger.warning("聊天AI调用失败（HTTP %s），本局不再为 %s 发起聊天，请检查该座位的 Key 与 API 地址",
                               status, player.name)
            else:
                logger.warning("聊天AI调用失败（HTTP %s）：%s", status, player.name)
            logger.debug("聊天AI调用失败详情", exc_info=True)
            return None
        except ValueError as exc:
            # 例如 claude/gemini 未提供 OpenAI 兼容地址：配置问题，同样只提示一次。
            self._muted.add(player.id)
            logger.warning("聊天AI配置不可用，本局不再为 %s 发起聊天：%s", player.name, exc)
            return None
        except Exception as exc:
            logger.warning("聊天AI调用失败（%s）：%s", type(exc).__name__, player.name)
            logger.debug("聊天AI调用失败详情", exc_info=True)
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
