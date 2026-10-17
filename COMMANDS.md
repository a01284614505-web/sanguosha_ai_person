# 常用命令速查

每个灰色代码块都可以整块复制粘贴。`#` 开头的是说明，粘进终端也不会执行。

- 手机：在 **Termux** 里运行，服务器就跑在手机上。
- 电脑：在 **PowerShell** 里运行（Windows）。

下面默认项目放在 `~/sanguosha_ai_person`（手机）或你自己克隆的位置（电脑）。

---

## 一、手机 Termux

### 第一次安装（只做一次）

```bash
# 更新软件源并安装 git 和 Python
pkg update
pkg install git python

# 把项目克隆到主目录
cd ~
git clone https://github.com/a01284614505-web/sanguosha_ai_person.git

# 进入项目，安装依赖
cd ~/sanguosha_ai_person
pip install -r requirements.txt
```

### 每次开玩

```bash
# 进入项目目录
cd ~/sanguosha_ai_person

# 拉取最新代码
git pull

# 防止切到别的 App 时安卓把 Termux 杀掉（断线重连要靠它）
termux-wake-lock

# 启动服务器，看到 "HTTP: http://localhost:8888" 就成功了
python game_server.py

# 然后在手机浏览器打开：http://127.0.0.1:8888
```

### 停止服务器

```bash
# 在运行服务器的 Termux 窗口里按 Ctrl+C（Termux 键盘上方的 CTRL 键 + C）

# 如果窗口已经关了、服务器还在后台占着端口，用这条结束它
pkill -f game_server.py

# 玩完后释放唤醒锁（省电）
termux-wake-unlock
```

### 后台运行（关掉 Termux 窗口也继续跑）

```bash
cd ~/sanguosha_ai_person
termux-wake-lock

# 在后台启动，输出写进 server.log
nohup python game_server.py > server.log 2>&1 &

# 实时查看服务器输出（按 Ctrl+C 退出查看，不会停掉服务器）
tail -f server.log

# 停止后台服务器
pkill -f game_server.py
```

---

## 二、电脑 PowerShell（Windows）

### 第一次安装（只做一次）

```powershell
# 克隆项目（会在当前目录下新建 sanguosha_ai_person 文件夹）
git clone https://github.com/a01284614505-web/sanguosha_ai_person.git

# 进入项目，安装依赖
cd sanguosha_ai_person
pip install -r requirements.txt
```

### 每次开玩

```powershell
# 进入项目目录（换成你自己的路径）
cd 你的路径\sanguosha_ai_person

# 拉取最新代码
git pull

# 启动服务器（前台运行，关掉窗口就停）
python game_server.py

# 浏览器打开：http://127.0.0.1:8888
```

### 用启动脚本（可后台运行）

```powershell
# 前台启动
powershell -ExecutionPolicy Bypass -File start_windows.ps1

# 后台启动
powershell -ExecutionPolicy Bypass -File start_windows.ps1 -Background

# 查看是否在运行
powershell -ExecutionPolicy Bypass -File start_windows.ps1 -Action status

# 重启（改了代码或 git pull 之后用）
powershell -ExecutionPolicy Bypass -File start_windows.ps1 -Action restart

# 停止
powershell -ExecutionPolicy Bypass -File start_windows.ps1 -Action stop
```

### 手机连电脑上的服务器

```powershell
# 查电脑的局域网 IP，看 "IPv4 地址" 那一行，一般是 192.168.x.x
ipconfig

# 手机和电脑连同一个 Wi-Fi，手机浏览器打开：http://电脑的IP:8888
# 第一次运行时 Windows 防火墙弹窗要点“允许”，否则手机连不上
```

---

## 三、Git 常用（手机、电脑通用）

```bash
# 拉取最新代码（最常用）
git pull

# 看本地有没有改动、当前在哪个分支
git status

# 看最近 10 次提交
git log --oneline -10

# 切回主分支（平时就待在 main 上）
git checkout main

# 列出所有远程分支
git branch -r

# 试玩某个还没合并的分支（把分支名换成实际的，例如 feat/xxx）
git fetch origin
git checkout 分支名

# 试完回到主分支
git checkout main
```

### git pull 失败时

```bash
# 报错说本地有改动、拒绝覆盖：先看看改了什么
git status
git diff

# 确定这些改动不要了，丢弃全部本地改动（不可恢复，慎用）
git checkout -- .

# 再拉取
git pull

# 想保留本地改动、先放一边再拉取
git stash
git pull
# 需要时把改动拿回来
git stash pop
```

---

## 四、依赖与检查

```bash
# 代码更新后提示缺少模块时，重新安装依赖
pip install -r requirements.txt

# 看 Python 版本
python --version

# 一键完整检查（测试 + 前端语法 + 协议同步 + 联机冒烟）
# 需要先安装开发依赖
pip install -r requirements-dev.txt
python scripts/verify_project.py

# 只跑测试
python -m pytest -q

# 30 局规则 AI 自动对局回归（约 1 分钟）
python -m scripts.verify_b7_games
```

---

## 五、常见问题

```bash
# 启动时报“端口被占用 / Address already in use”：上次的服务器还没关
# 手机 Termux：
pkill -f game_server.py
# 电脑 PowerShell（脚本启动的）：
#   powershell -ExecutionPolicy Bypass -File start_windows.ps1 -Action stop

# 浏览器显示旧界面：服务器已更新但页面有缓存
# 关掉标签页重新打开，或在浏览器里强制刷新

# 改了代码 / git pull 之后没生效：要先停掉服务器再重新启动
# （Ctrl+C 停止，然后再 python game_server.py）
```

---

## 六、数据文件在哪

```bash
# 战绩、连胜、身份卡（服务器端，删掉等于清空战绩）
#   logs/runtime/game_history.json

# 每局的对局日志（也可以在游戏的“日志”页里查看和删除）
#   logs/runtime/game_logs/

# 备份战绩（手机 Termux，在项目目录下执行）
cp logs/runtime/game_history.json ~/game_history_备份.json

# 查看保存了多少局日志
find logs/runtime/game_logs -name "*.json" | wc -l
```
