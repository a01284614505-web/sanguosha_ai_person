"""有界的真实请求快照；只记录 messages，不记录请求凭据或 API 地址。"""
from collections import deque
from .seats import seat_of
from urllib.parse import quote

MAX_CALLS_PER_PLAYER = 12


def redact(value, engine):
    secrets = set()

    def collect(obj):
        if isinstance(obj, dict):
            for key, item in obj.items():
                if str(key).lower() in ("api_key", "authorization", "access_token") and isinstance(item, str) and item:
                    secrets.add(item)
                else:
                    collect(item)
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                collect(item)

    collect(getattr(engine, "game_config", {}))
    for player in getattr(getattr(engine, "game_state", None), "players", []) or []:
        collect(getattr(player, "ai_config", {}))
    for secret in list(secrets):
        secrets.add(quote(secret, safe=""))

    def clean(obj):
        if isinstance(obj, str):
            for secret in sorted(secrets, key=len, reverse=True):
                obj = obj.replace(secret, "[REDACTED]")
            return obj
        if isinstance(obj, dict):
            return {clean(str(k)): "[REDACTED]" if str(k).lower() in
                    ("api_key", "authorization", "access_token") else clean(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, deque)):
            return [clean(v) for v in obj]
        return obj

    return clean(value)


def capture(engine, player, kind, messages):
    settings = (getattr(engine, "game_config", {}) or {}).get("global_settings") or {}
    if settings.get("log_include_thinking") is False or settings.get("log_incognito") is True:
        return
    ai = engine.ai_decision
    traces = getattr(ai, "prompt_traces", None)
    if traces is None:
        ai.prompt_traces = traces = {}
    bucket = traces.setdefault(player.id, deque(maxlen=MAX_CALLS_PER_PLAYER))
    bucket.append(redact({"player_id": player.id, "seat": seat_of(engine.game_state, player.id),
                          "round": engine.game_state.round_number, "kind": kind,
                          "messages": messages}, engine))
