"""皮肤服务器存储：校验、隔离、缓存与拒绝用例（不依赖外网）。"""
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from game_engine.skin_store import MAX_UPLOAD_BYTES, SkinError, SkinStore, sniff_image
from tests.skin_fixtures import fake_catalog, jpeg, png, webp

HEROES = {"caocao", "liubei"}


class SkinStoreBase(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.catalog, self.blobs = fake_catalog(self.root / "cat.json")
        self.calls = []
        self.offline = False
        self.store = SkinStore(self.root / "skins", self.catalog, lambda: HEROES, fetcher=self.fetch)

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, url):
        self.calls.append(url)
        if self.offline:
            raise OSError("offline")
        return self.blobs[url]


class SniffTest(unittest.TestCase):
    def test_reads_real_sizes(self):
        self.assertEqual(sniff_image(png(130, 70)), ("image/png", 130, 70))
        self.assertEqual(sniff_image(jpeg(640, 480)), ("image/jpeg", 640, 480))
        self.assertEqual(sniff_image(webp(512, 300)), ("image/webp", 512, 300))

    def test_rejects_non_images(self):
        for data in (b"", b"GIF89a" + b"\x00" * 40, b"<svg xmlns='x'>" + b" " * 40, b"MZ" + b"\x00" * 60):
            with self.assertRaises(SkinError):
                sniff_image(data)


