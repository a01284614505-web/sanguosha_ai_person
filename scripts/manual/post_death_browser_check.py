"""Exercise post-death UI using its real websocket client in an isolated browser."""
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

with tempfile.TemporaryDirectory(prefix="post-death-browser-") as tmp:
    root = Path(tmp)
    (root / "data").mkdir()
    (root / "data" / "heroes.json").write_bytes((ROOT / "data" / "heroes.json").read_bytes())
    (root / "frontend").symlink_to(ROOT / "frontend", target_is_directory=True)
    game_server.BASE_DIR = root
    server = ThreadingHTTPServer(("127.0.0.1", 0), game_server.CustomHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    node = r'''
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.argv[1];
const state = (mode='player') => ({round:3, deck_count:40, discard_count:3, current_player_id:1, current_name:'AI1', phase:'play', game_over:false,
  players:[{id:0,name:'玩家',is_ai:false,hero:{id:'caocao',name:'曹操',faction:'魏',skills:[]},hero_name:'曹操',hp:0,max_hp:4,alive:false,identity:null,hand_count:1,self_hand:[],equipment:{},judge_area:[],treasure_count:0},
    ...[1,2,3,4].map((id)=>({id,name:'AI'+id,is_ai:true,hero:{id:'liubei',name:'刘备',faction:'蜀',skills:[]},hero_name:'刘备',hp:3,max_hp:4,alive:true,identity:null,hand_count:2,equipment:{},judge_area:[]}))],
  self_hand:[],post_death:{available:mode==='player',mode,actions:['spectate','background','end']}});
async function setup(page, profile, startMode='player') {
  let socket, resumeRequested=0;
  const sent=[];
  page.on('pageerror', e=>page.__errors.push(e.message));
  page.on('console', m=>{if(m.type()==='error') console.error('PAGECONSOLE',m.text())});
  page.__errors=[];
  await page.addInitScript(({profile})=>{
    sessionStorage.setItem('gameConfig',JSON.stringify({selected_hero:{id:'caocao',name:'曹操',faction:'魏',skills:[]},ais:[1,2,3,4].map(i=>({name:'AI'+i})),player_name:'玩家'}));
    sessionStorage.setItem('profileId',JSON.stringify(profile));
  },{profile});
  await page.routeWebSocket('ws://127.0.0.1:8889', ws=>{
    socket=ws;
    ws.onMessage(raw=>{
      const msg=JSON.parse(raw.toString());
      sent.push(msg);
      if(msg.type==='create_game') {
        const cfg=msg.config;
        ws.send(JSON.stringify({type:'game_created',game_id:'dead-ui-'+profile,profile_id:profile}));
        ws.send(JSON.stringify({type:'game_state',state:state(startMode)}));
      } else if(msg.type==='resume_game') {
        resumeRequested++;
        ws.send(JSON.stringify({type:'game_resumed',game_id:msg.game_id,finished:false}));
        ws.send(JSON.stringify({type:'game_state',state:state('spectator')}));
      }
    });
  });
  await page.goto(base+'/game.html');
  await page.locator('#postDeathModal[open]').waitFor({timeout:10000}).catch(e=>{console.error('DEBUG',JSON.stringify({errors:page.__errors,sent,url:page.url()}));throw e});
  return {sent,get socket(){return socket;},get resumeRequested(){return resumeRequested;}};
}
const waitForSent=async (page, type, action, count=1)=>page.waitForFunction(({type,action,count})=>{
  const rows=window.__sentForCheck||[]; return rows.length>=count;
},{type,action,count});
(async()=>{
  const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
  try {
    const ctx=await browser.newContext({viewport:{width:1280,height:900}});
    const page=await ctx.newPage();
    const a=await setup(page,'profile_spectate');
    await page.locator('#postDeathSpectate').click();
    await page.waitForFunction(()=>document.querySelector('#postDeathSpectate').disabled);
    const actions=a.sent.filter(x=>x.type==='post_death_action');
    if(actions.length!==1||actions[0].action!=='spectate') throw Error('spectate sent unexpected requests '+JSON.stringify(actions));
    await page.locator('#postDeathSpectate').evaluate(el=>el.click());
    if(a.sent.filter(x=>x.type==='post_death_action').length!==1) throw Error('pending action was sent twice');
    a.socket.send(JSON.stringify({type:'post_death_action_result',game_id:'dead-ui-profile_spectate',action:'spectate',status:'accepted'}));
    await page.waitForFunction(()=>document.body.classList.contains('spectator-mode'));
    if(!(await page.locator('#actionBar').isHidden())||!(await page.locator('#myArea').isHidden())) throw Error('spectator controls remain visible');
    if(!(await page.locator('#sidePanel').isVisible())) throw Error('chat/log panel was hidden');
    await page.reload();
    await page.waitForFunction(()=>document.body.classList.contains('spectator-mode'));
    if(a.resumeRequested!==1) throw Error('refresh did not resume existing game');
    if(await page.locator('#postDeathModal').isVisible()) throw Error('spectator modal reappeared after resume');
    if(page.__errors.length) throw Error('spectator page errors '+JSON.stringify(page.__errors));
    await ctx.close();

    const ctxB=await browser.newContext({viewport:{width:1280,height:900}});
    const bg=await ctxB.newPage();
    const b=await setup(bg,'profile_background');
    await bg.locator('#postDeathBackground').click();
    if(!(await bg.locator('#postDeathBackground').isDisabled())) throw Error('background pending button not disabled');
    await bg.locator('#postDeathBackground').evaluate(el=>el.click());
    if(b.sent.filter(x=>x.type==='post_death_action'&&x.action==='background').length!==1) throw Error('background action was sent twice');
    b.socket.send(JSON.stringify({type:'post_death_action_result',game_id:'dead-ui-profile_background',action:'background',status:'accepted'}));
    await bg.waitForURL('**/index.html');
    await bg.waitForFunction(()=>document.body.innerText.includes('对局已转入后台结算'));
    if(await bg.evaluate(()=>sessionStorage.getItem('activeGame')!=='null')) throw Error('activeGame was not cleared');
    if(bg.__errors.length) throw Error('background page errors '+JSON.stringify(bg.__errors));
    await ctxB.close();

    const ctxE=await browser.newContext({viewport:{width:1280,height:900}});
    const end=await ctxE.newPage();
    const c=await setup(end,'profile_end');
    await end.locator('#postDeathEnd').click();
    if(!(await end.locator('#postDeathEnd').isDisabled())) throw Error('end pending button not disabled');
    await end.locator('#postDeathEnd').evaluate(el=>el.click());
    if(c.sent.filter(x=>x.type==='post_death_action'&&x.action==='end').length!==1) throw Error('end action was sent twice');
    c.socket.send(JSON.stringify({type:'post_death_action_result',game_id:'dead-ui-profile_end',action:'end',status:'accepted'}));
    await end.waitForFunction(()=>document.querySelector('#postDeathStatus').textContent.includes('等待正式结算'));
    if(await end.locator('#endModal').isVisible()) throw Error('end modal appeared before game_end');
    const finalState=state('spectator'); finalState.game_over=true; finalState.post_death.available=false;
    c.socket.send(JSON.stringify({type:'game_end',winner:'aborted',message:'玩家结束本局',state:finalState,player_identity:'未知',player_won:false}));
    await end.waitForFunction(()=>document.querySelector('#endModal').open);
    if(end.__errors.length) throw Error('end page errors '+JSON.stringify(end.__errors));
    console.log(JSON.stringify({check:'POST_DEATH_BROWSER_OK',spectate:{readonly:true,chat_log_visible:true,resume:true},background:{acknowledged:true,active_game_cleared:true,lobby_notice:true},end:{waited_for_game_end:true},page_errors:[]},null,2));
    await ctxE.close();
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exit(1)});
'''
    try:
        result = subprocess.run(["node", "-e", node, f"http://127.0.0.1:{server.server_port}"], env=os.environ.copy(), timeout=75, check=False)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    if result.returncode:
        raise SystemExit(result.returncode)
