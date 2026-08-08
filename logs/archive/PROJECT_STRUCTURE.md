# 🏛️ AI三国杀酒馆 · 项目结构说明（v2.0 整理版）

> **整理日期**：2026-08-03
> **整理目的**：统一"两张皮"（Termux工作区 + Download备份）的目录结构，合并50+个分散日志。

---

## 📂 目录结构总览

```
~/sanguosha_tavern/  （Termux · 工作区 · 13MB）
│
├── game_engine/          # 游戏引擎核心（11个py文件）
│   ├── main_engine.py        # 主引擎
│   ├── state_manager.py      # 状态管理
│   ├── rules_engine.py       # 规则引擎
│   ├── card_system.py        # 卡牌系统
│   ├── phase_controller.py   # 阶段控制
│   ├── event_bus.py          # 事件总线
│   ├── skill_system.py       # 技能框架
│   ├── skills_generated.py   # 27将技能定义
│   ├── identity_system.py    # 身份系统
│   ├── ai_decision.py        # AI决策（8个Provider）
│   └── chat_engine.py        # 聊天引擎
│
├── frontend/             # 前端（纯UI）
│   ├── index.html            # 大厅
│   ├── select_hero.html      # 选将
│   ├── game.html             # 游戏主界面
│   ├── result.html           # 结算
│   ├── settings.html         # 设置
│   ├── js/                   # WebSocket/渲染/控制/聊天
│   ├── css/                  # 样式
│   └── assets/               # 武将图片/音效
│
├── data/                 # 游戏数据（JSON）
│   ├── heroes.json           # 武将数据
│   ├── cards.json            # 卡牌数据
│   ├── skills.json           # 技能数据
│   └── heroes_complete.json  # 完整武将
│
├── worldbook/            # 世界书（MD源文件）
├── worldbook_generated/  # 世界书（生成JSON）
│
├── websocket/            # WebSocket通信层
├── identity_cards/       # 身份卡系统
├── scripts/              # 工具脚本
│   ├── sync_to_download.sh   # ← 手动同步
│   ├── watch_sync.sh         # ← 自动监听同步
│   ├── game_server.py        # 服务器入口
│   ├── generate_skills.py    # 技能生成
│   └── test_*.py             # 测试脚本
│
├── tests/                # 测试（test_full_game.py等）
├── docs/                 # 正式文档
│   ├── 项目书.txt / 项目架构.md / 附录.txt
│   └── README / QUICKSTART / DEV_LOG
├── logs/                 # ★ 统一日志目录（新建）
│   ├── CHRONICLE.md          # ★ 开发编年史（合并43个日志）
│   └── server.log            # 服务器运行日志
│
├── archive/              # 归档（不删，只移走）
│   └── status_logs/          # ★ 43个原始状态日志
│
├── game_server.py        # 服务器入口
├── sync_to_download.sh   # 手动同步脚本
├── watch_sync.sh         # 自动同步脚本
├── start.sh / install.sh / fix_network.sh
└── server.log
```

---

## 🔄 同步机制（如何保持两边一致）

### 工作区（活的）
**Termux** `~/sanguosha_tavern/`

### 备份区
**Download** `/storage/emulated/0/Download/sanguosha/sanguosha_data/`

### 手动同步
```bash
cd ~/sanguosha_tavern
bash sync_to_download.sh     # 将全部代码/文档同步到 Download
```

### 自动监听同步
```bash
tmux new -s sync
bash ~/sanguosha_tavern/watch_sync.sh
# Ctrl+B 然后 D 脱离（后台运行）
```

---

## 📜 日志管理规则（新规）

1. **日常开发**：所有开发日志统一追加到 `logs/CHRONICLE.md`
2. **新增记录格式**：在对应章节末尾追加，标注日期时间
3. **不再创建** 散落的 `XXX_STATUS.txt`、`XXX_SUMMARY.txt` 等文件
4. **老日志**：已在 `archive/status_logs/` 中，供查阅

### 快速查找
```bash
# 查看编年史
cat ~/sanguosha_tavern/logs/CHRONICLE.md

# 查看原始日志
ls ~/sanguosha_tavern/archive/status_logs/
```

---

## ✅ 本次整理完成的工作

| 项目 | 状态 |
|------|------|
| 重写 `sync_to_download.sh`（补全目录同步） | ✅ |
| 创建 `logs/CHRONICLE.md`（合并43个日志） | ✅ |
| 归档49个散落txt到 `archive/status_logs/` | ✅ |
| 同步到Download侧 | ✅ |

---

## ⏳ 下一步开发（按优先级）

1. **聊天系统**：心跳触发 + 事件触发 + AI对话（当前0%）
2. **22将数据补全**：5/27 → 27/27
3. **技能系统**：事件总线绑定27将技能
4. **卡牌补全**：锦囊牌 + 装备牌效果
5. **多模式**：8人局 / 2v2 / 斗地主
