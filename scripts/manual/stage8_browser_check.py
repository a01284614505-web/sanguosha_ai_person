"""Stage 8 browser smoke with isolated package data; requires an installed Playwright."""
import tempfile, threading, subprocess, sys
from pathlib import Path
from http.server import ThreadingHTTPServer
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
import game_server
with tempfile.TemporaryDirectory(prefix='stage8-browser-') as directory:
    root = Path(directory)
    (root/'data').mkdir()
    (root/'data/heroes.json').write_bytes((PROJECT_ROOT / 'data/heroes.json').read_bytes())
    (root/'frontend').symlink_to(PROJECT_ROOT / 'frontend', target_is_directory=True)
    game_server.BASE_DIR = root
    server = ThreadingHTTPServer(('127.0.0.1', 0), game_server.CustomHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    script = r'''
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async()=>{
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
try {
const page=await browser.newPage({viewport:{width:1280,height:900}});
const errors=[]; page.on('pageerror',e=>errors.push(e.message));
await page.goto(process.argv[1]+'/hero_manager.html');
await page.locator('#convertProvider option').first().waitFor({state:'attached'});
await page.locator('#packageId').fill('browser_pack');
await page.locator('#packageName').fill('浏览器包');
await page.locator('#inputText').fill('测试将 蜀\n体力:4\n技能:\n浏览器技能：摸一张牌。');
page.on('dialog',d=>d.accept());
await page.getByRole('button',{name:'转换',exact:true}).click();
const output=JSON.parse(await page.locator('#outputJSON').inputValue());
if(!/^[a-z0-9][a-z0-9_-]*$/.test(output.id)) throw Error('illegal generated ID');
await page.getByRole('button',{name:'导入到服务器',exact:true}).click();
await page.waitForFunction(()=>document.querySelector('#managerStatus').textContent.includes('已导入'));
await page.locator('[data-package="browser_pack"]').click();
await page.waitForFunction(()=>document.querySelector('[data-package="browser_pack"]')?.dataset.enabled==='false');
let pool=await page.request.get(process.argv[1]+'/api/heroes');
if(!(await pool.json()).heroes.some(h=>h.id===output.id)) throw Error('enabled hero missing');
await page.goto(process.argv[1]+'/handbook.html');
await page.waitForFunction(id=>Array.from(document.querySelectorAll('#heroList .hb-hero')).some(card=>card.innerHTML.includes(id)),output.id);
await page.goto(process.argv[1]+'/select_hero.html');
await page.locator('#heroGrid .hero-card[data-id="'+output.id+'"]').waitFor();
await page.goto(process.argv[1]+'/hero_manager.html');
await page.locator('[data-package="browser_pack"]').waitFor();
await page.locator('[data-package="browser_pack"]').click();
await page.waitForFunction(()=>document.querySelector('[data-package="browser_pack"]')?.dataset.enabled==='true');
pool=await page.request.get(process.argv[1]+'/api/heroes');
if((await pool.json()).heroes.some(h=>h.id===output.id)) throw Error('disabled hero remains');
await page.goto(process.argv[1]+'/handbook.html');
await page.waitForFunction(id=>!Array.from(document.querySelectorAll('#heroList .hb-hero')).some(card=>card.innerHTML.includes(id)),output.id);
if(errors.length) throw Error(errors.join('\n'));
console.log('STAGE8_BROWSER_OK: convert, import, enable, pool, handbook, select, disable; no page errors');
}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
'''
    try:
        result = subprocess.run(['node', '-e', script, f'http://127.0.0.1:{server.server_port}'], timeout=50)
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
    raise SystemExit(result.returncode)
