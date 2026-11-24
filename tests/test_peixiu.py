import asyncio
import json
from itertools import combinations
from unittest.mock import AsyncMock, patch

import pytest

from game_engine import MainEngine, peixiu
from game_engine.card_knowledge import current_view
from game_engine.card_odds import match_face
from game_engine.recovery import dump_engine, restore_engine
from game_engine.state_manager import Card, Phase
from test_card_knowledge import table, rig_opening


def preview(enabled=True):
    e = table(peixiu_enabled=enabled, selected_hero={'id': peixiu.HERO['id']})
    e.game_state.current_phase = Phase.PLAY
    return e, e.game_state.players[0]


def test_opt_in_and_modular_dp_matches_exhaustive():
    e, p = preview(False)
    assert p.hero['id'] != peixiu.HERO['id']
    assert all(a.get('skill_name') != '爵制' for a in e.get_available_actions(p))
    for ranks, expected in (((6, 8), 1), ((6, 7), 13), ((13, 13), 13)):
        assert peixiu.rank_total([Card(str(i), '杀', 'spade', r, 'basic') for i, r in enumerate(ranks)]) == expected
    places = [(Card(str(i), '杀', 'spade', r, 'basic'), 'hand') for i, r in enumerate([1, 4, 6, 8, 11, 13])]
    expected = {peixiu.rank_total([places[i][0] for i in idx]) for n in range(2, len(places)+1)
                for idx in combinations(range(len(places)), n)}
    suggestions = peixiu.suggestions(places)
    assert set(suggestions) == expected
    assert all(peixiu.rank_total([places[i][0] for i in idx]) == rank for rank, idx in suggestions.items())


def test_xingtu_slash_through_menu_resolution_and_save():
    async def run():
        e, p = preview()
        s = e.game_state
        # Q equipment -> 6 slash (draw) -> Q Peach; then 2 -> 8 slash with depleted quota.
        rig_opening(e, {p.id: [match_face(rank=12, name='方天画戟'),
                               match_face(rank=6, name='杀'), match_face(rank=12, name='桃'),
                               match_face(rank=2, name='杀'), match_face(rank=8, name='杀')]}, [])
        target = s.players[1]
        p.identity, p.identity_revealed = 'lord', True
        target.identity = 'rebel'
        with patch.object(e.card_system, 'ask_wuxie', AsyncMock(return_value=False)), \
                patch.object(e.card_system, '_sha_effect', AsyncMock(return_value=True)):
            action = next(a for a in e.get_available_actions(p) if a.get('card_index') == 0 and a['type'] == 'play_card')
            assert await e.execute_action(p, action)
            assert p.flags[peixiu.LAST_RANK] == 12
            action = next(a for a in e.get_available_actions(p) if a.get('card', {}).get('rank') == 6 and a['type'] == 'play_card')
            n = len(s.deck)
            assert await e.execute_action(p, action, [target.id])
            assert len(s.deck) == n - 1 and p.sha_count == 1 and p.flags[peixiu.LAST_RANK] == 6
            p.hp -= 1
            action = next(a for a in e.get_available_actions(p) if a.get('card', {}).get('rank') == 12 and a['type'] == 'play_card')
            assert await e.execute_action(p, action) and p.hp == p.max_hp
            assert p.flags[peixiu.LAST_RANK] == 12
            p.sha_count = 0
            action = next(a for a in e.get_available_actions(p) if a.get('card', {}).get('rank') == 2 and a['type'] == 'play_card')
            assert await e.execute_action(p, action, [target.id]) and p.sha_count == 1
            action = next(a for a in e.get_available_actions(p) if a.get('card', {}).get('rank') == 8 and a['type'] == 'play_card')
            assert await e.execute_action(p, action, [target.id])
            assert p.sha_count == 1
        restored = restore_engine(json.loads(json.dumps(dump_engine(e))), MainEngine)
        r = restored.game_state.players[0]
        assert r.flags[peixiu.LAST_RANK] == 8
        assert peixiu.xingtu(r, Card('other', '杀', 'spade', 8, 'basic')) == (True, True)
    asyncio.run(run())


def test_juezhi_choose_arbitrary_cost_and_hides_deck_success_before_payment():
    async def world(hidden_hit):
        e, p = preview()
        s = e.game_state
        rig_opening(e, {p.id: [match_face(rank=6), match_face(rank=8)]}, [])
        # Keep only one unknown live drawable and use a hidden opponent hand as
        # the other location for the A. Same public constraints in both worlds.
        aces = [c for c in s.deck if c.rank == 1]
        keep = aces[0]
        other = next(c for c in s.deck if c.rank != 1)
        s.players[1].hand[:] = [other if hidden_hit else keep]
        s.deck[:] = [c for c in s.deck if c is not keep and c is not other]
        s.discard_pile[:] = s.deck
        s.deck[:] = [keep if hidden_hit else other]
        from game_engine.card_knowledge import start_ledger
        s.card_knowledge = start_ledger(s, s._initial_faces)
        v = current_view(s, p.id)
        assert peixiu.search_forecast(v, 1)[0] == pytest.approx(0.5)
        assert peixiu.search_forecast(v, 1, name='闪电')[1] == 0
        menus = e.get_available_actions(p)
        action = next(a for a in menus if a.get('skill_name') == '爵制')
        with patch.object(e, 'ask_choose_cards', AsyncMock(return_value=list(p.hand))) as choose:
            assert await e.execute_action(p, action)
        assert len(p.hand) == int(hidden_hit)
        if hidden_hit:
            assert p.hand[0] is keep
        assert current_view(s, p.id) is not None
        return menus, choose.call_args.args[1]
    assert asyncio.run(world(True)) == asyncio.run(world(False))


def test_response_use_and_pure_response_have_distinct_rank_history():
    async def run():
        e, p = preview()
        s = e.game_state
        rig_opening(e, {p.id: [match_face(name='闪'), match_face(name='无懈可击', rank=12)]}, [])
        dodge, counter = p.hand
        p.flags[peixiu.LAST_RANK] = 12
        n = len(s.deck)
        assert await e.card_system._consume_response(p, {'bool': True, 'card': dodge}, '杀', {})
        assert p.flags[peixiu.LAST_RANK] == 12 and len(s.deck) == n
        assert await e.card_system._consume_response(
            p, {'bool': True, 'card': counter}, 'wuxie', {}, counts_as_use=True)
        assert p.flags[peixiu.LAST_RANK] == counter.rank and len(s.deck) == n - 1
        assert p.flags[peixiu.USE_SERIAL] == 1
    asyncio.run(run())


@pytest.mark.parametrize('nested', [False, True])
def test_failed_parent_does_not_erase_same_rank_nested_use(nested):
    async def run():
        e, p = preview()
        p.flags[peixiu.LAST_RANK] = 12
        slash = Card('slash', '杀', 'spade', 6, 'basic')

        async def resolve(*_):
            if nested:
                # A second use with exactly the same point must still survive rollback.
                peixiu.commit_use(p, slash)
            return False

        with patch.object(e.card_system, '_use_card_resolve', resolve):
            assert not await e.card_system.use_card(p, slash)
        assert p.flags[peixiu.LAST_RANK] == (6 if nested else 12)
    asyncio.run(run())
