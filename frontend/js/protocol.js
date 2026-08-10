// 自动生成，勿手改。来源：game_engine/protocol.py，由 scripts/gen_protocol_js.py 生成。
'use strict';
const Protocol = {
  VERSION: "1.0",
  INBOUND: {
  CREATE_GAME: "create_game",   PLAYER_ACTION: "player_action",   CHAT: "chat",   CARD_ANIMATION_DONE: "card_animation_done",   END_GAME: "end_game",   UPDATE_AI_CONFIG: "update_ai_config",   PING: "ping",   SERVER_INFO: "server_info"
  },
  OUTBOUND: {
  PONG: "pong",   SERVER_INFO: "server_info",   GAME_CREATED: "game_created",   GAME_STATE: "game_state",   YOUR_TURN: "your_turn",   REQUIRE_RESPONSE: "require_response",   ACTION_RESULT: "action_result",   AI_ACTION: "ai_action",   CHAT: "chat",   EVENT_NOTIFICATION: "event_notification",   AI_CONFIG_UPDATED: "ai_config_updated",   END_GAME_ACCEPTED: "end_game_accepted",   GAME_END: "game_end",   ERROR: "error"
  },
  PROVIDERS: [
  {
    "value": "qwen",
    "name": "通义千问",
    "default_model": "qwen-plus",
    "default_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"
  },
  {
    "value": "deepseek",
    "name": "DeepSeek",
    "default_model": "deepseek-chat",
    "default_url": "https://api.deepseek.com/v1"
  },
  {
    "value": "openai",
    "name": "OpenAI",
    "default_model": "gpt-4o-mini",
    "default_url": "https://api.openai.com/v1"
  },
  {
    "value": "gemini",
    "name": "Gemini",
    "default_model": "gemini-2.0-flash-exp",
    "default_url": "https://generativelanguage.googleapis.com/v1beta"
  },
  {
    "value": "claude",
    "name": "Claude",
    "default_model": "claude-3-5-sonnet-20241022",
    "default_url": "https://api.anthropic.com/v1"
  },
  {
    "value": "glm",
    "name": "智谱GLM",
    "default_model": "glm-4-flash",
    "default_url": "https://open.bigmodel.cn/api/paas/v4"
  },
  {
    "value": "grok",
    "name": "Grok",
    "default_model": "grok-2-latest",
    "default_url": "https://api.x.ai/v1"
  },
  {
    "value": "doubao",
    "name": "豆包",
    "default_model": "doubao-pro-32k",
    "default_url": "https://ark.cn-beijing.volces.com/api/v3"
  }
],
};
if (typeof module !== 'undefined' && module.exports) module.exports = Protocol;
