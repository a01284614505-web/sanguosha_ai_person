"""Browser-check public skill outcome messages and their saved replay timeline."""
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
from game_engine.game_logs import GameLogStore

with tempfile.TemporaryDirectory(prefix="skill-event-browser-") as tmp:
    root = Path(tmp)
    (root / "frontend").symlink_to(ROOT / "frontend", target_is_directory=True)
    game_server.BASE_DIR = root
    game_server.GAME_LOG_DIR = root / "runtime" / "game_logs"
    GameLogStore(game_server.GAME_LOG_DIR).save({
        "game_id": "skill_event_browser", "profile_id": "profile_skill_event_browser",
        "winner": "draw", "message": "浏览器技能轨迹验收", "rounds": 1, "duration": 10,
        "options": {"include_thinking": False}, "players": [],
        "timeline": [
            {"seq": 1, "round": 1, "kind": "skill_decision", "text": "AI接受【选目标试演】的选角色机会 · 已完成选择"},
            {"seq": 2, "round": 1, "kind": "skill_decision", "text": "AI拒绝【选目标试演】的发动机会 · 主动取消"},
            {"seq": 3, "round": 1, "kind": "dying_rescue", "text": "AI使用【桃】救援玩家"},
        ],
    })
    server = ThreadingHTTPServer(("127.0.0.1", 0), game_server.CustomHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    node = r'''
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.argv[1];
(async () => {
  const browser = await chromium.launch({headless:true,args:['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport:{width:1280,height:900}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.addInitScript(() => {
      localStorage.setItem('gameConfig', JSON.stringify({mode:'5人身份局',player_name:'浏览器玩家',
        selected_hero:{id:'caocao',name:'曹操'},ais:Array.from({length:4},(_,i)=>({name:'AI'+i}))}));
    });
    await page.goto(base + '/game.html');
    await page.waitForFunction(() => window.gameClient && typeof gameClient.onEventNotification === 'function');
    const live = await page.evaluate(() => {
      GameUI.players = [{id:1,name:'AI甲'},{id:2,name:'AI乙'}];
      gameClient.onEventNotification({event_kind:'skill_decision',actor_id:1,actor_name:'AI甲',skill_name:'选目标试演',
        decision:'declined',reason:'selection_cancelled',selection_kind:'choose_players'});
      gameClient.onEventNotification({event_kind:'skill_activation',actor_id:2,actor_name:'AI乙',skill_name:'摸牌试演'});
      gameClient.onEventNotification({event_kind:'dying_rescue',provider_id:1,target_id:2,card_name:'桃'});
      return {lines:Array.from(document.querySelectorAll('#log .log-line')).map(x=>({text:x.textContent,cls:x.className}))};
    });
    if (!live.lines.some(x=>x.cls.includes('skill-decision') && x.text.includes('主动取消'))) throw Error('skill decision was not shown as public result: '+JSON.stringify(live));
    if (!live.lines.some(x=>x.text.includes('发动【摸牌试演】'))) throw Error('skill activation fact missing');
    if (!live.lines.some(x=>x.text.includes('AI甲使用【桃】救援AI乙'))) throw Error('dying rescue event missing');

    await page.addInitScript(() => localStorage.setItem('profileId',JSON.stringify('profile_skill_event_browser')));
    await page.goto(base + '/logs.html');
    await page.locator('.log-item').waitFor();
    await page.locator('.log-item').click();
    await page.locator('#detailView:not([hidden])').waitFor();
    const replay = await page.evaluate(() => Array.from(document.querySelectorAll('#detailBody .tl-round .tl-line')).map(x=>({text:x.textContent,cls:x.className})));
    if (!replay.some(x=>x.cls.includes('tl-skill-decision') && x.text.includes('主动取消'))) throw Error('replay skill decision missing: '+JSON.stringify(replay));
    if (!replay.some(x=>x.cls.includes('tl-rescue') && x.text.includes('救援'))) throw Error('replay rescue event missing');
    if (errors.length) throw Error('Browser errors: '+JSON.stringify(errors));
    console.log(JSON.stringify({check:'SKILL_EVENT_BROWSER_OK',live,replay_count:replay.length,page_errors:errors},null,2));
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exit(1)});
'''
    try:
        result = subprocess.run(["node", "-e", node, f"http://127.0.0.1:{server.server_port}"],
            env=os.environ.copy(), timeout=45, check=False)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    if result.returncode:
        raise SystemExit(result.returncode)
