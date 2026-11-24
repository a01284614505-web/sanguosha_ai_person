"""Seat-local card knowledge, built solely from projected moves and the original deck list.

A zone holds face counts guaranteed to be there and anonymous slots in one or more
exchangeable pools. Shuffling the discard starts a separate pool, so anonymous
post-shuffle draws do not become exchangeable with untouched old hands.
"""
from collections import Counter
from dataclasses import dataclass

from .card_odds import (Face, JUDGES, NAMES, base_counts, convolve, distribution,
                        face_of, hypergeom, match_face)

DECK = (None, 'deck')
DISCARD = (None, 'discard')
OPEN = frozenset({'shown', 'discard', 'judge', 'equipment'})
PRIVATE = ('hand', 'treasure', 'temporary')


@dataclass(frozen=True)
class Move:
    source: tuple
    dest: tuple
    face: Face | None
    # This is the operation kind, not an inference from the true deck index.
    top: bool = False


class View:
    def __init__(self, catalogue, capacities, visible, *, degraded=False):
        self.fixed = {z: Counter(cards) for z, cards in visible.items()}
        self.pools = {0: catalogue.copy()}
        self.slots = {}
        self.degraded = degraded
        self.ordered_by_skill = False
        # Zero-based offsets from the current top, known only to this seat.
        self.positions: dict[int, Face] = {}
        self.valid = True
        for z, cap in capacities.items():
            fixed = self.fixed.get(z, Counter())
            self.pools[0].subtract(fixed)
            unknown = cap - fixed.total()
            if unknown < 0:
                self.valid = False
            elif unknown:
                self.slots[z] = Counter({0: unknown})
        self.next_pool = 1
        self._update()

    def capacity(self, z):
        return self.fixed.get(z, Counter()).total() + self.slots.get(z, Counter()).total()

    def _collapse(self):
        pool = Counter()
        for cards in self.pools.values():
            pool.update(cards)
        self.pools = {0: pool}
        self.slots = {z: Counter({0: slots.total()}) for z, slots in self.slots.items() if slots.total()}
        self.degraded = True

    def move(self, event):
        if not self.valid:
            return
        src, dst, face = event.source, event.dest, event.face
        anonymous_top = False
        if src == DECK:
            if event.top:
                top = self.positions.get(0)
                if top is not None:
                    if face is not None and face != top:
                        self.valid = False
                        self._update()
                        return
                    face = top
                elif self.positions:
                    # A face at a later position cannot explain this draw.
                    anonymous_top = self.fixed.get(DECK, Counter()) == Counter(self.positions.values())
                    if not anonymous_top:
                        self.positions.clear()
                        self.ordered_by_skill = True
                        self.degraded = True
                self.positions = {i - 1: f for i, f in self.positions.items() if i}
            else:
                # A blind, non-positional removal can shift the entire arrangement,
                # even if in the true world it happened to remove the top card.
                if self.positions:
                    self.positions.clear()
                    self.ordered_by_skill = True
                    self.degraded = True
        if dst == DECK:
            self.positions.clear()
            self.ordered_by_skill = True
            self.degraded = True
        known = self.fixed.setdefault(src, Counter())
        if not anonymous_top and face is None and not self.slots.get(src) and len(known) == 1:
            # A blind move out of a fully known homogeneous zone exposes no new fact.
            face = next(iter(known))
        if not anonymous_top and face is not None and known[face] > 0:
            known[face] -= 1
        else:
            if not anonymous_top and face is None and known.total():
                # Anonymous removal from a group containing known faces: retain only
                # provable lower bounds. The relaxed model is explicitly approximate.
                for f in list(known):
                    if known[f] > 0:
                        known[f] -= 1
                        self.pools.setdefault(0, Counter())[f] += 1
                        self.slots.setdefault(src, Counter())[0] += 1
                self._collapse()
            groups = +self.slots.get(src, Counter())
            if face is not None and len(groups) > 1:
                compatible = [g for g in groups if self.pools[g][face] > 0]
                if len(compatible) == 1:
                    groups = {compatible[0]: groups[compatible[0]]}
            if len(groups) > 1:
                self._collapse()
                groups = +self.slots.get(src, Counter())
            if not groups:
                self.valid = False
                self._update()
                return
            group = next(iter(groups))
            self.slots[src][group] -= 1
            if face is None:
                self.slots.setdefault(dst, Counter())[group] += 1
            else:
                self.pools[group][face] -= 1
        if face is not None:
            self.fixed.setdefault(dst, Counter())[face] += 1
        if src == DECK and not self.capacity(DECK):
            self.ordered_by_skill = False
        self._update()

    def reveal(self, z, face):
        # There may be several same-face copies; repeated displays are not additive.
        if self.valid and not self.fixed.get(z, Counter())[face]:
            self.move(Move(z, z, face))

    def peek(self, faces):
        """Apply a private top-card reveal before asking the owner to arrange it."""
        if not self.valid:
            return
        count = len(faces)
        after = Counter(faces) + Counter(f for i, f in self.positions.items() if i >= count)
        # Existing unordered deck facts can overlap the private peek. Keep the
        # stronger lower bound rather than double-counting a printed face.
        if any(self.positions[i] != f for i, f in enumerate(faces) if i in self.positions):
            self.valid = False  # A trusted prior position contradicts this reveal.
            self._update()
            return
        for f, n in (after - self.fixed.get(DECK, Counter())).items():
            for _ in range(n):
                self._learn_deck_face(f)
        self.positions.update(enumerate(faces))
        self._update()

    def _learn_deck_face(self, face):
        # A same-zone reveal turns an anonymous deck slot into a known face,
        # without changing deck order or accidentally consuming a known copy.
        groups = +self.slots.get(DECK, Counter())
        compatible = [g for g in groups if self.pools[g][face] > 0]
        if len(compatible) > 1:
            self._collapse()
            compatible = [0]
        if not compatible:
            self.valid = False
            return
        g = compatible[0]
        self.slots[DECK][g] -= 1
        self.pools[g][face] -= 1
        self.fixed.setdefault(DECK, Counter())[face] += 1

    def reorder(self, count, top=None, bottom=None):
        if top is None:
            # Other seats know a permutation happened, not how many went to each end.
            self.positions.clear()
            self.ordered_by_skill = True
            self.degraded = True
        elif self.valid:
            shift = len(top) - count
            size = self.capacity(DECK)
            self.positions = {i + shift: f for i, f in self.positions.items() if i >= count}
            self.positions.update(enumerate(top))
            self.positions.update(enumerate(bottom, size - len(bottom)))
        self._update()

    def refill(self, faces):
        if not self.valid:
            return
        if self.capacity(DECK) or self.fixed.get(DISCARD, Counter()) != faces:
            self.valid = False
        else:
            group = self.next_pool
            self.next_pool += 1
            self.fixed.pop(DISCARD, None)
            self.slots.pop(DISCARD, None)
            self.pools[group] = faces.copy()
            self.slots[DECK] = Counter({group: faces.total()})
            self.positions.clear()
            self.ordered_by_skill = False
        self._update()

    def _update(self):
        self.summary = {}
        self.judges = None
        if not self.valid:
            return
        self.fixed = {z: +cards for z, cards in self.fixed.items() if cards.total()}
        self.slots = {z: +groups for z, groups in self.slots.items() if groups.total()}
        used = Counter()
        for groups in self.slots.values():
            used.update(groups)
        if (any(n < 0 for pool in self.pools.values() for n in pool.values())
                or any(pool.total() != used[g] for g, pool in self.pools.items())
                or used.keys() - self.pools.keys()
                or Counter(self.positions.values()) - self.fixed.get(DECK, Counter())
                or any(not 0 <= i < self.capacity(DECK) for i in self.positions)):
            self.valid = False
            return
        self.pools = {g: +cards for g, cards in self.pools.items() if used[g]}
        # Recompute the small subscription set after each commit, not after a model asks.
        stats = {g: base_counts(tuple(sorted(cards.items(), key=lambda row: repr(row[0]))))
                 for g, cards in self.pools.items()}
        for z in self.fixed.keys() | self.slots.keys():
            if z[1] != 'hand':
                continue
            fixed = base_counts(tuple(self.fixed.get(z, {}).items()))
            groups = self.slots.get(z, {})
            rows = []
            for i, n in enumerate(fixed[:8]):
                dist = (0.0,) * n + (1.0,)
                for g, slots in groups.items():
                    dist = convolve(dist, hypergeom(self.pools[g].total(), stats[g][i], slots))
                rows.append(dist)
            self.summary[z[0]] = tuple(rows)
        top = self.positions.get(0)
        if top is not None:
            self.judges = tuple(float(test(top)) for test in JUDGES)
        elif not self.ordered_by_skill:
            # Reuse the per-pool counts already computed for the hand subscription.
            zone = DECK if self.capacity(DECK) else DISCARD
            fixed = self.fixed.get(zone, Counter())
            if zone == DECK and self.positions:
                fixed = fixed - Counter(self.positions.values())
            slots = self.slots.get(zone, {})
            size = fixed.total() + sum(slots.values())
            if size:
                known = base_counts(tuple(fixed.items()))
                self.judges = tuple((known[i] + sum(n * stats[g][i] / self.pools[g].total()
                                     for g, n in slots.items())) / size for i in range(8, 12))

    def odds(self, zones, **criteria):
        """Printed match counts over a UNION of zones, without assuming seat independence."""
        if not self.valid:
            return None
        fixed, groups = Counter(), Counter()
        for z in set(zones):
            fixed.update(self.fixed.get(z, {}))
            groups.update(self.slots.get(z, {}))
        return distribution(fixed, [(self.pools[g], slots) for g, slots in groups.items()],
                            match_face(**criteria))

    def hand_branch(self, target, dodge, helper=None):
        """P(no dodge), P(no dodge/peach/wine), P(helper peach | neither)."""
        tz, hz = (target, 'hand'), (helper, 'hand')
        either = lambda f: dodge(f) or f.name in ('桃', '酒')
        def p_zero(test):
            p = float(not any(test(f) for f in self.fixed.get(tz, {})))
            for g, slots in self.slots.get(tz, {}).items():
                pool = self.pools[g]
                n = sum(v for f, v in pool.items() if test(f))
                p *= hypergeom(pool.total(), n, slots)[0]
            return p
        no_dodge, neither = p_zero(dodge), p_zero(either)
        if not neither or helper is None:
            return no_dodge, neither, None
        no_peach = float(not any(f.name == '桃' for f in self.fixed.get(hz, {})))
        for g, slots in self.slots.get(hz, {}).items():
            pool = self.pools[g]
            # All peaches were excluded from the target's sampled slots.
            remaining = pool.total() - self.slots.get(tz, {}).get(g, 0)
            peaches = sum(v for f, v in pool.items() if f.name == '桃')
            no_peach *= hypergeom(remaining, peaches, slots)[0]
        return no_dodge, neither, 1 - no_peach

    def next_draw(self, test):
        if not self.valid:
            return None
        if self.positions.get(0) is not None:
            return float(test(self.positions[0]))
        if self.ordered_by_skill:
            return None
        zone = DECK if self.capacity(DECK) else DISCARD
        fixed = self.fixed.get(zone, Counter())
        if zone == DECK:
            fixed = fixed - Counter(self.positions.values())
        size = fixed.total() + self.slots.get(zone, Counter()).total()
        if not size:
            return None
        e = sum(n for f, n in fixed.items() if test(f))
        for g, slots in self.slots.get(zone, {}).items():
            pool = self.pools[g]
            e += slots * sum(n for f, n in pool.items() if test(f)) / pool.total()
        return e / size

    def dump(self):
        return {'fixed': [[list(z), list(c.items())] for z, c in sorted(self.fixed.items(), key=lambda row: repr(row[0]))],
                'slots': [[list(z), dict(c)] for z, c in sorted(self.slots.items(), key=lambda row: repr(row[0]))],
                'pools': {g: list(c.items()) for g, c in self.pools.items()},
                'next_pool': self.next_pool, 'valid': self.valid, 'degraded': self.degraded,
                'ordered_by_skill': self.ordered_by_skill,
                'positions': sorted(self.positions.items())}

    @classmethod
    def load(cls, data):
        view = cls.__new__(cls)
        view.fixed = {tuple(z): _faces(c) for z, c in data['fixed']}
        view.slots = {tuple(z): Counter({int(g): int(n) for g, n in c.items()}) for z, c in data['slots']}
        view.pools = {int(g): _faces(c) for g, c in data['pools'].items()}
        view.next_pool = int(data['next_pool'])
        view.valid = bool(data['valid'])
        view.degraded = bool(data['degraded'])
        view.ordered_by_skill = bool(data.get('ordered_by_skill'))
        view.positions = {int(i): Face(*f) for i, f in data.get('positions', [])}
        view._update()
        return view


