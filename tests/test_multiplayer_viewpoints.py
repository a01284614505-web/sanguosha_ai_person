"""Controller, turn order and opaque player ID are independent axes."""
import asyncio
from unittest.mock import AsyncMock

from game_engine.card_knowledge import current_view, prompt_block
from game_engine.card_odds import face_of, match_face
from game_engine.protocol import ENGINE_EVENT
from game_engine.state_manager import Phase
from game_engine.tactical_evidence import answer_query
from game_server import GameServer
from test_card_knowledge import rig_opening, table


def mixed_table():
    engine = table()
    state = engine.game_state
    # Two humans, an AI lord, and IDs which are not indices or seat numbers.
    a, b, lord, d, f = state.players
    for p, pid, role in zip(state.players, (41, 82, 19, 560, 247),
                            ('rebel', 'spy', 'lord', 'loyalist', 'rebel')):
        p.id, p.identity, p.identity_revealed = pid, role, role == 'lord'
    b.is_ai = False
    state.players[:] = [d, a, b, lord, f]
    state.current_player = a
    state.current_player_index = 1
    state.current_phase = Phase.PLAY
    rig_opening(engine, {a.id: [match_face(name='闪')], b.id: [match_face(name='杀')]}, [])
    return engine, a, b, lord


def test_counting_targets_and_private_facts_follow_player_not_controller_or_seat():
    async def run():
        e, a, b, lord = mixed_table()
        s = e.game_state
        assert s.seat_of(lord.id) == 1 and s.seat_of(a.id) == 4
        card = a.hand[0]
        assert await e.move_card(card, 'hand', 'hand', from_owner=a, to_owner=b,
                                 reason='测试暗给', visibility='owner')
        hand = (b.id, 'hand')
        for p in (a, b):
            assert current_view(s, p.id).fixed[hand][face_of(card)] == 1
        assert hand not in current_view(s, lord.id).fixed
        actions = [{'type': 'play_card', 'card': {'name': '杀'}, 'valid_targets': [b.id]}]
        query = {'target_seat': s.seat_of(b.id)}
        result = answer_query(e, a, actions, query)
        assert '可作闪牌100.0%' in result
        a.is_ai, b.is_ai = True, False
        assert answer_query(e, a, actions, query) == result
        assert f'{s.seat_of(b.id)}号' in prompt_block(e, a)
    asyncio.run(run())


def test_projection_and_input_require_the_recipient_player(tmp_path):
    async def run():
        e, a, b, lord = mixed_table()
        for p, secret in ((a, b), (b, a)):
            snapshot = e.serialize(viewer_id=p.id)
            rows = {row['id']: row for row in snapshot['players']}
            assert snapshot['viewer_id'] == p.id
            assert [c['id'] for c in snapshot['self_hand']] == [p.hand[0].id]
            assert rows[p.id]['identity'] == p.identity
            assert rows[secret.id]['identity'] is None and rows[lord.id]['identity'] == 'lord'
        for unknown in (None, 0, True):
            assert not e.serialize(viewer_id=unknown)['self_hand']
        e._remember_prompt('turn', ENGINE_EVENT.YOUR_TURN, {'player_id': a.id, 'hand': []})
        e._remember_prompt('reply', ENGINE_EVENT.REQUIRE_RESPONSE, {'player_id': b.id, 'options': ['B']})
        assert e.pending_prompts(viewer_id=a.id)[0]['payload']['hand'][0]['id'] == a.hand[0].id
        assert e.pending_prompts(viewer_id=b.id)[0]['payload']['options'] == ['B']
        assert e.pending_prompts(viewer_id=None) == []
        server = GameServer(tmp_path/'history.json', tmp_path/'recovery')
        gid = 'test'
        ws = object()
        server.viewers[gid], server.engines[gid], server.ws_map[ws] = ws, e, gid
        server.send = AsyncMock()
        # The same event is projected separately for each authenticated recipient.
        move = (await e.move_card(a.hand[0], 'hand', 'hand', from_owner=a, to_owner=b,
                                   reason='测试暗给', visibility='owner')).to_dict()
        for viewer in (a.id, b.id, lord.id, None):
            server._viewer_player_id = lambda *_: viewer
            await server._forward(gid, ENGINE_EVENT.CARD_MOVE)(move=move)
            seen = server.send.call_args.args[1]['move']['card_id']
            assert seen == (move['card_id'] if viewer in (a.id, b.id) else None)
        server._viewer_player_id = lambda *_: b.id
        server.send.reset_mock()
        await server._forward(gid, ENGINE_EVENT.YOUR_TURN)(player_id=a.id, hand=['private'])
        server.send.assert_not_awaited()
        e._waiting_for_action = True
        e._player_event = asyncio.Event()
        await server.do_action(ws, {'player_id': a.id, 'action': {'type': 'end_phase'}})
        assert not e._player_event.is_set()
        future = asyncio.get_running_loop().create_future()
        e._pending_requests['reply'] = future
        e._pending_request_specs['reply'] = {'player_id': b.id, 'kind': 'respond', 'options': [{}]}
        assert not e.submit_response_status('reply', 0, player_id=a.id)['success']
        assert not future.done()
        assert e.submit_response_status('reply', 0, player_id=b.id)['success']
        assert e.submit_action({'type': 'end_phase'}, [], player_id=a.id)['success']
    asyncio.run(run())
