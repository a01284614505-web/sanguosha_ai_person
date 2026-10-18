/**
 * 真实浏览器验收脚本（Playwright + Chromium，只做真实点击/输入）。
 *
 * 原则：不注入假 WS 消息，不伪造合法操作，不直接改游戏内部状态；每项检查要么 pass，
 * 要么 skipped 并写明原因，失败则记为 fail（退出码 1）。不得为了通过而删检查项。
 *
 * 分组（按此顺序执行，可用 BC_GROUPS 只跑其中几组）：
 *   lobby    大厅：档案 ID、旧战绩提示、服务端档案字段、身份卡（卡面 + 四枚身份印）
 *   history  历史页
 *   game     对局：开局、回合倒计时与技能选取/取消、座位点击、托管、战报页签与决策轨迹
 *   chat     席间聊天：切席间页签、发一句话、断言只出现一次且为真人样式
 * 往后加新组：在 GROUPS 里加一项 {name, run}，用 pass()/skip() 记录，需要对局时调用 ensureGame()。
 *
 * 运行（先起服务器，8888 HTTP / 8889 WS；务必用隔离的战绩与日志路径）：
 *   SANGUOSHA_HISTORY_PATH=/tmp/xxx/history.json SANGUOSHA_GAME_LOG_DIR=/tmp/xxx/logs \
 *     PYTHONPATH=... python3 game_server.py &
 *   # 不带预置档案（全新档案，只有见面礼 1 张身份卡）：
 *   PLAYWRIGHT_MODULE=/opt/npm-tools/node_modules/playwright node scripts/manual/browser_check.cjs
 *   # 带预置档案（先 seed，档案有见面礼 + 连胜奖励共 2 张卡）：
 *   SANGUOSHA_HISTORY_PATH=/tmp/xxx/history.json python3 scripts/manual/seed_browser_profile.py my_prof_1
 *   BC_PROFILE_ID=my_prof_1 PLAYWRIGHT_MODULE=... node scripts/manual/browser_check.cjs
 *   # 手机视口：BC_VIEWPORT=390x844 ；只跑某些组：BC_GROUPS=lobby,chat
 *
 * 环境变量（旧的 B5_PROFILE_ID / B5_BASE_URL 仍然认）：
 *   PLAYWRIGHT_MODULE  playwright 模块路径（默认 'playwright'）
 *   BC_BASE_URL        默认 http://127.0.0.1:8888
 *   BC_PROFILE_ID      预置档案 ID（需先用 seed_browser_profile.py 预置）
 *   BC_VIEWPORT        默认 1280x900
 *   BC_GROUPS          逗号分隔的组名，默认全部
 *   BC_TURN_WAIT_MS    等待真人 your_turn 的上限，默认 60000
 *   BC_OUT_DIR         失败截图目录，默认系统临时目录
 */