def _faces(rows):
    return Counter({Face(*face): int(n) for face, n in rows})


class CardKnowledge:
    def __init__(self, catalogue, projections, *, degraded=False):
        self.catalogue = catalogue
        self.views = {pid: View(catalogue, caps, faces, degraded=degraded)
                      for pid, (caps, faces) in projections.items()}
        self.version = 1
        self.last_move = 0

    def move(self, sequence, projected):
        if sequence <= self.last_move:
            return
        self.last_move = sequence
        self.version += 1
        for pid, move in projected.items():
            self.views[pid].move(move)

    def refill(self, faces):
        self.version += 1
        for view in self.views.values():
            view.refill(faces)

    def reveal(self, zone, face):
        self.version += 1
        for view in self.views.values():
            view.reveal(zone, face)

    def selective_search(self):
        # The search is rank-conditioned, not an anonymous top draw.
        for view in self.views.values():
            view.degraded = True

    def peek(self, viewer, faces):
        # A private look must not change the version shown to other seats.
        self.views[viewer].peek(faces)

    def reordered(self, viewer, count, top, bottom):
        self.version += 1
        for pid, view in self.views.items():
            if pid == viewer:
                view.reorder(count, top, bottom)
            else:
                view.reorder(count)

    def dump(self):
        return {'catalogue': list(self.catalogue.items()), 'version': self.version, 'last_move': self.last_move,
                'views': {pid: view.dump() for pid, view in self.views.items()}}

    @classmethod
    def load(cls, data):
        ledger = cls(_faces(data['catalogue']), {})
        ledger.version = int(data['version'])
        ledger.last_move = int(data['last_move'])
        ledger.views = {int(pid): View.load(view) for pid, view in data['views'].items()}
        return ledger


