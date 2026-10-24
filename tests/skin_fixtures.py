"""皮肤测试用的假图片与假目录：只造文件头，不依赖外网和图像库。"""
import json
import struct
import zlib

from game_engine.skin_store import git_blob_sha1


def png(width=128, height=96):
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x10\x20\x30" * width for _ in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def jpeg(width=128, height=96):
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + sof + b"\xff\xd9"


def webp(width=128, height=96):
    body = b"VP8X" + struct.pack("<I", 10) + b"\x00\x00\x00\x00" + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WEBP" + body


def fake_catalog(path, heroes=("caocao", "liubei"), per_hero=2):
    """返回 (catalog_path, {url: bytes})；每张假候选图的大小与哈希都和目录一致。"""
    items, blobs = [], {}
    for hero in heroes:
        for n in range(1, per_hero + 1):
            data = jpeg(200 + n, 300) + bytes([n]) * 40
            url = f"https://raw.githubusercontent.com/libccy/noname/abc/image/skin/{hero}/{n}.jpg"
            blobs[url] = data
            items.append({"hero_id": hero, "source_hero_id": hero, "path": f"image/skin/{hero}/{n}.jpg",
                          "filename": f"{n}.jpg", "git_blob_sha1": git_blob_sha1(data), "bytes": len(data), "url": url})
    path.write_text(json.dumps({"source_repository": "x", "source_commit": "abc", "source_tree_url": "y",
                                "license_evidence": {}, "items": items}), encoding="utf-8")
    return path, blobs
