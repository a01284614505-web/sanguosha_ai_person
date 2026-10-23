# F4 / E1 独立恢复与后台生命周期审查

日期：2026-10-20 UTC。审查范围：`game_engine/recovery.py`、恢复入口 `game_server.py`、恢复后的请求处理 `game_engine/main_engine.py`，以及真人阵亡后的后台生命周期。审查只新增独立测试与本报告；未修改生产实现或既有 F4/C/D/F3/前端测试。

## 结果

新增 `tests/test_plan_f4_independent_audit.py`，通过真实 `MainEngine`、`RecoveryStore` 与 `GameServer` 行为检查：

- 损坏 JSON 和旧快照版本均安全拒绝，恢复入口返回 `resume_failed/not_found`。
- 快照 `profile_id` 不匹配时返回 `forbidden`，不会创建或接管引擎。
- 重启恢复会生成新的 request epoch；旧进程的 request ID 返回 `stale`。
- 同 profile 创建新对局时，已由真人明确选为后台结算的旧局仍留在运行表中且未被中止；新局任务也已启动。
- 重复结束操作只写入一条战绩，第二次返回 `already_finished`。
- 正常快照恢复后的物理牌 ID 唯一。
- 把一张手牌 ID 同时追加到快照牌堆时，恢复必须抛出 `ValueError`，拒绝重复牌区引用。

重复牌缺陷的最小输入是在 `dump_engine(engine)` 后执行：

```python
hand_card_id = payload["state"]["players"][0]["hand"][0]
payload["state"]["deck"].append(hand_card_id)
restore_engine(payload, MainEngine)
```

最初审查观察到该状态能恢复，物理区有 109 个位置、108 个唯一 ID。主代理随后在 `restore_engine` 增加牌目录与全部牌区一一对应检查；新增测试现在确认该损坏快照被拒绝。此生产修复由主代理完成，本审查代理没有修改生产文件。

## 证据边界

这些是自动化真引擎/服务器行为测试，不是操作系统断电或任意时刻 `kill -9` 的破坏性恢复实验。后台并行场景实际调用 `do_create`，将两个引擎运行任务保持挂起来验证服务端生命周期映射；没有等待完整对局结束。终局快照和子进程恢复另由既有 F4 测试覆盖。

## 验证

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/root/sanguosha_ai_person_integrated_20261019 \
  /root/sanguosha_ai_person/.venv/bin/python -m pytest -q \
  tests/test_plan_f4_independent_audit.py \
  tests/test_plan_f4_crash_recovery.py \
  tests/test_plan_e_post_death_lifecycle.py --tb=short -p no:cacheprovider
```

退出码 0：`15 passed in 1.56s`。

`git diff --check` 退出码 0。
