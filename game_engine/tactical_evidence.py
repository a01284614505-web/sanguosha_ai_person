"""给当前座位比较出杀、留牌和治疗的依据。

从可见牌还原未知牌池，把尚未定位的实体牌视为等可能。下文数的是可能的手牌组合。
对手会不会出牌、值不值得冒险，是另一个问题，由模型结合对局历史判断。
"""
from dataclasses import dataclass
from functools import lru_cache
from math import comb
from pathlib import Path

from .deck_manager import DeckManager
from .seats import player_of, seat_of

BLACK = {"club", "spade"}
RED = {"diamond", "heart"}
SUIT = {"club": "♣", "spade": "♠", "diamond": "♦", "heart": "♥"}
QUERY_HINT = (
    '如需验算可只返回形如 {"tactical_query":{"target_seat":3}} 的JSON，填实际座位号。'
    '可选 helper_seat 指定另一名假设会救目标的玩家，keep_pick=true 假设其仍持最近五谷牌，'
    'keep_target_pick=true 对受杀目标作同样假设，'
    'decline_pct 为0至100的整数，表示当时有可作闪牌却未出闪的假设概率。'
    '每步最多验算一次，也可直接选择。'
)


@lru_cache(maxsize=3)
def catalogue(deck_id):
    rows = DeckManager(Path(__file__).resolve().parents[1]).load_deck_cards(deck_id)
    return {r["id"]: (r["name"], r["suit"], r["rank"]) for r in rows}


def unknown_cards(state, viewer):
    """从整副牌里扣掉本人可见的实体牌。未知池还包括他人暗牌，不能直接拿摸牌堆来算。"""
    visible = [*viewer.hand, *viewer.treasure_cards, *state.discard_pile]
    for p in state.players:
        visible.extend(p.equipment.values())
        visible.extend(p.judge_area)
        visible.extend(p.shown)
    remaining = catalogue(state.deck_id).copy()
    for c in visible:
        if remaining.pop(c.id, None) != (c.name, c.suit, c.rank):
            # 牌表与当前实体对不上时，继续相减可能多算或少算一张牌。
            return None
    return remaining


def _matching_copy(pool, row):
    face = (row["card_name"], row["suit"], row["rank"])
    return next((key for key, candidate in pool.items() if candidate == face), None)


def _located_picks(state, viewer, pool):
    """把仍能定位的五谷牌从未知池移到持有者手中。两处同时更新，防止一张牌占两个位置。"""
    located = {}
    for row in state.tactical_observations:
        if row["kind"] == "public_pick" and row.get("holding") == "known" and row["player"] != viewer.id:
            copy = _matching_copy(pool, row)
            if copy is not None:
                located.setdefault(row["player"], {})[row["move_seq"]] = pool.pop(copy)
    return located


def ways(n, k):
    return comb(n, k) if 0 <= k <= n else 0


@dataclass(frozen=True)
class HandOdds:
    """同一批等可能手牌中的组合数。neither 表示既无可作闪牌，也无牌面为桃或酒的牌。"""
    total: int
    no_dodge: int
    neither: int
    at_least_two_dodges: int

    @property
    def has_dodge(self):
        return 1 - self.no_dodge / self.total

    def with_dodge_after_pass(self, decline_pct):
        # 只留下能解释“上次没出闪”的情况：无闪的全留下，有闪的按假定的不出比例留下。
        # 两边都按百分数加权。分母为零表示这个假设根本解释不了观察到的行为。
        weighted_dodge = (self.total - self.no_dodge) * decline_pct
        denominator = weighted_dodge + 100 * self.no_dodge
        return weighted_dodge / denominator if denominator else None


def hand_odds(faces, count, *, qingguo=False, longdan=False, fixed=()):
    """count 包含已知手牌；faces 只含未知牌。先固定已知手牌，再填剩余位置。"""
    def usable(face):
        name, suit, _rank = face
        return name == "闪" or (qingguo and suit in BLACK) or (longdan and name == "杀")

    can_dodge = neither = 0
    for face in faces:
        dodge = usable(face)
        can_dodge += dodge
        # 倾国的黑酒同时能闪和自救，按实体判断“两者都不能”，避免重复扣除。
        neither += not dodge and face[0] not in ("桃", "酒")
    count -= len(fixed)
    total = ways(len(faces), count)
    if not total:
        return None
    fixed_dodges = sum(usable(face) for face in fixed)
    other = len(faces) - can_dodge
    no_dodge = 0 if fixed_dodges else ways(other, count)
    no_either = ways(neither, count) if no_dodge and all(c[0] not in ("桃", "酒") for c in fixed) else 0
    # 从全部手牌中排除零闪和恰好一闪，就是能凑足两闪的手牌。已知的闪也占名额。
    need_for_one = 1 - fixed_dodges
    exactly_one = ways(can_dodge, need_for_one) * ways(other, count - need_for_one)
    return HandOdds(total, no_dodge, no_either, total - no_dodge - exactly_one)


