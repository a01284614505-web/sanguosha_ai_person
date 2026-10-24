#!/usr/bin/env python3
"""正式选将面板的手机触摸仿真验收：360x640 / 412x720 / 432x800（Android Chrome UA，tap 点击）+ 电脑 1440x900。

每个视口走两遍真实开局：
  1. 用身份卡指定"忠臣"：看到主公已选的武将 + 5 张候选；点一张看技能说明，点"确定"，等待区，进入第 1 回合；
  2. 用身份卡指定"主公"：看到 7 张候选（全部主公技武将 + 2 名）。
断言：面板可见、候选张数正确、整页不滚动（文档高度 <= 视口）、卡片都在视口内且足够大、没有横向溢出、
点选后出现技能说明、确定后收起。截图写到 HD_OUT_DIR（默认 /tmp/claude-0/draft/shots），不进仓库。

运行（先起服务器，需持端口锁；见 agent_common.md）：
  SANGUOSHA_HISTORY_PATH=... python3 game_server.py &
  HD_OUT_DIR=/tmp/claude-0/draft/shots python3 scripts/manual/hero_draft_browser_check.py
"""

import json
import os
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("HD_BASE_URL", "http://127.0.0.1:8888")
OUT = Path(os.environ.get("HD_OUT_DIR", "/tmp/claude-0/draft/shots"))
ANDROID_UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")
VIEWPORTS = [("360x640", 360, 640, True), ("412x720", 412, 720, True),
             ("432x800", 432, 800, True), ("1440x900", 1440, 900, False)]

results = []


