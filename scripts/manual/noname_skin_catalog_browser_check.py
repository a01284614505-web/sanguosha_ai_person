#!/usr/bin/env python3
"""Browser check for the pinned, on-demand Noname image candidate catalog."""
import os
import subprocess
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

import sys
sys.path.insert(0, str(ROOT))
import game_server

NODE_CHECK = r'''
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.argv[1];
(async () => {
  const browser = await chromium.launch({headless:true,args:['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport:{width:390,height:844}});
    const errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto(base+'/skins.html');
    await page.waitForFunction(()=>document.querySelectorAll('#skinHeroIds option').length>0 &&
      document.querySelector('#sourceSkinChoice option')?.textContent.includes('候选图'));
    await page.locator('#skinHeroId').fill('caocao');
    await page.waitForFunction(()=>document.querySelector('#sourceSkinChoice').options.length>1);
    await page.locator('#sourceSkinChoice').selectOption('0');
    await page.locator('#previewSourceSkinBtn').click();
    await page.waitForFunction(()=>document.querySelector('#importSourceSkinBtn').disabled===false);
    const preview=await page.evaluate(()=>({
      src:document.querySelector('#sourceSkinPreview img').src,
      width:document.querySelector('#sourceSkinPreview img').naturalWidth,
      height:document.querySelector('#sourceSkinPreview img').naturalHeight,
      meta:document.querySelector('#sourceSkinMeta').textContent,
      options:document.querySelector('#sourceSkinChoice').options.length
    }));
    if(!preview.src.startsWith('blob:')||preview.width<64||!preview.meta.includes('SHA 已校验'))
      throw Error('candidate preview or pinned hash validation failed: '+JSON.stringify(preview));
    await page.locator('#importSourceSkinBtn').click();
    await page.waitForFunction(()=>document.querySelector('#skinStatus').textContent.includes('已导入并应用到 caocao'));
    const imported=await page.evaluate(async()=>({
      mapping:await LocalHeroSkins.getMapping('caocao'),
      items:await LocalHeroSkins.listResources(),
      width:innerWidth,scrollWidth:document.documentElement.scrollWidth
    }));
    if(!imported.mapping||!imported.items.some(item=>item.skin_id===imported.mapping.skin_id))
      throw Error('candidate not stored in IndexedDB');
    if(imported.scrollWidth>imported.width+1)throw Error('mobile layout overflows: '+JSON.stringify(imported));
    if(errors.length)throw Error('browser errors: '+JSON.stringify(errors));
    console.log(JSON.stringify({check:'NONAME_CATALOG_BROWSER_OK',hero_id:'caocao',catalog_choices:preview.options-1,
      preview:{width:preview.width,height:preview.height,hash_verified:preview.meta.includes('SHA 已校验')},
      imported_label:imported.items.find(item=>item.skin_id===imported.mapping.skin_id).label,
      indexeddb_mapping:true,mobile:{width:imported.width,scroll_width:imported.scrollWidth},page_errors:errors},null,2));
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exit(1)});
'''


def main() -> int:
    game_server.BASE_DIR = ROOT
    server = ThreadingHTTPServer(("127.0.0.1", 0), game_server.CustomHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            ["node", "-e", NODE_CHECK, f"http://127.0.0.1:{server.server_port}"],
            env=os.environ.copy(), timeout=90, check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
