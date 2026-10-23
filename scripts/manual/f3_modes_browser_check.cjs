/* Real browser + real WebSocket smoke for every currently registered F3 mode. */
'use strict';
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = (process.env.F3_BASE_URL || 'http://127.0.0.1:8888').replace(/\/$/, '');
const modes = ['5人身份局', '8人身份局', '2v2', '斗地主'];
(async () => {
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox'],
    ...(process.env.PLAYWRIGHT_EXECUTABLE_PATH ? {executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH} : {})});
  const page = await browser.newPage({viewport: {width: 390, height: 844}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const results = [];
  try {
    for (const mode of modes) {
      await page.goto(base + '/index.html', {waitUntil: 'domcontentloaded'});
      await page.waitForFunction(() => [...document.querySelectorAll('#modeCards [data-mode]')].length >= 3, null, {timeout: 10000});
      await page.locator('#modeCards [data-mode]').filter({hasText: mode}).click();
      const setup = await page.evaluate(() => ({
        selected: document.querySelector('#modeCards [aria-pressed="true"]')?.dataset.mode,
        aiSeats: document.querySelectorAll('#guestRow .guest').length,
        identityVisible: !document.querySelector('#identityCardSection').hidden,
        identityLineupVisible: !document.querySelector('#identityLineup').hidden,
        widths: [document.documentElement.scrollWidth, innerWidth]
      }));
      const expected = mode === '8人身份局' ? 7 : mode === '2v2' ? 3 : mode === '斗地主' ? 2 : 4;
      if (setup.selected !== mode || setup.aiSeats !== expected || setup.widths[0] > setup.widths[1] + 1)
        throw new Error(`mode setup mismatch ${mode}: ${JSON.stringify(setup)}`);
      if (['2v2', '斗地主'].includes(mode) && (setup.identityVisible || !setup.identityLineupVisible))
        throw new Error(`${mode} must hide identity card and show public teams`);
      await page.evaluate(() => { sessionStorage.removeItem('activeGame'); });
      await page.locator('#playerName').fill('F3浏览器验收');
      await page.locator('#startGameBtn').click();
      await page.waitForURL('**/select_hero.html');
      await page.locator('.hero-card[data-id="liubei"]').click();
      await page.locator('#confirmBtn').click();
      await page.waitForURL('**/game.html');
      await page.waitForFunction(expectedCount => window.GameUI && window.GameUI.state &&
        window.GameUI.state.players?.length === expectedCount, expected + 1, {timeout: 45000});
      const actual = await page.evaluate(() => ({
        mode: window.GameUI.state.mode,
        playerCount: window.GameUI.state.players.length,
        configuredAI: window.GameUI.cfg.ais.length,
        humanIdentity: window.GameUI.players.find(player => player.id === window.GameUI.meId)?.identity,
        created: !!JSON.parse(sessionStorage.getItem('activeGame') || 'null')?.game_id,
        gameId: JSON.parse(sessionStorage.getItem('activeGame') || 'null')?.game_id,
        wsPort: Number(location.port) + 1,
        widths: [document.documentElement.scrollWidth, innerWidth]
      }));
      if (actual.mode !== mode || actual.playerCount !== expected + 1 || actual.configuredAI !== expected || !actual.created)
        throw new Error(`real WS game mismatch ${mode}: ${JSON.stringify(actual)}`);
      if (actual.widths[0] > actual.widths[1] + 1) throw new Error(`table overflows at mobile width ${mode}: ${JSON.stringify(actual.widths)}`);
      results.push({mode, ai_seats: setup.aiSeats, configured_ai: actual.configuredAI,
        create_game_to_game_created_ack: actual.created, game_id: actual.gameId, ws_port: actual.wsPort,
        player_count: actual.playerCount, public_teams: ['2v2', '斗地主'].includes(mode) ? true : undefined,
        identity_card_hidden: ['2v2', '斗地主'].includes(mode) ? !setup.identityVisible : undefined,
        viewport: '390x844'});
      await page.locator('#quitBtn').click();
      await page.locator('dialog.sgs-dialog [data-v="1"]').click();
      await page.waitForFunction(() => document.querySelector('#endModal')?.open === true, null, {timeout: 15000});
      await page.locator('#endLobby').click();
      await page.waitForURL('**/index.html');
      await page.waitForFunction(() => document.querySelectorAll('#modeCards [data-mode]').length >= 4);
    }
    for (const [mode, winner, label] of [['2v2', 'team_a', 'A队获胜（2v2公开队伍）'], ['斗地主', 'farmer', '农民获胜（斗地主公开队伍）']]) {
      await page.evaluate(({mode, winner}) => localStorage.setItem('gameResult', JSON.stringify({
        mode, winner, player_won: true, player_identity: mode === '2v2' ? 'team_a' : 'farmer',
        players: [], total_rounds: 1, duration: 3
      })), {mode, winner});
      await page.goto(base + '/result.html', {waitUntil: 'domcontentloaded'});
      await page.waitForFunction(() => document.getElementById('resultSubtitle')?.textContent.length > 0);
      const subtitle = await page.locator('#resultSubtitle').textContent();
      if (!subtitle.includes(label)) throw new Error(`settlement winner wording mismatch: ${mode} / ${subtitle}`);
      const identityLabel = await page.locator('#yourIdentityLabel').textContent();
      const identityText = await page.locator('#yourIdentity').textContent();
      const expectedTeam = mode === '2v2' ? 'A队' : '农民';
      if (identityLabel !== '你的队伍' || identityText !== expectedTeam)
        throw new Error(`public team label mismatch: ${mode} / ${identityLabel} / ${identityText}`);
      results.push({mode, settlement_winner_text: subtitle});
    }
    if (errors.length) throw new Error('page errors: ' + JSON.stringify(errors));
    console.log(JSON.stringify({check: 'F3_MODES_BROWSER_OK', modes: results, page_errors: errors}, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
