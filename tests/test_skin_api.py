"""皮肤 HTTP 接口：真实 HTTPServer + 假 GitHub，覆盖往返、同档案跨“浏览器”同步与各类拒绝。"""
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

import game_server
from game_engine.skin_store import SkinStore
from tests.skin_fixtures import fake_catalog, jpeg, png, webp


class QuietHandler(game_server.CustomHandler):
    def log_message(self, *args):
        pass


class SkinApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = TemporaryDirectory()
        root = Path(cls.tmp.name)
        catalog, cls.blobs = fake_catalog(root / "cat.json")
        cls.offline = False

        def fetch(url):
            if cls.offline:
                raise OSError("offline")
            return cls.blobs[url]

        cls.old_store = game_server.SKIN_STORE
        game_server.SKIN_STORE = SkinStore(root / "skins", catalog, lambda: {"caocao", "liubei"}, fetcher=fetch)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        game_server.SKIN_STORE = cls.old_store
        cls.tmp.cleanup()

    def call(self, path, body=None, *, headers=None, method=None, raw=False):
        data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
        hdrs = dict(headers or {})
        if isinstance(body, dict):
            hdrs.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(self.base + path, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as resp:
                payload = resp.read()
                return resp.status, (payload if raw else json.loads(payload)), resp
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            return exc.code, (payload if raw else json.loads(payload)), exc

    WRITE = {"X-SGS-Skin": "1"}

    def upload(self, profile, hero, data, ctype, extra="", headers=None):
        return self.call(f"/api/skins/upload?profile_id={profile}&hero_id={hero}{extra}", data,
                         headers={"Content-Type": ctype, **(self.WRITE if headers is None else headers)})

    def test_upload_then_other_browser_sees_same_profile(self):
        status, body, _ = self.upload("sync_a", "caocao", png(), "image/png", "&label=%E6%88%91%E7%9A%84")
        self.assertEqual(status, 200, body)
        skin_id = body["upload"]["skin_id"]
        # “换一个浏览器”：没有任何 cookie/本地存储，只带同一个 profile_id
        status, state, _ = self.call("/api/skins?profile_id=sync_a")
        self.assertEqual(state["selection"]["caocao"]["skin_id"], skin_id)
        status, image, resp = self.call(state["selection"]["caocao"]["url"], raw=True)
        self.assertEqual((status, image, resp.headers["Content-Type"]), (200, png(), "image/png"))
        self.assertEqual(resp.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(self.call("/api/skins?profile_id=sync_b")[1]["selection"], {})
        # 别的档案不能凭 skin_id 读图
        self.assertEqual(self.call(f"/api/skins/image?profile_id=sync_b&hero_id=caocao&skin_id={skin_id}", raw=True)[0], 404)

    def test_select_default_delete_roundtrip(self):
        up = self.upload("rt", "liubei", webp(), "image/webp")[1]["upload"]["skin_id"]
        status, state, _ = self.call("/api/skins/select", {"profile_id": "rt", "hero_id": "liubei", "skin_id": None}, headers=self.WRITE)
        self.assertEqual((status, state["selection"]), (200, {}))
        status, state, _ = self.call("/api/skins/select", {"profile_id": "rt", "hero_id": "liubei", "skin_id": up}, headers=self.WRITE)
        self.assertEqual(state["selection"]["liubei"]["skin_id"], up)
        status, state, _ = self.call("/api/skins/delete", {"profile_id": "rt", "skin_id": up}, headers=self.WRITE)
        self.assertEqual((status, state["selection"], state["uploads"]), (200, {}, []))

    def test_noname_candidate_lazy_download_and_use(self):
        status, catalog, _ = self.call("/api/skins/catalog")
        self.assertEqual(status, 200)
        self.assertEqual(len(catalog["heroes"]["caocao"]), 2)
        self.assertNotIn("githubusercontent.com/libccy/noname/abc", json.dumps(catalog))
        status, state, _ = self.call("/api/skins/select", {"profile_id": "nn", "hero_id": "caocao", "skin_id": "nn_2"}, headers=self.WRITE)
        self.assertEqual(state["selection"]["caocao"]["url"], "/api/skins/image?hero_id=caocao&skin_id=nn_2")
        status, image, resp = self.call(state["selection"]["caocao"]["url"], raw=True)
        self.assertEqual((status, resp.headers["Content-Type"]), (200, "image/jpeg"))
        self.assertTrue(image.startswith(b"\xff\xd8"))

    def test_noname_offline_returns_actionable_message(self):
        type(self).offline = True
        try:
            status, body, _ = self.call("/api/skins/image?hero_id=liubei&skin_id=nn_1")
            self.assertEqual(status, 502)
            self.assertIn("download_noname_skins.py", body["message"])
            status, body, _ = self.call("/api/skins/select", {"profile_id": "off", "hero_id": "liubei", "skin_id": "nn_1"}, headers=self.WRITE)
            self.assertEqual(status, 502)
            self.assertEqual(self.call("/api/skins?profile_id=off")[1]["selection"], {})
        finally:
            type(self).offline = False

    def test_writes_require_marker_header(self):
        self.assertEqual(self.upload("csrf", "caocao", png(), "image/png", headers={})[0], 403)
        self.assertEqual(self.call("/api/skins/select", {"profile_id": "csrf", "hero_id": "caocao", "skin_id": None})[0], 403)
        self.assertEqual(self.call("/api/skins/delete", {"profile_id": "csrf", "skin_id": "up_" + "a" * 32})[0], 403)

    def test_upload_rejections(self):
        bad_ids = ["..", "../etc", "a%2Fb", "a%20b", "x" * 129, ""]
        for pid in bad_ids:
            with self.subTest(pid):
                self.assertEqual(self.upload(pid, "caocao", png(), "image/png")[0], 400)
        for hero in ("nobody", "..%2Fcaocao", "caocao%2F..", "%2Fetc%2Fpasswd"):
            with self.subTest(hero):
                self.assertIn(self.upload("rej", hero, png(), "image/png")[0], (400, 404))
        self.assertEqual(self.upload("rej", "caocao", png(), "image/jpeg")[0], 400)             # MIME 与魔数不符
        self.assertEqual(self.upload("rej", "caocao", b"<svg></svg>" * 5, "image/svg+xml")[0], 400)
        self.assertEqual(self.upload("rej", "caocao", b"GIF89a" + b"\0" * 80, "image/png")[0], 400)
        self.assertEqual(self.upload("rej", "caocao", png(20, 20), "image/png")[0], 400)        # 太小
        self.assertEqual(self.upload("rej", "caocao", png(3000, 100), "image/png")[0], 400)     # 太大
        self.assertEqual(self.upload("rej", "caocao", b"", "image/png")[0], 400)
        big = png() + b"\0" * (2 * 1024 * 1024)
        self.assertEqual(self.upload("rej", "caocao", big, "image/png")[0], 413)
        self.assertEqual(self.call("/api/skins?profile_id=rej")[1]["uploads"], [])
        self.assertEqual(self.call("/api/skins?profile_id=../x")[0], 400)
        self.assertEqual(self.call("/api/skins")[0], 400)

    def test_image_endpoint_rejects_injection(self):
        for query in ("hero_id=caocao&skin_id=../../../etc/passwd", "hero_id=../caocao&skin_id=nn_1", "hero_id=caocao&skin_id=nn_1/..",
                      "hero_id=caocao&skin_id=%2e%2e%2f%2e%2e%2fgame_server.py", "hero_id=nobody&skin_id=nn_1", "hero_id=caocao&skin_id=nn_999",
                      "hero_id=caocao&skin_id=up_" + "0" * 32 + "&profile_id=../..", "hero_id=caocao", "skin_id=nn_1"):
            with self.subTest(query):
                self.assertIn(self.call("/api/skins/image?" + query, raw=True)[0], (400, 404))

    def test_select_rejects_bad_input(self):
        for body in ({"profile_id": "s", "hero_id": "caocao", "skin_id": "../x"}, {"profile_id": "s", "hero_id": "caocao", "skin_id": "nn_77"},
                     {"profile_id": "s", "hero_id": "zzz", "skin_id": "nn_1"}, {"profile_id": "../s", "hero_id": "caocao", "skin_id": None},
                     {"profile_id": "s", "hero_id": "caocao", "skin_id": "up_" + "1" * 32}):
            with self.subTest(body):
                self.assertIn(self.call("/api/skins/select", body, headers=self.WRITE)[0], (400, 404))
        self.assertEqual(self.call("/api/skins/select", b"not json", headers=self.WRITE)[0], 400)
        self.assertEqual(self.call("/api/skins/delete", {"profile_id": "s", "skin_id": "../../x"}, headers=self.WRITE)[0], 400)


if __name__ == "__main__":
    unittest.main()
