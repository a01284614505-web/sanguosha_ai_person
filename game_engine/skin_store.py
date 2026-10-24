#!/usr/bin/env python3
"""武将皮肤的服务器存储：按档案保存「选择表 + 导入图片」，并代拉、缓存 noname 候选图。

设计取舍（为什么这样放）：
- 导入图片放在 <root>/profiles/<profile_id>/uploads/ 下，按档案隔离：别的档案既读不到也删不掉。
- noname 候选图是公共资源，所有档案共用 <root>/noname/<hero_id>/<n>.jpg，只缓存一份。
- 档案级选择表（hero_id -> skin_id）放在 <root>/profiles/<profile_id>/skins.json，浏览器只认 hero_id + skin_id。
- 所有路径都由「校验过的 ID + 固定扩展名」拼出，绝不使用用户给的文件名，所以没有路径穿越的入口。
- 不引入图像库：用文件头解析 PNG / JPEG / WebP 的真实宽高与魔数，拒绝改了扩展名的假图片。
"""
import hashlib
import json
import os
import re
import struct
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .game_history import validate_profile_id

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MIN_EDGE = 64
MAX_EDGE = 2048
MAX_UPLOADS_PER_PROFILE = 40
MAX_PROFILE_UPLOAD_BYTES = 40 * 1024 * 1024
MAX_NONAME_BYTES = 3 * 1024 * 1024
MAX_LABEL_CHARS = 40
FETCH_RETRY_SECONDS = 30.0        # 同一张图拉取失败后，这段时间内不再重复打 GitHub

HERO_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
UPLOAD_SKIN_ID = re.compile(r"^up_[0-9a-f]{32}$")
NONAME_SKIN_ID = re.compile(r"^nn_[0-9]{1,4}$")
CLIENT_REF = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ALLOWED_HOST_PREFIX = "https://raw.githubusercontent.com/"
MIME_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
EXT_MIME = {ext: mime for mime, ext in MIME_EXT.items()}

NONAME_HELP = "可稍后重试，或在电脑上运行 scripts/download_noname_skins.py 一次性下载全部候选图。"


class SkinError(ValueError):
    """带 HTTP 状态码的业务错误；message 直接给玩家看。"""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- 图片头解析
def sniff_image(data):
    """只看文件头：返回 (mime, width, height)；格式不对或尺寸读不出来则抛 SkinError。"""
    if not isinstance(data, (bytes, bytearray)) or len(data) < 24:
        raise SkinError("只接受真实 PNG、JPEG 或 WebP 图片。")
    data = bytes(data)
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        if data[12:16] != b"IHDR":
            raise SkinError("PNG 文件头损坏。")
        width, height = struct.unpack(">II", data[16:24])
        return "image/png", width, height
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg", *_jpeg_size(data)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", *_webp_size(data)
    raise SkinError("只接受真实 PNG、JPEG 或 WebP 图片。")


def _jpeg_size(data):
    pos = 2
    end = len(data)
    while pos + 4 <= end:
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker == 0xFF:          # 填充字节
            pos += 1
            continue
        if marker in (0x01, *range(0xD0, 0xD9)):   # 无长度的独立标记
            pos += 2
            continue
        length = struct.unpack(">H", data[pos + 2:pos + 4])[0]
        if length < 2:
            break
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if pos + 9 > end:
                break
            height, width = struct.unpack(">HH", data[pos + 5:pos + 9])
            return width, height
        pos += 2 + length
    raise SkinError("JPEG 文件头损坏，读不出尺寸。")


def _webp_size(data):
    kind = data[12:16]
    if kind == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
        width, height = struct.unpack("<HH", data[26:30])
        return width & 0x3FFF, height & 0x3FFF
    if kind == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
        b1, b2, b3, b4 = data[21:25]
        return 1 + (b1 | ((b2 & 0x3F) << 8)), 1 + ((b2 >> 6) | (b3 << 2) | ((b4 & 0x0F) << 10))
    if kind == b"VP8X" and len(data) >= 30:
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
        return width, height
    raise SkinError("WebP 文件头损坏，读不出尺寸。")