def capacities(state):
    """Engine-side adapter; no identity other than seat IDs, and no hidden faces."""
    sizes = {DECK: len(state.deck), DISCARD: len(state.discard_pile)}
    for p in state.players:
        for z, cards in _zones(p).items():
            sizes[p.id, z] = len(cards)
    return sizes


def _zones(p):
    return {'hand': p.hand, 'temporary': p.temporary, 'treasure': p.treasure_cards,
            'shown': p.shown, 'equipment': p.equipment.values(), 'judge': p.judge_area}


def start_ledger(state, catalogue, *, degraded=False):
    """Project separately *before* the estimator sees any facts."""
    sizes = capacities(state)
    public = {DISCARD: tuple(map(face_of, state.discard_pile))}
    for p in state.players:
        for z, cards in _zones(p).items():
            if z in OPEN:
                public[p.id, z] = tuple(map(face_of, cards))
    ledger = CardKnowledge(catalogue, {
        p.id: (sizes, {**public, **{(p.id, z): tuple(map(face_of, _zones(p)[z])) for z in PRIVATE}})
        for p in state.players
    }, degraded=degraded)
    ledger.last_move = state._card_move_sequence
    return ledger


def apply_move(ledger, event, card, *, top=False):
    src, dst = (event.from_owner, event.from_zone), (event.to_owner, event.to_zone)
    public = event.visibility == 'public' or src[1] in OPEN or dst[1] in OPEN
    face = face_of(card)
    ledger.move(event.sequence, {pid: Move(src, dst, face if public or pid in (src[0], dst[0]) else None, top)
                                 for pid in ledger.views})


