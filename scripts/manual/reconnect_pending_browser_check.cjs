/* Verify the client redraws an outstanding choice after the normal resume handshake. */
'use strict';
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = (process.env.UI_BASE_URL || 'http://127.0.0.1:8888').replace(/\/$/, '');
const gameId = 'ui-pending-resume-check';
const request = {type: 'require_response', request_id: 'pending-ui-req-1', kind: 'choose_option',
  prompt: '恢复中的待操作', options: [{label: '选择甲'}, {label: '选择乙'}],
  selection: {mode: 'single', min: 1, max: 1, cancelable: true}, timeout: 60};
const state = {round: 1, deck_count: 40, discard_count: 0, current_player_id: 0, current_name: '浏览器玩家', phase: 'play', game_over: false,
  players: [{id: 0, name: '浏览器玩家', is_ai: false, hero: {id: 'caocao', name: '曹操', faction: '魏', skills: []}, hero_name: '曹操', hp: 4, max_hp: 4, alive: true, identity: 'lord', hand_count: 0, self_hand: [], equipment: {}, judge_area: []},
    ...[1, 2, 3, 4].map((id) => ({id, name: 'AI' + id, is_ai: true, hero: {id: 'liubei', name: '刘备', faction: '蜀', skills: []}, hero_name: '刘备', hp: 3, max_hp: 4, alive: true, identity: null, hand_count: 2, equipment: {}, judge_area: []}))],
  self_hand: []};
(async () => {
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport: {width: 390, height: 844}});
    const errors = [];
    let resumes = 0;
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      sessionStorage.setItem('profileId', JSON.stringify('ui_pending_resume_profile'));
      sessionStorage.setItem('gameConfig', JSON.stringify({selected_hero: {id: 'caocao', name: '曹操', faction: '魏', skills: []},
        ais: [1, 2, 3, 4].map(i => ({name: 'AI' + i})), player_name: '浏览器玩家'}));
      sessionStorage.setItem('activeGame', JSON.stringify({game_id: 'ui-pending-resume-check', profile_id: 'ui_pending_resume_profile'}));
    });
    await page.routeWebSocket('ws://127.0.0.1:8889', ws => {
      ws.onMessage(raw => {
        const msg = JSON.parse(raw.toString());
        if (msg.type === 'resume_game') {
          resumes++;
          ws.send(JSON.stringify({type: 'game_resumed', game_id: gameId, finished: false}));
          ws.send(JSON.stringify({type: 'game_state', state}));
          ws.send(JSON.stringify(request));
        }
      });
    });
    await page.goto(base + '/game.html');
    await page.waitForFunction(() => document.querySelector('#abPrompt')?.textContent.includes('恢复中的待操作'));
    if (await page.locator('[data-opt]').count() !== 2 || await page.locator('#cancelBtn').isDisabled()) throw new Error('initial pending choice did not render');
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#abPrompt')?.textContent.includes('恢复中的待操作'));
    if (resumes !== 2) throw new Error('reload did not perform resume handshake');
    if (await page.locator('[data-opt]').count() !== 2 || await page.locator('#cancelBtn').isDisabled()) throw new Error('resumed pending choice was not restored');
    const reqId = await page.evaluate(() => window.GameUI && window.GameUI.req && window.GameUI.req.request_id);
    if (reqId !== request.request_id) throw new Error('restored request id changed: ' + reqId);
    if (errors.length) throw new Error('browser errors: ' + JSON.stringify(errors));
    console.log(JSON.stringify({check: 'RECONNECT_PENDING_BROWSER_OK', viewport: '390x844', resumes, request_id: reqId, pending_options: 2, page_errors: errors}, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
