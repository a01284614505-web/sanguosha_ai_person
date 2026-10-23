"""武将包校验与单文件原子持久化；包数据和其世界书条目共用一次提交。"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from .skill_dsl import compile_skill
from .skills_generated import get_all_skills

PACKAGE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
HERO_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
FACTIONS = {"魏", "蜀", "吴", "群"}
SKILL_STATUSES = {"data_only", "partial", "active"}
MAX_IMPORT_BYTES = 1_000_000
_LOCKS = {}
_LOCK_GUARD = threading.Lock()


class HeroImportError(ValueError):
    pass


def _lock_for(path):
    key = str(path.resolve())
    with _LOCK_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def _fsync_directory(path):
    try:
        dir_fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


def _read(path):
    if not path.exists():
        return {"schema_version": 1, "packages": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("packages"), list):
        raise RuntimeError("武将包存储损坏")
    return data


def _atomic_write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    backup_temp_name = None
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            backup_dir = path.parent / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup = backup_dir / f"{path.stem}.{stamp}.json"
            # Publish backups atomically too, so a failed copy never appears usable.
            backup_fd, backup_temp_name = tempfile.mkstemp(
                prefix=f".{backup.name}.", suffix=".tmp", dir=backup_dir
            )
            with os.fdopen(backup_fd, "wb") as stream:
                stream.write(path.read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(backup_temp_name, backup)
            backup_temp_name = None
            _fsync_directory(backup_dir)
        os.replace(temp_name, path)
        _fsync_directory(path.parent)
    except Exception:
        try: os.unlink(temp_name)
        except OSError: pass
        if backup_temp_name is not None:
            try: os.unlink(backup_temp_name)
            except OSError: pass
        raise


class HeroPackageStore:
    def __init__(self, project_root=None):
        self.project_root = Path(project_root or Path(__file__).resolve().parents[1]).resolve()
        self.path = self.project_root / "data" / "hero_packages.json"
        self.base_heroes_path = self.project_root / "data" / "heroes.json"
        self.lock = _lock_for(self.path)

    def _base_data(self):
        raw = json.loads(self.base_heroes_path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else raw.get("heroes", [])

    def _read_current(self):
        """Validate and normalize current package records for safe consumers."""
        try:
            data = _read(self.path)
            return self._validate_document(data)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise RuntimeError("武将包存储损坏") from exc

    def list_packages(self):
        with self.lock:
            data = self._read_current()
        return [{"id": p["id"], "name": p["name"], "version": p["version"],
                 "enabled": bool(p.get("enabled")), "heroes": [h["id"] for h in p.get("heroes", [])],
                 "hero_names": [h["name"] for h in p.get("heroes", [])]}
                for p in data["packages"]]

    def enabled_heroes(self):
        with self.lock:
            data = self._read_current()
        return [hero for package in data["packages"] if package.get("enabled")
                for hero in package.get("heroes", [])]

    def list_backups(self):
        directory = self.path.parent / "backups"
        if not directory.exists():
            return []
        return sorted((p.name for p in directory.iterdir()
                       if p.is_file() and re.fullmatch(r"hero_packages\.\d{8}T\d{12}Z\.json", p.name)), reverse=True)

    def restore_backup(self, filename):
        if not isinstance(filename, str) or not re.fullmatch(r"hero_packages\.\d{8}T\d{12}Z\.json", filename):
            raise HeroImportError("备份文件名无效")
        backup = self.path.parent / "backups" / filename
        with self.lock:
            if not backup.is_file():
                raise HeroImportError("备份不存在")
            try:
                data = self._validate_document(json.loads(backup.read_text(encoding="utf-8")))
            except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                raise HeroImportError(f"备份格式无效: {exc}") from exc
            _atomic_write(self.path, data)
        return {"restored": filename}

    def _validate_document(self, data):
        if not isinstance(data, dict) or set(data) != {"schema_version", "packages"} or data.get("schema_version") != 1 or not isinstance(data.get("packages"), list):
            raise HeroImportError("备份顶层格式无效")
        if len(data["packages"]) > 500:
            raise HeroImportError("备份包数量超限")
        package_ids, hero_ids = set(), set()
        skill_names = {s.name for s in get_all_skills()}
        clean_packages = []
        for package in data["packages"]:
            if not isinstance(package, dict) or set(package) != {"id", "name", "version", "enabled", "heroes"}:
                raise HeroImportError("备份 package 格式无效")
            package_id, name, version = package["id"], package["name"], package["version"]
            if not isinstance(package_id, str) or not PACKAGE_ID.fullmatch(package_id) or package_id in package_ids:
                raise HeroImportError("备份 package.id 无效或重复")
            if not isinstance(name, str) or not name or len(name) > 80 or not isinstance(version, str) or len(version) > 32:
                raise HeroImportError("备份 package 元数据无效")
            if type(package["enabled"]) is not bool or not isinstance(package["heroes"], list):
                raise HeroImportError("备份 package enabled/heroes 无效")
            package_ids.add(package_id)
            clean_heroes = []
            for raw_hero in package["heroes"]:
                normalized = self._validate_hero(raw_hero)
                if normalized["id"] in hero_ids or normalized["id"] in {h.get("id") for h in self._base_data()}:
                    raise HeroImportError("备份 hero.id 冲突")
                if raw_hero.get("package_id") != package_id:
                    raise HeroImportError("备份 hero.package_id 不匹配")
                hero_ids.add(normalized["id"])
                for skill in normalized["skills"]:
                    if skill["name"] in skill_names:
                        raise HeroImportError(f"备份技能名冲突: {skill['name']}")
                    skill_names.add(skill["name"])
                normalized["package_id"] = package_id
                clean_heroes.append(normalized)
            clean_packages.append({"id": package_id, "name": name, "version": version,
                                   "enabled": package["enabled"], "heroes": clean_heroes})
        return {"schema_version": 1, "packages": clean_packages}

    def import_hero(self, package, hero):
        if not isinstance(package, dict) or not isinstance(hero, dict):
            raise HeroImportError("package 和 hero 必须是对象")
        package_id = str(package.get("id") or "").strip()
        package_name = str(package.get("name") or "").strip()
        version = str(package.get("version") or "1.0")
        if not PACKAGE_ID.fullmatch(package_id): raise HeroImportError("package.id 格式无效")
        if not package_name or len(package_name) > 80: raise HeroImportError("package.name 必须为 1..80 字符")
        if len(version) > 32: raise HeroImportError("package.version 过长")
        normalized = self._validate_hero(hero)
        with self.lock:
            data = self._read_current()
            base = self._base_data()
            if any(h.get("id") == normalized["id"] for h in base):
                raise HeroImportError("hero.id 与内置武将冲突")
            existing_names = {s.name for s in get_all_skills()}
            existing_names.update(s["name"] for p in data["packages"] for h in p.get("heroes", []) for s in h.get("skills", []))
            for skill in normalized["skills"]:
                if skill["name"] in existing_names:
                    raise HeroImportError(f"技能名冲突: {skill['name']}")
                existing_names.add(skill["name"])
            row = next((p for p in data["packages"] if p["id"] == package_id), None)
            if row is None:
                if len(data["packages"]) >= 500:
                    raise HeroImportError("武将包数量超限")
                row = {"id": package_id, "name": package_name, "version": version,
                       "enabled": False, "heroes": []}
                data["packages"].append(row)
            elif (row["name"], row["version"]) != (package_name, version):
                raise HeroImportError("同一 package.id 的 name/version 不可修改")
            if any(h["id"] == normalized["id"] for p in data["packages"] for h in p.get("heroes", [])):
                raise HeroImportError("hero.id 已导入")
            normalized["package_id"] = package_id
            row["heroes"].append(normalized)
            self._validate_document(data)
            _atomic_write(self.path, data)
            return {"package": {"id": row["id"], "name": row["name"], "version": row["version"], "enabled": row["enabled"]},
                    "hero": normalized}

    def set_enabled(self, package_id, enabled):
        if not PACKAGE_ID.fullmatch(str(package_id or "")) or type(enabled) is not bool:
            raise HeroImportError("package id 或 enabled 无效")
        with self.lock:
            data = self._read_current()
            row = next((p for p in data["packages"] if p["id"] == package_id), None)
            if row is None: raise HeroImportError("武将包不存在")
            row["enabled"] = enabled
            _atomic_write(self.path, data)
            return {"id": row["id"], "enabled": row["enabled"]}

    def _validate_hero(self, raw):
        if not isinstance(raw, dict):
            raise HeroImportError("hero 必须是对象")
        hero_id = str(raw.get("id") or "").strip()
        name = str(raw.get("name") or "").strip()
        faction = raw.get("faction")
        hp = raw.get("max_hp")
        if not HERO_ID.fullmatch(hero_id): raise HeroImportError("hero.id 格式无效")
        if not name or len(name) > 80: raise HeroImportError("hero.name 必须为 1..80 字符")
        if not isinstance(faction, str) or faction not in FACTIONS: raise HeroImportError("hero.faction 无效")
        if type(hp) is not int or not 1 <= hp <= 8: raise HeroImportError("hero.max_hp 必须为 1..8 整数")
        skills = raw.get("skills", [])
        if not isinstance(skills, list) or len(skills) > 12: raise HeroImportError("hero.skills 必须是最多12项的数组")
        seen = set(); normalized_skills = []
        for item in skills:
            if not isinstance(item, dict): raise HeroImportError("skill 必须是对象")
            skill_name = str(item.get("name") or "").strip()
            desc = str(item.get("description") or "").strip()
            status = item.get("implementation_status", "data_only")
            if not skill_name or len(skill_name) > 60 or skill_name in seen: raise HeroImportError("skill.name 缺失、过长或重复")
            if len(desc) > 2000 or not isinstance(status, str) or status not in SKILL_STATUSES: raise HeroImportError("skill 描述或 implementation_status 无效")
            seen.add(skill_name)
            skill = {"name": skill_name, "description": desc,
                     "implementation_status": status, "type": str(item.get("type") or "trigger")[:32]}
            dsl = item.get("dsl")
            if dsl is not None:
                try: compile_skill(dsl)
                except (ValueError, TypeError) as exc: raise HeroImportError(f"技能 {skill_name} DSL 校验失败: {exc}") from exc
                skill["dsl"] = dsl
            if status == "active" and dsl is None:
                raise HeroImportError(f"active 技能 {skill_name} 必须带 DSL")
            normalized_skills.append(skill)
        image = raw.get("image")
        if image:
            image = str(image)
            if not re.fullmatch(r"assets/heroes/[A-Za-z0-9_-]{1,80}\.(?:png|jpg|jpeg)", image):
                raise HeroImportError("image 只允许 assets/heroes 下的 png/jpg/jpeg 相对路径")
        worldbook = raw.get("worldbook") or {}
        if not isinstance(worldbook, dict): raise HeroImportError("worldbook 必须是对象")
        wb = {"summary": str(worldbook.get("summary") or f"{name}，{faction}势力，体力值{hp}点。"),
              "skill_details": str(worldbook.get("skill_details") or "；".join(f"【{s['name']}】{s['description']}" for s in normalized_skills)),
              "usage_tips": str(worldbook.get("usage_tips") or "结合当前局势合理使用技能。"),
              "combos": worldbook.get("combos", []), "counters": worldbook.get("counters", [])}
        if any(len(wb[k]) > 2000 for k in ("summary", "skill_details", "usage_tips")):
            raise HeroImportError("worldbook 文本过长")
        if any(not isinstance(wb[k], list) or len(wb[k]) > 20 or any(not isinstance(x, str) or len(x) > 300 for x in wb[k]) for k in ("combos", "counters")):
            raise HeroImportError("worldbook combos/counters 必须是有限字符串数组")
        return {"id": hero_id, "name": name, "faction": faction, "max_hp": hp,
                "title": str(raw.get("title") or "")[:100], "code": str(raw.get("code") or "")[:40],
                "image": image or "", "skills": normalized_skills, "worldbook": wb,
                "package_id": ""}
