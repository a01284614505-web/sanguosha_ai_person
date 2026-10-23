# A/B/C 整合集成验证

日期：2026-10-20（UTC）。工作树：`/root/sanguosha_ai_person_integrated_20261019`。

执行命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/root/sanguosha_ai_person_integrated_20261019 \
  /root/sanguosha_ai_person/.venv/bin/python scripts/verify_project.py
```

结果（退出码 0）：

- Python：883 passed，50 subtests passed（23.26s）。
- 前端 JavaScript 检查全部通过，包含技能试验台脚本。
- 协议同步检查通过。
- WebSocket diagnostic smoke：winner=lord，`SMOKE_OK`。
- WebSocket engine smoke：收到 `game_end`，winner=lord，未异常中止，`SMOKE_OK`。
- 总门槛：`VERIFY_OK`。

本次只做离线与本地引擎验证；真实 Provider 连接、费用、延迟和缓存命中仍按计划单独验收。
