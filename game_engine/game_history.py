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

from .ai_titles import DEFAULT_AI_NAMES, NO_TITLE, title_view, update_player_stats


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
    return {"win_streak": 0, "total_games": 0, "identity_cards": 0, "history": [], "ai_players": {}}


# 见面礼：每个档案第一次出现时送一张身份卡（老档案在下次读取时补发一次）。
WELCOME_CARDS = 1


def _grant_welcome(profile):
    """未领过见面礼的档案补一张身份卡；返回是否发生了变化。"""
    if profile.get("welcome_card"):
        return False
    profile["identity_cards"] = int(profile.get("identity_cards", 0)) + WELCOME_CARDS
    profile["welcome_card"] = True
    return True


def _profile_entry(data, profile_id):
    profile = data["profiles"].setdefault(profile_id, _empty_profile())
    # Existing Stage T profiles predate persistent AI rosters.
    if not isinstance(profile.get("ai_players"), dict):
        profile["ai_players"] = {}
    _grant_welcome(profile)
    return profile


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
            profile = data["profiles"].get(profile_id)
            if profile is None:
                # 新档案还没写过盘：直接按“已领见面礼”展示，第一次写入时才真正落盘。
                fresh = _empty_profile()
                _grant_welcome(fresh)
                fresh["titles"] = title_view({})
                return fresh
            if _grant_welcome(profile):
                self._save(data)
            result = dict(profile)
            result.pop("ai_players", None)
            result["titles"] = title_view(profile.get("title_stats"), profile.get("equipped_title"))
            return result

    @staticmethod
    def _ai_id(value):
        return value if isinstance(value, str) and value in {f"ai_{i}" for i in range(1, 5)} else None

    def ai_players(self, profile_id):
        """Return the four stable AI accounts belonging to one browser profile."""
        profile_id = validate_profile_id(profile_id)
        with self._lock:
            data = self._load()
            profile = _profile_entry(data, profile_id)
            changed = False
            result = []
            for index, name in enumerate(DEFAULT_AI_NAMES, start=1):
                key = f"ai_{index}"
                row = profile["ai_players"].get(key)
                if not isinstance(row, dict):
                    row = {"id": key, "name": name, "stats": {}, "history": [], "equipped_title": None}
                    profile["ai_players"][key] = row
                    changed = True
                result.append({**row, "titles": title_view(row.get("stats"), row.get("equipped_title"))})
            if changed:
                self._save(data)
            return result

    def update_ai_player(self, profile_id, ai_id, *, name=None, equipped_title=None):
        profile_id = validate_profile_id(profile_id)
        ai_id = self._ai_id(ai_id)
        if ai_id is None:
            raise ValueError("AI 选手编号无效")
        with self._lock:
            data = self._load()
            profile = _profile_entry(data, profile_id)
            if not isinstance(profile.get("ai_players", {}).get(ai_id), dict):
                self.ai_players(profile_id)
                data = self._load()
                profile = data["profiles"][profile_id]
            row = profile["ai_players"][ai_id]
            if name is not None:
                clean = " ".join(str(name).split())[:16]
                if not clean:
                    raise ValueError("AI 名称不能为空")
                row["name"] = clean
            earned_ids = {item["id"] for item in title_view(row.get("stats"), row.get("equipped_title"))["earned"]}
            if equipped_title not in (None, "", NO_TITLE) and equipped_title not in earned_ids:
                raise ValueError("只能佩戴已获得的称号")
            if equipped_title is not None:
                row["equipped_title"] = NO_TITLE if equipped_title == NO_TITLE else equipped_title or None
            self._save(data)
            return {**row, "titles": title_view(row.get("stats"), row.get("equipped_title"))}

    def update_profile_title(self, profile_id, equipped_title):
        profile_id = validate_profile_id(profile_id)
        with self._lock:
            data = self._load()
            profile = _profile_entry(data, profile_id)
            earned_ids = {item["id"] for item in title_view(profile.get("title_stats"))["earned"]}
            if equipped_title not in (None, "", NO_TITLE) and equipped_title not in earned_ids:
                raise ValueError("只能佩戴已获得的称号")
            profile["equipped_title"] = NO_TITLE if equipped_title == NO_TITLE else equipped_title or None
            self._save(data)
            result = dict(profile)
            result["titles"] = title_view(profile.get("title_stats"), profile.get("equipped_title"))
            return result

    def reserve_identity_card(self, profile_id, game_id):
        profile_id = validate_profile_id(profile_id)
        game_id = str(game_id)
        with self._lock:
            data = self._load()
            if game_id in data["card_uses"]:
                return data["card_uses"][game_id] == profile_id
            profile = _profile_entry(data, profile_id)
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
            profile = _profile_entry(data, profile_id)
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
            profile = _profile_entry(data, profile_id)
            profile["total_games"] += 1
            reward = None
            cheat = payload.get("cheat") is True
            reset_title_streak = (winner == "aborted" and self._round_of(payload) > INTERRUPT_GRACE_ROUNDS
                                  and not (human is not None and human.get("alive") is False))
            human_title_awards = []
            if not cheat:
                old_human_title_ids = {item["id"] for item in title_view(profile.get("title_stats"))["earned"]}
                profile["title_stats"] = update_player_stats(
                    profile.get("title_stats"), human or {}, payload, player_won is True,
                    previous_streak=(profile.get("title_stats") or {}).get("win_streak", 0),
                    reset_streak=reset_title_streak,
                )
                human_title_awards = [item for item in title_view(profile.get("title_stats"))["earned"]
                                      if item["id"] not in old_human_title_ids]
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
            ai_awards = []
            if not cheat:
                ai_players = profile.setdefault("ai_players", {})
                for fallback_id, player in enumerate((p for p in players if p.get("is_ai")), start=1):
                    if fallback_id > 4 and self._ai_id(player.get("ai_id")) is None:
                        continue
                    ai_id = self._ai_id(player.get("ai_id")) or f"ai_{fallback_id}"
                    ai = ai_players.setdefault(ai_id, {"id": ai_id, "name": DEFAULT_AI_NAMES[int(ai_id[-1]) - 1],
                                                       "stats": {}, "history": [], "equipped_title": None})
                    ai["name"] = str(player.get("name") or ai["name"])[:16]
                    ai_won = winner == "lord" and player.get("identity") in ("lord", "loyalist") or winner == player.get("identity")
                    old_title_ids = {item["id"] for item in title_view(ai.get("stats"), ai.get("equipped_title"))["earned"]}
                    ai["stats"] = update_player_stats(ai.get("stats"), player, payload, ai_won,
                                                       previous_streak=(ai.get("stats") or {}).get("win_streak", 0),
                                                       reset_streak=reset_title_streak)
                    ai_record = {"game_id": game_id, "ended_at": record["ended_at"], "winner": winner,
                                 "won": ai_won, "identity": player.get("identity"),
                                 "hero_name": player.get("hero_name", ""), "cheat": False}
                    ai.setdefault("history", []).insert(0, ai_record)
                    ai["history"] = ai["history"][:100]
                    new_ids = {item["id"] for item in title_view(ai.get("stats"))["earned"]}
                    ai_awards.extend({"ai_id": ai_id, "title": item} for item in title_view(ai.get("stats"))["earned"]
                                     if item["id"] not in old_title_ids and item["id"] in new_ids)
            result_profile = dict(profile)
            result_profile.pop("ai_players", None)
            result_profile["titles"] = title_view(profile.get("title_stats"), profile.get("equipped_title"))
            receipt = {"profile": result_profile, "reward": reward, "player_won": player_won,
                       "player_identity": identity, "cheat": cheat, "ai_title_awards": ai_awards,
                       "human_title_awards": human_title_awards,
                       "ai_players": [{"id": key, "name": row.get("name"),
                                       "titles": title_view(row.get("stats"), row.get("equipped_title"))}
                                      for key, row in profile.get("ai_players", {}).items()]}
            data["games"][game_id] = {"profile_id": profile_id, "receipt": receipt}
            self._save(data)
            return dict(receipt)
