/* Verify per-skill parity details, freshness, cautious wording, and safe text rendering. */
'use strict';
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = (process.env.UI_BASE_URL || 'http://127.0.0.1:8888').replace(/\/$/, '');
const realApi = process.env.CERTIFICATION_REAL_API === '1';
const fixture = {
  success: true,
  report: {
    evidence_type: 'python_dsl_behavioral_parity', rules_version_verified: false,
    interpretation: 'Parity only',
    skills: [
      {skill: '英姿', status: 'scenario_parity', scenarios: ['test_yingzi_branch'], scope: 'draw phase; 3-card draw',
        branch_gaps: ['dead owner is not covered'], test_count: 1},
      {skill: '<img src=x onerror=alert(1)>', status: 'scenario_parity', scenarios: ['test_safe_text'], scope: 'safe rendering',
        branch_gaps: [], test_count: 1}
    ],
    supplemental_scenarios: [{id: 'abort_prompt', status: 'parity', covers: ['prompt cancellation'], skills_covered: ['英姿']}]
  }
};
(async () => {
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox'],
    ...(process.env.PLAYWRIGHT_EXECUTABLE_PATH ? {executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH} : {})});
  try {
    const page = await browser.newPage({viewport: {width: 390, height: 844}});
    const errors = [];
    let current = true;
    page.on('pageerror', error => errors.push(error.message));
    if (!realApi) await page.route('**/api/heroes/certification', route => route.fulfill({status: 200,
      contentType: 'application/json', body: JSON.stringify({...fixture, current})}));
    await page.goto(base + '/hero_manager.html');
    await page.waitForFunction(() => document.querySelector('#certificationStatus')?.textContent.includes('指纹'));
    await page.locator('#certificationOutput details.certification-item').first().waitFor();
    await page.locator('#certificationOutput details.certification-item').evaluateAll(items => items.forEach(item => { item.open = true; }));
    const currentCheck = await page.evaluate(() => ({
      status: document.querySelector('#certificationStatus').textContent,
      items: document.querySelectorAll('#certificationOutput details.certification-item').length,
      content: document.querySelector('#certificationOutput').innerText,
      injectedImages: document.querySelectorAll('#certificationOutput img').length,
      width: {body: document.documentElement.scrollWidth, viewport: innerWidth}
    }));
    if ((realApi ? currentCheck.items < 1 : currentCheck.items !== 2) ||
        (!realApi && (!currentCheck.content.includes('draw phase; 3-card draw') ||
          !currentCheck.content.includes('dead owner is not covered') || !currentCheck.content.includes('<img src=x onerror=alert(1)>'))) ||
        !currentCheck.content.includes('规则版本尚未核验') || currentCheck.injectedImages !== 0) {
      throw new Error('per-skill evidence was incomplete or unsafe: ' + JSON.stringify(currentCheck));
    }
    if (currentCheck.width.body > currentCheck.width.viewport + 1) throw new Error('mobile certification page overflows: ' + JSON.stringify(currentCheck.width));
    if (!realApi) {
      current = false;
      await page.locator('#refreshCertification').click();
      await page.waitForFunction(() => document.querySelector('#certificationStatus')?.textContent.includes('已过期'));
      if (await page.locator('.cert-stale-badge').count() !== 2) throw new Error('stale evidence badge missing on skill rows');
    }
    if (errors.length) throw new Error('page errors: ' + JSON.stringify(errors));
    console.log(JSON.stringify({check: realApi ? 'SKILL_CERTIFICATION_REAL_API_OK' : 'SKILL_CERTIFICATION_BROWSER_OK', viewport: '390x844',
      skill_rows: currentCheck.items, scope_and_gaps: true, rules_version_disclaimer: true,
      expired_marks: realApi ? 0 : 2, xss_safe: realApi ? 'fixture mode only' : true,
      no_horizontal_overflow: true, page_errors: errors}, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