def default_fetcher(url, timeout=20.0):
    """默认的 GitHub 拉取实现；测试里换成本地假函数，不碰外网。"""
    if not url.startswith(ALLOWED_HOST_PREFIX):
        raise OSError("拒绝非 raw.githubusercontent.com 的地址")
    request = urllib.request.Request(url, headers={"User-Agent": "sanguosha-ai-person-skin-cache"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(MAX_NONAME_BYTES + 1)
    if len(data) > MAX_NONAME_BYTES:
        raise OSError("远端图片超过大小上限")
    return data


def git_blob_sha1(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


class SkinStore:
    def __init__(self, root, catalog_path, hero_ids, fetcher=None):
        """hero_ids：返回当前合法武将 ID 集合的函数（含已启用武将包）。fetcher(url)->bytes。"""
        self.root = Path(root)
        self.hero_ids = hero_ids
        self.fetcher = fetcher or default_fetcher
        self._lock = threading.RLock()
        self._fetch_locks = {}
        self._fetch_failures = {}
        self._catalog = self._load_catalog(Path(catalog_path))

    # ------------------------------------------------------------ 目录与校验
    @staticmethod
    def _load_catalog(path):
        data = json.loads(path.read_text(encoding="utf-8"))
        by_hero = {}
        for item in data.get("items", []):
            stem = Path(item["filename"]).stem
            skin_id = f"nn_{stem}"
            if not NONAME_SKIN_ID.fullmatch(skin_id) or not HERO_ID.fullmatch(item["hero_id"]):
                continue
            by_hero.setdefault(item["hero_id"], {})[skin_id] = {
                "skin_id": skin_id, "label": f"候选 {stem}", "bytes": int(item["bytes"]),
                "url": item["url"], "sha1": item["git_blob_sha1"], "filename": f"{stem}.jpg",
            }
        return {"source": {k: data.get(k) for k in ("source_repository", "source_commit", "source_tree_url", "license_evidence")},
                "heroes": by_hero}

    def check_hero(self, hero_id):
        if not isinstance(hero_id, str) or not HERO_ID.fullmatch(hero_id):
            raise SkinError("武将 ID 格式无效。")
        if hero_id not in self.hero_ids():
            raise SkinError("未知武将。", 404)
        return hero_id

    @staticmethod
    def _label(value, fallback):
        text = "".join(ch for ch in str(value or "") if ch.isprintable()).strip()
        return (text or fallback)[:MAX_LABEL_CHARS]

    # ------------------------------------------------------------ 档案数据文件
    def _profile_dir(self, profile_id):
        return self.root / "profiles" / validate_profile_id(profile_id)

    def _read(self, profile_id):
        path = self._profile_dir(profile_id) / "skins.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"version": 1, "selection": {}, "uploads": {}}
        except (OSError, json.JSONDecodeError) as exc:
            raise SkinError("皮肤档案读取失败，请检查服务器日志。", 500) from exc
        data.setdefault("selection", {})
        data.setdefault("uploads", {})
        return data

    def _write(self, profile_id, data):
        folder = self._profile_dir(profile_id)
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / f"skins.json.{uuid.uuid4().hex}.tmp"
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, folder / "skins.json")
        finally:
            if tmp.exists():
                tmp.unlink()

    # ------------------------------------------------------------ 地址
    @staticmethod
    def noname_url(hero_id, skin_id):
        return f"/api/skins/image?hero_id={hero_id}&skin_id={skin_id}"

    @staticmethod
    def upload_url(profile_id, hero_id, skin_id):
        return f"/api/skins/image?profile_id={profile_id}&hero_id={hero_id}&skin_id={skin_id}"

    def _url(self, profile_id, hero_id, skin_id):
        if skin_id.startswith("up_"):
            return self.upload_url(profile_id, hero_id, skin_id)
        return self.noname_url(hero_id, skin_id)

    # ------------------------------------------------------------ 查询
    def catalog(self):
        """返回给浏览器的候选目录：不含 GitHub 地址，只有本服务器的图片地址和是否已缓存。"""
        heroes = {}
        for hero_id, items in self._catalog["heroes"].items():
            rows = []
            for skin_id, item in sorted(items.items(), key=lambda kv: int(kv[0][3:])):
                rows.append({"skin_id": skin_id, "label": item["label"], "bytes": item["bytes"],
                             "cached": self._noname_file(hero_id, item).exists(),
                             "url": self.noname_url(hero_id, skin_id)})
            heroes[hero_id] = rows
        return {"source": self._catalog["source"], "heroes": heroes}

    def state(self, profile_id):
        """档案当前状态：每名武将正在使用的皮肤（含地址）+ 已导入图片列表。"""
        profile_id = validate_profile_id(profile_id)
        with self._lock:
            data = self._read(profile_id)
        known = self.hero_ids()
        selection = {}
        for hero_id, skin_id in data["selection"].items():
            if hero_id not in known:
                continue
            if skin_id.startswith("up_") and skin_id not in data["uploads"]:
                continue
            if skin_id.startswith("nn_") and skin_id not in self._catalog["heroes"].get(hero_id, {}):
                continue
            selection[hero_id] = {"skin_id": skin_id, "url": self._url(profile_id, hero_id, skin_id)}
        uploads = []
        for skin_id, meta in sorted(data["uploads"].items(), key=lambda kv: kv[1].get("created_at", ""), reverse=True):
            uploads.append({"skin_id": skin_id, "hero_id": meta["hero_id"], "label": meta.get("label", ""),
                            "type": meta.get("type"), "size": meta.get("size"), "width": meta.get("width"),
                            "height": meta.get("height"), "created_at": meta.get("created_at"),
                            "url": self.upload_url(profile_id, meta["hero_id"], skin_id)})
        return {"profile_id": profile_id, "selection": selection, "uploads": uploads}

    # ------------------------------------------------------------ 导入
    def save_upload(self, profile_id, hero_id, data, content_type, label=None, client_ref=None, select="1"):
        profile_id = validate_profile_id(profile_id)
        self.check_hero(hero_id)
        if select not in ("0", "1", "if_empty"):
            raise SkinError("select 参数无效。")
        if client_ref is not None and not CLIENT_REF.fullmatch(client_ref):
            raise SkinError("client_ref 格式无效。")
        if not data or len(data) > MAX_UPLOAD_BYTES:
            raise SkinError("图片大小必须在 1 字节到 2 MiB 之间。", 413 if data else 400)
        mime, width, height = sniff_image(data)
        declared = (content_type or "").split(";")[0].strip().lower()
        if declared != mime:
            raise SkinError("文件类型与内容不一致，已拒绝。")
        if not (MIN_EDGE <= width <= MAX_EDGE and MIN_EDGE <= height <= MAX_EDGE):
            raise SkinError("图片宽高必须各在 64 到 2048 像素之间。")
        with self._lock:
            record = self._read(profile_id)
            if client_ref:
                for skin_id, meta in record["uploads"].items():
                    if meta.get("client_ref") == client_ref and meta["hero_id"] == hero_id:
                        self._apply_select(record, hero_id, skin_id, select)
                        self._write(profile_id, record)
                        return {"skin_id": skin_id, "duplicate": True, **self._public_meta(profile_id, skin_id, meta)}
            used = sum(int(m.get("size", 0)) for m in record["uploads"].values())
            if len(record["uploads"]) >= MAX_UPLOADS_PER_PROFILE or used + len(data) > MAX_PROFILE_UPLOAD_BYTES:
                raise SkinError(f"每个档案最多保存 {MAX_UPLOADS_PER_PROFILE} 张导入图片（合计 40 MiB），请先删除不用的。", 409)
            skin_id = "up_" + uuid.uuid4().hex
            ext = MIME_EXT[mime]
            folder = self._profile_dir(profile_id) / "uploads"
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / f"{skin_id}.{ext}"
            tmp = folder / f"{skin_id}.tmp"
            try:
                tmp.write_bytes(data)
                os.replace(tmp, target)
            finally:
                if tmp.exists():
                    tmp.unlink()
            meta = {"hero_id": hero_id, "label": self._label(label, "自定义图片"), "type": mime, "ext": ext,
                    "size": len(data), "width": width, "height": height, "client_ref": client_ref,
                    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            record["uploads"][skin_id] = meta
            self._apply_select(record, hero_id, skin_id, select)
            try:
                self._write(profile_id, record)
            except Exception:
                target.unlink(missing_ok=True)
                raise
        return {"skin_id": skin_id, "duplicate": False, **self._public_meta(profile_id, skin_id, meta)}

    def _public_meta(self, profile_id, skin_id, meta):
        return {"hero_id": meta["hero_id"], "label": meta.get("label", ""), "type": meta["type"], "size": meta["size"],
                "width": meta["width"], "height": meta["height"], "url": self.upload_url(profile_id, meta["hero_id"], skin_id)}

    @staticmethod
    def _apply_select(record, hero_id, skin_id, select):
        if select == "1" or (select == "if_empty" and hero_id not in record["selection"]):
            record["selection"][hero_id] = skin_id

    # ------------------------------------------------------------ 选择 / 删除
    def select(self, profile_id, hero_id, skin_id):
        profile_id = validate_profile_id(profile_id)
        self.check_hero(hero_id)
        if skin_id in (None, ""):
            with self._lock:
                record = self._read(profile_id)
                record["selection"].pop(hero_id, None)
                self._write(profile_id, record)
            return self.state(profile_id)
        if not isinstance(skin_id, str):
            raise SkinError("skin_id 无效。")
        if UPLOAD_SKIN_ID.fullmatch(skin_id):
            with self._lock:
                record = self._read(profile_id)
                meta = record["uploads"].get(skin_id)
                if not meta or meta["hero_id"] != hero_id:
                    raise SkinError("没有这张导入图片。", 404)
                record["selection"][hero_id] = skin_id
                self._write(profile_id, record)
        elif NONAME_SKIN_ID.fullmatch(skin_id):
            item = self._catalog["heroes"].get(hero_id, {}).get(skin_id)
            if not item:
                raise SkinError("这名武将没有这张候选图。", 404)
            self._ensure_noname(hero_id, item)       # 先确保已缓存：失败就别把「使用中」标成一张打不开的图
            with self._lock:
                record = self._read(profile_id)
                record["selection"][hero_id] = skin_id
                self._write(profile_id, record)
        else:
            raise SkinError("skin_id 格式无效。")
        return self.state(profile_id)

    def delete_upload(self, profile_id, skin_id):
        profile_id = validate_profile_id(profile_id)
        if not isinstance(skin_id, str) or not UPLOAD_SKIN_ID.fullmatch(skin_id):
            raise SkinError("skin_id 格式无效。")
        with self._lock:
            record = self._read(profile_id)
            meta = record["uploads"].pop(skin_id, None)
            if meta is None:
                raise SkinError("没有这张导入图片。", 404)
            for hero_id in [h for h, s in record["selection"].items() if s == skin_id]:
                record["selection"].pop(hero_id)
            self._write(profile_id, record)
            (self._profile_dir(profile_id) / "uploads" / f"{skin_id}.{meta['ext']}").unlink(missing_ok=True)
        return self.state(profile_id)

    # ------------------------------------------------------------ 取图
    def upload_file(self, profile_id, hero_id, skin_id):
        profile_id = validate_profile_id(profile_id)
        if not isinstance(skin_id, str) or not UPLOAD_SKIN_ID.fullmatch(skin_id):
            raise SkinError("skin_id 格式无效。")
        record = self._read(profile_id)
        meta = record["uploads"].get(skin_id)
        if not meta or meta["hero_id"] != hero_id:
            raise SkinError("没有这张导入图片。", 404)
        path = self._profile_dir(profile_id) / "uploads" / f"{skin_id}.{meta['ext']}"
        if not path.is_file():
            raise SkinError("图片文件丢失。", 404)
        return path, meta["type"]

    def _noname_file(self, hero_id, item):
        return self.root / "noname" / hero_id / item["filename"]

    def noname_file(self, hero_id, skin_id):
        if not isinstance(hero_id, str) or not HERO_ID.fullmatch(hero_id):
            raise SkinError("武将 ID 格式无效。")
        if not isinstance(skin_id, str) or not NONAME_SKIN_ID.fullmatch(skin_id):
            raise SkinError("skin_id 格式无效。")
        item = self._catalog["heroes"].get(hero_id, {}).get(skin_id)
        if not item:
            raise SkinError("这名武将没有这张候选图。", 404)
        return self._ensure_noname(hero_id, item), "image/jpeg"

    def _ensure_noname(self, hero_id, item):
        """已缓存直接返回；否则从固定提交的 GitHub 地址拉取，核对大小与 git blob 哈希后落盘。"""
        path = self._noname_file(hero_id, item)
        if path.is_file():
            return path
        key = (hero_id, item["skin_id"])
        with self._lock:
            gate = self._fetch_locks.setdefault(key, threading.Lock())
        with gate:
            if path.is_file():
                return path
            failed = self._fetch_failures.get(key)
            if failed and time.monotonic() - failed[0] < FETCH_RETRY_SECONDS:
                raise SkinError(failed[1], 502)
            try:
                data = self.fetcher(item["url"])
                if len(data) != item["bytes"] or git_blob_sha1(data) != item["sha1"]:
                    raise OSError("下载内容与目录记录的大小/哈希不一致")
                sniff_image(data)
            except (OSError, urllib.error.URLError, SkinError, TimeoutError) as exc:
                message = f"无法从 GitHub 拉取这张候选图（{type(exc).__name__}）。{NONAME_HELP}"
                self._fetch_failures[key] = (time.monotonic(), message)
                raise SkinError(message, 502) from exc
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
            try:
                tmp.write_bytes(data)
                os.replace(tmp, path)
            finally:
                if tmp.exists():
                    tmp.unlink()
            self._fetch_failures.pop(key, None)
            return path

    def ensure_noname(self, hero_id, skin_id):
        """给下载脚本用：确保缓存并返回路径。"""
        return self.noname_file(hero_id, skin_id)[0]

    def all_noname(self):
        return [(hero_id, skin_id) for hero_id, items in self._catalog["heroes"].items() for skin_id in items]
