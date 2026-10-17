"""Atomic, idempotent server-side match history for the five-player game."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1
# 中断局在第几轮之后才清零连胜（用户 2026-10-17 指定：第 2 轮之后）。
INTERRUPT_GRACE_ROUNDS = 2
PROFILE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class HistoryCorruptError(RuntimeError):
    pass


def validate_profile_id(value):
    if not isinstance(value, str) or not PROFILE_ID.fullmatch(value):
        raise ValueError("profile_id 格式错误")
    return value


def _empty_profile():
    return {"win_streak": 0, "total_games": 0, "identity_cards": 0, "history": []}


class GameHistoryStore:
    """One writer per process; replace the whole JSON file after each committed result."""

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def _load(self):
        if not self.path.exists():
            return {"schema_version": SCHEMA_VERSION, "profiles": {}, "games": {}, "card_uses": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if (not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION
                    or not all(isinstance(data.get(key), dict)
                               for key in ("profiles", "games", "card_uses"))):
                raise ValueError("unknown schema or invalid structure")
            return data
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup = self.path.with_name(f"{self.path.name}.corrupt.{stamp}")
            try:
                shutil.copy2(self.path, backup)
            except OSError:
                backup = self.path
            raise HistoryCorruptError(f"战绩文件损坏，原文件已保留：{backup}") from exc

    def _save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def profile(self, profile_id):
        profile_id = validate_profile_id(profile_id)
        with self._lock:
            data = self._load()
            return dict(data["profiles"].get(profile_id, _empty_profile()))

    def reserve_identity_card(self, profile_id, game_id):
        profile_id = validate_profile_id(profile_id)
        game_id = str(game_id)
        with self._lock:
            data = self._load()
            if game_id in data["card_uses"]:
                return data["card_uses"][game_id] == profile_id
            profile = data["profiles"].setdefault(profile_id, _empty_profile())
            if profile["identity_cards"] < 1:
                raise ValueError("身份卡不足")
            profile["identity_cards"] -= 1
            data["card_uses"][game_id] = profile_id
            self._save(data)
            return True

    def refund_identity_card(self, profile_id, game_id):
        """Undo a reservation only when the engine failed before a result was recorded."""
        profile_id = validate_profile_id(profile_id)
        game_id = str(game_id)
        with self._lock:
            data = self._load()
            if data["card_uses"].get(game_id) != profile_id or game_id in data["games"]:
                return False
            profile = data["profiles"].setdefault(profile_id, _empty_profile())
            profile["identity_cards"] += 1
            del data["card_uses"][game_id]
            self._save(data)
            return True

    @staticmethod
    def _round_of(payload):
        try:
            return int((payload.get("state") or {}).get("round") or 0)
        except (TypeError, ValueError):
            return 0

    def record_result(self, profile_id, game_id, payload):
        profile_id = validate_profile_id(profile_id)
        game_id = str(game_id)
        with self._lock:
            data = self._load()
            previous = data["games"].get(game_id)
            if previous is not None:
                if previous["profile_id"] != profile_id:
                    raise ValueError("对局 ID 已属于其他战绩档案")
                return dict(previous["receipt"])

            winner = payload.get("winner")
            players = (payload.get("state") or {}).get("players") or []
            human = next((p for p in players if p.get("is_ai") is False), None)
            identity = human.get("identity") if human else None
            player_won = None
            if winner in ("lord", "rebel", "spy"):
                player_won = (winner == "lord" and identity in ("lord", "loyalist")) or winner == identity
            profile = data["profiles"].setdefault(profile_id, _empty_profile())
            profile["total_games"] += 1
            reward = None
            cheat = payload.get("cheat") is True
            if cheat:
                pass  # 作弊局：照常记入历史，但不影响连胜与身份卡
            elif player_won is True:
                profile["win_streak"] += 1
                if profile["win_streak"] % 2 == 0:
                    profile["identity_cards"] += 1
                    reward = "identity_card"
            elif player_won is False or winner == "draw":
                profile["win_streak"] = 0
            elif (winner == "aborted" and self._round_of(payload) > INTERRUPT_GRACE_ROUNDS
                  and not (human is not None and human.get("alive") is False)):
                # 前两轮内退出不计；之后中断视同输掉连胜，防止快输时退出保连胜。
                # 真人已阵亡时的中止（观战超时等）不清零，也不加：过渡规则，见 Stage T 方案第 20 节 H 项。
                profile["win_streak"] = 0

            record = {
                "game_id": game_id,
                "ended_at": datetime.now(timezone.utc).isoformat(),
                "winner": winner,
                "player_won": player_won,
                "player_identity": identity,
                "hero_name": (human or {}).get("hero_name", ""),
                "duration": payload.get("duration", 0),
                "rounds": self._round_of(payload),
                "stats": (human or {}).get("stats") or {},
                "status": "interrupted" if winner == "aborted" else "completed",
                "cheat": cheat,
            }
            profile["history"].insert(0, record)
            profile["history"] = profile["history"][:100]
            receipt = {"profile": dict(profile), "reward": reward, "player_won": player_won,
                       "player_identity": identity, "cheat": cheat}
            data["games"][game_id] = {"profile_id": profile_id, "receipt": receipt}
            self._save(data)
            return dict(receipt)