def slash_targets(actions):
    return {pid for a in actions if a.get("type") == "play_card" and (a.get("card") or {}).get("name") == "杀"
            for pid in a.get("valid_targets", [])}


def enabled(engine):
    return (engine.game_config.get("ai_ablation") or {}).get("tactical_evidence", True) is not False


def history_enabled(engine):
    return (engine.game_config.get("ai_ablation") or {}).get("tactical_history", enabled(engine)) is not False


def history_block(state):
    lines = []
    for row in state.tactical_observations[-10:]:
        seat = seat_of(state, row["player"])
        prefix = f"第{row['round']}轮{seat}号"
        if row["kind"] == "public_pick":
            status = {"known": "，仍可定位在手", "left": "，已离手"}.get(row.get("holding"), "，现去向待推断")
            lines.append(f"{prefix}五谷取{SUIT.get(row['suit'], '')}{row['rank']}{row['card_name']}{status}")
        elif row["kind"] == "unanswered_damage":
            lines.append(f"{prefix}未挡住{row['card_name']}，受{row['damage']}伤，当时{row['hand_count']}手牌")
        elif row["kind"] == "damage_skill":
            attacker = seat_of(state, row["source"])
            damage = f"受{attacker}号伤害" if attacker is not None else "受伤"
            given = f"，分出{row['distributed']}张" if "distributed" in row else ""
            lines.append(f"{prefix}{damage}后发动{row['skill']}获{row['gained']}张{given}")
        elif row["kind"] == "borrow_weapon":
            lines.append(f"{prefix}被{seat_of(state, row['source'])}号借刀，指定杀"
                         f"{seat_of(state, row['victim'])}号，结果交出{row['weapon']}")
        elif row["kind"] == "rescue":
            lines.append(f"{prefix}濒死，由{seat_of(state, row['source'])}号提供{row['as_name']}救回1体力")
    return ("\n【可复查的公开经过】" + "；".join(lines)
            + "。判断意图时，可比较主动配合、误判和敌对的解释。") if lines else ""


def _odds(engine, target, pool, fixed=()):
    return hand_odds(pool.values(), target.get_hand_count(),
                     qingguo=engine.skill_manager.has_skill(target, "倾国"),
                     longdan=engine.skill_manager.has_skill(target, "龙胆"), fixed=fixed)


def _possible_pick(state, holder, pool):
    pick = next((r for r in reversed(state.tactical_observations)
                 if r["kind"] == "public_pick" and r["player"] == holder.id), None)
    if not pick or pick.get("holding") in {"left", "known"} or not holder.get_hand_count():
        return None
    copy = _matching_copy(pool, pick)
    if copy is None:
        return None
    if list(catalogue(state.deck_id).values()).count(pool[copy]) > 1:
        return copy  # 再次亮出相同牌面，旁观者仍不能分辨是哪一张实体牌。
    public_zones = {"shown", "discard", "judge", "equipment"}
    for move in reversed(state.card_move_events):
        if move.sequence <= pick.get("move_seq", -1):
            break
        if (move.visibility == "public" and (move.from_zone in public_zones or move.to_zone in public_zones)
                and move.card_id == copy):
            return None
    return copy


def _reserve(engine, viewer, actions):
    if not engine.skill_manager.has_skill(viewer, "急救"):
        return ""
    cards = list(viewer.hand)
    if getattr(viewer.equipment.get("treasure"), "name", None) == "木牛流马":
        cards.extend(viewer.treasure_cards)
    red = {i for i, c in enumerate(cards) if c.suit in RED
           and (i >= len(viewer.hand) or not viewer.flags.get("cannot_use_hand"))}
    if not red:
        return ""
    # 按付费后剩余的红牌数合并操作。这里只算眼前确定的消耗，击杀奖励还没有发生。
    costs = {}
    for i, a in enumerate(actions):
        if a.get("skill_name") == "青囊":
            indices = a.get("card_indices", [])
        elif a.get("type") == "play_card" and (a.get("card") or {}).get("name") == "杀":
            indices = [a.get("card_index")]
        else:
            continue
        after = len(red.difference(indices))
        costs.setdefault(after, []).append(str(i))
    text = f"若直接结束出牌，现有{len(red)}张红牌可留作回合外急救（弃牌阶段前）。"
    for after, indices in costs.items():
        text += f"操作{','.join(indices)}支付牌后余{after}张。"
    return text


