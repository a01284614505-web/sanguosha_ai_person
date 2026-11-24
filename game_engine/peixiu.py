"""Opt-in mobile Pei Xiu preview; not enrolled in normal hero drafting."""
from .card_knowledge import DECK, current_view, pct
from .card_table import CARD_TABLE, card_label

HERO = {
    'id': 'peixiu_mobile_preview', 'name': '裴秀（移动版预览）', 'faction': 'qun', 'max_hp': 3,
    'skills': [
        {'name': '行图', 'type': 'locked', 'description': '使用的牌点数是上一张牌点数的约数则摸一张；是其倍数则无次数限制。'},
        {'name': '爵制', 'type': 'active', 'description': '出牌阶段可弃至少两张手牌或装备，随机获取牌堆中点数等于总和模13（0作K）的牌。'},
    ],
}
LAST_RANK = 'peixiu_preview_last_rank'
USE_SERIAL = 'peixiu_preview_use_serial'  # Distinguishes nested uses of the same printed rank.


def active(player):
    # Preview hero is resolved only through an opt-in config, not through client
    # hero metadata or the production registry.
    return (player.hero or {}).get('id') == HERO['id']


def valid_rank(card):
    rank = getattr(card, 'rank', None)
    return rank if type(rank) is int and 1 <= rank <= 13 else None


def xingtu(player, card):
    if not active(player):
        return False, False
    old, new = player.flags.get(LAST_RANK), valid_rank(card)
    if type(old) is not int or not 1 <= old <= 13 or not new:
        return False, False
    return old % new == 0, new % old == 0


def commit_use(player, card, *, effect_context=None):
    """Record before resolving any nested use; keep the parent's quota decision on its context."""
    if not active(player):
        return False
    draw, no_quota = xingtu(player, card)
    if effect_context is not None:
        effect_context.ignore_use_quota = no_quota
    player.flags[LAST_RANK] = valid_rank(card)
    player.flags[USE_SERIAL] = player.flags.get(USE_SERIAL, 0) + 1
    return draw


def rank_total(cards):
    return (sum(valid_rank(c) for c in cards) - 1) % 13 + 1


def cost_places(player):
    return [(c, 'hand') for c in player.hand if valid_rank(c)] + [
        (c, 'equipment') for c in player.equipment.values() if valid_rank(c)]


def suggestions(places):
    """Bounded DP: best cheap representative for each modulo, with ≥2 cards."""
    best = {(0, 0): (0, ())}
    for index, (card, _) in enumerate(places):
        value = getattr(CARD_TABLE.get(card.name), 'discard_keep_score', 20)
        for (count, r), (cost, ids) in list(best.items()):
            key = (min(2, count + 1), (r + card.rank) % 13)
            candidate = (cost + value, (*ids, index))
            before = best.get(key)
            order = lambda value: (value[0], len(value[1]), value[1])
            if before is None or order(candidate) < order(before):
                best[key] = candidate
    return {r or 13: ids for (count, r), (_, ids) in best.items() if count == 2}


def search_forecast(view, rank, *, name=None):
    """Return (chance of hit, unconditional named chance, chance given a hit).

    Relative shares among equally ranked cards are exchangeable in the single
    pool model. Don't infer them from actual hidden deck contents or order.
    """
    if view is None or not view.valid:
        return None
    dist = view.odds([DECK], rank=rank)
    hit = 1 - dist[0]
    if name is None:
        return hit, None, None
    by_name = view.odds([DECK], rank=rank, name=name)
    if by_name[0] == 1:
        return hit, 0.0, 0.0 if hit else None
    slots = view.slots.get(DECK, {})
    if len(slots) == 1 and not view.fixed.get(DECK):
        pool = view.pools[next(iter(slots))]
        count = sum(n for f, n in pool.items() if f.rank == rank)
        matching = sum(n for f, n in pool.items() if f.rank == rank and f.name == name)
        conditional = matching / count if hit and count else None
        return hit, hit * conditional if conditional is not None else 0.0, conditional
    return hit, None, None


