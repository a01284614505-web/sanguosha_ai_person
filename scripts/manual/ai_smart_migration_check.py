"""AI 旧配置迁移故障冒烟：故意拦截一次迁移 POST，验证不会误报完成且下次可重试。"""
import os
import json
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
 browser=pw.chromium.launch(executable_path=os.environ.get('AI_BROWSER_EXECUTABLE') or None,headless=True,args=['--no-sandbox'])
 ctx=browser.new_context()
 profile='migration_ai_smart_browser'
 setup="""localStorage.setItem('profileId',JSON.stringify('migration_ai_smart_browser'));
 if(!localStorage.getItem('lobbyAIs')) localStorage.setItem('lobbyAIs',JSON.stringify([1,2,3,4].map(i=>({name:'旧选手'+i,model:'legacy-model-'+i,provider:'openai',apiKey:''}))));"""
 ctx.add_init_script(setup)
 page=ctx.new_page()
 count=[0]
 def fail_once(route):
  count[0]+=1
  if count[0]==1: route.fulfill(status=503,content_type='application/json',body='{"success":false}')
  else: route.continue_()
 page.route('**/api/ai-players/update',fail_once)
 page.goto(os.environ.get('AI_BROWSER_BASE_URL', 'http://127.0.0.1:8888').rstrip('/')+'/index.html')
 page.wait_for_function('window.lobby && lobby.pendingProfileSaves.length===4')
 page.wait_for_timeout(250)
 assert page.evaluate("JSON.parse(localStorage.getItem('lobbyAIMigrated'))") is False
 page.reload()
 page.wait_for_function("JSON.parse(localStorage.getItem('lobbyAIMigrated'))===true")
 response=ctx.request.get(os.environ.get('AI_BROWSER_BASE_URL', 'http://127.0.0.1:8888').rstrip('/')+'/api/ai-players?profile_id='+profile).json()
 assert [p['name'] for p in response['players']]==['旧选手1','旧选手2','旧选手3','旧选手4']
 assert page.evaluate('lobby.aiConfigs.map(a=>a.model)')==['legacy-model-1','legacy-model-2','legacy-model-3','legacy-model-4']
 print('PASS: failed migration is not marked complete; reload retries; server names and per-account local models preserved')
 browser.close()
