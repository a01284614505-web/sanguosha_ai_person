#!/usr/bin/env python3
"""从 game_engine/protocol.py 生成 frontend/js/protocol.js。

生成结果带「自动生成，勿手改」头部；`tests/test_protocol_sync.py` 断言
已提交的 protocol.js 与重新生成内容一致，防止协议漂移。
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "frontend" / "js" / "protocol.js"


def _class_members(cls) -> dict:
    return {k: v for k, v in vars(cls).items()
            if isinstance(v, str) and not k.startswith("__")}


def generate_js() -> str:
    sys.path.insert(0, str(PROJECT_ROOT))
    from game_engine import protocol

    def obj(name: str) -> str:
        cls = getattr(protocol, name)
        entries = ", ".join(f"  {k}: {json.dumps(v, ensure_ascii=False)}"
                            for k, v in _class_members(cls).items())
        return f"  {name}: {{\n{entries}\n  }}"

    providers_js = json.dumps(protocol.PROVIDERS, ensure_ascii=False, indent=2)
    return (
        "// 自动生成，勿手改。来源：game_engine/protocol.py，由 scripts/gen_protocol_js.py 生成。\n"
        "'use strict';\n"
        "const Protocol = {\n"
        f"  VERSION: {json.dumps(protocol.PROTOCOL_VERSION)},\n"
        f"{obj('INBOUND')},\n"
        f"{obj('OUTBOUND')},\n"
        f"  PROVIDERS: {providers_js},\n"
        "};\n"
        "if (typeof module !== 'undefined' && module.exports) module.exports = Protocol;\n"
    )


def main() -> int:
    text = generate_js()
    OUTPUT_PATH.write_text(text, encoding="utf-8")
    print(f"已生成 {OUTPUT_PATH}（{len(text)} 字节）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