def previous_decision(engine, viewer):
    state = engine.game_state
    previous = next((r for r in reversed(getattr(engine, "decision_log", []))
                     if r.get("player_id") == viewer.id and r.get("kind") == "play"
                     and "public_changes" in r and r.get("reason")), None)
    if previous:
        targets = "、".join(str(seat_of(state, pid)) for pid in previous["target_ids"])
        changes = "，".join(f"{c['seat']}号{c['before']}→{c['after']}" for c in previous["public_changes"])
        return (f"\n【你的上次出牌判断】第{previous['round']}轮，你选择{previous['choice'][:40]}（实选目标座位{targets or '无'}），"
                f"当时理由「{previous['reason'][:100]}」。结算期间[体力,手牌数]变化：{changes or '无'}。")
    return ""


def decision_block(engine, viewer, actions):
    if not enabled(engine):
        return ""
    state = engine.game_state
    parts = [_reserve(engine, viewer, actions)]
    targets = slash_targets(actions)
    if targets:
        pool = unknown_cards(state, viewer)
        if pool is not None:
            double_dodge = engine.skill_manager.has_skill(viewer, "无双")
            located = _located_picks(state, viewer, pool)
            rows = []
            for p in state.players:
                if p.id in targets:
                    fixed = list(located.get(p.id, {}).values())
                    odds = _odds(engine, p, pool, fixed)
                    if odds:
                        row = f"{seat_of(state, p.id)}号 {odds.has_dodge:.0%}"
                        if double_dodge:
                            row += f"（无双要求两闪时，手牌够两张 {odds.at_least_two_dodges / odds.total:.1%}）"
                        pick_id = _possible_pick(state, p, pool)
                        if pick_id:
                            other = pool.copy()
                            face = other.pop(pick_id)
                            pinned = _odds(engine, p, other, [*fixed, face])
                            if pinned:
                                row += f"（若仍持上次五谷牌 {pinned.has_dodge:.0%}）"
                        armor = p.equipment.get("armor")
                        if armor:
                            row += f"（另有{armor.name}）"
                        rows.append(row)
            if rows:
                parts.append(f"扣除可见牌与仍能公开定位的五谷牌，余{len(pool)}张。按未知牌均匀分配，手牌至少一张可作闪牌（原生闪、倾国、龙胆）："
                             + "，".join(rows) + "。持牌概率未计防具、求援、封手、出闪意愿和其他留牌策略。")
                if getattr(viewer, "jiu_buff", False):
                    parts.append("你有酒的增伤，下一张杀结算时基础伤害加一。")
    lines = [p for p in parts if p]
    return ("\n【战术依据】" + "\n".join(lines) + "\n") if lines else ""


