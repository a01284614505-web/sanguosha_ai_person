#!/usr/bin/env python3
'''开局配置规范化：所有游戏域校验均由引擎拥有。'''
import copy
import os
from pathlib import Path
from .chat_director import DEFAULT_CHAT_LEVEL, normalize_level
from .deck_manager import DECKS, DeckManager
from .hero_registry import HeroRegistry
from .mode_registry import get_mode
DEFAULT_API_KEY = os.getenv("SANGUOSHA_DEFAULT_API_KEY", "")
def normalize_ai(raw_ai, use_default=True):
    ai = copy.deepcopy(raw_ai or {})
    ai["name"] = ai.get("name") or "AI玩家"
    ai["provider"] = (ai.get("provider") or "deepseek").lower()
    ai["model"] = ai.get("model") or "deepseek-chat"
    ai["api_url"] = ai.get("api_url") or ai.get("apiUrl") or ""
    supplied_key = ai.get("api_key") or ai.get("apiKey")
    ai["api_key"] = supplied_key if supplied_key is not None else (
        DEFAULT_API_KEY if use_default else ""
    )
    try:
        ai["temperature"] = float(ai.get("temperature", 0.8))
    except (TypeError, ValueError):
        ai["temperature"] = 0.8
    return ai
# 只能由服务器决定的运行参数：浏览器发来的同名字段一律丢弃，使用服务器默认值。
# 其中 idle_abort_seconds 是"5 分钟离席"铁规则，绝不能由客户端改写。
SERVER_ONLY_KEYS = (
    "idle_abort_seconds", "idle_check_interval", "max_turns",
    "human_action_timeout", "response_timeout", "phase_delay", "turn_delay",
    "session_max_l2", "session_max_chars", "session_variable_max_chars",
)


def sanitize_client_config(raw_config):
    """浏览器开局配置的入口过滤：去掉服务器专属参数，真人座位不能自称 AI。"""
    if not isinstance(raw_config, dict):
        raise ValueError("config必须是JSON对象")
    cfg = {key: value for key, value in raw_config.items() if key not in SERVER_ONLY_KEYS}
    player = cfg.get("player")
    if isinstance(player, dict):
        player = dict(player)
        player["is_ai"] = False
        player.pop("ai_config", None)
        cfg["player"] = player
    return cfg


def normalize_config(raw_config, project_root=None, hero_registry=None):
    if not isinstance(raw_config, dict):
        raise ValueError("config必须是JSON对象")
    cfg = copy.deepcopy(raw_config)
    cfg.setdefault("mode", "5人身份局")
    mode = get_mode(cfg["mode"])
    if mode.assignment == "fixed" and (cfg.get("identity_card") or {}).get("use"):
        raise ValueError(f"{mode.mode_id}不支持身份卡")
    ais = cfg.get("ais") or []
    if len(ais) != mode.ai_count:
        raise ValueError(f"{mode.mode_id}需要{mode.ai_count}个AI，当前收到{len(ais)}个")
    root = Path(project_root or Path(__file__).resolve().parents[1]).resolve()
    heroes = hero_registry or HeroRegistry(root)
    selected_hero = cfg.get("selected_hero") or {}
    player_cfg = cfg.get("player") or {}
    player_cfg.setdefault("name", cfg.get("player_name", "玩家"))
    player_cfg.setdefault("is_ai", False)
    player_cfg["hero"] = heroes.canonical_hero(
        player_cfg.get("hero") or selected_hero, 0
    )
    if player_cfg.get("is_ai") and not player_cfg.get("ai_config"):
        player_cfg["ai_config"] = normalize_ai(player_cfg, use_default=False)
    cfg["player"] = player_cfg
    normalized_ais = []
    used_hero_ids = {player_cfg.get("hero", {}).get("id")}
    for index, raw_ai in enumerate(ais, start=1):
        ai = normalize_ai(raw_ai, use_default=True)
        ai["hero"] = heroes.canonical_hero(ai.get("hero"), index, used_hero_ids)
        used_hero_ids.add(ai.get("hero", {}).get("id"))
        normalized_ais.append(ai)
    cfg["ais"] = normalized_ais
    requested_deck = cfg.get("deck_id")
    if requested_deck:
        deck_id = DeckManager.normalize_deck_id(requested_deck)
        if deck_id not in DECKS:
            raise ValueError(f"未知牌堆ID: {requested_deck}")
        cfg["deck_id"] = deck_id
    # 开局锁定的布尔选项：只接受 true，其它值一律视为关闭。
    cfg["cheat_mode"] = cfg.get("cheat_mode") is True
    cfg["ai_spectate"] = cfg.get("ai_spectate", True) is True
    cfg["hide_dead_identity"] = cfg.get("hide_dead_identity") is True
    # 热闹程度：缺省为正常档；给了就必须是合法档位（非法值直接拒绝，不静默回落）。
    cfg["chat_level"] = normalize_level(cfg.get("chat_level") or DEFAULT_CHAT_LEVEL)
    cfg.setdefault("max_turns", 300)
    cfg.setdefault("human_action_timeout", 120)
    cfg.setdefault("phase_delay", 0.05)
    cfg.setdefault("turn_delay", 0.1)
    # 模型会话的动态历史预算由服务端固定；稳定 L0/L1 前缀不计入此限额。
    cfg.setdefault("session_variable_max_chars", 8000)
    return cfg
__all__ = ["normalize_config", "sanitize_client_config", "SERVER_ONLY_KEYS"]
