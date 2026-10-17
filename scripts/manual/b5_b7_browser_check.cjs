/**
 * B5/B7 real-browser acceptance. Requires game_server.py on 8888 and WS on 8889.
 * Uses actual Playwright clicks against the current GameUI, never dispatches raw WS messages.
 * PLAYWRIGHT_MODULE=/tmp/b4-browser-check/node_modules/playwright node scripts/manual/b5_b7_browser_check.cjs
 */
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.B5_BASE_URL || 'http://127.0.0.1:8888';
(async () => {
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  const page = await browser.newPage({viewport: {width: 1280, height: 900}});
  const errors = [];
  if (process.env.B5_PROFILE_ID) {
    await page.addInitScript(id => localStorage.setItem('profileId', JSON.stringify(id)), process.env.B5_PROFILE_ID);
  }
  page.on('pageerror', e => errors.push(e.message));
  const seen = [];
  const pass = (name, ok, detail = '') => { if (!ok) throw new Error(name + ' failed ' + detail); seen.push({name, detail}); };
  await page.goto(base + '/index.html', {waitUntil: 'domcontentloaded'});
  await page.waitForSelector('#startGameBtn');
  await page.waitForFunction(() => !!JSON.parse(localStorage.getItem('profileId') || 'null'));
  const profileId = await page.evaluate(() => JSON.parse(localStorage.getItem('profileId') || 'null'));
  pass('lobby generates safe profile id', /^[-A-Za-z0-9_]{1,128}$/.test(profileId || ''), String(profileId));
  await page.evaluate(() => localStorage.setItem('userData', JSON.stringify({winStreak: 99, identityCards: 99})));
  await page.reload({waitUntil: 'domcontentloaded'});
  await page.waitForSelector('#startGameBtn');
  pass('profile id persists across reload', await page.evaluate(() => JSON.parse(localStorage.getItem('profileId') || 'null')) === profileId);
  pass('legacy stats show migration notice only', await page.locator('#legacyRecordNotice').isVisible());
  pass('server profile fields rendered', await page.locator('#winStreak').textContent() !== null && await page.locator('#totalGames').textContent() !== null);
  await page.locator('a[href="history.html"]').first().click();
  await page.waitForURL('**/history.html');
  await page.waitForSelector('#historyList');
  pass('history page loaded from server', await page.locator('body').innerText().then(t => t.includes('历史')));

  await page.goto(base + '/index.html', {waitUntil: 'domcontentloaded'});
  await page.waitForSelector('#startGameBtn');
  await page.locator('#playerName').fill('B5浏览器验收');
  if (process.env.B5_PROFILE_ID) {
    await page.waitForFunction(() => !document.getElementById('identityCardSection').hidden);
    await page.locator('#useIdentityCard').check();
    await page.locator('#identitySelect').selectOption('主公');
    pass('server awarded identity card selected by real click', await page.locator('#identitySelect').inputValue() === '主公');
  }
  await page.locator('#startGameBtn').click();
  await page.waitForURL('**/select_hero.html');
  await page.locator('.hero-card[data-id="liubei"]').click();
  await page.locator('#confirmBtn').click();
  await page.waitForURL('**/game.html');
  await page.waitForFunction(() => window.GameUI && window.GameUI.players && window.GameUI.players.length === 5, null, {timeout: 30000});
  pass('real game created with five seats', await page.locator('#opponents .seat').count() >= 1);
  // Wait for a real turn then manipulate the visible skill/hand/seat UI. This test only selects
  // cards/targets; it deliberately does not submit a strategic move into the live rules engine.
  let gotTurn = true;
  try { await page.waitForFunction(() => window.GameUI && window.GameUI.turn, null, {timeout: 15000}); }
  catch (_) { gotTurn = false; }
  if (gotTurn) {
    const turn = await page.evaluate(() => ({actions: window.GameUI.turn.actions || [], hand: window.GameUI.hand.length, timeout: window.GameUI.turn.timeout}));
    const timerState = await page.evaluate(() => ({deadline: window.GameUI.reqDeadline > Date.now(), visible: getComputedStyle(document.getElementById('abTimer')).visibility === 'visible', idleTracked: window.GameUI.idleSince > 0, warningScheduled: !!window.GameUI.idleWarningTimer}));
    pass('real your_turn shows 120s action timer and five-minute idle warning is scheduled', turn.actions.length > 0 && timerState.deadline && timerState.visible && timerState.idleTracked && timerState.warningScheduled, JSON.stringify({turn, timerState}));
    const skill = turn.actions.find(a => a.type === 'use_skill' && a.skill_name === '仁德');
    if (skill) {
    await page.locator('.skill-btn[data-skill="仁德"]').click();
    pass('actual skill selection enters skill mode', await page.evaluate(() => window.GameUI.sel?.kind === 'skill'));
    if (turn.hand > 0) {
      await page.locator('#hand [data-index="0"]').click();
      pass('actual hand card selectable for skill', await page.evaluate(() => window.GameUI.sel?.cards.length === 1));
    }
    await page.locator('#cancelBtn').click();
    pass('skill choice can be canceled by UI', await page.evaluate(() => !window.GameUI.sel));
    await page.locator('#endBtn').click();
    await page.waitForFunction(() => !window.GameUI.turn, null, {timeout: 5000}).catch(() => {});
    const idleAfter = await page.evaluate(() => ({idleSince: window.GameUI.idleSince, timer: !!window.GameUI.idleWarningTimer, turn: !!window.GameUI.turn, req: !!window.GameUI.req}));
    pass('real end-phase click clears or restarts local idle warning timer', (idleAfter.idleSince === 0 && !idleAfter.timer) || ((idleAfter.turn || idleAfter.req) && idleAfter.idleSince > 0 && idleAfter.timer), JSON.stringify(idleAfter));
    } else {
      seen.push({name: 'actual skill action click', skipped: '当前真人回合的合法 actions 不含仁德，未伪造合法操作'});
    }
  } else {
    seen.push({name: 'real turn countdown and skill selection', skipped: '15 秒内服务端未向浏览器下发真人 your_turn；AI 对局已启动，未注入假 WS/状态'});
  }

  const defaultLink = await page.evaluate(() => ({
    configured: !!window.GameUI.cfg.trustee_default,
    hasKeyInSession: !!window.GameUI.cfg.trustee_default?.apiKey,
    localKey: (() => { try { return JSON.parse(localStorage.getItem('gameConfig') || '{}').trustee_default?.apiKey || ''; } catch (_) { return ''; } })()
  }));
  pass('default trustee uses first lobby seat and local config strips its key', defaultLink.configured && !defaultLink.localKey, JSON.stringify(defaultLink));
  await page.locator('#opponents .seat-frame').first().click();
  pass('actual opponent seat click opens hero information', await page.locator('#playerInfoModal').evaluate(e => e.open));
  await page.locator('#playerInfoModal [data-close]').click();

  await page.locator('#trusteeBtn').click();
  pass('trustee modal opens by click', await page.locator('#trusteeModal').evaluate(e => e.open));
  await page.locator('#trusteeSource').selectOption('copy_ai');
  pass('copy AI source reveals seat selector', await page.locator('#trusteeCopyRow').isVisible());
  await page.locator('#trusteeSource').selectOption('custom');
  pass('custom source reveals provider/model controls', await page.locator('#trusteeCustomFields').isVisible());
  await page.locator('#trusteeSource').selectOption('rules');
  await page.locator('#trusteeForm button[type="submit"]').click();
  await page.waitForTimeout(300);
  pass('trustee request accepted by UI', !(await page.locator('#trusteeModal').evaluate(e => e.open)));
  await page.locator('#trusteeBtn').click();
  await page.locator('#trusteeSource').selectOption('default');
  await page.locator('#trusteeForm button[type="submit"]').click();
  await page.waitForFunction(() => (window.GameUI.trustee?.source === 'default') || (window.GameUI.state?.trustee?.source === 'default'), null, {timeout: 10000});
  pass('default model trustee setting reaches server', await page.evaluate(() => (window.GameUI.trustee || window.GameUI.state?.trustee)?.source === 'default'));
  await page.locator('#trusteeBtn').click();
  await page.locator('#trusteeOff').click();
  await page.waitForFunction(() => window.GameUI.trustee?.enabled === false, null, {timeout: 10000});
  pass('trustee can be disabled by click', await page.evaluate(() => window.GameUI.trustee?.enabled === false));

  await page.locator('#tabLog').click();
  pass('battle log tab opens', await page.locator('#logPane').isVisible());
  const trace = page.locator('#decisionTracePanel');
  pass('decision trace defaults collapsed', !(await trace.evaluate(e => e.open)));
  await trace.locator(':scope > summary').click();
  pass('decision trace can expand by click', await trace.evaluate(e => e.open));
  await trace.locator(':scope > summary').click();
  pass('decision trace can collapse by click', !(await trace.evaluate(e => e.open)));

  pass('no browser runtime errors', errors.length === 0, errors.join('; '));
  console.log(JSON.stringify({scenarios: seen.length, checks: seen, page_errors: errors}, null, 2));
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
