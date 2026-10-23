# F4 崩溃恢复实现与验证

日期：2026-10-20（UTC）

## 序列化边界

- 只在引擎初始化完成、以及一个回合完整结算并切换到下一角色后保存安全检查点。进程在回合中退出时，恢复到该回合开始前，避免保存一半结算。
- 快照为带 `version=1` 的 JSON，原子写入 `logs/runtime/recovery/<game_id>.json`，临时文件落盘并 `fsync` 后 `os.replace`，文件权限为 `0600`。
- 集成审核将快照对象冻结放回引擎事件循环，只把已构造的 JSON payload 交给工作线程写盘，避免聊天/事件任务在跨线程序列化期间改动状态。
- 独立审核发现恶意/损坏快照可让同一实体牌 ID 同时恢复到两处；现在 `restore_engine` 在构造引擎前校验卡目录与牌区一一对应且无重复。109 个位置引用 108 个 ID 的复现现抛 `ValueError`，不再恢复该快照。
- 保存实体牌及每个牌区、玩家规则状态、牌移动序号、统计、技能实例状态、行为账本、认知笔记、AI 会话/打法、公开日志与请求计数。
- 不保存 WebSocket、事件处理器、`asyncio.Task/Event/Future`、动画 ACK waiter、watchdog 或聊天后台任务。恢复时重新创建这些运行时对象。
- 每个引擎进程生成新的请求 epoch，请求 ID 包含该 epoch。epoch 不进入快照，因此崩溃前页面提交的旧请求在新进程中必定返回 `stale`。
- 结束事件仍由既有 `_emit_game_end_once` 与 `GameHistoryStore.record_result(game_id)` 负责幂等；结束事件处理完成后删除活跃快照。即使模拟“战绩已写、快照尚未删”并再次恢复，同一 `game_id` 也只计一次战绩。

## 外部行为

真实启动 `game_server.py`，通过 WebSocket 创建对局，等待磁盘快照后终止服务器进程；启动全新服务器进程，用原 `game_id/profile_id` 发 `resume_game`。新进程返回：

```json
{"messages":["game_resumed","game_state","trustee_status"],"cards":108,"game_over":false}
```

快照中 108 张实体牌 ID 唯一，数量等于初始牌堆数。

## 验证命令与退出码

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /root/sanguosha_ai_person/.venv/bin/python \
  -m pytest -q tests/test_plan_f4_crash_recovery.py tests/test_reconnect.py \
  tests/test_plan_e_post_death_lifecycle.py tests/test_response_channel.py \
  tests/test_game_stats.py --tb=short -p no:cacheprovider

62 passed in 3.21s
exit 0
```

WebSocket 双进程脚本：`game_server.py` 进程 1 创建并落盘 → terminate → `game_server.py` 进程 2 恢复；输出如上，退出码 `0`。

项目级 `scripts/verify_project.py` 同期结果为 `919 passed, 50 subtests passed, 1 failed`。唯一失败是
`tests/test_plan_b_parity.py::test_guicai_dsl_matches_native_judgment_replacement_and_discard`，单独复跑仍失败；
失败位于并行修改中的鬼才技能范围，不在 F4 修改文件内，已交由集成负责人处理，不能将本次项目级命令记为通过。

上述鬼才夹具现已修正；负责人审核冻结边界后的定向命令 `pytest -q tests/test_plan_f4_crash_recovery.py tests/test_reconnect.py tests/test_plan_e_post_death_lifecycle.py` 退出码 0，`15 passed`。最终完整集成结果另记，不将先前失败的项目级命令改写为通过。

## 限制

恢复粒度是完整回合边界。崩溃时正在进行的当前回合会从其开始处重新执行；不会重复应用已经写进安全检查点的牌移动或结算。没有客户端发起 `resume_game` 时，磁盘中的对局不会在服务器启动后自行消耗模型或继续后台运行。
