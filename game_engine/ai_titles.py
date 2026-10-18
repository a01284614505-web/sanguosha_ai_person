"""Data-driven title rules shared by human and AI player records."""

from __future__ import annotations

import json
from pathlib import Path

TITLE_PATH = Path(__file__).resolve().parents[1] / "data" / "ai_titles.json"
TIER_RANK = {"普通": 1, "高级": 2, "稀有": 3}
DEFAULT_AI_NAMES = ("诸葛村夫", "曹操的粉丝", "小乔我老婆", "酒馆常客")
NO_TITLE = "__none__"


def title_catalog():
    try:
        rows = json.loads(TITLE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [row for row in rows if isinstance(row, dict) and row.get("id") and row.get("name")]


def earned_titles(stats):
    stats = stats if isinstance(stats, dict) else {}
    return [row["id"] for row in title_catalog()
            if int(stats.get(row.get("metric"), 0) or 0) >= int(row.get("threshold", 1))]


def highest_title(stats):
    catalog = {row["id"]: row for row in title_catalog()}
    earned = [catalog[key] for key in earned_titles(stats) if key in catalog]
    return max(earned, key=lambda row: (TIER_RANK.get(row.get("tier"), 0),
                                        int(row.get("threshold", 0)))) if earned else None


def title_view(stats, equipped=None):
    catalog = {row["id"]: row for row in title_catalog()}
    earned = earned_titles(stats)
    selected = None if equipped == NO_TITLE else catalog.get(equipped) if equipped in earned else highest_title(stats)
    return {"earned": [catalog[key] for key in earned if key in catalog],
            "equipped": selected}


def _deep_cover_award(payload, player):
    """Only the engine's complete, round-covered hidden-player decision can award this."""
    if not player or player.get("identity") not in ("loyalist", "rebel", "spy"):
        return False
    target_id = player.get("id")
    hidden_players = payload.get("_title_hidden_players")
    return isinstance(hidden_players, list) and target_id in hidden_players


def _spy_lord_award(payload, player):
    return (payload.get("winner") == "spy" and payload.get("spy_duel_lord") is True
            and player.get("identity") == "spy" and player.get("alive") is not False)


def update_player_stats(stats, player, payload, won, *, previous_streak=0, reset_streak=False):
    stats = dict(stats or {})
    stats["total_games"] = int(stats.get("total_games", 0)) + 1
    if won:
        stats["wins"] = int(stats.get("wins", 0)) + 1
        stats["win_streak"] = int(previous_streak) + 1
        identity = player.get("identity")
        key = {"lord": "lord_wins", "loyalist": "loyalist_wins", "rebel": "rebel_wins", "spy": "spy_wins"}.get(identity)
        if key:
            stats[key] = int(stats.get(key, 0)) + 1
        if _spy_lord_award(payload, player):
            stats["spy_lord_wins"] = int(stats.get("spy_lord_wins", 0)) + 1
        if _deep_cover_award(payload, player):
            stats["deep_cover_wins"] = int(stats.get("deep_cover_wins", 0)) + 1
    elif payload.get("winner") in ("lord", "rebel", "spy", "draw") or reset_streak:
        stats["win_streak"] = 0
    if (payload.get("mvp") or {}).get("player_id") == player.get("id"):
        stats["mvp"] = int(stats.get("mvp", 0)) + 1
    try:
        death_round = int(player.get("death_round"))
    except (TypeError, ValueError):
        death_round = 0
    if (payload.get("winner") in ("lord", "rebel", "spy", "draw")
            and player.get("alive") is False and death_round == 1):
        stats["first_death"] = int(stats.get("first_death", 0)) + 1
    return stats

