import asyncio
import json
import math
from collections import Counter
from itertools import combinations
from unittest.mock import AsyncMock, patch

import pytest

from game_engine import MainEngine
from game_engine.card_knowledge import DECK, DISCARD, Move, View, current_view, prompt_block, start_ledger
from game_engine.card_odds import Face, JUDGES, face_of, match_face
from game_engine.recovery import dump_engine, restore_engine
from game_engine.state_manager import GameState, Phase
from game_engine.tactical_evidence import answer_query


def table(deck='standard', **config):
    return MainEngine(MainEngine.normalize_config({
        'mode': '5人身份局', 'deck_id': deck, 'selected_hero': {'id': 'sunquan'},
        'ais': [{'hero': {'id': h}, 'name': h} for h in ('zhenji', 'lvbu', 'simayi', 'huatuo')],
        **config,
    }))


def rig_opening(engine, hands, top):
    s = engine.game_state
    pool = sorted([*s.deck, *(c for p in s.players for c in p.hand)], key=lambda card: card.id)
    def select(tests):
        selected = []
        for test in tests:
            card = next(c for c in pool if test(face_of(c)))
            pool.remove(card)
            selected.append(card)
        return selected
    for p in s.players:
        p.hand[:] = select(hands.get(p.id, []))
    s.deck[:] = select(top) + pool
    s.card_knowledge = start_ledger(s, s._initial_faces)


@pytest.mark.parametrize('deck,n', [('standard', 108), ('extra', 53), ('combined', 161)])
def test_start_by_real_catalogue(deck, n):
    s = table(deck).game_state
    assert s.initial_deck_count == n
    ledger = s.card_knowledge
    assert ledger.version == 1
    for p in s.players:
        v = current_view(s, p.id)
        assert v.summary and len(v.summary) == 5
        assert v.capacity((p.id, 'hand')) == 4
        assert len(v.pools[0]) > 0 and v.pools[0].total() == n - 4
        assert sum(v.odds([(p.id, 'hand')], rank=1, nature='fire')) == pytest.approx(1)


def test_standard_opening_known_odds_and_first_prompt():
    e = table()
    s = e.game_state
    for i in range(len(s.deck)):
        p = s.players[0]
        if not any(c.name == '闪' for c in p.hand):
            break
        if s.deck[i].name != '闪':
            j = next(k for k, c in enumerate(p.hand) if c.name == '闪')
            p.hand[j], s.deck[i] = s.deck[i], p.hand[j]
    s.card_knowledge = start_ledger(s, s._initial_faces)
    expected = 1 - math.comb(89, 4) / math.comb(104, 4)
    v = current_view(s, 0)
    assert 1 - v.summary[1][1][0] == pytest.approx(expected)
    assert v.next_draw(match_face(name='闪')) == pytest.approx(15 / 104)
    assert '实时牌账 v1' in e.ai_decision.build_decision_turn_message(p, [{'type': 'end_turn'}])
    assert '实时牌账 v1' in e.ai_decision.build_response_prompt(p, {'options': []})


def test_formal_draft_deals_once_even_if_disabled():
    for enabled in (True, False):
        e = table(hero_draft='standard', ai_ablation={'live_card_knowledge': enabled})
        s = e.game_state
        assert not s.card_knowledge and all(not p.hand for p in s.players)
        s.deal_initial_hands()
        s.deal_initial_hands()
        assert all(len(p.hand) == 4 for p in s.players)
        assert bool(s.card_knowledge) == enabled


def test_luoshen_guarantee_then_public_response_updates_and_checkpoint():
    async def run():
        e = table()
        s = e.game_state
        actor, zhen, *_ = s.players
        rig_opening(e, {actor.id: [match_face(name='杀')]},
                    [match_face(name='杀', suit='club', rank=11), match_face(color='red')])
        handler = next(h for h in e.skill_manager.handlers if hasattr(h, '_luoshen'))
        await handler._luoshen(zhen)
        assert '可作闪100%' in prompt_block(e, actor) and '♣J杀' in prompt_block(e, actor)
        s.current_phase = Phase.PLAY
        actions = e.get_available_actions(actor)
        query = {'target_seat': s.seat_of(zhen.id)}
        assert '100.0%' in answer_query(e, actor, actions, query)
        snapshot = json.loads(json.dumps(dump_engine(e)))
        restored = restore_engine(snapshot, MainEngine)
        assert prompt_block(restored, restored.game_state.players[0]) == prompt_block(e, actor)
        del snapshot['state']['card_knowledge']
        old = restore_engine(snapshot, MainEngine)
        assert '近似估计' in prompt_block(old, old.game_state.players[0])
        assert current_view(old.game_state, 0).judges is None
        zhen.flags['cannot_use_hand'] = True
        assert '当前封手' in prompt_block(e, actor)
        assert '不能使用或打出手牌' in answer_query(e, actor, actions, query)
        await e.move_card(zhen.hand[0], 'hand', 'discard', from_owner=zhen, reason='respond')
        assert '可作闪0%' in prompt_block(e, actor)
    asyncio.run(run())


