"""AI P0–P5 浏览器冒烟：先运行 seed_ai_smart_profile.py，再以同一隔离历史路径启动服务器。

需可选工具 playwright；AI_BROWSER_BASE_URL / AI_BROWSER_EXECUTABLE / AI_BROWSER_ARTIFACTS 可覆盖。
仅真实点击与真实 WebSocket 状态；合成称号档案是展示夹具，不代表真实模型胜率。
"""
import json, os, tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_URL=os.environ.get('AI_BROWSER_BASE_URL', 'http://127.0.0.1:8888').rstrip('/')
ROOT=Path(os.environ.get('AI_BROWSER_ARTIFACTS', str(Path(tempfile.gettempdir())/'ai-smart-browser-artifacts')))
ROOT.mkdir(exist_ok=True)
report=[]
with sync_playwright() as pw:
 browser=pw.chromium.launch(executable_path=os.environ.get('AI_BROWSER_EXECUTABLE') or None,headless=True,args=['--no-sandbox'])
 for label,width,height in [('desktop',1440,1000),('mobile',390,844)]:
  ctx=browser.new_context(viewport={'width':width,'height':height}, device_scale_factor=1)
  ctx.add_init_script("localStorage.setItem('profileId', JSON.stringify('ai_smart_browser')); localStorage.setItem('lobbyPrefs', JSON.stringify({playerName:'浏览器验收', chatEnabled:false}));")
  page=ctx.new_page()
  errors=[]
  page.on('pageerror',lambda error:errors.append(str(error)))
  frames=[]
  def socket(ws):
   def receive(raw):
    try: frames.append(json.loads(raw))
    except (ValueError,TypeError): pass
   ws.on('framereceived',receive)
  page.on('websocket',socket)
  page.goto(BASE_URL+'/index.html')
  page.locator('.ai-player-select').first.wait_for()
  assert page.locator('.ai-player-select').count()==4
  assert page.locator('.title-badge').count()==3
  # 真实 UI 选择一个已占用档案，自动交换而非禁用选项。
  page.locator('.ai-player-select').nth(0).select_option('ai_2')
  values=page.locator('.ai-player-select').evaluate_all('(rows)=>rows.map(r=>r.value)')
  assert values==['ai_2','ai_1','ai_3','ai_4'],values
  page.screenshot(path=str(ROOT/f'{label}-lobby.png'),full_page=True)
  page.goto(BASE_URL+'/history.html')
  page.locator('[data-ai-name="ai_1"]').wait_for()
  assert page.locator('.ai-archive-card').count()==4
  assert page.locator('[data-ai-title="ai_1"]').input_value()=='wins_10'
  assert page.locator('[data-ai-title="ai_4"]').input_value()=='__none__'
  page.locator('[data-ai-name="ai_1"]').fill('持久验收选手')
  page.locator('[data-save-ai="ai_1"]').click()
  page.wait_for_function("document.querySelector('[data-ai-name=ai_1]').value==='持久验收选手'")
  page.locator('#humanTitleSelect').select_option('__none__')
  page.locator('#saveHumanTitle').click()
  page.reload()
  page.locator('#humanTitleSelect').wait_for()
  assert page.locator('#humanTitleSelect').input_value()=='__none__'
  overflow=page.evaluate('document.documentElement.scrollWidth>innerWidth')
  assert not overflow,'history horizontal overflow'
  page.screenshot(path=str(ROOT/f'{label}-history.png'),full_page=True)
  page.goto(BASE_URL+'/index.html')
  page.locator('.ai-player-select').first.wait_for()
  assert '持久验收选手' in page.locator('#guestRow').inner_text()
  # 选择内奸保证主公不在真人内部 ID 0；使用见面礼卡，只跑规则 AI。
  page.locator('[data-identity="内奸"]').click()
  page.locator('#startGameBtn').click()
  page.wait_for_url('**/select_hero.html')
  page.locator('.hero-card').first.click()
  page.locator('#confirmBtn').click()
  page.wait_for_url('**/game.html')
  page.locator('.s-name').first.wait_for(timeout=20000)
  page.wait_for_timeout(700)
  states=[f.get('state',f) for f in frames if f.get('type') in ('game_created','game_state') and (f.get('state',f)).get('players')]
  assert states,'no real state received'
  state=states[-1]
  players=state['players']
  lord=next(p for p in players if p['identity']=='lord')
  assert lord['id']!=0 and lord['seat']==1
  assert len(set(p['seat'] for p in players))==5
  ai_ids=[p['ai_id'] for p in players if p['is_ai']]
  assert ai_ids==values,(ai_ids,values)
  assert page.locator('.ai-title-badge').count()==3
  names=page.locator('.s-name').all_text_contents()
  for p in players:
   assert any(name.startswith(str(p['seat'])+'号 ') and p['name'] in name for name in names),(p['seat'],names)
  assert page.locator('.ai-title-badge').evaluate_all('(rows)=>rows.every(e=>e.scrollWidth<=e.clientWidth)'), 'four-character title clipped'
  page.emulate_media(reduced_motion='reduce')
  animated=page.locator('.ai-title-badge.title-高级, .ai-title-badge.title-稀有').first
  assert animated.evaluate("e=>getComputedStyle(e,'::after').animationName")=='none'
  page.screenshot(path=str(ROOT/f'{label}-game.png'),full_page=True)
  report.append({'viewport':label,'seat_swap':values,'lord_id':lord['id'],'lord_seat':lord['seat'],
                 'title_badges':page.locator('.ai-title-badge').count(),'history_no_overflow':not overflow,'js_errors':errors})
  assert not errors,errors
  page.locator('#quitBtn').click()
  page.locator('dialog[open] button[data-v="1"]').click()
  page.wait_for_timeout(700)
  ctx.close()
 browser.close()
print(json.dumps(report,ensure_ascii=False,indent=2))
(ROOT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