class UploadTest(SkinStoreBase):
    def test_upload_selects_and_roundtrips(self):
        result = self.store.save_upload("p1", "caocao", png(), "image/png", label="我的曹操")
        state = self.store.state("p1")
        self.assertEqual(state["selection"]["caocao"]["skin_id"], result["skin_id"])
        self.assertEqual(state["uploads"][0]["label"], "我的曹操")
        path, mime = self.store.upload_file("p1", "caocao", result["skin_id"])
        self.assertEqual((mime, path.read_bytes()), ("image/png", png()))

    def test_profiles_are_isolated(self):
        skin = self.store.save_upload("p1", "caocao", png(), "image/png")["skin_id"]
        self.assertEqual(self.store.state("p2"), {"profile_id": "p2", "selection": {}, "uploads": []})
        with self.assertRaises(SkinError):
            self.store.upload_file("p2", "caocao", skin)
        with self.assertRaises(SkinError):
            self.store.select("p2", "caocao", skin)
        with self.assertRaises(SkinError):
            self.store.delete_upload("p2", skin)

    def test_rejections(self):
        cases = [
            ("bad profile", ("../x", "caocao", png(), "image/png")),
            ("slash profile", ("a/b", "caocao", png(), "image/png")),
            ("unknown hero", ("p1", "nobody", png(), "image/png")),
            ("traversal hero", ("p1", "../caocao", png(), "image/png")),
            ("hero with slash", ("p1", "caocao/x", png(), "image/png")),
            ("mime mismatch", ("p1", "caocao", png(), "image/jpeg")),
            ("fake png", ("p1", "caocao", b"not an image at all, just text bytes", "image/png")),
            ("svg", ("p1", "caocao", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", "image/svg+xml")),
            ("too small", ("p1", "caocao", png(32, 200), "image/png")),
            ("too large edge", ("p1", "caocao", png(2049, 100), "image/png")),
            ("empty", ("p1", "caocao", b"", "image/png")),
            ("over 2MiB", ("p1", "caocao", png() + b"\0" * MAX_UPLOAD_BYTES, "image/png")),
        ]
        for name, args in cases:
            with self.subTest(name):
                with self.assertRaises(ValueError):
                    self.store.save_upload(*args)
        self.assertEqual(self.store.state("p1")["uploads"], [])
        self.assertFalse(list((self.root / "skins").rglob("*.png")))

    def test_bad_client_ref_and_select(self):
        with self.assertRaises(SkinError):
            self.store.save_upload("p1", "caocao", png(), "image/png", client_ref="../../x")
        with self.assertRaises(SkinError):
            self.store.save_upload("p1", "caocao", png(), "image/png", select="yes")

    def test_client_ref_is_idempotent_and_if_empty_keeps_selection(self):
        first = self.store.save_upload("p1", "caocao", png(), "image/png", client_ref="loc1", select="if_empty")
        again = self.store.save_upload("p1", "caocao", png(), "image/png", client_ref="loc1", select="if_empty")
        self.assertEqual(first["skin_id"], again["skin_id"])
        self.assertTrue(again["duplicate"])
        self.assertEqual(len(self.store.state("p1")["uploads"]), 1)
        manual = self.store.save_upload("p1", "caocao", jpeg(), "image/jpeg")
        self.store.save_upload("p1", "caocao", webp(), "image/webp", client_ref="loc2", select="if_empty")
        self.assertEqual(self.store.state("p1")["selection"]["caocao"]["skin_id"], manual["skin_id"])

    def test_quota(self):
        from game_engine import skin_store
        old = skin_store.MAX_UPLOADS_PER_PROFILE
        skin_store.MAX_UPLOADS_PER_PROFILE = 2
        try:
            self.store.save_upload("p1", "caocao", png(), "image/png")
            self.store.save_upload("p1", "caocao", png(), "image/png")
            with self.assertRaises(SkinError) as ctx:
                self.store.save_upload("p1", "caocao", png(), "image/png")
            self.assertEqual(ctx.exception.status, 409)
        finally:
            skin_store.MAX_UPLOADS_PER_PROFILE = old

    def test_delete_clears_selection_and_file(self):
        skin = self.store.save_upload("p1", "caocao", png(), "image/png")["skin_id"]
        state = self.store.delete_upload("p1", skin)
        self.assertEqual((state["selection"], state["uploads"]), ({}, []))
        self.assertFalse(list((self.root / "skins" / "profiles" / "p1" / "uploads").glob("*")))

    def test_upload_bound_to_its_hero(self):
        skin = self.store.save_upload("p1", "caocao", png(), "image/png")["skin_id"]
        with self.assertRaises(SkinError):
            self.store.select("p1", "liubei", skin)
        with self.assertRaises(SkinError):
            self.store.upload_file("p1", "liubei", skin)


class SelectionTest(SkinStoreBase):
    def test_default_restore(self):
        skin = self.store.save_upload("p1", "caocao", png(), "image/png")["skin_id"]
        self.assertEqual(self.store.select("p1", "caocao", None)["selection"], {})
        self.assertIn("caocao", self.store.select("p1", "caocao", skin)["selection"])

    def test_select_rejections(self):
        for hero, skin in (("caocao", "nn_99"), ("caocao", "../x"), ("caocao", "nn_1/../../x"), ("caocao", "up_" + "0" * 32),
                           ("caocao", 5), ("nobody", "nn_1"), ("liubei", "nn_3")):
            with self.subTest((hero, skin)):
                with self.assertRaises(ValueError):
                    self.store.select("p1", hero, skin)
        self.assertEqual(self.calls, [])      # 非法请求不应触发任何外网拉取

    def test_selection_survives_new_store_instance(self):
        self.store.select("p1", "caocao", "nn_2")
        other = SkinStore(self.root / "skins", self.catalog, lambda: HEROES, fetcher=self.fetch)
        self.assertEqual(other.state("p1")["selection"]["caocao"]["skin_id"], "nn_2")


class NonameCacheTest(SkinStoreBase):
    def test_fetch_once_then_cached(self):
        for _ in range(3):
            path, mime = self.store.noname_file("caocao", "nn_1")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(mime, "image/jpeg")
        self.assertTrue(path.is_file())
        self.assertTrue(next(r for r in self.store.catalog()["heroes"]["caocao"] if r["skin_id"] == "nn_1")["cached"])

    def test_catalog_hides_github_urls(self):
        text = str(self.store.catalog())
        self.assertNotIn("githubusercontent", text.replace(self.store.catalog()["source"]["source_tree_url"] or "", ""))
        self.assertEqual(sorted(self.store.catalog()["heroes"]), ["caocao", "liubei"])

    def test_offline_gives_clear_error_and_backs_off(self):
        self.offline = True
        with self.assertRaises(SkinError) as ctx:
            self.store.noname_file("caocao", "nn_1")
        self.assertEqual(ctx.exception.status, 502)
        self.assertIn("download_noname_skins.py", str(ctx.exception))
        with self.assertRaises(SkinError):
            self.store.noname_file("caocao", "nn_1")
        self.assertEqual(len(self.calls), 1)        # 短时间内不重复打 GitHub
        with self.assertRaises(SkinError):
            self.store.select("p1", "caocao", "nn_1")
        self.assertEqual(self.store.state("p1")["selection"], {})   # 拉不下来就不标成使用中

    def test_corrupted_download_is_rejected_not_cached(self):
        url = next(iter(self.blobs))
        self.blobs[url] = self.blobs[url][:-1] + b"X"
        with self.assertRaises(SkinError):
            self.store.noname_file("caocao", "nn_1")
        self.assertFalse(list((self.root / "skins" / "noname").rglob("*.jpg")))

    def test_concurrent_requests_fetch_once(self):
        threads = [threading.Thread(target=lambda: self.store.noname_file("liubei", "nn_2")) for _ in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(len(self.calls), 1)

    def test_noname_traversal_rejected(self):
        for hero, skin in (("../caocao", "nn_1"), ("caocao", "nn_1/../../etc"), ("caocao", "../../x.jpg"), ("", "nn_1")):
            with self.assertRaises(ValueError):
                self.store.noname_file(hero, skin)


if __name__ == "__main__":
    unittest.main()


class DownloadScriptTest(unittest.TestCase):
    def load(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("dl", Path(__file__).resolve().parents[1] / "scripts/download_noname_skins.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_downloads_all_then_resumes_after_failures(self):
        module = self.load()
        with TemporaryDirectory() as tmp:
            catalog, blobs = fake_catalog(Path(tmp) / "cat.json")
            out = Path(tmp) / "out"
            flaky = {"on": True}

            def fetch(url):
                if flaky["on"] and "liubei" in url:
                    raise OSError("offline")
                return blobs[url]

            self.assertEqual(module.main(["--dir", str(out), "--retries", "1"], fetcher=fetch, catalog=catalog), 1)
            self.assertEqual(len(list((out / "noname").rglob("*.jpg"))), 2)       # 只有曹操两张成功
            flaky["on"] = False
            self.assertEqual(module.main(["--dir", str(out), "--retries", "1"], fetcher=fetch, catalog=catalog), 0)
            self.assertEqual(len(list((out / "noname").rglob("*.jpg"))), 4)
            self.assertEqual(module.main(["--dir", str(out), "--hero", "nobody"], fetcher=fetch, catalog=catalog), 1)

    def test_real_catalog_has_307_items(self):
        import json
        real = Path(__file__).resolve().parents[1] / "frontend/data/noname_skin_candidates.json"
        self.assertEqual(len(json.loads(real.read_text(encoding="utf-8"))["items"]), 307)
