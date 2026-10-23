import json
from game_engine.game_history import GameHistoryStore
from game_engine.seats import seat_of
from game_server import GameServer
from test_ai_smart_p0 import make_engine


def test_serialized_fixed_ai_ids_follow_accounts_after_seat_swap(tmp_path):
    e = make_engine()
    ids = ['ai_4', 'ai_2', 'ai_3', 'ai_1']
    for p, ai_id in zip(e.game_state.players[1:], ids):
        p.ai_config.update(ai_id=ai_id, api_key='never-persist-this-key')
    e.game_state.game_over = True
    state = e.serialize()
    assert [p['ai_id'] for p in state['players'][1:]] == ids
    store = GameHistoryStore(tmp_path / 'history.json')
    store.update_ai_player('integration', 'ai_4', name='开局后改名')
    store.record_result('integration', 'swapped', {'winner': 'spy', 'state': state})
    accounts = {p['id']: p for p in store.ai_players('integration')}
    assert accounts['ai_4']['stats']['wins'] == 1
    assert accounts['ai_4']['name'] == '开局后改名'
    assert accounts['ai_1']['stats'].get('wins', 0) == 0
    assert 'never-persist-this-key' not in (tmp_path / 'history.json').read_text()


def test_transient_correct_high_guess_cannot_be_erased_before_round_snapshot():
    e = make_engine()
    owner, target = e.game_state.players[1], e.game_state.players[3]
    key = str(seat_of(e.game_state, target.id))
    e.notes.ensure(owner.id)
    e.notes.update(owner.id, {key: {'guess': 'loyalist', 'conf': '高', 'why': '短暂猜中'}})
    e.notes.update(owner.id, {key: {'guess': 'unknown', 'conf': '低', 'why': '后来改口'}})
    e.notes.snapshot(1)
    snapshot = e.notes.snapshots[0]
    assert snapshot['notes'][key]['guess'] == 'unknown'
    assert int(key) in snapshot['judged_seats']
    assert target.id not in GameServer._title_hidden_players(e)
    assert e.notes.high_guess_events[0]['target_id'] == target.id
    # 没有短暂猜中时，同样完整的低把握样本可以获得保守覆盖资格。
    e.notes.high_guess_events.clear()
    assert target.id in GameServer._title_hidden_players(e)


def test_delayed_wuxie_prompt_uses_actual_trick_user_and_does_not_guess_unknown_source():
    import asyncio
    from game_engine.state_manager import Card
    e = make_engine()
    user, victim, responder = e.game_state.players[3], e.game_state.players[1], e.game_state.players[4]
    for p in e.game_state.players:
        p.hand.clear()
    responder.hand.append(Card('wx', '无懈可击', 'club', 3, 'trick'))
    seen = []
    async def decline(player, request):
        seen.append(request)
        return {'bool': False}
    e.card_system.responder = decline
    trick = Card('delayed', '乐不思蜀', 'heart', 6, 'trick')
    asyncio.run(e.card_system.ask_wuxie(trick, victim, [victim], trick_user=user))
    assert seen[0]['context']['card_source'] is user
    prompt = e.ai_decision.build_response_prompt(responder, seen[0])
    assert '锦囊原始来源：2号 选手3' in prompt and '目标：5号 选手1' in prompt
    assert seen[0]['prompt'].startswith('2号 选手3的【乐不思蜀】')
    seen.clear()
    asyncio.run(e.card_system.ask_wuxie(trick, victim, [victim], trick_user=None))
    assert seen[0]['context']['card_source'] is None
    assert '锦囊原始来源：引擎未记录' in e.ai_decision.build_response_prompt(responder, seen[0])
    assert seen[0]['prompt'].startswith('来源未记录的【乐不思蜀】')
