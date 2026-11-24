import asyncio
import logging
import random
from collections import Counter
from unittest.mock import AsyncMock, patch

import pytest

from game_engine import MainEngine, local_tactical_simulation as sim
from game_engine.card_knowledge import start_ledger
from game_engine.card_odds import face_of
from game_engine.recovery import dump_engine
from game_engine.state_manager import Card, Phase, Player


def scene(*, hero=None, armor=None, hand=(), enemy=(), rescuer=(), hp=3, wine=False, top=()):
    e = MainEngine({'local_tactical_simulation': True})
    a, b, c, d, f = players = [Player(n, str(n), identity=role, identity_revealed=role == 'lord')
                              for n, role in zip((50, 17, 98, 31, 4),
                                                 ('rebel', 'lord', 'loyalist', 'spy', 'rebel'))]
    if hero:
        a.hero = {'id': hero}
    seen = []

    def make(spec):
        name, suit, nature = (*spec, None) if len(spec) == 2 else spec
        card = Card(str(len(seen)), name, suit, 3, sim.CARD_TABLE[name].card_type, nature=nature)
        seen.append(card)
        return card

    a.hand, b.hand, c.hand = [list(map(make, rows)) for rows in (hand, enemy, rescuer)]
    if armor:
        b.equipment['armor'] = make((armor, 'club'))
    b.hp, a.jiu_buff = hp, wine
    s = e.game_state
    s.players, s.current_player, s.current_phase = players, a, Phase.PLAY
    s.deck, s.discard_pile = list(map(make, top)), []
    s.card_knowledge = start_ledger(s, Counter(map(face_of, seen)))
    e.skill_manager.bind_engine(e)
    return e, a, b, c


def query(e, a, *, n=1, **kwargs):
    actions = e.get_available_actions(a)
    arms = [{'action_index': i, 'target_ids': [1]} for i in range(n)]
    result = asyncio.run(sim.compare(e, a, actions, arms, samples=1, **kwargs))
    assert result['status'] == 'ok', result
    return [row['totals'] for row in result['branches']]


@pytest.mark.parametrize('armor, expected', [('仁王盾', [(1, 0), (0, 1), (1, 0)]),
                                             ('藤甲', [(1, 0), (1, 0), (0, 2)])])
def test_armor_and_nature(armor, expected):
    e, a, *_ = scene(armor=armor, hand=[('杀', 'spade'), ('杀', 'heart'), ('杀', 'club', 'fire')])
    actions = e.get_available_actions(a)
    pairs = ([{'action_index': i, 'target_ids': [1]} for i in pair] for pair in [(0, 1), (2,)])
    got = []
    for pair in pairs:
        r = asyncio.run(sim.compare(e, a, actions, pair, samples=1))
        assert r['status'] == 'ok', r
        got.extend((row['totals'][1]['immune'], row['totals'][1]['damage']) for row in r['branches'])
    assert got == expected


@pytest.mark.parametrize('dodge', [0, 1, 2])
def test_lubu_needs_two_dodges(dodge):
    e, a, *_ = scene(hero='lvbu', hand=[('杀', 'heart')], enemy=[('闪', 'heart')] * dodge)
    row = query(e, a)[0][1]
    assert row['dodged'] == (dodge == 2)
    assert row['damage'] == (dodge < 2)
    assert row['resources'] == -dodge


@pytest.mark.parametrize('peaches', [0, 1, 2])
def test_negative_one_hp_requires_two_heals(peaches):
    e, a, *_ = scene(hand=[('杀', 'heart')], enemy=[('桃', 'heart')] * peaches, hp=1, wine=True)
    row = query(e, a)[0][1]
    assert (row['damage'], row['dying'], row['rescued'], row['dead']) == (2, 1, int(peaches == 2), int(peaches < 2))


def test_equivalent_observation_and_no_side_effects(caplog):
    e, a, b, c = scene(hand=[('杀', 'heart'), ('杀', 'spade')], enemy=[('闪', 'heart')],
                       rescuer=[('桃', 'heart')], top=[('酒', 'spade'), ('杀', 'diamond')])
    state = e.game_state
    # Use a different real PRNG from the simulator's; neither one may advance.
    state._rng = random.Random(99)
    actions = e.get_available_actions(a)
    emit = AsyncMock(side_effect=AssertionError('real emit'))
    q = [{'action_index': i, 'target_ids': [1]} for i in (0, 1)]
    def check():
        before = dump_engine(e)
        with patch.object(e, 'emit', emit), patch('game_engine.ai_decision.AIGateway.call_ai',
                                                 side_effect=AssertionError('provider')), caplog.at_level(logging.INFO):
            caplog.clear()
            rng = (random.getstate(), state._rng.getstate())
            out = asyncio.run(sim.compare(e, a, actions, q, samples=4))
            assert out['status'] == 'ok' and out['samples'] == 4
            assert rng == (random.getstate(), state._rng.getstate())
            assert not caplog.records
        assert before == dump_engine(e)
        return out
    first = check()
    c.hand[0], state.deck[0] = state.deck[0], c.hand[0]
    state.deck.reverse()
    c.identity, state.players[3].identity = state.players[3].identity, c.identity
    assert first == check()
    emit.assert_not_called()


def test_reject_bad_menu_and_budget():
    e, a, *_ = scene(hand=[('杀', 'heart')])
    actions = e.get_available_actions(a)
    item = {'action_index': 0, 'target_ids': [1]}
    for arms in ([item] * 2, [{**item, 'target_ids': [17]}], [{**item, 'action_index': True}]):
        assert asyncio.run(sim.compare(e, a, actions, arms)) == {'status': 'unsupported'}
    assert asyncio.run(sim.compare(e, a, actions, [item], seconds=0))['status'] == 'budget'
    assert 'local_tactical_simulation' not in __import__('game_engine.config_validator', fromlist=['sanitize_client_config']).sanitize_client_config(e.game_config)
