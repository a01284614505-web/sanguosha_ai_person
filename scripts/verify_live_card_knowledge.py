"""Offline replay and local latency probe; no network/model/WS calls."""
import asyncio
import json
import random
import statistics
from time import perf_counter

from game_engine import MainEngine
from game_engine.card_knowledge import prompt_block
from game_engine.card_odds import match_face


async def run():
    config = MainEngine.normalize_config({
        'mode': '5人身份局', 'deck_id': 'standard', 'selected_hero': {'id': 'sunquan'},
        'ais': [{'hero': {'id': h}, 'name': h} for h in ('zhenji', 'lvbu', 'simayi', 'huatuo')],
    })
    config['_rng'] = random.Random(231123)
    engine = MainEngine(config)
    state = engine.game_state
    print(prompt_block(engine, state.players[0]))
    test = match_face(name='杀', suit='club', rank=11)
    from game_engine.card_odds import face_of
    found = next((i for i, c in enumerate(state.deck) if test(face_of(c))), None)
    if found is not None:
        # Fixture only: choose a deterministic deck order, not card ownership.
        state.deck.insert(0, state.deck.pop(found))
        red = next(i for i, c in enumerate(state.deck) if i and c.suit in ('heart', 'diamond'))
        state.deck.insert(1, state.deck.pop(red))
        handler = next(h for h in engine.skill_manager.handlers if hasattr(h, '_luoshen'))
        await handler._luoshen(state.players[1])
        summary = prompt_block(engine, state.players[0])
        assert '♣J杀' in summary and '可作闪100%' in summary
        print(summary)
    timings, sizes = [], []
    for i in range(200):
        p = state.players[i % len(state.players)]
        t = perf_counter()
        assert state.refill_deck_if_empty()
        assert state.move_card(state.deck[0], 'deck', 'hand', to_owner=p, reason='benchmark draw', visibility='owner')
        block = prompt_block(engine, p)
        assert '暂不可用。' not in block
        timings.append((perf_counter() - t) * 1000)
        sizes.append(len(block.encode('utf-8')))
        assert state.move_card(p.hand[0], 'hand', 'discard', from_owner=p, reason='benchmark discard')
    quantile = lambda xs: sorted(xs)[int(len(xs) * .95) - 1]
    print(json.dumps({'samples': len(timings), 'scope': 'sync draw/refill + all-seat ledger + one prompt block',
                      'p50_ms': round(statistics.median(timings), 3), 'p95_ms': round(quantile(timings), 3),
                      'p95_prompt_utf8_bytes': quantile(sizes)}, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(run())
