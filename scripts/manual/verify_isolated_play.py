"""Loopback-only WS smokes and next-turn browser smoke; no provider credentials.

Browser pass needs Playwright/Chromium already installed in this interpreter.
Run from the repo root with -m scripts.manual.verify_isolated_play --browser.
"""
import argparse
import asyncio
from pathlib import Path
import random
from http.server import ThreadingHTTPServer
from tempfile import TemporaryDirectory
from threading import Thread
from unittest.mock import patch

from websockets.asyncio.server import serve


async def browser_test(server, port, *, executable):
    from playwright.async_api import async_playwright
    from game_engine import MainEngine, peixiu
    from game_engine.card_knowledge import start_ledger

    class PreviewEngine(MainEngine):
        """Trusted test fixture only: never enable the preview from a WS payload."""
        def __init__(self, cfg):
            cfg = {**cfg, 'peixiu_enabled': True, 'selected_hero': {'id': peixiu.HERO['id']},
                   '_rng': random.Random(20261123)}
            cfg['player'] = {**cfg['player'], 'hero': {'id': peixiu.HERO['id']}}
            super().__init__(MainEngine.normalize_config(cfg))
            # The injected RNG lives on state; it is not a serializable config field.
            self.game_config.pop("_rng", None)
            assign = self.identity_system.assign_identities
            # Hold the human opening seat fixed without changing production config.
            self.identity_system.assign_identities = lambda players, mode, _: assign(
                players, mode, {'use': True, 'identity': 'lord'})
            state = self.game_state
            human = self.human_player()
            # Keep a real, conserved deck and put a certain 6+8 cost and an A into
            # the right zones so this smoke does not depend on the opening hand.
            state.deck.extend(human.hand)
            human.hand.clear()
            for rank in (6, 8):
                card = next(c for c in state.deck if c.rank == rank)
                state.deck.remove(card)
                human.hand.append(card)
            # The first draw cannot supply an A, so the post-skill assertion
            # witnesses the search result rather than an Ace already in hand.
            opening = [c for c in state.deck if c.rank != 1][:2]
            state.deck[:] = opening + [c for c in state.deck if c not in opening]
            assert any(c.rank == 1 for c in state.deck)
            state.card_knowledge = start_ledger(state, state._initial_faces)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path=executable, args=['--no-sandbox'])
        page = await browser.new_page(viewport={'width': 1440, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        # Neither images nor scripts may initiate an outbound request in this test.
        address = f'http://127.0.0.1:{port}'
        async def local_only(route):
            if route.request.url.startswith(address + '/'):
                await route.continue_()
            else:
                await route.abort()
        await page.route('**/*', local_only)
        await page.add_init_script('''sessionStorage.setItem('gameConfig', JSON.stringify({
            mode:'5人身份局', selected_hero:{id:'sunquan'}, chat_level:'quiet',
            ais:['zhenji','lvbu','simayi','huatuo'].map(id=>({hero:{id},api_key:''}))
        }));''')
        with patch('game_server.MainEngine', PreviewEngine):
            await page.goto(address + '/game.html')
            ready = page.locator('[data-skill="爵制"].ready')
            await ready.click(timeout=10000)
            await page.locator('#okBtn').click()
            await page.wait_for_function('GameUI.req?.prompt?.includes("【爵制】")')
            indices = await page.evaluate('''[6,8].map(rank => GameUI.req.options.findIndex(o => o.card?.rank === rank))''')
            assert min(indices) >= 0
            for index in indices:
                await page.locator(f'[data-opt="{index}"]').click()
            await page.locator('#okBtn').click()
            await ready.wait_for(timeout=15000)
            engine = next(iter(server.engines.values()))
            player = engine.human_player()
            assert any(c.rank == 1 for c in player.hand)
            assert {6, 8} <= {c.rank for c in engine.game_state.discard_pile}
            await page.locator('#endBtn').click()
            # The fixture leaves three cards after 爵制, below the lord's cap.
            await page.wait_for_function('GameUI.state?.completed_turns >= 1', timeout=15000)
            assert engine.completed_turns >= 1 and engine.game_state.current_player is not player
            assert not errors, errors
        await browser.close()
    print('BROWSER_OK: 爵制 6+8→A，结束出牌并转交回合', flush=True)


async def run(args):
    import game_server
    from game_engine import config_validator
    from game_engine.ai_decision import AIGateway
    from scripts.manual import ws_diag_smoke, ws_engine_smoke

    provider_calls = []

    async def no_provider(*_args, **_kwargs):
        provider_calls.append(True)
        raise AssertionError('isolated smoke must not call an AI provider')

    with TemporaryDirectory(prefix='sgs-verify-') as tmp, \
            patch.object(config_validator, 'DEFAULT_API_KEY', ''), patch.object(AIGateway, 'call_ai', no_provider):
        # Keep runtime outputs in an ephemeral directory, not in production stores.
        root = Path(tmp)
        with patch.multiple(game_server, HISTORY_PATH=root/'history.json',
                            GAME_LOG_DIR=root/'logs', RECOVERY_DIR=root/'recovery', SKIN_DIR=root/'skins'):
            server = game_server.GameServer()
            http = ThreadingHTTPServer(('127.0.0.1', args.port), game_server.CustomHandler) if args.browser else None
            if http:
                Thread(target=http.serve_forever, daemon=True).start()
            try:
                async with serve(server.handle, '127.0.0.1', args.port + 1, max_size=2**20):
                    if args.browser:
                        await browser_test(server, args.port, executable=args.executable)
                    else:
                        ws_engine_smoke.WS_URI = ws_diag_smoke.WS_URI = f'ws://127.0.0.1:{args.port + 1}'
                        assert await ws_engine_smoke.run() == 0
                        assert await ws_diag_smoke.run_client() == 0
                    assert not provider_calls, 'unexpected AI provider request'
            finally:
                # Cancel only the test-owned engine/timer tasks before removing temp data.
                pending = {task for task in asyncio.all_tasks() if task is not asyncio.current_task()}
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                if http:
                    http.shutdown()
                    http.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=18888)
    parser.add_argument('--browser', action='store_true')
    parser.add_argument('--executable')
    asyncio.run(run(parser.parse_args()))
