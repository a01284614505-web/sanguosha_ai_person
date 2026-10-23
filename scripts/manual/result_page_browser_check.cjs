/* Result-page smoke at desktop and phone widths against a running local server. */
'use strict';
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = (process.env.UI_BASE_URL || 'http://127.0.0.1:8888').replace(/\/$/, '');
const result = {
  winner: 'lord', player_won: true, player_identity: 'lord', total_rounds: 4, duration: 125,
  game_id: 'ui-result-browser-check', log_saved: true, reward: 'identity_card',
  profile: {win_streak: 2, total_games: 7, identity_cards: 1, titles: {equipped: null}},
  mvp: {player_id: 1, hero_id: 'liubei', hero_name: '刘备', player_name: '刘备', damage_dealt: 3, kills: 1, healing: 2, cards_played: 9},
  players: [{id: 0, seat: 1, name: '浏览器玩家', hero_name: '曹操', identity: 'lord', alive: true,
    hero: {id: 'caocao', name: '曹操'}, stats: {damage_dealt: 2, damage_taken: 1, healing: 1, kills: 0, cards_played: 8, cards_lost: 2, skill_activations: 1}},
    {id: 1, seat: 2, name: '刘备', hero_name: '刘备', identity: 'loyalist', alive: true,
      hero: {id: 'liubei', name: '刘备'}, stats: {damage_dealt: 3, damage_taken: 2, healing: 2, kills: 1, cards_played: 9, cards_lost: 3, skill_activations: 2}}]
};
(async () => {
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  const report = [];
  try {
    for (const [label, width, height] of [['desktop', 1280, 900], ['mobile', 390, 844]]) {
      const page = await browser.newPage({viewport: {width, height}});
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(base + '/result.html');
      await page.waitForSelector('#resultMain');
      if (!(await page.locator('#resultMain').innerText()).includes('暂无战绩')) throw new Error(label + ': empty-result fallback missing');
      await page.evaluate(data => localStorage.setItem('gameResult', JSON.stringify(data)), result);
      await page.reload();
      await page.waitForFunction(() => document.querySelector('#resultTitle')?.textContent === '旗开得胜');
      if ((await page.locator('#statsList tbody tr').count()) !== 2) throw new Error(label + ': result stats rows missing');
      if (!(await page.locator('#rewardSection').isVisible())) throw new Error(label + ': identity-card reward missing');
      if (!(await page.locator('#viewLogBtn').getAttribute('href')).includes('ui-result-browser-check')) throw new Error(label + ': result log link missing');
      const layout = await page.evaluate(() => ({viewport: innerWidth, body: document.documentElement.scrollWidth,
        table: document.querySelector('#statsList').scrollWidth, tableClient: document.querySelector('#statsList').clientWidth}));
      if (width <= 500 && layout.body > width + 1) throw new Error(label + ': page has horizontal overflow ' + JSON.stringify(layout));
      if (errors.length) throw new Error(label + ': JS errors ' + JSON.stringify(errors));
      report.push({viewport: label, no_result_fallback: true, players: 2, reward: true, log_link: true, layout});
      await page.close();
    }
    console.log(JSON.stringify({check: 'RESULT_PAGE_BROWSER_OK', report}, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
