# AI 三国杀酒馆 · 项目架构
> 当前开发环境：Windows 10 / Python 3.12  
> 当前阶段：Stage 5 与 C 档重构 R0–R8 已完成；下一步 Stage 6A（交互原语层）
> 更新时间：2026-09-12
> 路线图见 [ROADMAP.md](ROADMAP.md)，现状事实基线见 [项目现状评估报告](logs/handover/20260912_2230_项目现状评估报告.md)
## 1. 架构铁律
```text
引擎自驱（全部游戏逻辑） / 服务器纯消息泵 / 前端纯 UI
```
- **引擎是唯一真理来源**：`game_engine/` 计算合法操作、复核选择并执行结算。
- **服务器只负责传输**：`game_server.py` 管理 HTTP/WebSocket、连接映射、消息转发及动画 ACK/Future；配置、武将、牌堆、结算和统计均经 `MainEngine` 门面决定。
- **前端只负责显示和输入**：`frontend/` 渲染引擎状态并提交用户选择，不自行决定规则合法性。
## 2. 当前结构
```text
sanguosha_data/
├── game_server.py              # HTTP 8888 + WebSocket 8889
├── start_windows.ps1           # Windows 开发启动器
├── requirements.txt            # Python 运行依赖
├── game_engine/
│   ├── main_engine.py          # 自驱主循环、输入等待、事件、序列化及服务器门面
│   ├── hero_registry.py        # data/heroes.json 权威武将注册表
│   ├── config_validator.py     # 开局配置与规则规范化
│   ├── state_manager.py        # 玩家、卡牌、牌堆与游戏状态
│   ├── rules_engine.py         # 合法性校验
│   ├── card_system.py          # 卡牌效果、响应链、伤害与濒死
│   ├── phase_controller.py     # 六阶段执行
│   ├── identity_system.py      # 身份分配与胜利判定
│   ├── deck_manager.py         # 真实牌堆注册、加载与切换
│   ├── ai_decision.py          # 多 Provider 决策与会话缓存
│   ├── chat_engine.py          # 聊天生成骨架
│   ├── skill_manager.py        # 技能注册与统一调度
│   ├── skill_runtime_core.py   # 技能运行时基础类型
│   ├── skills_generated.py     # 27 将技能定义
│   └── skills_{wei,shu,wu,qun}.py
├── frontend/
│   ├── index.html              # 大厅
│   ├── select_hero.html        # 选将
│   ├── game.html               # 对局页
│   ├── settings.html           # 设置页
│   ├── result.html             # 结算页
│   ├── hero_manager.html       # 武将数据管理页
│   ├── js/                     # 活跃前端逻辑（含 game_main.js / protocol.js / lobby.js）
│   ├── css/                    # 活跃样式（main.css + game.css）
│   └── assets/                 # 武将、卡牌和音频资产
├── data/                       # 武将、技能与真实牌堆 JSON
├── worldbook_generated/        # AI 世界书数据
├── tests/                      # 86 项 pytest 回归
├── scripts/                    # 检查、提取与手工工具
├── legacy_reference/           # 后续阶段仍有价值的历史参考
└── logs/
    ├── CHRONICLE.md            # 历史编年史与交接索引
    ├── handover/               # 方案与阶段交接
    └── runtime/                # 运行日志（不进 Git）
```
`event_bus.py`、`skill_system.py` 及未接线旧前端已在 R2 删除；技能事件由 `SkillManager` 调度。
## 3. 核心数据流
```text
浏览器选择/操作
    ↓ WebSocket 入站消息
GameServer 解码并调用 MainEngine
    ↓
MainEngine / RulesEngine / CardSystem / SkillManager
    ↓ 引擎事件
GameServer 转成 WebSocket 出站消息
    ↓
浏览器渲染状态、动画与响应面板
```
典型对局流程：
1. 前端发送 `create_game`，服务器构造 `MainEngine` 并启动 `run()`。
2. 引擎从权威注册表规范化武将、分配身份并持续发出状态和回合事件。
3. 真人只从 `your_turn` 或 `require_response` 给出的合法候选中选择。
4. `player_action` 进入 `MainEngine.submit_action()`，由引擎再次复核。
5. AI 从引擎候选中决策；规则 AI 或外部模型都不越过合法操作列表。
6. 引擎判定胜负并发出 `game_end`。
## 4. 当前 WebSocket 协议
> 本表记录 `game_server.py` 当前实际收发类型。R6 已收敛为 `protocol.py` 与自动生成的 `protocol.js`。
### 4.1 入站：前端 → 服务器（8 种）
| 类型 | 用途 |
|---|---|
| `create_game` | 创建对局并提交配置 |
| `player_action` | 提交出牌、结束阶段或场外响应 |
| `chat` | 提交真人聊天消息 |
| `card_animation_done` | 通知卡牌动画已播放完成 |
| `end_game` | 请求主动结束当前对局 |
| `update_ai_config` | 局内更新指定 AI 配置 |
| `ping` | 连接心跳 |
| `server_info` | 请求服务器能力信息 |
### 4.2 出站：服务器 → 前端（14 种）
| 类型 | 用途 |
|---|---|
| `pong` | 心跳响应 |
| `server_info` | 引擎、模式、武将和技能统计 |
| `game_created` | 对局创建回执 |
| `game_state` | 完整可见状态更新 |
| `your_turn` | 真人出牌阶段及合法候选 |
| `require_response` | 回合外响应请求及合法候选 |
| `action_result` | 真人操作执行结果 |
| `ai_action` | AI 回合或出牌展示 |
| `chat` | 真人或 AI 聊天消息 |
| `event_notification` | 游戏事件与动画通知 |
| `ai_config_updated` | AI 配置更新回执 |
| `end_game_accepted` | 主动结束请求回执 |
| `game_end` | 对局结束与结算状态 |
| `error` | 协议、配置或执行错误 |
## 5. 游戏与 AI 系统
### 游戏引擎
- 5 人身份局：主公 ×1、忠臣 ×1、反贼 ×2、内奸 ×1。
- 六阶段回合：准备、判定、摸牌、出牌、弃牌、结束。
- 牌堆由 `DeckManager.DECKS` 注册：标准 108 张、军争 53 张、合并 161 张。
- 场外响应经唯一响应通道处理，包含出闪、濒死求桃、无懈可击及技能转化。
- 无懈可击链不设人为深度上限，终止性由有限牌数保证。
### AI 决策
1. 引擎生成合法操作列表。
2. AI 使用外部 API 或规则脚本从列表中选择。
3. 引擎复核后执行，并把结果回灌到该 AI 的会话窗口。
4. 同一 AI 整局复用窗口；L0 全局层不含玩家专属内容，以提高跨玩家缓存命中。
Provider 清单以 `game_engine/protocol.py` 为单一来源，经 `/api/providers` 与生成的 `protocol.js` 下发；大厅读取 `default_url` / `default_model`。
### 日志与缓存统计轮转
- 引擎全部 `print` 已迁移至 `logging`（模块级 `logger = logging.getLogger(__name__)`）；正常流程 `INFO`，拒绝/未实现/异常路径 `WARNING`/`ERROR`。
- `game_server.py` 在 `__main__` 调用 `configure_logging()`（`basicConfig(stream=sys.stdout, force=True)`）。服务器自身的连接/错误横幅仍用 `print`，不在引擎日志范围内。
- AI 会话缓存统计写入 `logs/ai_cache_stats.jsonl` 前先做 5 MiB 轮转：超阈值即用可排序时间戳命名为 `ai_cache_stats.YYYYMMDD_HHMMSS.jsonl`（冲突追加只读序号 `.N`）归档，`os.replace` 原子替换，不清理旧档。
## 6. 开发与验证
```powershell
# 后台启动
powershell -ExecutionPolicy Bypass -File start_windows.ps1 -Action start -Background
# 状态 / 停止
powershell -ExecutionPolicy Bypass -File start_windows.ps1 -Action status
powershell -ExecutionPolicy Bypass -File start_windows.ps1 -Action stop
```
浏览器访问：`http://127.0.0.1:8888/`  
WebSocket：`ws://127.0.0.1:8889`
```bash
# 完整回归（Windows Git Bash 需固定 UTF-8 输出）
PYTHONIOENCODING=utf-8 python -m pytest -q --tb=no -p no:cacheprovider
# 前端内联与外部 JavaScript 语法检查
python scripts/check_frontend_js.py
```
## 7. 已知边界与后续阶段
> 逐项事实核定（含实测输出与代码行号）见 [项目现状评估报告](logs/handover/20260912_2230_项目现状评估报告.md)；分阶段计划见 [ROADMAP.md](ROADMAP.md)。
### 7.1 重构阶段（已完成）
- R4：Python 包化与 import 统一（已完成）。
- R5：服务器去逻辑化（已完成，`game_server.py` 249 行）。
- R6：协议、Provider、牌表与序列化单一真相源（已完成；`protocol.py` + `CARD_TABLE` + `card_to_dict`，前端经 `gen_protocol_js.py` 生成同步）。
- R7：拆分 `game.html`、样式变量化并接线武将头像（已完成；`game.html` 79 行纯结构 + `css/game.css` + `js/game_main.js`，回归 83）。
- R8：日志机制与重构总交接（已完成；引擎 84 处 `print` → `logging`，缓存统计 5 MiB 轮转，回归提升至 86）。
### 7.2 当前功能边界（2026-09-12 实测核定）
| 领域 | 状态 |
|---|---|
| 模式 | 只支持 5 人身份局（`config_validator.py:29`、`identity_system.py:19` 硬阻断） |
| 基本牌 | 4/4 |
| 锦囊 | 6/15 已实现 + 无懈可击（响应）；8 张标 `usage="unimplemented"`，不会进 `available_actions` |
| 装备 | 0/23 效果；武器射程表暂硬编码于 `state_manager.py:88`，待收回 `card_table.py` |
| 距离系统 | 已实现（座位环距 + 马匹修正 + 技能 `modify_distance`/`ignore_distance`） |
| 技能 | 54 个已注册且可执行，但除 `skills_qun.py:120` 外**全部为确定性自动结算，无发动/选目标/选牌询问** |
| 弃牌阶段 | 引擎按 `CARD_TABLE.discard_keep_score` 自动弃，真人不可选 |
| 结算统计 | 引擎不产出 kills/damage/healing/MVP，`result.js` 的 MVP 区块不渲染 |
| 托管 | CHRONICLE 13.5.3 四种来源只实现第 4 种（规则脚本兜底） |
| 武将导入 | `hero_manager.html` 为 UI 空壳，后端无导入 API |
### 7.3 下一阶段
**Stage 6A 交互原语层**（硬前置）：把 `MainEngine.request_response` 泛化为 `ask_confirm` / `ask_choose_players` / `ask_choose_cards` / `ask_choose_option` 四原语，并让弃牌阶段改真人手选。施工方案见 [Stage 6A](logs/handover/20260912_2245_Stage6A交互原语层施工方案.md)。

此后顺序：6C 牌面补全 → 6B 技能交互 → Stage 7 系统骨架 → Stage 8 武将 DSL → Stage 9 UI 与皮肤 → Stage 10 多模式 → Stage 11 打磨。
### 7.4 验收工具提示
`scripts/manual/ws_engine_smoke.py` 提交场外响应时缺 `type:"response"` 字段，会使每次响应等满 30 秒再落托管（`main_engine.py:438` 靠该字段路由）。请使用 `scripts/manual/ws_diag_smoke.py`（带动画 ACK 与消息统计）作为自驱冒烟入口。
当前完成状态以 `logs/handover/` 最新交接及真实测试输出为准；`logs/CHRONICLE.md` 的早期章节只代表当时记录。
