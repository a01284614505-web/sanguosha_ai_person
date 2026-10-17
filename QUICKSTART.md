# 快速开始

旧版说明（`start.sh`、8000 端口、`test_server.py`）已经过时。

请看 **[COMMANDS.md](COMMANDS.md)**：手机 Termux 和电脑 PowerShell 的安装、启动、更新、停止和常见问题，每条命令都能直接复制。

最短路径（手机 Termux）：

```bash
# 进入项目、拉最新代码、启动
cd ~/sanguosha_ai_person
git pull
termux-wake-lock
python game_server.py
# 浏览器打开 http://127.0.0.1:8888
```