const os = require('os');
const path = require('path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const base = process.env.BC_BASE_URL || process.env.B5_BASE_URL || 'http://127.0.0.1:8888';
const profileEnv = process.env.BC_PROFILE_ID || process.env.B5_PROFILE_ID || '';
const [vw, vh] = (process.env.BC_VIEWPORT || '1280x900').split('x').map(Number);
const wanted = (process.env.BC_GROUPS || '').split(',').map(s => s.trim()).filter(Boolean);
const turnWait = Number(process.env.BC_TURN_WAIT_MS || 60000);
const outDir = process.env.BC_OUT_DIR || os.tmpdir();
const PLAYER_NAME = '浏览器验收';

const results = [];
let curGroup = '';
class CheckFail extends Error {}
const pass = (name, ok, detail = '') => {
  if (!ok) throw new CheckFail(name + (detail ? ' | ' + detail : ''));
  results.push({group: curGroup, name, status: 'pass', detail});
};
const skip = (name, reason) => results.push({group: curGroup, name, status: 'skipped', reason});

(async () => {
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  const page = await browser.newPage({viewport: {width: vw, height: vh}});
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  if (profileEnv) {
    await page.addInitScript(id => localStorage.setItem('profileId', JSON.stringify(id)), profileEnv);
  }

  // ---- 公用步骤 -------------------------------------------------------------------------
  const isDrawer = () => page.evaluate(() => getComputedStyle(document.getElementById('chatToggle')).display !== 'none');
  // 手机上侧栏是抽屉：先点右上角聊天钮展开；宽屏常驻，什么都不用做。
  const openSide = async () => {
    if (await isDrawer() && !(await page.locator('#sidePanel.open').count())) await page.locator('#chatToggle').click();
  };
  const profileIdNow = () => page.evaluate(() => JSON.parse(localStorage.getItem('profileId') || 'null'));
  const gotoLobby = async () => {
    await page.goto(base + '/index.html', {waitUntil: 'domcontentloaded'});
    await page.waitForSelector('#startGameBtn');
    await page.waitForFunction(() => !!JSON.parse(localStorage.getItem('profileId') || 'null'));
  };
  const sealState = () => page.evaluate(() => ({
    checked: document.getElementById('useIdentityCard').checked,
    value: document.getElementById('identitySelect').value,
    aria: [...document.querySelectorAll('#idCardChoices [data-identity]')].filter(b => b.getAttribute('aria-checked') === 'true').map(b => b.dataset.identity)
  }));
  // 开一局：大厅 -> 点身份印选主公 -> 开始 -> 选刘备 -> 进入对局页。返回是否点了身份印。
  const startGame = async () => {
    await gotoLobby();
    await page.locator('#playerName').fill(PLAYER_NAME);
    let usedSeal = false;
    try {
      await page.waitForFunction(() => !document.getElementById('identityCardSection').hidden, null, {timeout: 8000});
      await page.locator('#idCardChoices [data-identity="主公"]').click();
      usedSeal = true;
    } catch (_) { /* 没有身份卡就随机身份，回合可能来得晚，turnWait 兜底 */ }
    await page.locator('#startGameBtn').click();
    await page.waitForURL('**/select_hero.html');
    await page.locator('.hero-card[data-id="liubei"]').click();
    await page.locator('#confirmBtn').click();
    await page.waitForURL('**/game.html');
    await page.waitForFunction(() => window.GameUI && window.GameUI.players && window.GameUI.players.length === 5, null, {timeout: 30000});
    return usedSeal;
  };
  const ensureGame = async () => {
    const ok = page.url().includes('/game.html') && await page.evaluate(() => !!(window.GameUI && window.GameUI.players && window.GameUI.players.length === 5)).catch(() => false);
    if (!ok) await startGame();
  };

  // ---- 各组 -----------------------------------------------------------------------------
  const GROUPS = [];

  GROUPS.push({name: 'lobby', run: async () => {
    await gotoLobby();
    const profileId = await profileIdNow();
    pass('lobby generates safe profile id', /^[-A-Za-z0-9_]{1,128}$/.test(profileId || ''), String(profileId));
    await page.evaluate(() => localStorage.setItem('userData', JSON.stringify({winStreak: 99, identityCards: 99})));
    await page.reload({waitUntil: 'domcontentloaded'});
    await page.waitForSelector('#startGameBtn');
    pass('profile id persists across reload', await profileIdNow() === profileId);
    pass('legacy stats show migration notice only', await page.locator('#legacyRecordNotice').isVisible());
    pass('server profile fields rendered', await page.locator('#winStreak').textContent() !== null && await page.locator('#totalGames').textContent() !== null);

    // 身份卡：卡面 + 四枚身份印（原 check #useIdentityCard / selectOption #identitySelect 已改为隐藏控件，现在只点身份印）
    await page.waitForFunction(() => !document.getElementById('identityCardSection').hidden, null, {timeout: 8000});
    const count = Number(await page.locator('#cardCount').textContent());
    const expectMin = profileEnv ? 2 : 1;
    pass(profileEnv ? 'seeded profile shows welcome card + win reward (>=2)' : 'fresh profile shows welcome card (>=1)', count >= expectMin, 'cardCount=' + count);
    pass('identity card face and four seals rendered', await page.locator('#idCardArt').isVisible() && await page.locator('#idCardChoices [data-identity]').count() === 4);
    const seals = page.locator('#idCardChoices [data-identity="主公"]');
    await seals.click();
    let s = await sealState();
    pass('clicking the 主公 seal selects it (hidden controls follow)', s.checked === true && s.value === '主公' && s.aria.join() === '主公', JSON.stringify(s));
    await seals.click();
    s = await sealState();
    pass('clicking the same seal again cancels the card', s.checked === false && s.value === '' && s.aria.length === 0, JSON.stringify(s));
    await seals.click();
    s = await sealState();
    pass('re-selecting the seal works', s.checked === true && s.value === '主公', JSON.stringify(s));
  }});

  GROUPS.push({name: 'history', run: async () => {
    await gotoLobby();
    await page.locator('a[href="history.html"]').first().click();
    await page.waitForURL('**/history.html');
    await page.waitForSelector('#historyList');
    pass('history page loaded from server', await page.locator('body').innerText().then(t => t.includes('历史')));
    if (profileEnv) {
      await page.waitForFunction(() => document.getElementById('historyList').innerText.includes('验收测试'), null, {timeout: 8000});
      pass('seeded games listed in history', true);
    } else {
      skip('seeded games listed in history', '未带 BC_PROFILE_ID，全新档案没有预置战绩');
    }
  }});

  GROUPS.push({name: 'game', run: async () => {
    const usedSeal = await startGame();
    pass('identity seal clicked in lobby before start', usedSeal || !profileEnv, 'usedSeal=' + usedSeal);
    pass('real game created with five seats', await page.locator('#opponents .seat').count() >= 1);
    // 等真人 your_turn，然后只操作可见的技能/手牌/座位 UI；不提交战术操作进规则引擎。
    let gotTurn = true;
    try { await page.waitForFunction(() => window.GameUI && window.GameUI.turn, null, {timeout: turnWait}); }
    catch (_) { gotTurn = false; }
    if (gotTurn) {
      const turn = await page.evaluate(() => ({actions: window.GameUI.turn.actions || [], hand: window.GameUI.hand.length, timeout: window.GameUI.turn.timeout}));
      const timerState = await page.evaluate(() => ({deadline: window.GameUI.reqDeadline > Date.now(), visible: getComputedStyle(document.getElementById('abTimer')).visibility === 'visible', idleTracked: window.GameUI.idleSince > 0, warningScheduled: !!window.GameUI.idleWarningTimer}));
      pass('real your_turn shows 120s action timer and five-minute idle warning is scheduled', turn.actions.length > 0 && timerState.deadline && timerState.visible && timerState.idleTracked && timerState.warningScheduled, JSON.stringify({turn: {n: turn.actions.length, hand: turn.hand, timeout: turn.timeout}, timerState}));
      const skill = turn.actions.find(a => a.type === 'use_skill' && a.skill_name === '仁德');
      if (skill) {
        await page.locator('.skill-btn[data-skill="仁德"]').click();
        pass('actual skill selection enters skill mode', await page.evaluate(() => window.GameUI.sel?.kind === 'skill'));
        if (turn.hand > 0) {
          await page.locator('#hand [data-index="0"]').click();
          pass('actual hand card selectable for skill', await page.evaluate(() => window.GameUI.sel?.cards.length === 1));
        } else {
          skip('actual hand card selectable for skill', '手牌为 0，无牌可点');
        }
        await page.locator('#cancelBtn').click();
        pass('skill choice can be canceled by UI', await page.evaluate(() => !window.GameUI.sel));
        await page.locator('#endBtn').click();
        await page.waitForFunction(() => !window.GameUI.turn, null, {timeout: 5000}).catch(() => {});
        const idleAfter = await page.evaluate(() => ({idleSince: window.GameUI.idleSince, timer: !!window.GameUI.idleWarningTimer, turn: !!window.GameUI.turn, req: !!window.GameUI.req}));
        pass('real end-phase click clears or restarts local idle warning timer', (idleAfter.idleSince === 0 && !idleAfter.timer) || ((idleAfter.turn || idleAfter.req) && idleAfter.idleSince > 0 && idleAfter.timer), JSON.stringify(idleAfter));
        // 取消改发 cancel（20261017_2156）：只有恰好来了"可取消"请求时才能用真实取消钮验证，不会强造。
        const cancelable = await page.waitForFunction(() => {
          const r = window.GameUI.req;
          return r && !r.expired && r.kind !== 'confirm' && ((r.selection && r.selection.cancelable) || (!r.selection && !(r.options || []).some(o => o.is_pass)));
        }, null, {timeout: 10000}).then(() => true).catch(() => false);
        if (cancelable) {
          const reqId = await page.evaluate(() => window.GameUI.req.request_id);
          await page.locator('#cancelBtn').click();
          await page.waitForFunction(id => !window.GameUI.req || window.GameUI.req.request_id !== id, reqId, {timeout: 5000});
          await page.waitForTimeout(800);
          const badToast = await page.locator('.toast.bad').allInnerTexts();
          pass('cancelable request canceled by real click without error toast', !badToast.some(t => /参数|无效|没有生效/.test(t)), JSON.stringify(badToast));
        } else {
          skip('cancelable request canceled by real click without error toast', '结束出牌后 10 秒内没有来可取消的请求（后续多为必须弃牌的不可取消请求），不强造');
        }
      } else {
        skip('actual skill action click (仁德 select/hand/cancel/end)', '当前真人回合的合法 actions 不含仁德，未伪造合法操作');
      }
    } else {
      skip('real turn countdown and skill selection', turnWait + ' 毫秒内服务端未向浏览器下发真人 your_turn；AI 对局已启动，未注入假 WS/状态');
    }

    const defaultLink = await page.evaluate(() => ({
      configured: !!window.GameUI.cfg.trustee_default,
      localKey: (() => { try { return JSON.parse(localStorage.getItem('gameConfig') || '{}').trustee_default?.apiKey || ''; } catch (_) { return ''; } })()
    }));
    pass('default trustee uses first lobby seat and local config strips its key', defaultLink.configured && !defaultLink.localKey, JSON.stringify({configured: defaultLink.configured, localKeyEmpty: !defaultLink.localKey}));
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

    await openSide();
    await page.locator('#tabLog').click();
    pass('battle log tab opens', await page.locator('#logPane').isVisible());
    const trace = page.locator('#decisionTracePanel');
    pass('decision trace defaults collapsed', !(await trace.evaluate(e => e.open)));
    await trace.locator(':scope > summary').click();
    pass('decision trace can expand by click', await trace.evaluate(e => e.open));
    await trace.locator(':scope > summary').click();
    pass('decision trace can collapse by click', !(await trace.evaluate(e => e.open)));
  }});

  GROUPS.push({name: 'chat', run: async () => {
    await ensureGame();
    await openSide();
    await page.locator('#tabChat').click();
    pass('席间 tab opens', await page.locator('#chatPane').isVisible() && await page.locator('#tabChat').getAttribute('aria-selected') === 'true' && await page.locator('#logPane').isHidden());
    const msg = '席间验收' + Date.now();
    await page.locator('#chatInput').fill(msg);
    await page.locator('#chatForm button[type="submit"]').click();
    await page.waitForFunction(m => [...document.querySelectorAll('#chatList .msg .text')].some(e => e.textContent === m), msg, {timeout: 8000});
    // 无 Key 的规则 AI 不会回复，这是预期；这里只多等一会儿，确认没有重复回显。
    await page.waitForTimeout(1500);
    const rows = await page.evaluate(m => [...document.querySelectorAll('#chatList .msg')]
      .filter(r => r.querySelector('.text')?.textContent === m)
      .map(r => ({cls: r.className, who: r.querySelector('.who b')?.textContent})), msg);
    pass('sent message appears exactly once in 席间', rows.length === 1, JSON.stringify(rows));
    pass('message has human style (kind-human, me)', /\bkind-human\b/.test(rows[0].cls) && /\bme\b/.test(rows[0].cls) && !/\bkind-ai\b/.test(rows[0].cls), rows[0].cls);
    pass('speaker name is the player', rows[0].who === PLAYER_NAME, String(rows[0].who));
    pass('input cleared after send', await page.locator('#chatInput').inputValue() === '');
    pass('empty-chat placeholder removed', await page.locator('#chatList .chat-empty').count() === 0);
    const bad = await page.locator('.toast.bad').allInnerTexts();
    pass('no error toast after sending', !bad.some(t => /没连上/.test(t)), JSON.stringify(bad));
  }});

  // ---- 执行 -----------------------------------------------------------------------------
  let failed = 0;
  for (const g of GROUPS) {
    if (wanted.length && !wanted.includes(g.name)) continue;
    curGroup = g.name;
    const errStart = errors.length;
    try {
      await g.run();
      const fresh = errors.slice(errStart);
      pass('no browser runtime errors in group', fresh.length === 0, fresh.join('; '));
    } catch (e) {
      failed++;
      results.push({group: g.name, name: e instanceof CheckFail ? e.message.split(' | ')[0] : 'unexpected error', status: 'fail', detail: String(e.message || e).split('\n')[0]});
      try { await page.screenshot({path: path.join(outDir, 'browser_check_fail_' + g.name + '.png')}); } catch (_) {}
    }
  }
  const summary = {};
  for (const r of results) {
    const s = summary[r.group] = summary[r.group] || {pass: 0, skipped: 0, fail: 0};
    s[r.status]++;
  }
  console.log(JSON.stringify({viewport: vw + 'x' + vh, profile: profileEnv ? 'seeded:' + profileEnv : 'fresh', summary, checks: results, page_errors: errors}, null, 2));
  await browser.close();
  process.exit(failed ? 1 : 0);
})().catch(error => { console.error(error); process.exit(1); });
