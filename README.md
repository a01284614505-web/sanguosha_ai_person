# AI三国杀酒馆

一个自托管的三国杀游戏服务器：用浏览器打开即玩，AI 对手由你自己的 API Key 驱动（8 家 Provider 可选），没有 Key 时自动回退规则 AI。

## 项目状态

最近批次（2026-10-18）：Stage 8 武将 DSL 与导入管线已实现，验收记录见 `logs/handover/`。

- ✅ 引擎与规则：5 人身份局完整流程；27 将 / 54 技能；标准牌堆 108 张 / 军争 53 张 / 合并 161 张可切换
- ✅ 真人交互：弃牌阶段自己选；过河拆桥 / 顺手牵羊 / 五谷丰登由你选牌（他人手牌隐藏、装备与判定区明牌，被拆的牌明牌展示）
- ✅ 真实结算统计：伤害 / 承伤 / 治疗 / 击杀 / 出牌 / 失牌 / 技能发动 + MVP，随结算页展示
- ✅ WebSocket 协议单一真相源（`protocol.py` 生成前端 `protocol.js`）
- ✅ 自定义武将包导入、启禁、将池与世界书生成；技能 DSL 有 active/partial/data_only 门控
- ✅ DSL 沙箱与 5 项 Python 等价测试；33/54 项可表达声明见 [覆盖清单](data/skill_dsl_coverage.json)
- ⏳ 武器 / 防具特效、服务端战绩持久化 —— 见 [ROADMAP.md](ROADMAP.md)

## 快速开始

> 常用命令（安装、启动、更新、停止、排错）都整理在 **[COMMANDS.md](COMMANDS.md)**，可直接复制粘贴。

### Windows（开发）

```powershell
pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File start_windows.ps1              # 前台
powershell -ExecutionPolicy Bypass -File start_windows.ps1 -Background # 后台
powershell -ExecutionPolicy Bypass -File start_windows.ps1 -Action stop
```

### 通用（Termux / Linux）

```bash
pip install -r requirements.txt
python -u game_server.py
```

浏览器打开 `http://localhost:8888`（HTTP 8888 提供页面，WebSocket 8889 负责对局）。
在大厅配置玩家名与各座位 AI（Provider / 模型 / API 地址 / Key；Key 留空的座位使用规则 AI）。

## 项目结构

```text
sanguosha_data/
├── game_server.py          # 服务器：HTTP 静态服务 + WebSocket 消息泵（不含规则）
├── game_engine/            # 引擎（唯一规则来源）
│   ├── main_engine.py      # 对局主循环、交互原语与选择复核
│   ├── phase_controller.py # 回合六阶段
│   ├── card_system.py      # 卡牌效果
│   ├── card_table.py       # 42 种牌单一牌表
│   ├── rules_engine.py     # 规则校验与合法操作
│   ├── skill_manager.py    # 技能统一调度及 active DSL 接线
│   ├── skill_dsl.py        # 受限 JSON DSL 编译与运行
│   ├── hero_package_store.py # 导入包、校验、备份与恢复
│   ├── skills_{wei,shu,wu,qun}.py
│   ├── state_manager.py    # 状态管理与序列化
│   ├── identity_system.py  # 身份分配与胜负
│   ├── deck_manager.py     # 牌堆加载与切换
│   ├── game_stats.py       # 真实对局统计（7 项指标 + MVP）
│   ├── ai_decision.py      # 多 Provider 决策与会话缓存
│   └── protocol.py         # 协议单一真相源（生成前端 protocol.js）
├── frontend/               # 原生 HTML/CSS/JS（纯 UI）
│   ├── index.html          # 大厅
│   ├── select_hero.html    # 选将
│   ├── game.html           # 对局
│   ├── result.html         # 结算（真实统计 + MVP）
│   ├── settings.html       # 设置（牌堆切换、全局设置、数据状态）
│   ├── hero_manager.html   # 武将包导入、编辑、启用与禁用
│   ├── handbook.html       # 图鉴（42 种卡牌说明 + 27 将技能）
│   ├── js/                 # protocol.js(生成) / ws_client.js / sgs_common.js / card_info.js /
│   │                       # lobby.js / select_hero.js / game_main.js /
│   │                       # chat_panel.js(席间聊天+战报) / result.js / settings_page.js
│   └── css/                # sgs.css(公共主题) / pages.css / game.css（main.css 仅 hero_manager 使用）
├── data/                   # heroes.json / skills.json / deck_*.json 与本机导入包
├── scripts/                # gen_protocol_js.py / check_frontend_js.py / manual/ 冒烟
├── tests/                  # pytest 回归与 Stage 8 专项
├── logs/                   # CHRONICLE 编年史 / handover 交接 / runtime 日志 / reports 报告
└── worldbook*, wujiang/    # 世界书与原始数据（供 AI 理解，不参与规则执行）
```

## 测试与验收

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python scripts/verify_project.py  # pytest、前端 JS、协议同步、两项 WS 冒烟
```

## 架构与约定

- **引擎自驱**：回合推进与结算全在引擎；服务器只转发消息；前端只渲染与采集输入。详见 [ARCHITECTURE.md](ARCHITECTURE.md)。
- **服务端复核一切**：真人只从引擎下发的合法候选中选择，提交的数量、牌区、重复、过期与收摊状态都会被引擎复核，非法输入不落地。
- **隐藏信息不越界**：他人手牌只下发占位，AI 决策不按牌面值评估隐藏手牌。
- **统计在真实状态变化点记录**：口径见 `game_engine/game_stats.py`，不在 UI 层计算。
- **自定义技能声明**：受限结构、效果白名单和限制说明见 [SKILL_DSL.md](SKILL_DSL.md)。33 项覆盖清单证明可编译表达性，5 项 parity 测试单独验证与 Python 行为等价；二者口径不同。

## 相关文档

- [ARCHITECTURE.md](ARCHITECTURE.md) — 架构与当前功能边界
- [ROADMAP.md](ROADMAP.md) — 开发路线图与下一步
- [logs/CHRONICLE.md](logs/CHRONICLE.md) — 编年史与交接索引

## 技术栈

- **后端**：Python 3.12 + `websockets`（HTTP 静态服务使用标准库）+ `httpx`（AI 调用）
- **前端**：原生 HTML / CSS / JavaScript，零框架
- **部署**：Windows / Linux / Android Termux

## 许可

项目用于个人学习和娱乐。
