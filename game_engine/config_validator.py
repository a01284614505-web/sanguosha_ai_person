#!/usr/bin/env python3
'''开局配置规范化：所有游戏域校验均由引擎拥有。'''
import copy
import os
from pathlib import Path
from .deck_manager import DECKS, DeckManager
from .hero_registry import HeroRegistry
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
def normalize_config(raw_config, project_root=None, hero_registry=None):
    if not isinstance(raw_config, dict):
        raise ValueError("config必须是JSON对象")
    cfg = copy.deepcopy(raw_config)
    cfg.setdefault("mode", "5人身份局")
    if cfg["mode"] != "5人身份局":
        raise ValueError("P0当前只开放5人身份局；其他模式将在后续阶段实现")
    ais = cfg.get("ais") or []
    if len(ais) != 4:
        raise ValueError(f"5人身份局需要4个AI，当前收到{len(ais)}个")
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
    cfg.setdefault("max_turns", 300)
    cfg.setdefault("human_action_timeout", 120)
    cfg.setdefault("phase_delay", 0.05)
    cfg.setdefault("turn_delay", 0.1)
    return cfg
__all__ = ["normalize_config"]
