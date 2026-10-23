"""Check public timeline replay controls, keyboard, switching, and legacy fallbacks."""
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

with tempfile.TemporaryDirectory(prefix="timeline-player-browser-") as tmp:
    root = Path(tmp)
    (root / "frontend").symlink_to(ROOT / "frontend", target_is_directory=True)
    game_server.BASE_DIR = root
    game_server.GAME_LOG_DIR = root / "runtime" / "game_logs"
    store = GameLogStore(game_server.GAME_LOG_DIR)
    common = {"profile_id": "profile_timeline_browser", "winner": "draw", "rounds": 2,
        "duration": 10, "options": {"include_thinking": False}, "players": [], "decisions": []}
    store.save(dict(common, game_id="timeline_ordered", message="有序日志", timeline=[
        {"seq": 4, "round": 2, "kind": "event", "text": "第三条公开事件"},
        {"seq": 1, "round": 1, "kind": "event", "text": "第一条公开事件"},
        {"seq": 2, "round": 1, "kind": "skill_decision", "text": "第二条公开事件"},
    ]))
    store.save(dict(common, game_id="timeline_legacy", message="旧格式日志", timeline=[
        {"round": 1, "kind": "event", "text": "旧事件甲"}, {"round": 2, "kind": "event", "text": "旧事件乙"},
    ]))
    store.save(dict(common, game_id="timeline_empty", message="无轨迹日志", timeline=[]))
    server = ThreadingHTTPServer(("127.0.0.1", 0), game_server.CustomHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    node = r'''
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');const base=process.argv[1];
(async()=>{const browser=await chromium.launch({headless:true,args:['--no-sandbox']});try{
 const page=await browser.newPage({viewport:{width:1280,height:900}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>localStorage.setItem('profileId',JSON.stringify('profile_timeline_browser')));
 await page.goto(base+'/logs.html');await page.locator('.log-item').first().waitFor();
 async function open(title){if(await page.locator('#detailView').isVisible())await page.locator('#backBtn').click();await page.locator('.log-item').filter({hasText:title}).click();await page.locator('#detailView:not([hidden])').waitFor();}
 async function index(){return Number(await page.locator('.tl-active').getAttribute('data-timeline-index'));}
 await open('有序日志');
 if(await index()!==0||!(await page.locator('.tl-active').textContent()).includes('第一条'))throw Error('initial/seq ordering failed');
 await page.locator('#timelineNextBtn').click();if(await index()!==1)throw Error('next button failed');
 await page.locator('#timelinePrevBtn').click();if(await index()!==0)throw Error('previous button failed');
 await page.locator('#timelineLastBtn').click();if(await index()!==2)throw Error('last button failed');
 await page.locator('#timelineFirstBtn').click();if(await index()!==0)throw Error('first button failed');
 await page.keyboard.press('ArrowRight');if(await index()!==1)throw Error('ArrowRight failed');
 await page.keyboard.press('ArrowLeft');if(await index()!==0)throw Error('ArrowLeft failed');
 await page.keyboard.press('End');if(await index()!==2)throw Error('End failed');
 await page.keyboard.press('Home');if(await index()!==0)throw Error('Home failed');
 const speeds=await page.locator('#timelineSpeed option').evaluateAll(xs=>xs.map(x=>x.value));
 if(speeds.join(',')!=='0.5,1,2')throw Error('speed options missing '+speeds);
 await page.locator('#timelineSpeed').selectOption('2');
 await page.locator('#timelinePlayBtn').click();
 await page.waitForFunction(()=>document.querySelector('.tl-active')?.dataset.timelineIndex==='1',{timeout:1800});
 await page.keyboard.press('Space');
 const paused=await index();await page.waitForTimeout(650);if(await index()!==paused)throw Error('keyboard pause did not stop playback');
 await page.locator('#timelinePlayBtn').click();
 await page.locator('#timelinePlayBtn').click();
 const buttonPaused=await index();await page.waitForTimeout(650);if(await index()!==buttonPaused)throw Error('button pause did not stop playback');
 await open('旧格式日志');
 if(await index()!==0||!(await page.locator('.tl-active').textContent()).includes('旧事件甲'))throw Error('legacy no-seq order/reset failed');
 await page.locator('#timelineNextBtn').click();if(await index()!==1||!(await page.locator('.tl-active').textContent()).includes('旧事件乙'))throw Error('legacy next event failed');
 await open('无轨迹日志');
 if(await page.locator('#timelinePlayBtn').isDisabled()===false)throw Error('empty timeline controls should be disabled');
 if(await page.locator('.tl-active').count())throw Error('switching to empty timeline left stale highlight');
 if(errors.length)throw Error('page errors '+JSON.stringify(errors));
 console.log(JSON.stringify({check:'TIMELINE_PLAYER_BROWSER_OK',ordered_controls:true,keyboard:['ArrowLeft','ArrowRight','Home','End'],speed_options:speeds,pause:true,legacy_no_seq:true,empty_timeline:true,page_errors:errors},null,2));
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
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