def current_view(state, pid):
    ledger = getattr(state, 'card_knowledge', None)
    view = ledger.views.get(pid) if ledger else None
    if view and view.valid:
        sizes = capacities(state)
        if all(view.capacity(z) == n for z, n in sizes.items()):
            # Cross-check only own and public faces; same-count opaque replacements
            # must never affect a spectator solely because of the new hidden face.
            for p in state.players:
                for z, cards in _zones(p).items():
                    if (z in OPEN or p.id == pid) and Counter(map(face_of, cards)) != view.fixed.get((p.id, z), Counter()):
                        return None
            if Counter(map(face_of, state.discard_pile)) == view.fixed.get(DISCARD, Counter()):
                return view
    return None


def live_enabled(engine):
    return (engine.game_config.get('ai_ablation') or {}).get('live_card_knowledge', True) is not False


def pct(probability, digits=0):
    """Do not display a rounded estimate as a logical impossibility or certainty."""
    step = 10 ** -digits
    if 0 < probability < step / 200:
        return f'<{step:g}%'
    if 1 - step / 200 < probability < 1:
        return f'>{100 - step:g}%'
    return f'{min(1, max(0, probability)):.{digits}%}'


def _face_label(f):
    suit = {'spade': '♠', 'club': '♣', 'heart': '♥', 'diamond': '♦'}.get(f.suit, f.suit)
    rank = {1: 'A', 11: 'J', 12: 'Q', 13: 'K'}.get(f.rank, f.rank)
    nature = {'fire': '火', 'thunder': '雷'}.get(f.nature, f.nature or '')
    return f'{suit}{rank}{nature}{f.name}'