def check(name, ok, detail=""):
    results.append({"name": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + (f" | {detail}" if detail and not ok else ""))


# ---- 慢速"模型"桩：让 AI 座位走真实的模型选将路径，面板才有机会停在"等待他人"状态可供截图 ----
STUB_PORT = int(os.environ.get("HD_STUB_PORT", "9911"))
STUB_DELAY = float(os.environ.get("HD_STUB_DELAY", "3"))


class StubModel(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        time.sleep(STUB_DELAY)
        body = json.dumps({"choices": [{"message": {"content": '{"reasoning":"桩","option_indices":[0]}'}}],
                           "usage": {"prompt_tokens": 10, "completion_tokens": 5}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def start_stub():
    server = ThreadingHTTPServer(("127.0.0.1", STUB_PORT), StubModel)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


PATCH_AIS = """
(() => {
  if (!location.pathname.endsWith('game.html') || sessionStorage.getItem('hd_patched')) return;
  try {
    const cfg = JSON.parse(sessionStorage.getItem('gameConfig') || 'null');
    if (!cfg) return;
    cfg.ais.forEach(a => { a.apiKey = 'sk-stub'; a.provider = 'openai'; a.apiUrl = 'http://127.0.0.1:%d/v1'; a.model = 'stub'; });
    sessionStorage.setItem('gameConfig', JSON.stringify(cfg));
    sessionStorage.setItem('hd_patched', '1');
  } catch (_) {}
})();
""" % STUB_PORT


def new_context(browser, width, height, mobile):
    options = dict(viewport={"width": width, "height": height})
    if mobile:
        options.update(device_scale_factor=2.75, is_mobile=True, has_touch=True, user_agent=ANDROID_UA)
    context = browser.new_context(**options)
    profile = "hd_" + uuid.uuid4().hex[:12]
    context.add_init_script(f"localStorage.setItem('profileId', JSON.stringify('{profile}'))")
    return context


def tap(page, mobile, selector):
    locator = page.locator(selector).first
    locator.tap() if mobile else locator.click()


def start_game(page, mobile, identity):
    page.goto(BASE + "/index.html", wait_until="domcontentloaded")
    page.wait_for_selector("#startGameBtn")
    page.wait_for_function("!document.getElementById('startGameBtn').disabled", timeout=15000)
    page.evaluate("try { sessionStorage.removeItem('activeGame'); } catch (_) {}")
    page.locator("#playerName").fill("触摸验收")
    page.wait_for_function("!document.getElementById('identityCardSection').hidden", timeout=10000)
    tap(page, mobile, f'#idCardChoices [data-identity="{identity}"]')
    check("lobby: 自由选将默认关闭", not page.locator("#freeDraft").is_checked())
    tap(page, mobile, "#startGameBtn")
    page.wait_for_url("**/game.html", timeout=15000)


def layout_metrics(page):
    return page.evaluate("""() => {
        const doc = document.scrollingElement;
        const cards = [...document.querySelectorAll('#heroDraft .hd-card')].map(el => {
            const r = el.getBoundingClientRect();
            return {l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height};
        });
        const sheet = document.querySelector('#heroDraft .hd-sheet').getBoundingClientRect();
        return {vw: innerWidth, vh: innerHeight, scrollH: doc.scrollHeight, scrollW: doc.scrollWidth,
                cards, sheet: {l: sheet.left, t: sheet.top, r: sheet.right, b: sheet.bottom}};
    }""")


def run_viewport(browser, label, width, height, mobile):
    context = new_context(browser, width, height, mobile)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    frames = []
    page.on("websocket", lambda ws: ws.on("framereceived", lambda payload: frames.append(payload)))

    # ---- 场景 1：忠臣 ----
    start_game(page, mobile, "忠臣")
    page.wait_for_selector("#heroDraft .hd-card", timeout=60000)
    n = page.locator("#heroDraft .hd-card").count()
    check(f"{label} 忠臣: 面板出现且有 5 张候选", n == 5, f"n={n}")
    check(f"{label} 忠臣: 显示自己的身份", "忠臣" in page.locator("#heroDraft .hd-who-txt").inner_text())
    check(f"{label} 忠臣: 显示主公已选武将", page.locator("#heroDraft .hd-lord-name").count() == 1,
          page.locator("#heroDraft .hd-sheet").inner_text()[:80])
    page.wait_for_timeout(500)
    m = layout_metrics(page)
    check(f"{label} 忠臣: 整页不滚动", m["scrollH"] <= m["vh"] + 1 and m["scrollW"] <= m["vw"] + 1, json.dumps(
        {k: m[k] for k in ("vw", "vh", "scrollH", "scrollW")}))
    check(f"{label} 忠臣: 5 张卡都在视口内", all(c["l"] >= 0 and c["r"] <= m["vw"] and c["t"] >= 0 and c["b"] <= m["vh"] for c in m["cards"]))
    check(f"{label} 忠臣: 卡片够大可点（宽>=52 高>=68）", all(c["w"] >= 52 and c["h"] >= 68 for c in m["cards"]),
          str([(round(c["w"]), round(c["h"])) for c in m["cards"]]))
    check(f"{label} 忠臣: 候选互不重叠", all(m["cards"][i]["r"] <= m["cards"][i + 1]["l"] + 0.5 for i in range(len(m["cards"]) - 1)))
    check(f"{label} 忠臣: 面板在视口内", m["sheet"]["l"] >= 0 and m["sheet"]["r"] <= m["vw"] and m["sheet"]["t"] >= 0 and m["sheet"]["b"] <= m["vh"],
          json.dumps(m["sheet"]))
    check(f"{label} 忠臣: 没点选前确定按钮不可用", page.locator("#hdOk").is_disabled())
    page.screenshot(path=str(OUT / f"{label}_1_loyalist_choose.png"))

    tap(page, mobile, "#heroDraft .hd-card:nth-child(2)")
    page.wait_for_selector("#heroDraft .hd-card.on")
    check(f"{label} 忠臣: 点选后显示技能说明", page.locator("#heroDraft .hd-d-skill").count() >= 1)
    check(f"{label} 忠臣: 点选后确定按钮可用", page.locator("#hdOk").is_enabled())
    m = layout_metrics(page)
    check(f"{label} 忠臣: 点选后整页仍不滚动", m["scrollH"] <= m["vh"] + 1, f"scrollH={m['scrollH']} vh={m['vh']}")
    page.screenshot(path=str(OUT / f"{label}_2_loyalist_picked.png"))

    tap(page, mobile, "#hdOk")
    page.wait_for_function("window.GameUI && window.GameUI.state && window.GameUI.state.hero_draft && !window.GameUI.state.hero_draft.active",
                           timeout=60000)
    page.wait_for_selector("#heroDraft", state="hidden", timeout=10000)
    check(f"{label} 忠臣: 确定后面板收起并开局", True)
    state = page.evaluate("window.GameUI.state")
    check(f"{label} 忠臣: 五人都有武将、起手牌 4 张",
          all(p["hero"]["id"] for p in state["players"]) and len(state["self_hand"]) == 4,
          str([(p["hero_name"]) for p in state["players"]]))
    page.wait_for_function("window.GameUI.state.round >= 1 && window.GameUI.state.current_player_id !== null", timeout=15000)
    check(f"{label} 忠臣: 进入第 1 回合", page.evaluate("window.GameUI.state.round") >= 1)
    page.wait_for_timeout(600)
    page.screenshot(path=str(OUT / f"{label}_3_loyalist_game.png"))
    hero_requests = [m for m in (json.loads(f) for f in frames if '"choose_hero"' in f)
                     if m.get("type") == "require_response" and m.get("kind") == "choose_hero"]
    check(f"{label} 忠臣: 只收到 1 条选将请求（只有自己的候选）", len(hero_requests) == 1 and len(hero_requests[0]["heroes"]) == 5)
    check(f"{label} 忠臣: 无浏览器运行错误", not errors, "; ".join(errors))
    context.close()

    # ---- 场景 2：主公 ----
    context = new_context(browser, width, height, mobile)
    page = context.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    start_game(page, mobile, "主公")
    page.wait_for_selector("#heroDraft .hd-card", timeout=60000)
    n = page.locator("#heroDraft .hd-card").count()
    check(f"{label} 主公: 7 张候选（5 名主公技 + 2 名随机）", n == 7, f"n={n}")
    page.wait_for_timeout(500)
    m = layout_metrics(page)
    check(f"{label} 主公: 整页不滚动", m["scrollH"] <= m["vh"] + 1 and m["scrollW"] <= m["vw"] + 1,
          json.dumps({k: m[k] for k in ("vw", "vh", "scrollH", "scrollW")}))
    check(f"{label} 主公: 7 张卡都在视口内", all(c["l"] >= 0 and c["r"] <= m["vw"] and c["t"] >= 0 and c["b"] <= m["vh"] for c in m["cards"]))
    check(f"{label} 主公: 卡片够大可点（宽>=52 高>=68）", all(c["w"] >= 52 and c["h"] >= 68 for c in m["cards"]),
          str([(round(c["w"]), round(c["h"])) for c in m["cards"]]))
    page.screenshot(path=str(OUT / f"{label}_4_lord_choose.png"))
    tap(page, mobile, "#heroDraft .hd-card:nth-child(1)")
    page.wait_for_selector("#heroDraft .hd-card.on")
    page.screenshot(path=str(OUT / f"{label}_5_lord_picked.png"))
    tap(page, mobile, "#hdOk")
    # 主公选完后进入等待态，随后全部选完收起
    page.wait_for_function("window.GameUI.state && window.GameUI.state.hero_draft && window.GameUI.state.hero_draft.stage === 'others'", timeout=30000)
    page.screenshot(path=str(OUT / f"{label}_6_lord_waiting.png"))
    page.wait_for_selector("#heroDraft", state="hidden", timeout=60000)
    lord = next(p for p in page.evaluate("window.GameUI.state.players") if p["identity"] == "lord")
    check(f"{label} 主公: 体力上限含主公 +1", lord["max_hp"] == lord["hero"]["max_hp"] + 1, json.dumps(
        {"max_hp": lord["max_hp"], "base": lord["hero"]["max_hp"]}))
    check(f"{label} 主公: 无浏览器运行错误", not errors, "; ".join(errors))
    context.close()


def run_waiting(browser, label, width, height, mobile):
    """真实的"等待他人"状态：AI 走慢速模型桩，面板先停在"主公选将中"，自己选完后再停在"其他角色选将中"。"""
    context = new_context(browser, width, height, mobile)
    context.add_init_script(PATCH_AIS)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    start_game(page, mobile, "忠臣")
    page.wait_for_selector("#heroDraft .hd-sheet.waiting", timeout=20000)
    text = page.locator("#heroDraft").inner_text()
    check(f"{label} 等待: 主公选将时显示等待提示", "主公正在选将" in text, text[:80])
    page.wait_for_timeout(300)
    page.screenshot(path=str(OUT / f"{label}_7_waiting_for_lord.png"))
    page.wait_for_selector("#heroDraft .hd-card", timeout=30000)
    tap(page, mobile, "#heroDraft .hd-card:nth-child(1)")
    tap(page, mobile, "#hdOk")
    page.wait_for_selector("#heroDraft .hd-sheet.waiting", timeout=10000)
    text = page.locator("#heroDraft").inner_text()
    check(f"{label} 等待: 自己选完后显示其他角色选将中", "其他角色选将中" in text, text[:100])
    check(f"{label} 等待: 显示主公已选与自己所选", page.locator("#heroDraft .hd-lord-name").count() == 1 and page.locator("#heroDraft .hd-mine").count() == 1)
    page.wait_for_timeout(300)
    page.screenshot(path=str(OUT / f"{label}_8_waiting_for_others.png"))
    page.wait_for_selector("#heroDraft", state="hidden", timeout=40000)
    check(f"{label} 等待: 全部选完后收起", True)
    check(f"{label} 等待: 无浏览器运行错误", not errors, "; ".join(errors))
    context.close()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    only = os.environ.get("HD_VIEWPORTS")
    start_stub()
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        for label, width, height, mobile in VIEWPORTS:
            if only and label not in only.split(","):
                continue
            try:
                run_viewport(browser, label, width, height, mobile)
                run_waiting(browser, label, width, height, mobile)
            except Exception as exc:     # 一个视口失败不拖垮其余视口
                check(f"{label}: 脚本异常", False, repr(exc)[:300])
        browser.close()
    failed = [r for r in results if not r["ok"]]
    print(json.dumps({"total": len(results), "failed": len(failed), "screenshots": str(OUT)}, ensure_ascii=False))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
