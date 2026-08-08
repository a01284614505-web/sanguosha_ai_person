# AI 开发执行规范

> 本文件由 `aidev` 生成。项目：`/data/data/com.termux/files/home/sanguosha_tavern`

## 权限原则

1. `run_command`/Shell 保持完整权限，不做目录或命令白名单限制。
2. 项目目录不是固定值；每次任务使用用户提供路径、当前目录或 `aidev -p PATH` 明确目标。
3. `aidev` 是辅助工具，不是沙箱；必要时允许直接运行任意命令。

## 修改流程

1. 修改前读取当前文件，确认实际内容，不依赖旧对话中的副本。
2. 修改前执行 `aidev snapshot NAME`，或确认项目已有可回滚版本。
3. 小范围改动优先使用统一补丁：`aidev apply-patch PATCH --yes`。
4. 整文件写入优先使用原子写入：`aidev atomic-write TARGET --source FILE --yes`。
5. 可传 `--expected-sha256` 防止基于旧版本覆盖新内容。
6. 修改后展示 diff，运行相关语法检查和测试。
7. 未看到命令成功输出前，不得声称“已完成”或“测试通过”。

## 高风险操作

执行删除、覆盖、批量移动、停止服务、强制杀进程、安装/卸载软件、Git 历史重写、外网上传前：

- 先说明完整命令；
- 说明影响范围和回滚方法；
- 除非用户已在当前任务中明确授权，否则先等待确认。

此规则是行为规范，不会从技术上阻止不受限 Shell。

## 密钥与隐私

1. 不主动读取 `.ssh`、`.netrc`、`.git-credentials`、Shell 历史或无关项目配置。
2. 不在回复、日志、补丁、记忆文件中输出 API Key、Bearer Token、密码和私钥。
3. 命令输出优先通过 `aidev exec` 脱敏；确需原始输出时使用 `--raw`，且不得回显凭据。
4. 向量索引和长期记忆不得包含真实密钥。

## 项目边界

1. 开始任务时确认真正源代码、运行副本、公共备份分别位于哪里。
2. 不把备份副本误认为运行源代码。
3. 不同时修改多个副本；维持唯一事实来源。
4. 大型第三方源码、依赖、构建产物和媒体资源默认不进入向量索引。

## 推荐命令

```bash
# 项目诊断
aidev doctor

# 创建快照
aidev snapshot before_change

# 搜索
aidev search '关键词'

# 应用补丁
aidev apply-patch /path/to/change.patch --yes

# 运行任意命令（输出默认脱敏）
aidev exec -- your command here

# 运行项目预设
aidev preset test.integration

# 查看快照
aidev snapshots
```
