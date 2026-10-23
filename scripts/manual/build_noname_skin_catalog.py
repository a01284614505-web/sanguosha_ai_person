#!/usr/bin/env python3
"""Regenerate the pinned noname 27-hero candidate catalog from GitHub's tree API."""
from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMMIT = "c9f9424eff49d7f5deacbe5e3dad76c0c0fb6a03"
HERO_IDS = [
    "caocao", "simayi", "xiahoudun", "zhangliao", "xuzhu", "guojia", "zhenji",
    "liubei", "guanyu", "zhangfei", "zhugeliang", "zhaoyun", "machao",
    "huangyueying", "sunquan", "ganning", "lvmeng", "huanggai", "zhouyu",
    "daqiao", "luxun", "huatuo", "lvbu", "diaochan", "huaxiong", "yuanshao",
    "zhangjiao",
]
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


def main() -> int:
    url = f"https://api.github.com/repos/libccy/noname/git/trees/{COMMIT}?recursive=1"
    request = urllib.request.Request(url, headers={"User-Agent": "sanguosha-resource-audit/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        tree = json.load(response)
    if tree.get("truncated"):
        raise SystemExit("GitHub returned a truncated tree; refusing to publish a partial catalog")

    records = []
    for project_id in HERO_IDS:
        source_id = "xuzhu" if project_id == "xuzhu" else project_id
        prefix = f"image/skin/{source_id}/"
        files = sorted(
            (item for item in tree["tree"]
             if item["type"] == "blob" and item["path"].startswith(prefix)
             and item["path"].lower().endswith(IMAGE_EXTENSIONS)),
            key=lambda item: item["path"],
        )
        for item in files:
            path = item["path"]
            records.append({
                "hero_id": "xuchu" if project_id == "xuzhu" else project_id,
                "source_hero_id": source_id,
                "path": path,
                "filename": path.rsplit("/", 1)[-1],
                "git_blob_sha1": item["sha"],
                "bytes": item["size"],
                "url": f"https://raw.githubusercontent.com/libccy/noname/{COMMIT}/{path}",
            })

    if len(records) != 307 or len({row["hero_id"] for row in records}) != 27:
        raise SystemExit(f"Unexpected source catalog shape: {len(records)} images")
    catalog = {
        "schema_version": 1,
        "source_repository": "https://github.com/libccy/noname",
        "source_commit": COMMIT,
        "source_commit_date": "2022-05-30T10:35:29Z",
        "source_tree_url": f"https://github.com/libccy/noname/tree/{COMMIT}/image/skin",
        "selection_note": (
            "This is the complete image/skin subset for this project's 27 hero IDs at the pinned commit. "
            "It is 307 images, not the unrecovered historical 379-image archive. xuzhu maps to xuchu. "
            "Image bytes are fetched from the pinned raw URL only when a user previews/imports a choice."
        ),
        "license_evidence": {
            "repository_license": "GPL-3.0 root LICENSE at the pinned commit",
            "artwork_rights": "No per-image authorship or artwork-specific license metadata was verified. Do not infer commercial or redistribution permission from the repository license alone.",
        },
        "items": records,
    }
    output = ROOT / "frontend/data/noname_skin_candidates.json"
    output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote={output.relative_to(ROOT)} images={len(records)} heroes=27 sha256={hashlib.sha256(output.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