def action(player):
    if not active(player) or len(cost_places(player)) < 2:
        return None
    return {'type': 'use_skill', 'skill_name': '爵制', 'variant': 'peixiu_preview',
            'description': '另开选牌：弃置至少两张手牌或装备，按点数和定点找牌。',
            'requires_target': False, 'valid_targets': []}


async def execute(engine, player):
    if not (active(player) and engine.game_state.current_phase.value == 'play'
            and engine.game_state.current_player is player and player.alive):
        return False
    places = cost_places(player)
    if len(places) < 2:
        return False
    view = current_view(engine.game_state, player.id)
    combos = suggestions(places)
    recommendations = []
    for rank, indices in combos.items():
        odds = search_forecast(view, rank, name='诸葛连弩' if rank == 1 else None)
        recommendations.append((odds[0] if odds else -1, rank, indices, odds))
    recommendations.sort(key=lambda row: (-row[0], len(row[2]), row[1]))
    text = []
    # Always surface the A chain when available; then a few representative picks.
    short = sorted(recommendations, key=lambda row: row[1] != 1)[:4]
    for _, rank, ids, odds in short:
        hit = pct(odds[0]) if odds else '未知'
        faces = '＋'.join(f'#{i}{places[i][0].rank}{card_label(places[i][0])}' for i in ids)
        line = f'{faces}→{rank}点（命中{hit}）'
        if rank == 1 and odds and odds[1] is not None:
            line += f'，连弩总概率{pct(odds[1])}'
            if odds[2] is not None:
                line += f'（命中A后{pct(odds[2])}）'
        text.append(line)
    note = '近似估计' if view and view.degraded else '等权估计'
    cards = await engine.ask_choose_cards(
        player, '【爵制】选至少两张；点数之和模13（0作K）。可选任意合法组合。'
        + f'参考（未计弃牌触发，{note}）：' + '；'.join(text),
        [c for c, _ in places], min_n=2, max_n=len(places), zone='mixed',
        skill_name='爵制', context={'intent': 'discard'}, places=[(player, z) for _, z in places],
    )
    live = {id(c): z for c, z in cost_places(player)}
    if engine.game_aborted or len(cards) < 2 or len({id(c) for c in cards}) != len(cards) or any(id(c) not in live for c in cards):
        return False
    rank = rank_total(cards)
    # Commit the entire cost before any post-discard hook can request another choice.
    movements = []
    for c in cards:
        event = await engine.move_card(c, live[id(c)], 'discard', from_owner=player,
                                       reason='爵制', actor_id=player.id, project=False)
        if not event:
            return False
        movements.append((c, event))
    for c, event in movements:
        await engine.skill_manager.on_card_move(c, event)
        await engine.skill_manager.on_card_discarded(player, c, '爵制')
    if engine.game_aborted or not player.alive or engine.game_state.game_over:
        return True
    # Preview: search current deck only, no implicit reshuffle. Availability does
    # not change the menu or cost. Only recipient sees the exact acquired face.
    state = engine.game_state
    matches = [c for c in state.deck if c.rank == rank]
    if matches:
        if state.card_knowledge:
            state.card_knowledge.selective_search()
        acquired = state._rng.choice(matches)
        moved = await engine.move_card(acquired, 'deck', 'hand', to_owner=player,
                                       reason='爵制', actor_id=player.id, visibility='owner')
        if moved:
            await engine.skill_manager.on_card_gained(player, [acquired], '爵制')
    return True


def prompt_suffix(engine, viewer):
    if not active(viewer):
        return ''
    last = viewer.flags.get(LAST_RANK)
    return (f'\n【裴秀预览】行图上一张使用点数：{last if last else "无"}。'
            '约数摸牌，倍数不计入次数，同点数同时生效。爵制按费用点数和找牌。')