def test_wash_cohort_and_joint_prediction_against_exhaustive_deals():
    # Two old-hand slots cannot suddenly contain a peach from the refill cohort.
    dodge = Face('闪', 'heart', 2, None, 'basic')
    peach = Face('桃', 'heart', 3, None, 'basic')
    slash = Face('杀', 'spade', 7, 'thunder', 'basic')
    other = Face('闪电', 'spade', 1, None, 'delay')
    a, b, c = ((i, 'hand') for i in range(3))
    refill = Counter([peach, dodge, slash])
    v = View(Counter([other, slash, *refill]), {a: 1, b: 1, DISCARD: 3}, {DISCARD: refill})
    v.refill(refill)
    v.move(Move(DECK, c, None))
    assert v.odds([a, b], name='桃') == (1., 0., 0.)
    cards = [peach, dodge, slash]
    expected = sum(slash in pair for pair in combinations(cards, 2)) / 3
    assert v.odds([DECK], name='杀', suit='spade', rank=7, nature='thunder')[1] == pytest.approx(expected)
    assert v.next_draw(JUDGES[3]) == pytest.approx(1 / 3)
    assert v.hand_branch(2, lambda f: f == dodge, 0) == pytest.approx((2/3, 1/3, 0))
    v.move(Move(DECK, a, peach))
    assert v.odds([c], name='桃')[0] == 1
    assert v.odds([a, c], color='red')[1:] == pytest.approx((0.5, 0.5, 0.0))


def test_hidden_worlds_and_same_face_transfers_are_spectator_invariant():
    async def world(which):
        e = table()
        s = e.game_state
        viewer, owner, recipient, *_ = s.players
        rig_opening(e, {owner.id: [match_face(name='闪')]}, [match_face(name='杀', color='black')])
        await e.move_card(s.deck[0], 'deck', 'hand', to_owner=owner, reason='明拿')
        await e.move_card(owner.hand[which], 'hand', 'hand', from_owner=owner, to_owner=recipient,
                          reason='暗给', visibility='owner')
        s.current_phase = Phase.PLAY
        s.deck.reverse() if which else None
        s.players[1].identity = 'spy' if which else 'rebel'
        v = current_view(s, viewer.id)
        assert v.degraded
        assert current_view(s, owner.id).fixed[owner.id, 'hand'] != current_view(s, recipient.id).fixed[recipient.id, 'hand']
        actions = e.get_available_actions(viewer)
        return v.dump(), actions, e.ai_decision.build_decision_turn_message(viewer, actions)
    assert asyncio.run(world(0)) == asyncio.run(world(1))


def test_reveal_does_not_duplicate_and_duplicate_sequence_is_ignored():
    e = table()
    s = e.game_state
    owner = s.players[1]
    f = face_of(owner.hand[0])
    ledger = s.card_knowledge
    ledger.reveal((owner.id, 'hand'), f)
    ledger.reveal((owner.id, 'hand'), f)
    before = ledger.version
    v = current_view(s, 0)
    assert v.fixed[owner.id, 'hand'][f] == 1
    s.move_card(owner.hand[0], 'hand', 'discard', from_owner=owner, reason='discard')
    saved = v.dump()
    ledger.move(ledger.last_move, {0: Move((1, 'hand'), DISCARD, f)})
    assert v.dump() == saved and ledger.version == before + 1
    for _ in range(75):
        s.observe_tactic('test', owner)
    assert v.dump() == saved


def test_response_and_play_each_get_summary_without_extra_model_calls():
    async def run():
        e = table()
        p = e.game_state.players[1]
        p.ai_config['api_key'] = 'stub'
        e.game_state.current_player = p
        e.game_state.current_phase = Phase.PLAY
        mock = AsyncMock(return_value='{"action_index":0}')
        with patch.object(e.ai_decision, '_call_with_session', mock):
            await e.ai_decision.make_decision(p, [{'type': 'end_turn'}])
        mock.assert_awaited_once()
        assert '实时牌账 v1' in mock.call_args.args[-1]
    asyncio.run(run())
