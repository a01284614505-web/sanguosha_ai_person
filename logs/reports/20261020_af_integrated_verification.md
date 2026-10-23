# A–F 当前可执行范围整合验证

日期：2026-10-20（UTC）。工作树：`/root/sanguosha_ai_person_integrated_20261019`。

执行：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. \
  /root/sanguosha_ai_person/.venv/bin/python scripts/verify_project.py
```

最终结果（退出码 0）：

- Python：909 passed，50 subtests passed（24.64s）。
- 前端 HTML 内联脚本与全部 JavaScript 语法检查通过。
- Python/JavaScript 协议生成同步通过。
- WebSocket diagnostic smoke：winner=rebel，`SMOKE_OK`。
- WebSocket engine smoke：winner=spy，非 aborted，`SMOKE_OK`。
- 总门槛：`VERIFY_OK`。

新增真实 Chromium 证据：技能试验台、本地皮肤、阵亡后三种生命周期、公开模型诊断和公开事件播放器，分别保存在同目录对应 `*_browser_check.log`。

范围限制：真实 Provider、Windows、Android/Termux 未在本机冒充验收；F3 新模式等待具体规则版本，F4 存档恢复等待状态序列化边界设计，F6 语音等待资源与体验预算。
