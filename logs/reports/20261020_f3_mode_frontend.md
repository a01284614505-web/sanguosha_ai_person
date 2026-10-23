# F3 模式前端接线与浏览器验收

日期：2026-10-20 UTC。范围：`frontend/**`、F3 手工浏览器脚本、B2 浏览器脚本的可选真实 API 模式；未改后端、路线图或既有计划文件。真实运行使用隔离 HTTP/WS 端口 18888/18889，未停止或修改原有 8888/8889 进程。

## 实现

- 大厅经 WebSocket `server_info` 同时读取 `supported_modes` 和 `modes`，仅展示两者都确认的已注册模式。斗地主随服务端注册自动显示，客户端不维护“是否开放”的静态清单。
- 按 `mode.ai_count` 展示 AI 座位、生成开局配置，并按最大 AI 数向 `/api/ai-players?count=N` 请求档案。保留原四名 AI 档案、配置、称号和座次；未能读取额外档案时使用服务端接受的 `ai_5`…`ai_7` 默认身份，不把未知的本地 ID 传给后端。
- 身份卡只在暗身份胜负模式显示；身份池徽记由后端 `identity_pool` 生成。2v2 和斗地主显示公开队伍标识及结算中的“你的队伍”。结算支持 A/B 队、地主/农民赢家文案。
- WebSocket 端口由页面 HTTP 端口推导为相邻端口（标准 HTTP 80/443 仍使用 8889），支持隔离端口的真实浏览器检查。

## 真实浏览器结果

命令：

```bash
PLAYWRIGHT_MODULE=/tmp/ui-check-playwright/node_modules/playwright \
PLAYWRIGHT_EXECUTABLE_PATH=/root/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome \
F3_BASE_URL=http://127.0.0.1:18888 \
node scripts/manual/f3_modes_browser_check.cjs
```

隔离服务以临时包装脚本启动，对本进程模块常量覆盖 `HTTP_PORT=18888`、`WS_PORT=18889`，历史/日志放在 `/tmp/f3-isolated/`：

```bash
F3_HTTP_PORT=18888 SANGUOSHA_HISTORY_PATH=/tmp/f3-isolated/history.json \
SANGUOSHA_GAME_LOG_DIR=/tmp/f3-isolated/logs PYTHONPATH=. \
python3 /tmp/start_f3_isolated_server.py
```

退出码 **0**，`F3_MODES_BROWSER_OK`，390×844，每种模式均通过真实开局 WebSocket、真实结束对局并返回大厅：

| 模式 | AI 席 | 实际玩家数 | 结果 |
|---|---:|---:|---|
| 5人身份局 | 4 | 5 | `create_game → game_created → game_state`、结束、返回大厅通过 |
| 8人身份局 | 7 | 8 | `create_game → game_created → game_state`、结束、返回大厅通过 |
| 2v2 | 3 | 4 | `create_game → game_created → game_state`、结束、返回大厅通过；身份卡隐藏，公开队伍显示 |
| 斗地主 | 2 | 3 | `create_game → game_created → game_state`、结束、返回大厅通过；身份卡隐藏，公开队伍显示 |

四次对局的 WS 端口均为 **18889**；脚本输出每局实际 `game_id` 及提交的 AI 数，均与 `mode.ai_count` 一致。原 **8888/8889** 进程未停止、未接收这些验收对局。

浏览器另用明确标注的结算页面数据检查 2v2 的“A队获胜（2v2公开队伍）”与斗地主的“农民获胜（斗地主公开队伍）”及“你的队伍”文案；对局本身用真实 WebSocket 开局/结束，不通过假消息推进。无页面 JS 错误或手机横向溢出。

## B2 真实 API

浏览器测试脚本可设 `CERTIFICATION_REAL_API=1` 跳过 fixture，直接读取指定 `UI_BASE_URL` 的认证 API。使用隔离服务执行：

```bash
PLAYWRIGHT_MODULE=/tmp/ui-check-playwright/node_modules/playwright \
PLAYWRIGHT_EXECUTABLE_PATH=/root/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome \
UI_BASE_URL=http://127.0.0.1:18888 CERTIFICATION_REAL_API=1 \
node scripts/manual/skill_certification_browser_check.cjs
```

退出码 **0**，`SKILL_CERTIFICATION_REAL_API_OK`：临时服务 API 返回 `success=true`、`current=true`、10 项技能证据均渲染；范围/分支缺口、规则版本提示、390×844 无溢出、0 页面错误。该检查只呈现接口当前指纹状态，不依赖 fixture 的过期切换与 XSS 样本。

## 静态检查

```bash
python3 scripts/check_frontend_js.py && \
node --check scripts/manual/f3_modes_browser_check.cjs && \
node --check scripts/manual/skill_certification_browser_check.cjs && \
git diff --check
```

退出码 **0**。完整浏览器 JSON 输出来自上述命令，可再次运行复验。
