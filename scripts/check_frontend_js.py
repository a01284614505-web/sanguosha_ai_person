#!/usr/bin/env python3
"""提取 HTML 内联 <script> 并用 node --check 做语法校验。

用法：
    python scripts/check_frontend_js.py frontend/game.html frontend/settings.html

不传参数时默认检查 frontend 下全部 .html（跳过 .backup_ 副本）。
写临时文件到系统临时目录，检查完即删；不修改项目文件。
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATTERN = re.compile(
    r"<script\b(?P<attrs>[^>]*)>(?P<body>.*?)</script>", re.IGNORECASE | re.DOTALL
)


def inline_blocks(html_text):
    """返回 [(起始行号, 脚本内容)]，跳过 src= 外链脚本。"""
    blocks = []
    for match in SCRIPT_PATTERN.finditer(html_text):
        if "src=" in match.group("attrs").lower():
            continue
        body = match.group("body")
        if not body.strip():
            continue
        line_no = html_text.count("\n", 0, match.start("body")) + 1
        blocks.append((line_no, body))
    return blocks


def check_file(path):
    html_text = path.read_text(encoding="utf-8")
    blocks = inline_blocks(html_text)
    if not blocks:
        print(f"{path.name}: 无内联脚本")
        return True

    ok = True
    for line_no, body in blocks:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".js", encoding="utf-8", delete=False
        ) as handle:
            handle.write(body)
            temp_path = Path(handle.name)
        try:
            result = subprocess.run(
                ["node", "--check", str(temp_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        finally:
            temp_path.unlink(missing_ok=True)

        if result.returncode == 0:
            print(f"{path.name}: 第{line_no}行起的脚本块 语法通过")
        else:
            ok = False
            print(f"{path.name}: 第{line_no}行起的脚本块 语法失败")
            print((result.stderr or result.stdout).strip())
    return ok


def main(argv):
    if argv:
        targets = [Path(arg) if Path(arg).is_absolute() else PROJECT_ROOT / arg for arg in argv]
    else:
        targets = sorted(
            path
            for path in (PROJECT_ROOT / "frontend").glob("*.html")
            if ".backup_" not in path.name
        )

    all_ok = True
    for path in targets:
        if not path.exists():
            print(f"{path}: 文件不存在")
            all_ok = False
            continue
        all_ok = check_file(path) and all_ok
    print("全部通过" if all_ok else "存在语法错误")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
