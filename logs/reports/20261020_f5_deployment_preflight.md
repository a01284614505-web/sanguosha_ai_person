# F5 跨平台部署预检查

日期：2026-10-20 UTC。本机是 Linux，以下仅为静态与本机入口检查，**不代表 Windows 或 Android/Termux 实机验收**。

## 本轮修正

- 新增 `start.sh` 作为仓库根目录的 Linux/Termux 入口；项目路径取脚本自身位置，支持 `SGS_PYTHON` 选择解释器，强制 UTF-8 输出；`--check` 只导入依赖，不占用端口。
- `start_windows.ps1` 优先使用项目 `.venv`/`venv`，再尝试现有 Python 3.12 路径及 PATH；不再只能在固定安装位置启动。
- README 的 Termux 命令与实际脚本一致，并指向最新功能台账。

## 已执行

```text
bash -n start.sh && SGS_PYTHON=/root/sanguosha_ai_person/.venv/bin/python ./start.sh --check
退出码 0；DEPENDENCIES_OK

command -v pwsh
无结果：本机没有 PowerShell，因此未把 Windows 语法或启动标为通过。
```

## 目标环境仍需执行

1. Windows：在真实 PowerShell 运行 `start_windows.ps1 -Action start -Background` / `status` / `stop`，完成浏览器开局、存档、进程重启恢复与中文日志编码核验。
2. Android/Termux：安装 `requirements.txt` 后运行 `./start.sh --check`、`./start.sh`，在手机浏览器完成开局、断线重连、进程重启恢复与本地路径/中文文件名核验。
3. 两端均使用隔离测试档案和临时战绩路径，记录 Python/依赖版本、命令退出码与日志；不接入真实模型密钥。
