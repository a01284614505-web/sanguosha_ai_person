#!/usr/bin/env python3
"""Exercise safe copy and symlink rejection in skin_asset_inventory.py."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).with_name("skin_asset_inventory.py")


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def expect_rejected(label: str, *args: str) -> None:
    result = run(*args)
    assert result.returncode == 2 and "symbolic link" in result.stderr, (
        label, result.returncode, result.stderr
    )
    print(f"{label}: exit={result.returncode} rejected=true")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="skin-symlink-check-") as temp:
        root = Path(temp)
        source = root / "pack"
        (source / "hero").mkdir(parents=True)
        (source / "hero" / "ok.png").write_bytes(b"asset")

        dest = root / "destination"
        copied = run(str(source), "--copy-relative", "hero/ok.png", "--dest", str(dest))
        assert copied.returncode == 0, copied.stderr
        record = json.loads(copied.stdout)["copied"][0]
        assert (dest / "ok.png").read_bytes() == b"asset"
        print(f"valid_copy: exit={copied.returncode} file={record['source']} sha256={record['sha256']}")

        real = root / "real"
        real.mkdir()
        (real / "ok.png").write_bytes(b"asset")
        linked = root / "linked"
        linked.symlink_to(real, target_is_directory=True)
        expect_rejected("intermediate_scan", str(linked))
        expect_rejected("intermediate_copy", str(linked), "--copy-relative", "ok.png",
                        "--dest", str(root / "copy-through-link"))

        (source / "hero" / "alias.png").symlink_to(source / "hero" / "ok.png")
        expect_rejected("file_link_scan", str(source))

        real_dest = root / "real-dest"
        real_dest.mkdir()
        linked_dest = root / "linked-dest"
        linked_dest.symlink_to(real_dest, target_is_directory=True)
        expect_rejected("destination_link_copy", str(real), "--copy-relative", "ok.png",
                        "--dest", str(linked_dest))


if __name__ == "__main__":
    main()
