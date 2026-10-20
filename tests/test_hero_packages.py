import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from game_engine.hero_package_store import HeroImportError, HeroPackageStore
from game_engine.hero_registry import HeroRegistry


class HeroPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "data").mkdir()
        native = Path(__file__).resolve().parents[1] / "data" / "heroes.json"
        (self.root / "data" / "heroes.json").write_bytes(native.read_bytes())
        self.store = HeroPackageStore(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def hero(self, *, status="data_only", dsl=None):
        skill = {"name": "测试新技", "description": "摸一张牌。", "implementation_status": status}
        if dsl is not None:
            skill["dsl"] = dsl
        return {"id": "test_hero", "name": "测试武将", "faction": "群", "max_hp": 4, "skills": [skill]}

    def package(self):
        return {"id": "test_pack", "name": "测试包", "version": "1.0"}

    def test_import_is_atomic_enabled_pool_and_worldbook_source(self):
        imported = self.store.import_hero(self.package(), self.hero())
        self.assertFalse(imported["package"]["enabled"])
        self.assertNotIn("test_hero", {x["id"] for x in HeroRegistry(self.root).all_heroes()})
        self.store.set_enabled("test_pack", True)
        registry = HeroRegistry(self.root)
        hero = next(x for x in registry.all_heroes() if x["id"] == "test_hero")
        self.assertEqual(hero["worldbook"]["summary"], "测试武将，群势力，体力值4点。")
        self.assertEqual(self.store.list_packages()[0]["hero_names"], ["测试武将"])
        self.assertTrue(list((self.root / "data" / "backups").glob("hero_packages.*.json")))
        self.store.set_enabled("test_pack", False)
        self.assertNotIn("test_hero", {x["id"] for x in HeroRegistry(self.root).all_heroes()})

    def test_invalid_import_leaves_store_unchanged_and_active_requires_compilable_dsl(self):
        invalid = self.hero(status="active", dsl={"version": 1, "trigger": "phase_start", "effects": [{"type": "python"}]})
        with self.assertRaises(HeroImportError):
            self.store.import_hero(self.package(), invalid)
        self.assertFalse((self.root / "data" / "hero_packages.json").exists())
        valid = self.hero(status="active", dsl={"version": 1, "trigger": "phase_start", "effects": [{"type": "draw_cards", "count": 1}]})
        self.store.import_hero(self.package(), valid)
        self.assertEqual(self.store.list_packages()[0]["heroes"], ["test_hero"])

    def test_rejects_path_ids_duplicate_native_ids_and_skill_conflicts(self):
        for package_id in ("../outside", "A uppercase", ""):
            with self.assertRaises(HeroImportError):
                self.store.import_hero({**self.package(), "id": package_id}, self.hero())
        native_id = self.hero(); native_id["id"] = "caocao"
        with self.assertRaises(HeroImportError): self.store.import_hero(self.package(), native_id)
        conflict = self.hero(); conflict["skills"][0]["name"] = "奸雄"
        with self.assertRaises(HeroImportError): self.store.import_hero(self.package(), conflict)

    def test_backup_publish_failure_preserves_committed_data_and_backup_can_restore(self):
        self.store.import_hero(self.package(), self.hero())
        committed = (self.root / "data" / "hero_packages.json").read_bytes()
        with patch("game_engine.hero_package_store.os.replace", side_effect=OSError("simulated replace failure")):
            with self.assertRaises(OSError): self.store.set_enabled("test_pack", True)
        self.assertEqual((self.root / "data" / "hero_packages.json").read_bytes(), committed)
        self.assertEqual(self.store.list_backups(), [])
        self.store.set_enabled("test_pack", True)
        self.store.set_enabled("test_pack", False)
        backup = self.store.list_backups()[0]
        self.store.restore_backup(backup)
        self.assertTrue(self.store.list_packages()[0]["enabled"])

    def test_main_registry_replace_failure_preserves_current_and_published_backup(self):
        self.store.import_hero(self.package(), self.hero())
        committed = self.store.path.read_bytes()
        real_replace = os.replace

        def fail_only_current(src, dst):
            if Path(dst) == self.store.path:
                raise OSError("simulated registry replace failure")
            return real_replace(src, dst)

        with patch("game_engine.hero_package_store.os.replace", side_effect=fail_only_current):
            with self.assertRaisesRegex(OSError, "registry replace failure"):
                self.store.set_enabled("test_pack", True)

        self.assertEqual(self.store.path.read_bytes(), committed)
        backups = self.store.list_backups()
        self.assertEqual(len(backups), 1)
        backup_data = json.loads((self.root / "data" / "backups" / backups[0]).read_text(encoding="utf-8"))
        self.assertEqual(backup_data["packages"][0]["enabled"], False)
        self.assertFalse([p for p in (self.root / "data").iterdir() if p.name.endswith(".tmp")])
        self.assertFalse([p for p in (self.root / "data" / "backups").iterdir() if p.name.endswith(".tmp")])

    def test_malformed_inner_store_records_are_rejected_without_rewrite(self):
        self.store.import_hero(self.package(), self.hero())
        self.store.set_enabled("test_pack", True)
        malformed = json.loads(self.store.path.read_text(encoding="utf-8"))
        malformed["packages"][0]["heroes"][0] = None
        self.store.path.write_text(json.dumps(malformed), encoding="utf-8")
        committed = self.store.path.read_bytes()

        with self.assertRaisesRegex(RuntimeError, "武将包存储损坏"):
            self.store.set_enabled("test_pack", True)
        second = self.hero()
        second["id"] = "second_hero"
        second["skills"][0]["name"] = "第二测试技"
        with self.assertRaisesRegex(RuntimeError, "武将包存储损坏"):
            self.store.import_hero(self.package(), second)

        self.assertEqual(self.store.path.read_bytes(), committed)
        self.store.restore_backup(self.store.list_backups()[0])
        self.assertFalse(self.store.list_packages()[0]["enabled"])

    def test_registry_rejects_malformed_enabled_package_records(self):
        self.store.import_hero(self.package(), self.hero())
        self.store.set_enabled("test_pack", True)
        malformed = json.loads(self.store.path.read_text(encoding="utf-8"))
        malformed["packages"][0]["heroes"][0] = None
        self.store.path.write_text(json.dumps(malformed), encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "武将包数据加载失败"):
            HeroRegistry(self.root)

    def test_import_cannot_write_package_beyond_current_storage_limit(self):
        packages = [{"id": f"pack_{i}", "name": f"包{i}", "version": "1.0",
                     "enabled": False, "heroes": []} for i in range(500)]
        self.store.path.write_text(json.dumps({"schema_version": 1, "packages": packages}), encoding="utf-8")
        committed = self.store.path.read_bytes()

        with self.assertRaisesRegex(HeroImportError, "武将包数量超限"):
            self.store.import_hero({"id": "overflow", "name": "超限包"}, self.hero())

        self.assertEqual(self.store.path.read_bytes(), committed)

    def test_backup_write_failure_preserves_current_registry_and_existing_backups(self):
        self.store.import_hero(self.package(), self.hero())
        self.store.set_enabled("test_pack", True)
        committed = (self.root / "data" / "hero_packages.json").read_bytes()
        backups_before = self.store.list_backups()
        backup_dir = self.root / "data" / "backups"

        real_fsync = os.fsync
        calls = 0

        def fail_backup_fsync(fd):
            nonlocal calls
            calls += 1
            if calls == 2:  # current temp is synced first; this is the backup temp
                raise OSError("simulated backup write failure")
            return real_fsync(fd)

        with patch("game_engine.hero_package_store.os.fsync", side_effect=fail_backup_fsync):
            with self.assertRaisesRegex(OSError, "backup write failure"):
                self.store.set_enabled("test_pack", False)

        self.assertEqual((self.root / "data" / "hero_packages.json").read_bytes(), committed)
        self.assertEqual(self.store.list_backups(), backups_before)
        self.assertFalse([p for p in backup_dir.iterdir() if p.name.endswith(".tmp")])
        self.assertIn("test_hero", {h["id"] for h in HeroRegistry(self.root).all_heroes()})
        saved_backup = json.loads((backup_dir / backups_before[0]).read_text(encoding="utf-8"))
        self.assertFalse(saved_backup["packages"][0]["enabled"])

    def test_corrupt_nested_backup_is_rejected_without_replacing_current_data(self):
        self.store.import_hero(self.package(), self.hero())
        before = (self.root / "data" / "hero_packages.json").read_bytes()
        backup = self.root / "data" / "backups" / "hero_packages.20261018T000000000000Z.json"
        backup.parent.mkdir(parents=True, exist_ok=True)
        payload = json.loads(before)
        payload["packages"][0]["heroes"][0]["id"] = "../escape"
        backup.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(HeroImportError):
            self.store.restore_backup(backup.name)
        self.assertEqual((self.root / "data" / "hero_packages.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
