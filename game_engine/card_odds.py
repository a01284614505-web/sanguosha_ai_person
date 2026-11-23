"""Counting only; no engine state, hidden entity IDs, or policy decisions."""
from collections import Counter
from functools import lru_cache
from math import comb
from typing import NamedTuple


class Face(NamedTuple):
    name: str
    suit: str
    rank: int
    nature: str | None
    kind: str


def face_of(card):
    kind = getattr(card.card_type, 'value', card.card_type)
    return Face(card.name, card.suit, card.rank, card.nature, kind)


RED = frozenset({'heart', 'diamond'})
BLACK = frozenset({'spade', 'club'})


@lru_cache(maxsize=4096)
def hypergeom(population, matches, slots):
    """Distribution indexed by number of matches in `slots` draws without replacement."""
    denom = comb(population, slots)
    return tuple(comb(matches, k) * comb(population - matches, slots - k) / denom
                 if k <= matches and slots - k <= population - matches else 0.0
                 for k in range(slots + 1))


def distribution(fixed, pools, matches):
    certainty = sum(n for f, n in fixed.items() if matches(f))
    result = (0.0,) * certainty + (1.0,)
    for pool, slots in pools:
        n = pool.total()
        d = sum(v for f, v in pool.items() if matches(f))
        result = convolve(result, hypergeom(n, d, slots))
    return result


def convolve(a, b):
    if a == (1.0,):
        return b
    if b == (1.0,):
        return a
    out = [0.0] * (len(a) + len(b) - 1)
    for i, p in enumerate(a):
        for j, q in enumerate(b):
            out[i + j] += p * q
    return tuple(out)


def match_face(*, name=None, suit=None, rank=None, nature=None, kind=None, color=None):
    """Combine printed criteria; use nature='' for an un-attributed card."""
    return lambda f: ((name is None or name == f.name) and (suit is None or suit == f.suit)
                      and (rank is None or rank == f.rank) and (kind is None or kind == f.kind)
                      and (nature is None or nature == (f.nature or ''))
                      and (color is None or f.suit in {'red': RED, 'black': BLACK}.get(color, ())))


NAMES = ('杀', '闪', '桃', '酒', '无懈可击')
JUDGES = (lambda f: f.suit in RED, lambda f: f.suit == 'heart',
          lambda f: f.suit == 'club', lambda f: f.suit == 'spade' and 2 <= f.rank <= 9)
HAND_FILTERS = tuple(match_face(name=name) for name in NAMES) + (
    lambda f: f.name == '闪' or f.suit in BLACK,
    lambda f: f.name in ('闪', '杀'),
    lambda f: f.name in ('闪', '杀') or f.suit in BLACK,
)


@lru_cache(maxsize=1024)
def base_counts(faces):
    pool = Counter(dict(faces))
    return tuple(sum(n for f, n in pool.items() if test(f)) for test in HAND_FILTERS + JUDGES)
