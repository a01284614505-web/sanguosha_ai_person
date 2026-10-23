"""Verify browser-local skin import, mapping, persistence, rejection and fallback."""
import os
import struct
import subprocess
import sys
import tempfile
import threading
import zlib
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import game_server


def png_bytes(color):
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)
    width = height = 128
    row = b"\x00" + bytes((*color, 255)) * width
    raw = row * height
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


with tempfile.TemporaryDirectory(prefix="local-skins-browser-") as tmp:
    root = Path(tmp)
    (root / "data").mkdir()
    (root / "data" / "heroes.json").write_bytes((ROOT / "data" / "heroes.json").read_bytes())
    (root / "frontend").symlink_to(ROOT / "frontend", target_is_directory=True)
    valid_red = root / "red.png"
    valid_blue = root / "blue.png"
    invalid_png = root / "fake.png"
    oversized = root / "large.png"
    valid_red.write_bytes(png_bytes((235, 42, 52)))
    valid_blue.write_bytes(png_bytes((32, 92, 220)))
    invalid_png.write_bytes(b"\x89PNG\r\n\x1a\nnot an image")
    oversized.write_bytes(b"x" * (2 * 1024 * 1024 + 1))

    game_server.BASE_DIR = root
    server = ThreadingHTTPServer(("127.0.0.1", 0), game_server.CustomHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    node = r'''
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.argv[1], red = process.argv[2], blue = process.argv[3], bad = process.argv[4], large = process.argv[5];
(async () => {
  const browser = await chromium.launch({headless:true,args:['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport:{width:1280,height:900}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(base + '/skins.html');
    await page.waitForFunction(() => document.querySelectorAll('#skinHeroIds option').length > 0);
    async function importFor(hero, path) {
      await page.locator('#skinHeroId').fill(hero);
      await page.locator('#skinFile').setInputFiles(path);
      await page.locator('#scanSkinBtn').click();
      await page.waitForFunction(() => document.querySelector('#importSkinBtn').disabled === false);
      const info = await page.locator('#skinFileInfo').textContent();
      if (!info.includes('image/png') || !info.includes('128×128')) throw Error('scan/preview metadata missing: '+info);
      await page.locator('#importSkinBtn').click();
      await page.waitForFunction(() => document.querySelector('#skinStatus').textContent.includes('已导入并应用'));
      return await page.evaluate(id => LocalHeroSkins.getMapping(id), hero);
    }
    const caocao = await importFor('caocao', red);
    const liubei = await importFor('liubei', blue);
    await page.locator('#skinHeroId').fill('liubei');
    await page.locator('#existingSkin').selectOption(caocao.skin_id);
    await page.locator('#bindSkinBtn').click();
    await page.waitForFunction(() => document.querySelector('#skinStatus').textContent.includes('已将所选本地资源绑定'));
    const switched = await page.evaluate(async () => ({
      caocao: await LocalHeroSkins.getMapping('caocao'), liubei: await LocalHeroSkins.getMapping('liubei')
    }));
    if (switched.caocao.skin_id !== caocao.skin_id || switched.liubei.skin_id !== caocao.skin_id) throw Error('existing resource could not be selected for another hero');

    await page.goto(base + '/index.html');
    await page.waitForFunction(() => Array.from(document.querySelectorAll('img[data-hero-id="caocao"],img[data-hero-id="liubei"]')).every(img => img.src.startsWith('blob:')));
    const beforeRefresh = await page.evaluate(() => Array.from(document.querySelectorAll('img[data-hero-id]')).map(img=>({id:img.dataset.heroId,src:img.src})).filter(x=>['caocao','liubei'].includes(x.id)));
    await page.reload();
    await page.waitForFunction(() => Array.from(document.querySelectorAll('img[data-hero-id="caocao"],img[data-hero-id="liubei"]')).every(img => img.src.startsWith('blob:')));
    const afterRefresh = await page.evaluate(() => Array.from(document.querySelectorAll('img[data-hero-id]')).map(img=>({id:img.dataset.heroId,src:img.src})).filter(x=>['caocao','liubei'].includes(x.id)));

    await page.goto(base + '/skins.html');
    await page.waitForFunction(() => document.querySelectorAll('#skinHeroIds option').length > 0);
    async function assertRejected(path, text) {
      await page.locator('#skinHeroId').fill('caocao');
      await page.locator('#skinFile').setInputFiles(path);
      await page.locator('#scanSkinBtn').click();
      await page.waitForFunction(expected => document.querySelector('#skinStatus').textContent.includes(expected), text);
      if (!await page.locator('#importSkinBtn').isDisabled()) throw Error('invalid file enabled import button');
    }
    await assertRejected(bad, '无法解码');
    await assertRejected(large, '2 MiB');

    await page.locator('#skinHeroId').fill('caocao');
    await page.locator('#resetSkinBtn').click();
    await page.waitForFunction(() => document.querySelector('#skinStatus').textContent.includes('已恢复 caocao'));
    await page.goto(base + '/index.html');
    await page.waitForFunction(() => document.querySelector('img[data-hero-id="caocao"]').src.endsWith('/assets/heroes/caocao.jpg'));

    await page.goto(base + '/skins.html');
    page.once('dialog', dialog => dialog.accept());
    await page.locator('[data-delete-skin="'+caocao.skin_id+'"]').click();
    await page.waitForFunction(() => document.querySelector('#skinStatus').textContent.includes('本地资源已删除'));
    const unbound = await page.evaluate(id => LocalHeroSkins.getMapping(id), 'liubei');
    if (unbound) throw Error('deleting a resource left a stale hero mapping');
    if (errors.length) throw Error('Browser errors: '+JSON.stringify(errors));
    console.log(JSON.stringify({check:'LOCAL_SKINS_BROWSER_OK',mapping_ids:[caocao.skin_id,liubei.skin_id],
      switched_to:switched.liubei.skin_id,persisted_after_refresh:afterRefresh.map(x=>x.id),
      rejected:['corrupt PNG','over 2 MiB'],restored_default:true,deleted_mapping_cleared:true,
      page_errors:errors},null,2));
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exit(1)});
'''
    try:
        result = subprocess.run(["node", "-e", node, f"http://127.0.0.1:{server.server_port}",
            str(valid_red), str(valid_blue), str(invalid_png), str(oversized)],
            env=os.environ.copy(), timeout=75, check=False)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    if result.returncode:
        raise SystemExit(result.returncode)
