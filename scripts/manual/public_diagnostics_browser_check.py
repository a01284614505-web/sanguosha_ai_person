"""Verify public situation/selection diagnostics render and legacy logs stay compatible."""
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

with tempfile.TemporaryDirectory(prefix="public-diagnostics-browser-") as tmp:
    root = Path(tmp)
    (root / "frontend").symlink_to(ROOT / "frontend", target_is_directory=True)
    game_server.BASE_DIR = root
    game_server.GAME_LOG_DIR = root / "runtime" / "game_logs"
    store = GameLogStore(game_server.GAME_LOG_DIR)
    store.save({
        "game_id": "diagnostics_browser", "profile_id": "profile_diagnostics_browser",
        "winner": "draw", "message": "公开诊断验收", "rounds": 2, "duration": 20,
        "options": {"include_thinking": False}, "players": [], "timeline": [],
        "public_situation": {"schema_version": 1, "state_version": "pub-state-0123", "event_seq": 17,
            "card_move_seq": 9, "round": 2, "phase": "play", "current_player_id": 1,
            "deck_count": 42, "discard": {"count": 3, "by_name": {"杀": 2, "桃": 1}, "latest": ["杀", "桃"]},
            "players": [{"id": 0, "identity": None, "hand_count": 2}]},
        "decisions": [{"seq": 4, "round": 2, "player_id": 1, "player_name": "AI乙",
            "situation_version": "pub-state-0123", "selection_kind": "choose_players",
            "candidates_summary": "choose_players：2 个引擎候选", "chosen_summary": "目标：玩家",
            "validation_status": "accepted", "fallback_reason": None,
            "private_hand": ["PRIVATE_CARD_MARKER"], "cognitive_notes": ["PRIVATE_NOTE_MARKER"],
            "prompt": "PRIVATE_PROMPT_MARKER"}]
    })
    store.save({"game_id": "legacy_diagnostics", "profile_id": "profile_diagnostics_browser",
        "winner": "draw", "message": "旧格式日志", "rounds": 1, "duration": 5,
        "options": {"include_thinking": False}, "players": [], "timeline": [], "decisions": []})
    server = ThreadingHTTPServer(("127.0.0.1", 0), game_server.CustomHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    node = r'''
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base=process.argv[1];
(async()=>{
  const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
  try {
    const page=await browser.newPage({viewport:{width:1280,height:900}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.addInitScript(()=>localStorage.setItem('profileId',JSON.stringify('profile_diagnostics_browser')));
    await page.goto(base+'/logs.html');
    await page.locator('.log-item').first().waitFor();
    await page.locator('.log-item').filter({hasText:'公开诊断验收'}).click();
    const details=page.locator('#detailBody');
    await details.locator('.log-diagnostics').first().waitFor();
    const rendered=await details.locator('.log-diagnostics').allTextContents();
    const safeText=rendered.join(' ');
    for(const expected of ['pub-state-0123','第','play','弃牌摘要','杀 ×2','choose_players','2 个引擎候选','目标：玩家','accepted','无'])
      if(!safeText.includes(expected)) throw Error('missing diagnostic '+expected+': '+safeText);
    for(const secret of ['PRIVATE_CARD_MARKER','PRIVATE_NOTE_MARKER','PRIVATE_PROMPT_MARKER'])
      if(safeText.includes(secret)) throw Error('private field rendered in diagnostic: '+secret);
    await page.locator('#backBtn').click();
    await page.locator('.log-item').filter({hasText:'旧格式日志'}).click();
    if(await page.locator('#detailBody .log-diagnostics').count()) throw Error('legacy log rendered an empty diagnostic section');
    if(errors.length) throw Error('page errors '+JSON.stringify(errors));
    console.log(JSON.stringify({check:'PUBLIC_DIAGNOSTICS_BROWSER_OK',public_diagnostic_facts:rendered[0],legacy_without_diagnostics:true,private_markers_absent:true,page_errors:errors},null,2));
  } finally {await browser.close()}
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
