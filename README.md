# AI三国杀酒馆

一个运行在Android Termux上的三国杀游戏服务器，通过手机浏览器游玩，所有AI对手由用户自己的API Key驱动。

## 项目状态

🚧 **开发中** - 前端框架已完成，游戏引擎开发中

## 已完成

- ✅ 前端HTML页面（大厅、选将、游戏、结算）
- ✅ 前端CSS样式（响应式布局，适配手机）
- ✅ WebSocket通信框架
- ✅ 游戏状态渲染系统
- ✅ UI交互控制
- ✅ 聊天系统
- ✅ 测试服务器（返回模拟数据）

## 待实现

- ⏳ 游戏引擎核心
- ⏳ 规则系统
- ⏳ 武将技能系统
- ⏳ AI决策系统
- ⏳ 多AI Provider适配

## 快速开始

### 1. 安装依赖

```bash
pkg install python
pip install fastapi uvicorn[standard] websockets
```

### 2. 启动测试服务器

```bash
cd ~/sanguosha_tavern
python test_server.py
```

### 3. 打开浏览器

在手机浏览器访问: `http://localhost:8000`

## 项目结构

```
sanguosha_tavern/
├── frontend/              # 前端文件
│   ├── index.html        # 大厅页面
│   ├── select_hero.html  # 选将页面
│   ├── game.html         # 游戏主界面
│   ├── result.html       # 结算页面
│   ├── css/              # 样式文件
│   │   ├── main.css      # 主样式
│   │   ├── game.css      # 游戏布局
│   │   └── cards.css     # 卡牌样式（占位符）
│   ├── js/               # JavaScript文件
│   │   ├── ws_client.js  # WebSocket客户端
│   │   ├── lobby.js      # 大厅逻辑
│   │   ├── select_hero.js # 选将逻辑
│   │   ├── game_render.js # 状态渲染
│   │   ├── ui_controls.js # UI控制
│   │   ├── chat.js       # 聊天系统
│   │   └── result.js     # 结算页面
│   └── assets/           # 资源文件
│       └── heroes/       # 武将图片（待添加）
├── game_engine/          # 游戏引擎（待实现）
├── test_server.py        # 测试服务器
└── README.md
```

## 前端功能

### 大厅页面
- 4种模式选择（5人身份局、8人身份局、2v2、斗地主）
- AI配置（名称、Provider、模型、温度、思考模式）
- 身份卡系统
- 聊天开关

### 选将页面
- 武将列表展示
- 武将选择
- 倒计时
- 其他玩家选择状态

### 游戏主界面
- 对手信息区（头像、体力、手牌数、装备）
- 桌面中央区（牌堆、弃牌堆、事件日志）
- 聊天区（可折叠）
- 玩家区（手牌、装备、操作按钮）
- 目标选择系统
- 游戏菜单

### 结算页面
- 胜负展示
- 游戏统计
- MVP信息
- 身份揭示
- 连胜奖励

## 样式说明

### 占位符内容
目前卡牌和武将使用的是占位符样式，需要用户后续添加：
- 武将图片放在 `frontend/assets/heroes/` 目录
- 卡牌样式在 `frontend/css/cards.css` 中自定义
- 可以添加动画效果和特效

### 颜色主题
- 主色调：红色 `#c41e3a`
- 背景：深色渐变
- 支持自定义CSS变量

## 下一步

1. 实现游戏引擎核心（状态管理、规则验证）
2. 实现卡牌系统
3. 实现武将技能系统
4. 接入AI API
5. 完善前端资源

## 技术栈

- **前端**: 原生HTML/CSS/JavaScript
- **后端**: FastAPI + WebSocket
- **部署**: Android Termux

## 许可

项目用于个人学习和娱乐。
