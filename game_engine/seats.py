"""唯一的公开座次映射。内部 ID 保持不变；主公起按行动顺序编号，包含阵亡者。"""

IDENTITY_NAMES = {"lord": "主公", "loyalist": "忠臣", "rebel": "反贼", "spy": "内奸"}


def seat_map(state):
    players = list(getattr(state, "players", None) or [])
    fixed = getattr(state, "_public_seats", None)
    if fixed is not None:
        return fixed
    anchor = next((i for i, p in enumerate(players) if getattr(p, "identity", None) == "lord"), 0)
    ordered = players[anchor:] + players[:anchor]
    mapping = {p.id: i for i, p in enumerate(ordered, 1)}
    # 身份分配之前的预览不能锁定开局座次。
    if any(getattr(p, "identity", None) == "lord" for p in players):
        state._public_seats = mapping
    return mapping


def seat_of(state, player_id):
    return seat_map(state).get(player_id)


def player_of(state, seat):
    if type(seat) is not int:
        return None
    pid = next((pid for pid, number in seat_map(state).items() if number == seat), None)
    return next((p for p in getattr(state, "players", []) if p.id == pid), None)


def player_label(state, player_id):
    player = next((p for p in getattr(state, "players", []) if p.id == player_id), None)
    if player is None:
        return "未知角色"
    identity = getattr(player, "identity", None)
    tag = f"（{IDENTITY_NAMES.get(identity, identity)}）" if getattr(player, "identity_revealed", False) else ""
    return f"{seat_of(state, player_id)}号 {player.name}{tag}"
