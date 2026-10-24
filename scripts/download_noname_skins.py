#!/usr/bin/env python3
"""一次性把 noname 皮肤候选图（307 张）拉到本地资源目录，之后游戏服务器不再需要访问 GitHub。

用法（在项目根目录）：
    python3 scripts/download_noname_skins.py              # 全部
    python3 scripts/download_noname_skins.py --hero caocao # 只拉某位武将
    python3 scripts/download_noname_skins.py --dir D:\\skins   # 指定资源目录（要和服务器的 SANGUOSHA_SKIN_DIR 一致）

已下载的会跳过，可以反复运行补齐失败的；每张都会核对大小和 git 哈希。
图片来源未核实授权，仅限个人非商用，请勿再分发。
"""
import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from game_engine.skin_store import SkinError, SkinStore  # noqa: E402


def main(argv=None, fetcher=None, catalog=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", default=os.environ.get("SANGUOSHA_SKIN_DIR") or str(ROOT / "data" / "skins"))
    parser.add_argument("--hero", action="append", help="只下载这名武将，可重复")
    parser.add_argument("--retries", type=int, default=3)
    args = parser.parse_args(argv)
    store = SkinStore(args.dir, catalog or ROOT / "frontend/data/noname_skin_candidates.json", lambda: set(), fetcher=fetcher)
    todo = [pair for pair in store.all_noname() if not args.hero or pair[0] in args.hero]
    if not todo:
        print("没有匹配的候选图。")
        return 1
    done = failed = 0
    for index, (hero_id, skin_id) in enumerate(todo, 1):
        for attempt in range(1, args.retries + 1):
            try:
                store._fetch_failures.clear()      # 脚本自己重试，不用服务器的 30 秒退避
                store.ensure_noname(hero_id, skin_id)
                done += 1
                print(f"[{index}/{len(todo)}] OK   {hero_id}/{skin_id}", flush=True)
                break
            except SkinError as exc:
                if attempt == args.retries:
                    failed += 1
                    print(f"[{index}/{len(todo)}] FAIL {hero_id}/{skin_id}: {exc}", flush=True)
                else:
                    time.sleep(1.5 * attempt)
    print(f"完成：成功 {done}，失败 {failed}，目录 {Path(args.dir) / 'noname'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