def answer_query(engine, viewer, actions, query):
    """在本座位可见的牌池里验算一次假设。整段推算不会取出对手的实际手牌。"""
    if not enabled(engine) or not isinstance(query, dict):
        return "缺少有效验算条件。"
    if any(type(query[key]) is not bool for key in ("keep_pick", "keep_target_pick") if key in query):
        return "五谷留牌假设需要布尔值 true 或 false。"
    state = engine.game_state
    target = player_of(state, query.get("target_seat"))
    if target is None or target.id not in slash_targets(actions):
        return "目标须为本次实体杀的合法目标。"
    pool = unknown_cards(state, viewer)
    if pool is None:
        return "已见实体牌与牌表不一致，无法计算。"
    h = target.get_hand_count()
    helper = player_of(state, query.get("helper_seat"))
    if "helper_seat" in query and (helper is None or helper.id in {viewer.id, target.id} or not helper.alive):
        return "假设救援者须为另一名存活角色。"
    parts = [f"{query['target_seat']}号现有{h}张手牌。"]
    located = _located_picks(state, viewer, pool)
    for flag, holder in (("keep_target_pick", target), ("keep_pick", helper)):
        if query.get(flag) is not True:
            continue
        if not holder or not holder.get_hand_count():
            return "保留五谷牌需要指定有手牌的角色。"
        known = located.setdefault(holder.id, {})
        latest = next((r for r in reversed(state.tactical_observations)
                       if r["kind"] == "public_pick" and r["player"] == holder.id), None)
        if latest and latest.get("move_seq") in known:
            face = known[latest["move_seq"]]
            parts.append(f"公开仍能定位{seat_of(state, holder.id)}号五谷所取{SUIT[face[1]]}{face[2]}{face[0]}，占一个手牌位。")
            continue
        pick_id = _possible_pick(state, holder, pool)
        if pick_id is None:
            return "没有可用于该假设的公开五谷记录，或该实体牌已另行定位。"
        face = pool.pop(pick_id)
        known[latest["move_seq"]] = face
        parts.append(f"假设{seat_of(state, holder.id)}号仍持五谷所取{SUIT[face[1]]}{face[2]}{face[0]}，占一个手牌位。")
    fixed = list(located.get(target.id, {}).values())
    if helper and len(located.get(helper.id, {})) > helper.get_hand_count():
        return "假设救援者保留的牌超过其公开手牌数。"
    odds = _odds(engine, target, pool, fixed)
    if odds is None:
        return "手牌数与未知牌池不相容。"
    parts.append(f"先只按其余未定位牌均匀分配，持可作闪牌{odds.has_dodge:.1%}，"
                 f"同时无可作闪牌和印刷桃酒{odds.neither / odds.total:.1%}。")
    if engine.skill_manager.has_skill(viewer, "无双"):
        parts.append(f"若本次无双要求两闪，手牌够两张{odds.at_least_two_dodges / odds.total:.1%}。")
    if odds.no_dodge:
        parts.append(f"若确无可作闪牌，持印刷桃酒{1 - odds.neither / odds.no_dodge:.1%}。")
    if helper and odds.neither:
        helper_cards = located.get(helper.id, {}).values()
        slots = helper.get_hand_count() - len(helper_cards)
        n = len(pool) - (h - len(fixed))
        peaches = sum(face[0] == "桃" for face in pool.values())
        denom = ways(n, slots)
        if not denom:
            return "两人手牌数与未知牌池不相容。"
        # 这个分支已经排除了目标持桃，所以池里的桃都留在目标以外。
        # 给救援者的空位配牌时，扣掉目标占去的未知位置，但不再扣一次桃。
        chance = 1.0 if any(name == "桃" for name, _, _ in helper_cards) else 1 - ways(n - peaches, slots) / denom
        parts.append(f"在目标两者皆无的分支，{query['helper_seat']}号手里至少一张印刷桃{chance:.1%}。")
    if (helper and any(f[1] in BLACK for f in located.get(helper.id, {}).values())
            and engine.skill_manager.has_skill(helper, "鬼才") and engine.skill_manager.has_skill(target, "洛神")):
        parts.append("若该黑牌留到洛神、鬼才可发动且愿意改红判，则可让这一次判定获得一张黑牌。")
    if "decline_pct" in query:
        pct = query["decline_pct"]
        if type(pct) is not int or not 0 <= pct <= 100:
            return "decline_pct 需为0至100的整数。"
        event = next((r for r in reversed(state.tactical_observations)
                      if r["kind"] == "unanswered_damage" and r["player"] == target.id
                      and r["card_name"] == "万箭齐发"), None)
        if not event or event["hand_count"] != h or _hand_moved_since(state, target, event):
            parts.append("缺少可比的万箭观察，或之后已有手牌进出，本次不更新。")
        else:
            posterior = odds.with_dodge_after_pass(pct)
            parts.append(f"假设从当时至今手牌及转化能力相同、无额外响应来源、有闪时{pct}%选择不出。")
            if posterior is None:
                parts.append("这些条件下该观察不可能。")
            else:
                # 在本来就没有闪的那一组，人人都会不出闪，观察不会改变其中有桃酒的比例。
                # 把这组的新占比乘以组内“两者皆无”的占比，才是同一假设下可比较的数字。
                neither_after_pass = (1 - posterior) * odds.neither / odds.no_dodge if odds.no_dodge else 0.0
                parts.append(f"观察未出后持可作闪牌{posterior:.1%}，同时无可作闪牌和印刷桃酒"
                             f"{neither_after_pass:.1%}。外部救援另计。")
                # 两种持牌情形都可能时，给出两种极端打法作对照，不需要模型再调用一次。
                if 0 < odds.no_dodge < odds.total:
                    parts.append("同一观察，若当时有闪必出，持可作闪牌为0%。"
                                 f"若当时总会承伤，仍为{odds.has_dodge:.1%}。")
    parts.append("各比例描述手牌；是否响应、实际伤害、能否击杀及是否值得冒险仍需判断。")
    return "".join(parts)


def _hand_moved_since(state, target, observation):
    # 手牌张数相同也可能已经换过牌。只核对进出手牌的座位，暗摸的牌面不参与判断。
    for move in reversed(state.card_move_events):
        if move.sequence <= observation.get("move_seq", -1):
            break
        if ((move.from_zone == "hand" and move.from_owner == target.id)
                or (move.to_zone == "hand" and move.to_owner == target.id)):
            return True
    return False
