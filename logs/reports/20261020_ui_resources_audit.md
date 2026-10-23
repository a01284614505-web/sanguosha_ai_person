# UI 与皮肤资源审计

日期：2026-10-20 UTC。审计范围：整合工作树 P5 当前 UI、E4/E5 浏览器流程和 F1 皮肤资源可访问性。没有编辑后端、AI 决策、路线图或既有计划文档。工作区原有 `ROADMAP.md`、交接/计划文档未提交变更保持不动。

## F1：资源与映射

- 对 `/root` 可访问目录进行盘点后，没有发现独立的 379 张皮肤包或资源目录。工作树中的 `frontend/assets/heroes/` 只有 27 张内置默认武将图；没有将仓库副本或无关生成图片认作皮肤包。
- 27 个默认文件名与 `frontend/data/heroes.json` 中的 27 个项目英雄 ID 一一对应：每个 ID 恰好 1 张默认图。
- 资源包约定的映射缺口：`xuzhu` 映射项目 `xuchu`；`sunshangxiang` 在当前 27 将没有目标 ID；项目有 `zhangjiao`，资源包没有对应目录/条目。资源包本身未找到，因此无法核实这三项映射是否能在原始文件中匹配，也不声称 379 张已盘清。
- 增加 [skin_asset_inventory.py](../../scripts/manual/skin_asset_inventory.py)：默认只读扫描用户明确指定的目录，输出 JSON 文件清单、字节数、SHA-256、识别到的英雄 ID 及 379 数量对照。只有显式传入 `--copy-relative ... --dest ...` 才复制所选文件；拒绝越界路径、符号链接、非图片格式和覆盖已有文件，使用临时文件后原子改名。文件复制后仍需通过网页图片解码/尺寸/大小校验才能导入 IndexedDB。
- 现有 [本地皮肤页](../../frontend/skins.html) 已提供预览、检查、按需导入、绑定、恢复默认和删除；浏览器验收确认数据只存在当前设备的 IndexedDB。没有资源服务器或云同步接口需求。

可复跑的目录盘点命令：

```bash
python3 scripts/manual/skin_asset_inventory.py frontend/assets/heroes
```

结果：27 个文件、27 个英雄各 1 张、未映射数 0、`expected_count_match=false`（27 ≠ 379）。这是默认头像盘点，不是外部资源包盘点。

## E4/E5：P5 当前页面浏览器核验

| 页面/流程 | 证据 | 结果 |
|---|---|---|
| 大厅 | `browser_check.cjs`，390×844，真实身份卡选择/取消、档案和大厅状态 | 10 pass，0 fail |
| 历史 | 同上，真实页面加载 | 1 pass；预置战绩项因使用新档案跳过；无 JS 错误 |
| 选将/牌桌 | `browser_check.cjs` 从大厅开局、点选刘备并进入牌桌 | 真正进入五座位对局；真人回合、技能选择和取消、手牌选择、结束出牌、座位信息、托管设置均通过。取消技能交互通过；本次真人回合未出现可取消服务端请求，因此该项脚本按约定跳过，没有伪造合法状态。 |
| 牌桌手机交互 | 同一对局流程，390×844 | 20 pass，0 fail，1 个上述合法取消请求跳过，无浏览器运行错误 |
| 结算 | 新增 `result_page_browser_check.cjs`，1280×900 与 390×844 | 无战绩回退、战绩统计、身份卡奖励、日志链接通过；手机页面宽度无横向溢出 |
| 阵亡/后台/观战 | `post_death_browser_check.py` | 观战只读、刷新恢复、后台结算通知、等待正式结算通过 |
| 重连待操作恢复 | 新增 `reconnect_pending_browser_check.cjs`，390×844 | 刷新后重复正常 resume 握手；相同请求 ID、两项候选和取消按钮恢复；0 JS 错误。使用受控 WebSocket 消息验证前端恢复显示，不代替服务端断连集成测试。 |
| 公开事件复盘 | `timeline_player_browser_check.py` | 有序播放控件、键盘、速度、暂停、旧格式/空事件数据通过 |
| 本地皮肤 | `local_skins_browser_check.py` | 导入/绑定/刷新持久化、损坏图片和超限文件拒绝、恢复默认、删除映射通过 |

没有发现明确的 P5 页面缺陷需要修正；本次新增两个可复用手工浏览器脚本与资源盘点脚本。该核验不覆盖完整手机长局滚动压力、真实弱网/断网恢复时延，也不声称已测量动画 ACK 的延迟分布。

## 本次命令与退出码