def prompt_block(engine, viewer):
    if not live_enabled(engine):
        return ''
    state = engine.game_state
    view = current_view(state, viewer.id)
    if view is None:
        return '' if state.hero_draft_pending else '\n【实时牌账】暂不可用。'
    from .seats import seat_of
    labels = '、'.join(('杀', '闪', '桃', '酒', '无懈'))
    rows = []
    has = engine.skill_manager.has_skill
    for p in state.players:
        if p.id == viewer.id or not p.alive:
            continue
        stats = view.summary.get(p.id, ((1.0,),) * 8)
        text = f'{seat_of(state, p.id)}号 {view.capacity((p.id, "hand"))}张：' + '/'.join(pct(1-d[0]) for d in stats[:5])
        q, l = has(p, '倾国'), has(p, '龙胆')
        if q or l:
            d = stats[7 if q and l else 5 if q else 6]
            text += f'；可作闪{pct(1-d[0])}'
        else:
            d = stats[1]
        if has(viewer, '无双'):
            text += f'；两闪{pct(1-sum(d[:2]))}'
        if p.flags.get('cannot_use_hand'):
            text += '；当前封手'
        faces = view.fixed.get((p.id, 'hand'), {})
        if faces:
            known = [f'{_face_label(f)}' + (f'×{n}' if n > 1 else '')
                     for f, n in sorted(faces.items(), key=lambda row: repr(row[0]))]
            text += '；明持' + '、'.join(known[:3]) + ('等' if len(known) > 3 else '')
        rows.append(text)
    judge = ('下一判（八卦红/乐红桃/兵梅花/闪电中）' + '/'.join(pct(p) for p in view.judges)
             if view.judges is not None else '下一判暂不可用')
    if 0 in view.positions and view.judges is not None:
        judge = f'已知堆顶{_face_label(view.positions[0])}；' + judge
    label = '近似估计（部分约束已降级）' if view.degraded else '等权条件估计'
    return (f'\n【实时牌账 v{state.card_knowledge.version}｜{label}】他席手牌至少一张（{labels}）：\n'
            + '\n'.join(rows) + '\n' + judge + '；未计改判、防具、木牛、求援或响应意愿。')
