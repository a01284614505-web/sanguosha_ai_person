#!/usr/bin/env python3
"""协议单一真相源：入站/出站消息类型、Provider 清单与协议版本。

Python 侧唯一权威定义；`scripts/gen_protocol_js.py` 据此生成
`frontend/js/protocol.js` 供前端引用，二者同步由 `tests/test_protocol_sync.py`
断言。任何新消息类型、新 Provider 只改本文件。
"""

PROTOCOL_VERSION = "1.0"


class INBOUND:
    """前端 → 服务器（WebSocket 入站消息类型，8 种）。"""

    CREATE_GAME = "create_game"
    PLAYER_ACTION = "player_action"
    CHAT = "chat"
    CARD_ANIMATION_DONE = "card_animation_done"
    END_GAME = "end_game"
    UPDATE_AI_CONFIG = "update_ai_config"
    PING = "ping"
    SERVER_INFO = "server_info"


class OUTBOUND:
    """服务器 → 前端（WebSocket 出站消息类型，14 种）。"""

    PONG = "pong"
    SERVER_INFO = "server_info"
    GAME_CREATED = "game_created"
    GAME_STATE = "game_state"
    YOUR_TURN = "your_turn"
    REQUIRE_RESPONSE = "require_response"
    ACTION_RESULT = "action_result"
    AI_ACTION = "ai_action"
    CHAT = "chat"
    EVENT_NOTIFICATION = "event_notification"
    AI_CONFIG_UPDATED = "ai_config_updated"
    END_GAME_ACCEPTED = "end_game_accepted"
    GAME_END = "game_end"
    ERROR = "error"


class ENGINE_EVENT:
    """引擎事件名（ENGINE_EVENTS 的具名成员 + 特化事件）。引擎侧 emit、服务器侧注册一律引用本常量。"""

    STATE_CHANGED = "state_changed"
    YOUR_TURN = "your_turn"
    ACTION_RESULT = "action_result"
    AI_ACTION = "ai_action"
    CHAT = "chat"
    EVENT_NOTIFICATION = "event_notification"
    REQUIRE_RESPONSE = "require_response"
    GAME_END = "game_end"
    # 特化事件：卡牌动画，经专用 handler 转发（await_ui ACK 机制），不在 ENGINE_EVENTS 循环注册。
    CARD_ANIMATION = "card_animation"


# 引擎事件名 → 出站消息类型。未在此映射中的引擎事件名与出站类型同名透传。
ENGINE_EVENT_MAP = {
    ENGINE_EVENT.STATE_CHANGED: OUTBOUND.GAME_STATE,
    ENGINE_EVENT.EVENT_NOTIFICATION: OUTBOUND.EVENT_NOTIFICATION,
}


# 服务器创建对局时向引擎注册的事件名（引擎 emit 后由服务器转发）。
ENGINE_EVENTS = (
    ENGINE_EVENT.STATE_CHANGED,
    ENGINE_EVENT.YOUR_TURN,
    ENGINE_EVENT.ACTION_RESULT,
    ENGINE_EVENT.AI_ACTION,
    ENGINE_EVENT.CHAT,
    ENGINE_EVENT.EVENT_NOTIFICATION,
    ENGINE_EVENT.REQUIRE_RESPONSE,
    ENGINE_EVENT.GAME_END,
)

# Provider 清单（8 家）。default_url 均为 OpenAI 兼容端点；
# claude/gemini 原生协议未接入时，调用方需另行提供 base_url（见 AIGateway）。
PROVIDERS = [
    {"value": "qwen", "name": "通义千问", "default_model": "qwen-plus",
     "default_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
    {"value": "deepseek", "name": "DeepSeek", "default_model": "deepseek-chat",
     "default_url": "https://api.deepseek.com/v1"},
    {"value": "openai", "name": "OpenAI", "default_model": "gpt-4o-mini",
     "default_url": "https://api.openai.com/v1"},
    {"value": "gemini", "name": "Gemini", "default_model": "gemini-2.0-flash-exp",
     "default_url": "https://generativelanguage.googleapis.com/v1beta"},
    {"value": "claude", "name": "Claude", "default_model": "claude-3-5-sonnet-20241022",
     "default_url": "https://api.anthropic.com/v1"},
    {"value": "glm", "name": "智谱GLM", "default_model": "glm-4-flash",
     "default_url": "https://open.bigmodel.cn/api/paas/v4"},
    {"value": "grok", "name": "Grok", "default_model": "grok-2-latest",
     "default_url": "https://api.x.ai/v1"},
    {"value": "doubao", "name": "豆包", "default_model": "doubao-pro-32k",
     "default_url": "https://ark.cn-beijing.volces.com/api/v3"},
]

def _message_types(cls) -> list:
    """类中全部字符串常量（跳过 __module__/__doc__ 等 dunder 属性）。"""
    return [v for k, v in vars(cls).items() if isinstance(v, str) and not k.startswith("__")]


ALL_INBOUND = _message_types(INBOUND)
ALL_OUTBOUND = _message_types(OUTBOUND)
PROVIDER_VALUES = [p["value"] for p in PROVIDERS]