- `python3 scripts/check_frontend_js.py` — **0**，所有页面内联脚本及前端 JavaScript 语法检查通过。
- `PLAYWRIGHT_MODULE=/tmp/b4-browser-check/node_modules/playwright PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /root/sanguosha_ai_person/.venv/bin/python scripts/manual/ai_smart_browser_check.py` — **1**，启动失败：该 Python 虚拟环境没有 `playwright` 包。对应当前 P5 移动大厅/历史/实际开局流程改由 Node Playwright `browser_check.cjs` 覆盖。
- `PLAYWRIGHT_MODULE=/tmp/b4-browser-check/node_modules/playwright BC_GROUPS=lobby,history BC_VIEWPORT=390x844 BC_TURN_WAIT_MS=10000 BC_OUT_DIR=/tmp/luna-ui-browser PYTHONDONTWRITEBYTECODE=1 node scripts/manual/browser_check.cjs` — **0**。
- `PLAYWRIGHT_MODULE=/tmp/b4-browser-check/node_modules/playwright BC_GROUPS=game BC_VIEWPORT=390x844 BC_TURN_WAIT_MS=15000 BC_OUT_DIR=/tmp/luna-ui-browser PYTHONDONTWRITEBYTECODE=1 node scripts/manual/browser_check.cjs` — **0**。
- `PLAYWRIGHT_MODULE=/tmp/b4-browser-check/node_modules/playwright PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /root/sanguosha_ai_person/.venv/bin/python scripts/manual/local_skins_browser_check.py` — **0**，`LOCAL_SKINS_BROWSER_OK`。
- `PLAYWRIGHT_MODULE=/tmp/b4-browser-check/node_modules/playwright PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /root/sanguosha_ai_person/.venv/bin/python scripts/manual/post_death_browser_check.py` — **0**，`POST_DEATH_BROWSER_OK`。
- `PLAYWRIGHT_MODULE=/tmp/b4-browser-check/node_modules/playwright PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /root/sanguosha_ai_person/.venv/bin/python scripts/manual/timeline_player_browser_check.py` — **0**，`TIMELINE_PLAYER_BROWSER_OK`。
- `PLAYWRIGHT_MODULE=/tmp/b4-browser-check/node_modules/playwright node scripts/manual/result_page_browser_check.cjs` — **0**，`RESULT_PAGE_BROWSER_OK`。
- `PLAYWRIGHT_MODULE=/tmp/b4-browser-check/node_modules/playwright node scripts/manual/reconnect_pending_browser_check.cjs` — **0**，`RECONNECT_PENDING_BROWSER_OK`。

手工浏览器脚本使用隔离历史和/或受控 WebSocket；未调用真实模型 Provider。B2 使用父任务新增的认证接口契约；该接口在当前监听进程中不可达，具体情况见下文。

## F6：浏览器内置语音播报

- `frontend/js/audio.js` 增加可选 `SpeechAnnouncer`，默认关闭，只处理公开事件 allowlist 中的技能发动/选择、阶段、摸牌、判定、弃牌和求救事件；播报使用公开消息字段，屏蔽聊天、决策轨迹及私人牌面事件，不读取麦克风或上传语音内容。
- 通过浏览器 `SpeechSynthesis` 提供本机 TTS；关闭时取消队列，异常静默忽略，事件 UI 流程不等待播报。语音列表取决于浏览器、操作系统和设备是否安装中文语音；若没有中文语音，交由浏览器选择系统默认声音，用户也可保持关闭。
- 全局设置中新增播报开关和设备依赖说明，默认关闭；设置窗在 390×844 下无横向溢出。
- `tts_browser_check.cjs` 以 mock speech synthesis 验证默认关闭、公开事件、非 allowlist 忽略、关闭取消、失败不影响事件流程。headless mock 只能验证调用与控制流，不证明设备实际发声或特定语音存在。

## B2：技能行为证据管理视图

- `hero_manager.html` 新增按技能展开的证据列表，呈现状态、scope、场景、测试数和 branch gaps，并标注内容指纹是否当前。
- 页面明确说明具名场景 parity 仅证明列出场景下 Python / DSL 实现一致，不等于规则正确、客户端版本一致或所有分支已认证；当 `rules_version_verified=false` 时显示醒目提示。渲染使用 `textContent`，不将证据字符串作为 HTML。
- `skill_certification_browser_check.cjs` 使用接口 fixture 核验当前/过期、逐项范围与分支缺口、false 规则标志、XSS 文本安全及 390×844 无横向溢出。接口 fixture 验证的是前端契约；本次没有完成运行中后端接口集成核验。
- 探测 `http://127.0.0.1:8888/api/heroes/certification` 返回 **404**，该端口当前由 `Python SimpleHTTP/0.6` 静态服务器占用；8889 对 HTTP 返回 **426**（WebSocket）。源代码中能看到路由，但当前运行进程未提供该 API，需由负责服务进程的任务确认真实 API host/启动方式后补集成核验。

## F6/B2 与扫描器复验命令

- `python3 scripts/check_frontend_js.py && node --check scripts/manual/tts_browser_check.cjs && node --check scripts/manual/skill_certification_browser_check.cjs && python3 -m py_compile scripts/manual/skin_asset_inventory.py && git diff --check` — **0**。
- `PLAYWRIGHT_MODULE=/tmp/ui-check-playwright/node_modules/playwright PLAYWRIGHT_EXECUTABLE_PATH=/root/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome node scripts/manual/tts_browser_check.cjs` — **0**，`TTS_BROWSER_OK`，390×844，0 page errors。
- `PLAYWRIGHT_MODULE=/tmp/ui-check-playwright/node_modules/playwright PLAYWRIGHT_EXECUTABLE_PATH=/root/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome node scripts/manual/skill_certification_browser_check.cjs` — **0**，`SKILL_CERTIFICATION_BROWSER_OK`，390×844，过期标记、范围/缺口、安全文本、规则提示通过，0 page errors。
- `python3 scripts/manual/skin_asset_inventory_symlink_check.py` — **0**，显式单文件复制为 **0** 并核对内容/SHA；中间层目录链接扫描/复制、图片文件链接扫描、目标目录链接复制均返回 argparse 拒绝 **2**。
- `curl -i --max-time 3 http://127.0.0.1:8888/api/heroes/certification` — **0**（curl 成功获得 HTTP 响应），响应状态 **404**，见上方接口集成限制。
