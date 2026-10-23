#!/usr/bin/env python3
"""Read-only inventory of a supplied skin pack; optional explicit single-file copy.

No asset directory is assumed and nothing is copied unless --copy-relative is used.
The report is JSON so a real pack can be inspected before assets are imported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
SUPPORTED = {".png", ".jpg", ".jpeg", ".webp"}
# Names used by the referenced noname skin pack versus this project's stable IDs.
ALIASES = {"xuzhu": "xuchu", "sunshangxiang": None}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def symlink_component(path: Path) -> Optional[Path]:
    """Return the first symlink in a lexical path, including intermediate parts."""
    raw = os.fspath(path)
    if os.path.isabs(raw):
        current = Path(os.path.sep)
        parts = Path(raw).parts[1:]
    else:
        current = Path.cwd()
        parts = Path(raw).parts
    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            current = current.parent
            continue
        current = current / part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                return current
        except FileNotFoundError:
            # Continue lexically: a later component still must not pass through
            # any existing symlink if the path becomes resolvable.
            continue
    return None


def assert_no_symlinks(path: Path, label: str) -> None:
    link = symlink_component(path)
    if link is not None:
        raise ValueError(f"{label} contains a symbolic link: {link}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="existing, user-selected resource directory")
    parser.add_argument("--copy-relative", action="append", default=[], metavar="PATH",
                        help="copy this one relative file; repeat to copy explicitly selected files")
    parser.add_argument("--dest", type=Path, help="destination directory required with --copy-relative")
    args = parser.parse_args()
    source_input = args.source.expanduser()
    try:
        assert_no_symlinks(source_input, "source path")
        source = source_input.resolve(strict=True)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if not source.is_dir():
        parser.error("source must be a directory")
    if bool(args.copy_relative) != bool(args.dest):
        parser.error("--copy-relative and --dest must be used together")

    heroes = json.loads((ROOT / "frontend/data/heroes.json").read_text(encoding="utf-8"))
    hero_ids = {str(hero["id"]) for hero in heroes}
    files = []
    try:
        def walk_error(error: OSError) -> None:
            raise error

        for directory, dirnames, filenames in os.walk(source, followlinks=False, onerror=walk_error):
            parent = Path(directory)
            dirnames.sort()
            filenames.sort()
            for name in [*dirnames, *filenames]:
                candidate = parent / name
                if candidate.is_symlink():
                    raise ValueError(f"source tree contains a symbolic link: {candidate}")
            for name in sorted(filenames):
                path = parent / name
                if not path.is_file() or path.suffix.lower() not in SUPPORTED:
                    continue
                rel = path.relative_to(source).as_posix()
                size = path.stat().st_size
                # Common pack layout: <hero-id>/<skin-name>.<ext>. Other layouts remain
                # visible in the report but are not guessed into a hero mapping.
                folder = path.parent.name.lower()
                mapped = ALIASES.get(folder, folder)
                hero_id = mapped if mapped in hero_ids else None
                if hero_id is None:
                    stem = path.stem.lower()
                    mapped = ALIASES.get(stem, stem)
                    if mapped in hero_ids:
                        hero_id = mapped
                files.append({"path": rel, "bytes": size, "sha256": digest(path), "hero_id": hero_id})
    except (OSError, ValueError) as error:
        parser.error(str(error))

    copied = []
    if args.copy_relative:
        dest_input = args.dest.expanduser()
        try:
            assert_no_symlinks(dest_input, "destination path")
            dest = dest_input.resolve()
        except (OSError, ValueError) as error:
            parser.error(str(error))
        for raw in args.copy_relative:
            rel = Path(raw)
            if rel.is_absolute() or ".." in rel.parts:
                parser.error(f"copy path must stay inside source: {raw}")
            source_candidate = source / rel
            try:
                assert_no_symlinks(source_candidate, "copy source path")
                src = source_candidate.resolve(strict=True)
            except (OSError, ValueError) as error:
                parser.error(str(error))
            if not src.is_relative_to(source) or not src.is_file() or src.suffix.lower() not in SUPPORTED:
                parser.error(f"not a supported regular image inside source: {raw}")
            dest.mkdir(parents=True, exist_ok=True)
            try:
                assert_no_symlinks(dest, "destination path")
            except ValueError as error:
                parser.error(str(error))
            target = dest / src.name
            if target.exists() or target.is_symlink():
                parser.error(f"refusing to overwrite existing destination: {target}")
            fd, temporary = tempfile.mkstemp(prefix=".skin-import-", dir=dest)
            os.close(fd)
            try:
                shutil.copyfile(src, temporary)
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            copied.append({"source": rel.as_posix(), "destination": str(target), "sha256": digest(target)})

    summary = {
        "source": str(source),
        "pack_images_found": len(files),
        "claimed_expected_count": 379,
        "expected_count_match": len(files) == 379,
        "mappings": {hero: sum(item["hero_id"] == hero for item in files) for hero in sorted(hero_ids)},
        "unmapped_image_count": sum(item["hero_id"] is None for item in files),
        "alias_rules": ALIASES,
        "files": files,
        "copied": copied,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
