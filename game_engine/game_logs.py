"""局后对局日志：每局结束自动保存一份（无痕模式除外），供日志页查看、下载与删除。

存储位置：``<root>/<profile_id>/<game_id>.json``，每个浏览器档案一个目录。
日志里绝不出现 API Key：AI 只记录服务商与模型名（取自已脱敏的 serialize()）。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .game_history import validate_profile_id
from .prompt_trace import redact
from .token_usage import USAGE_KINDS, empty_bucket

LOG_SCHEMA = 1
GAME_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_TIMELINE = 4000
# 运行时的系统提示（已连接、阶段切换等）对复盘没有价值，不写进时间线。
SKIP_KINDS = {"phase"}


def validate_game_id(value):
    if not isinstance(value, str) or not GAME_ID.fullmatch(value):
        raise ValueError("game_id 格式错误")
    return value


def _player_summary(p: Dict, stats: Dict) -> Dict:
    ai = p.get("ai_config") or {}
    pid = p.get("id")
    return {
        "id": pid,
        "seat": p.get("seat"),
        "name": p.get("name"),
        "hero": p.get("hero_name") or (p.get("hero") or {}).get("name"),
        "identity": p.get("identity"),
        "alive": p.get("alive"),
        "is_ai": p.get("is_ai"),
        "provider": ai.get("provider") if p.get("is_ai") else None,
        "model": ai.get("model") if p.get("is_ai") else None,
        "stats": p.get("stats") or (stats or {}).get(str(pid)) or (stats or {}).get(pid) or {},
    }


def _token_usage_summary(engine) -> List[Dict]:
    """每个 AI 座位一行，四类调用各一组计数；只含座位名与服务商/模型名，不含任何 Key 或地址。"""
    usage = getattr(engine, "usage_stats", None) or {}
    rows = []
    for p in getattr(getattr(engine, "game_state", None), "players", None) or []:
        if not p.is_ai:
            continue
        ai = p.ai_config or {}
        seat = usage.get(p.id) or {}
        rows.append({
            "id": p.id,
            "name": p.name,
            "provider": ai.get("provider"),
            "model": ai.get("model"),
            "kinds": {kind: dict(empty_bucket(), **(seat.get(kind) or {})) for kind in USAGE_KINDS},
        })
    return rows


def build_game_log(engine, game_end: Dict, *, include_thinking: bool) -> Dict:
    """从引擎与 game_end 载荷组装日志。只读，不改引擎状态。"""
    state = game_end.get("state") or {}
    stats = game_end.get("stats") or {}
    config = engine.game_config or {}
    timeline: List[Dict] = []
    for entry in list(getattr(engine, "game_log", []))[-MAX_TIMELINE:]:
        if entry.get("event_kind") in SKIP_KINDS:
            continue
        message = entry.get("message")
        if not message:
            continue
        timeline.append({"seq": entry.get("seq"), "round": entry.get("round"), "kind": entry.get("event_kind") or "log",
                         "text": str(message)[:300]})
    ledger = getattr(engine, "ledger", None)
    decisions = []
    if include_thinking:
        decisions = [dict(d) for d in getattr(engine, "decision_log", [])]
    else:
        # 不含思考过程：只保留“谁在第几轮做了什么”，去掉理由。
        decisions = [{k: v for k, v in d.items() if k != "reason"} for d in getattr(engine, "decision_log", [])]
    return redact({
        "prompt_traces": [trace for traces in getattr(getattr(engine, "ai_decision", None), "prompt_traces", {}).values() for trace in traces] if include_thinking else [],
        "schema": LOG_SCHEMA,
        "game_id": engine.game_id,
        "profile_id": config.get("profile_id"),
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "mode": config.get("mode"),
        "deck_id": config.get("deck_id") or state.get("deck_id"),
        "winner": game_end.get("winner"),
        "message": game_end.get("message"),
        "duration": game_end.get("duration"),
        "rounds": state.get("round"),
        "options": {
            "cheat_mode": bool(getattr(engine, "cheat_mode", False)),
            "hide_dead_identity": bool(getattr(engine, "hide_dead_identity", False)),
            "chat_enabled": bool(getattr(engine, "chat_enabled", True)),
            "include_thinking": include_thinking,
        },
        "players": [_player_summary(p, stats) for p in state.get("players") or []],
        "mvp": game_end.get("mvp"),
        "timeline": timeline,
        "plan_snapshots": [{"round": s["round"], "player_id": s["player_id"], "seat": s.get("seat"), "plan": s["plan"]}
                           for s in getattr(getattr(engine, "notes", None), "snapshots", []) if s.get("plan")],
        "notes_diagnostics": list(getattr(getattr(engine, "ai_decision", None), "notes_diagnostics", [])),
        "blocked_chat": list(getattr(engine, "blocked_chat", [])),
        "chat": list(getattr(engine, "chat_log", []))[-1000:],
        "decisions": decisions[-2000:],
        "token_usage": _token_usage_summary(engine),
        # 行为账本流水（Stage T · T1）：均为公开事实，不含手牌区牌名与任何隐藏信息。
        "ledger": ledger.snapshot() if ledger is not None else [],
        # 认知笔记快照（Stage T · T2）：每个模型 AI 每轮一份，非作弊局也写（对局结束后才落盘，不影响游戏体验）。
        "cognitive_notes": [dict(item) for item in getattr(getattr(engine, "notes", None), "snapshots", [])],
    }, engine)


class GameLogStore:
    def __init__(self, root):
        self.root = Path(root)
        self._lock = threading.RLock()

    def _dir(self, profile_id) -> Path:
        return self.root / validate_profile_id(profile_id)

    def save(self, record: Dict) -> Path:
        profile_dir = self._dir(record.get("profile_id"))
        game_id = validate_game_id(str(record.get("game_id")))
        with self._lock:
            profile_dir.mkdir(parents=True, exist_ok=True)
            target = profile_dir / f"{game_id}.json"
            fd, temp = tempfile.mkstemp(prefix=".log.", dir=profile_dir)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(record, stream, ensure_ascii=False, separators=(",", ":"))
                os.replace(temp, target)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
            return target

    def list(self, profile_id) -> List[Dict]:
        profile_dir = self._dir(profile_id)
        items = []
        if not profile_dir.is_dir():
            return items
        for path in profile_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            me = next((p for p in data.get("players") or [] if p.get("is_ai") is False), {})
            items.append({
                "game_id": data.get("game_id"), "ended_at": data.get("ended_at"),
                "winner": data.get("winner"), "message": data.get("message"),
                "rounds": data.get("rounds"), "duration": data.get("duration"),
                "hero": me.get("hero"), "identity": me.get("identity"),
                "cheat": (data.get("options") or {}).get("cheat_mode", False),
                "size": path.stat().st_size,
            })
        items.sort(key=lambda item: item.get("ended_at") or "", reverse=True)
        return items

    def get(self, profile_id, game_id) -> Optional[Dict]:
        path = self._dir(profile_id) / f"{validate_game_id(game_id)}.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def delete(self, profile_id, game_ids: Optional[Iterable[str]] = None, *, delete_all=False) -> int:
        profile_dir = self._dir(profile_id)
        if not profile_dir.is_dir():
            return 0
        with self._lock:
            if delete_all:
                paths = list(profile_dir.glob("*.json"))
            else:
                paths = [profile_dir / f"{validate_game_id(str(g))}.json" for g in (game_ids or [])]
            removed = 0
            for path in paths:
                if path.is_file():
                    path.unlink()
                    removed += 1
            return removed


__all__ = ["GameLogStore", "build_game_log", "validate_game_id"]
