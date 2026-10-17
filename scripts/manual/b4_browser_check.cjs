// DEPRECATED: superseded by b5_b7_browser_check.cjs; the former window.selectTarget API was removed.
/**
 * B4 Chromium 检查：先运行 game_server.py，再提供 Playwright 模块路径。
 * 例如：npm install --prefix /tmp/b4-browser-check playwright
 * PLAYWRIGHT_MODULE=/tmp/b4-browser-check/node_modules/playwright node scripts/manual/b4_browser_check.cjs
 */
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('fs');
const path = require('path');
const root = path.resolve(__dirname, '../..');
const manifest = fs.readdirSync(root + '/frontend/assets/cards').filter(file => file.endsWith('.png')).map(file => ({image: file.slice(0, -4)}));
(async () => {
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  const page = await browser.newPage({viewport: {width: 1280, height: 800}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem('gameConfig', JSON.stringify({
    mode: '5人身份局', player_name: 'B4浏览器验收',
    selected_hero: {id: 'caocao', name: '曹操'},
    ais: Array.from({length: 4}, (_, i) => ({name: `AI${i}`})),
    deck_id: 'combined', chat_enabled: false
  })));
  await page.goto((process.env.B4_BASE_URL || 'http://127.0.0.1:8888') + '/game.html', {waitUntil: 'domcontentloaded'});
  await page.waitForFunction(() => typeof window.selectTarget === 'function' && !!window.GameUI, null, {timeout: 10000});
  // 真实浏览器逐个解码 PNG，覆盖服务端静态路径与浏览器图片加载能力。
  const art = await page.evaluate(async slugs => Promise.all(slugs.map(slug => new Promise(resolve => {
    const image = new Image();
    image.onload = () => resolve({slug, ok: image.naturalWidth > 0, width: image.naturalWidth});
    image.onerror = () => resolve({slug, ok: false, width: 0});
    image.src = 'assets/cards/' + slug + '.png';
  }))), manifest.map(item => item.image));
  if (art.length !== 42 || art.some(item => !item.ok)) {
    throw new Error('Failed art: ' + JSON.stringify(art.filter(item => !item.ok)));
  }
  // 方天画戟使用合法候选组的前缀选择逻辑；在隔离的假目标上检查提交参数。
  const targetCheck = await page.evaluate(() => {
    for (const id of [101, 102, 103]) {
      const p = document.createElement('div'); p.className = 'pl'; p.id = 'opp_' + id;
      document.body.appendChild(p);
    }
    GameUI.sel = 0;
    GameUI.selectedLegalAction = {type: 'play_card', card_index: 0,
      requires_target: true, target_count: 3,
      valid_targets: [101, 102, 103],
      valid_target_groups: [[101], [101, 102], [101, 102, 103]]};
    GameUI.targetSelection = [];
    selectTarget(101); selectTarget(102); selectTarget(103);
    return {selection: GameUI.targetSelection, pending: GameUI.pendingAction};
  });
  if (JSON.stringify(targetCheck.pending?.target_ids) !== JSON.stringify([101,102,103])) {
    throw new Error('Fangtian target UI failed: ' + JSON.stringify(targetCheck));
  }
  if (errors.length) throw new Error('Browser JS errors: ' + JSON.stringify(errors));
  console.log(JSON.stringify({url: page.url(), art_loaded: art.length,
    art_min_width: Math.min(...art.map(item => item.width)), targetCheck,
    page_errors: errors, viewport: '1280x800'}, null, 2));
  await browser.close();
})().catch(error => {console.error(error); process.exit(1)});
