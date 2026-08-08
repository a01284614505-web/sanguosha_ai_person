╔══════════════════════════════════════════════════════════════╗
║           📁 数据文件夹使用说明                              ║
╚══════════════════════════════════════════════════════════════╝

## 📂 文件夹位置

```
/storage/emulated/0/Download/sanguosha/sanguosha_data/
```

你可以在任何文件管理器中找到这个文件夹（如ES文件浏览器、MT管理器等）

## 📋 目录结构

```
sanguosha_data/
├── docs/           # 📄 所有文档
│   ├── README.md
│   ├── QUICKSTART.md
│   ├── PROJECT_STATUS.txt
│   ├── NEW_FEATURES.txt
│   ├── RESOURCE_CHECKLIST.txt
│   ├── UPDATE_LOG.txt
│   └── FIXED.txt
│
├── scripts/        # 📜 脚本文件
│   ├── start.sh              (启动脚本)
│   ├── install.sh            (安装脚本)
│   ├── fix_network.sh        (网络修复)
│   ├── sync_to_download.sh   (同步脚本)
│   ├── test_server.py        (测试服务器)
│   └── test_server_simple.py (简化服务器)
│
├── data/           # 📊 游戏数据（你需要创建）
│   ├── heroes.json     (武将数据)
│   ├── cards.json      (卡牌数据)
│   └── skills.json     (技能数据)
│
└── worldbook/      # 📖 世界书（你需要创建）
    ├── rules.md         (游戏规则)
    ├── heroes_skills.md (武将技能详解)
    ├── cards.md         (卡牌详解)
    └── terms.md         (术语解释)
```

## 🔄 如何同步

### 自动同步（推荐）
在Termux中运行：
```bash
bash ~/sanguosha_tavern/sync_to_download.sh
```

会自动将所有文档和脚本复制到Download文件夹。

### 手动同步
你也可以手动复制文件到对应目录。

## 📝 如何使用

### 1. 查看文档
用任何文本编辑器打开 `docs/` 目录下的文件：
- **README.md** - 项目说明
- **QUICKSTART.md** - 快速开始指南
- **RESOURCE_CHECKLIST.txt** - 资源清单（重要！）
- **UPDATE_LOG.txt** - 更新日志

### 2. 编辑数据文件
在 `data/` 目录下创建和编辑游戏数据：

**heroes.json 示例：**
```json
[
  {
    "id": "caocao",
    "name": "曹操",
    "faction": "魏",
    "max_hp": 4,
    "skills": [
      {
        "name": "奸雄",
        "description": "当你受到伤害后，你可以获得造成伤害的牌。"
      }
    ]
  }
]
```

**cards.json 示例：**
```json
[
  {
    "id": "sha_spade_7",
    "name": "杀",
    "type": "基本",
    "suit": "黑桃",
    "rank": 7
  }
]
```

### 3. 编写世界书
在 `worldbook/` 目录下创建Markdown文件：

**rules.md** - 游戏规则说明
**heroes_skills.md** - 武将技能详解
**cards.md** - 卡牌效果说明
**terms.md** - 术语解释

## 🎯 你需要做的工作

### 高优先级
1. **收集武将头像**
   - 至少5个武将的图片
   - 放在项目的 `frontend/assets/heroes/` 目录
   
2. **编写基础数据**
   - 在 `data/heroes.json` 写5个武将
   - 在 `data/cards.json` 写30张基本牌

3. **编写简化规则**
   - 在 `worldbook/rules.md` 写基础规则
   - 不需要太详细，够AI理解即可

### 中优先级
4. 完善27将数据
5. 完善108张卡数据
6. 详细的世界书内容

### 低优先级
7. 卡牌图片
8. 背景图片
9. 音效资源

## 💡 编辑建议

### 推荐的编辑器
- **手机端**
  * MT管理器（支持语法高亮）
  * QuickEdit（轻量级）
  * Jota Text Editor
  
- **电脑端**（如果你用电脑）
  * VSCode
  * Sublime Text
  * Notepad++

### 编辑流程
1. 在文件管理器中打开 `sanguosha_data/data/`
2. 用文本编辑器打开 `heroes.json`
3. 按照示例格式编写数据
4. 保存文件
5. 将文件复制回项目目录（或重新运行同步脚本）

## 🔄 更新流程

当项目有更新时：
1. 运行同步脚本更新文档
2. 查看 `docs/UPDATE_LOG.txt` 了解新功能
3. 根据需要更新你的数据文件

## 📱 文件管理器访问

### 路径快捷方式
在大多数文件管理器中：
1. 打开 "内部存储" 或 "Internal Storage"
2. 进入 "Download" 文件夹
3. 进入 "sanguosha" 文件夹
4. 进入 "sanguosha_data" 文件夹

### 直接输入路径
在文件管理器的地址栏输入：
```
/storage/emulated/0/Download/sanguosha/sanguosha_data
```

## ⚠️ 注意事项

1. **编码格式**
   - 所有JSON文件使用UTF-8编码
   - 所有Markdown文件使用UTF-8编码
   
2. **JSON格式**
   - 严格遵守JSON语法
   - 注意逗号、引号、括号
   - 可以用在线JSON验证工具检查
   
3. **文件同步**
   - 修改Download目录的文件后
   - 需要手动复制回项目目录
   - 或者直接在项目目录编辑

## 🔗 相关命令

### 查看文件列表
```bash
ls -lh /storage/emulated/0/Download/sanguosha/sanguosha_data/docs/
```

### 编辑文件（Termux）
```bash
micro /storage/emulated/0/Download/sanguosha/sanguosha_data/data/heroes.json
```

### 同步文件
```bash
bash ~/sanguosha_tavern/sync_to_download.sh
```

### 复制回项目
```bash
cp /storage/emulated/0/Download/sanguosha/sanguosha_data/data/*.json ~/sanguosha_tavern/data/
```

## 📞 获取帮助

如果遇到问题：
1. 查看 `docs/QUICKSTART.md`
2. 查看 `docs/RESOURCE_CHECKLIST.txt`
3. 查看项目的README文档

═══════════════════════════════════════════════════════════════
     现在你可以在文件管理器中方便地查看和编辑所有文件了！
═══════════════════════════════════════════════════════════════
