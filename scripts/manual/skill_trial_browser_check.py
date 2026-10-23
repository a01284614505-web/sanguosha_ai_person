"""Exercise the skill trial UI and real HTTP endpoint with isolated temporary data.

Usage: PLAYWRIGHT_MODULE=/tmp/b4-browser-check/node_modules/playwright python3 \
       scripts/manual/skill_trial_browser_check.py
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import game_server

SCENARIOS = ["active_choose_target", "damage_received", "phase_draw", "cancel_activation"]
SKILLS = [
    {"name": "选目标试演", "implementation_status": "active", "dsl": {
        "version": 1, "trigger": "play_action",
        "cost": [{"interaction": "ask_confirm", "prompt": "是否发动？"}],
        "targets": {"selector": "chosen_players", "candidates": "alive_others", "min": 1, "max": 1},
        "effects": [{"type": "draw_cards", "target": "targets", "count": 1, "reason": "选目标试演"}]}},
    {"name": "受伤试演", "implementation_status": "active", "dsl": {
        "version": 1, "trigger": "damage_received",
        "effects": [{"type": "draw_cards", "target": "owner", "count": 1, "reason": "受伤试演"}]}},
    {"name": "摸牌试演", "implementation_status": "active", "dsl": {
        "version": 1, "trigger": "phase_start",
        "condition": {"op": "eq", "path": "event.phase", "value": "draw"},
        "effects": [{"type": "draw_cards", "target": "owner", "count": 1, "reason": "摸牌试演"}]}}
]

with tempfile.TemporaryDirectory(prefix="skill-trial-browser-") as tmp:
    data = Path(tmp) / "data"
    data.mkdir()
    (data / "heroes.json").write_bytes((ROOT / "data" / "heroes.json").read_bytes())
    (Path(tmp) / "frontend").symlink_to(ROOT / "frontend", target_is_directory=True)
    game_server.BASE_DIR = Path(tmp)
    formal_packages = ROOT / "data" / "hero_packages.json"
    before_hash = hashlib.sha256(formal_packages.read_bytes()).hexdigest() if formal_packages.exists() else None
    server = ThreadingHTTPServer(("127.0.0.1", 0), game_server.CustomHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    node = r'''
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.argv[1];
const scenarios = JSON.parse(process.argv[2]);
const skills = JSON.parse(process.argv[3]);
(async () => {
  const browser = await chromium.launch({headless:true,args:['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport:{width:1280,height:900}});
    const errors = [];
    const apiResults = [];
    const requestPayloads = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(base + '/hero_manager.html');
    await page.locator('#trialTitle').waitFor();
    const results = [];
    for (const scenario of scenarios) {
      await page.locator('#outputJSON').fill(JSON.stringify({id:'trial_browser_hero',name:'试验浏览器将',faction:'吴',max_hp:4,
        skills}));
      await page.locator('.trial-scenario[data-scenario="'+scenario+'"]').click();
      await page.locator('#trialSeed').fill('20261019');
      const requestPromise = page.waitForRequest(request => request.url().endsWith('/api/heroes/trial'));
      const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/heroes/trial'));
      await page.locator('#runSkillTrial').click();
      const request = await requestPromise;
      requestPayloads.push(request.postDataJSON());
      const response = await responsePromise;
      apiResults.push(await response.json());
      await page.waitForFunction(() => document.querySelector('#trialStatus').textContent !== '正在创建隔离试验…', null, {timeout:15000});
      const result = await page.evaluate(() => ({status:document.querySelector('#trialStatus').textContent,
        outcome:document.querySelector('#trialOutput h3')?.textContent || '',
        cards:Array.from(document.querySelectorAll('#trialOutput h3')).map(x=>x.textContent)}));
      if (!result.outcome) throw Error(scenario + ' did not render structured trial result: ' + result.status);
      if (!result.cards.includes('触发与选择轨迹') || !result.cards.includes('状态差异')) throw Error(scenario + ' missing trace/diff cards');
      results.push({scenario,...result});
    }
    const expectedOutcomes = ['success','success','success','declined'];
    const expectedChoices = [2,0,0,1];
    const expectedMoves = [1,1,3,0];
    if (apiResults.length !== scenarios.length) throw Error('Expected four real trial responses; got ' + apiResults.length);
    apiResults.forEach((payload, i) => {
      if (!payload.success || payload.trial.outcome !== expectedOutcomes[i]) throw Error('Unexpected outcome for ' + scenarios[i] + ': ' + JSON.stringify(payload));
      if (payload.trial.choices.length !== expectedChoices[i] || payload.trial.card_moves.length !== expectedMoves[i]) throw Error('Unexpected choice/move counts for ' + scenarios[i]);
      if (payload.trial.scenario_id !== scenarios[i]) throw Error('Scenario order mismatch for ' + scenarios[i]);
    });
    requestPayloads.forEach((payload, i) => {
      if (JSON.stringify(Object.keys(payload).sort()) !== JSON.stringify(['hero','package','scenario_id','seed'])) throw Error('Unexpected request keys: ' + JSON.stringify(payload));
      if (JSON.stringify(Object.keys(payload.hero).sort()) !== JSON.stringify(['faction','id','max_hp','name','skills'])) throw Error('Unexpected hero fields: ' + JSON.stringify(payload.hero));
      if (payload.scenario_id !== scenarios[i] || payload.seed !== 20261019) throw Error('Request scenario or seed mismatch');
    });
    if (errors.length) throw Error('Browser errors: ' + JSON.stringify(errors));
    console.log(JSON.stringify({check:'SKILL_TRIAL_BROWSER_OK',results,api_outcomes:apiResults.map(x=>x.trial.outcome),
      choice_counts:apiResults.map(x=>x.trial.choices.length),move_counts:apiResults.map(x=>x.trial.card_moves.length),
      request_keys:Object.keys(requestPayloads[0]).sort(),formal_package_data:'unchanged',page_errors:errors},null,2));
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exit(1)});
'''
    try:
        result = subprocess.run(
            ["node", "-e", node, f"http://127.0.0.1:{server.server_port}", json.dumps(SCENARIOS), json.dumps(SKILLS)],
            env=os.environ.copy(), timeout=75, check=False)
        package_file = data / "hero_packages.json"
        if package_file.exists():
            raise RuntimeError("Trial unexpectedly persisted package data: " + str(package_file))
        after_hash = hashlib.sha256(formal_packages.read_bytes()).hexdigest() if formal_packages.exists() else None
        if before_hash != after_hash:
            raise RuntimeError("Formal hero_packages.json changed during isolated trial")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    if result.returncode:
        raise SystemExit(result.returncode)
