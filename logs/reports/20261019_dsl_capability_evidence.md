# DSL 能力与规则行为证据（整合工作树快照）

更新：2026-10-19。基线为整合树 HEAD `2cfc2b2a143c49fb25d1263f7fecd60f55ec437b` 加当前未提交的 Stage 8、A1–A3 与认证测试改动。机器可读逐项记录及源文件 SHA-256 见 [`data/skill_dsl_evidence.json`](../../data/skill_dsl_evidence.json)。SHA 绑定当前快照；共享工作树后续代码变化后须重跑并更新。

本轮清单覆盖 54 项技能：33 项有完整 DSL 声明并逐项通过编译测试，21 项仍由原生 Python 处理。现有 Python/DSL 对照场景共 10 项：英姿、闭月、克己、替身、连营、天妒、鬼才、鬼道、奸雄、反馈。当前所选客户端规则版本核验仍为 0 项。编译、具名行为场景、Python/DSL 场景等价和规则版本依据分别登记，不能把 33/54 表述为行为认证率。

DSL 定向命令：

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/root/sanguosha_ai_person_integrated_20261019 /root/sanguosha_ai_person/.venv/bin/python -m pytest -q tests/test_skill_dsl.py tests/test_skill_dsl_active.py tests/test_skill_dsl_coverage.py tests/test_skill_dsl_parity.py tests/test_stage8_review.py tests/test_plan_b_parity.py --tb=short -p no:cacheprovider
```

结果：**47 passed in 3.90s**，退出码 0；其中 33/33 DSL 声明编译通过，10 个具名 parity 场景全绿。五项 B 批逐场景范围见机器表及 [`tests/test_plan_b_parity.py`](../../tests/test_plan_b_parity.py)：

- 天妒：接受发动，将展示中的判定牌移动到持有者手牌并阻止默认弃置。
- 鬼才：接受发动，以手牌替换判定牌，原判定牌进入弃牌堆。
- 鬼道：以黑桃替换牌，取得原判定牌；黑桃 2–9 条件摸一张牌。
- 奸雄：伤害牌仍在弃牌堆时取得该牌并摸一张牌。
- 反馈：两点伤害逐点询问；第一次接受并取得来源手牌，第二次拒绝。

旧五项和新增五项只认证所列固定场景；没有覆盖到的分支仍保留缺口。原生与 DSL 共用公共牌移动、判定、摸牌等引擎能力；对照通过不能单独证明共同规则实现正确。

A 规则场景位于 [`tests/test_plan_a_rules.py`](../../tests/test_plan_a_rules.py)，定向结果 **14 passed in 0.41s**。14 项分别覆盖：

1. 判定区按后放先判的快照顺序；较早处理移走快照内后续牌时不再复活。
2. 闪电未命中传递、兵粮寸断与乐不思蜀混合结算顺序及实体守恒。
3. 闪电致死后停止后续判定；剩余延时锦囊随死亡清理进入弃牌堆。
4. 第一项判定中止对局后停止快照后续项。
5. 真人翻面跳过整回合，不触发阶段钩子、不误清横置且不遗留跳过标记。
6. AI 与托管真人翻面路径同样不派发被跳过阶段钩子。
7. 兵粮跳过摸牌时不调用原生或 DSL 阶段开始/结束钩子。
8. 乐不思蜀跳过出牌时消费标记且不派发阶段钩子。
9. 翻面跳过回合重置酒、杀次数、杀上限与回合技能作用域，但不发回合开始技能事件。
10. 体力 -1 时本人可连续用两张酒自救；不改变本回合用酒/酒杀加成状态。
11. 本人可用木牛中的酒自救，实际消耗储存牌并保留木牛装备。
12. 其他角色不能用自己的酒救濒死者。
13. 本人拒绝自救后继续询问其他角色；合法视为桃响应可正常救援且不消费拒绝者的桃。
14. 桃救援不会更改正常出牌酒次数或酒杀加成。

A 完整对局使用 [`scripts/verify_b7_games.py`](../../scripts/verify_b7_games.py) 的固定种子组合：标准牌堆、扩展牌堆、合并牌堆各 10 局，共 30 局。结果完整数据见 [`20261019_luna_rules_b7_games.json`](20261019_luna_rules_b7_games.json)：30 局均正常结束，0 局非法动作，0 次异常终止，实体牌数量/唯一性检查全部通过，0 局判和；最长 53 回合。胜率仅记录，不作为本轮通过条件。

试验台四场景此前进行过真实浏览器检查，页面载入成功，但当时后端 `POST /api/heroes/trial` 返回 HTTP 404；这份历史输出见 [`20261019_luna_rules_trial_browser.json`](20261019_luna_rules_trial_browser.json)。后端路由现已实现；浏览器端到端复验由 UI 负责人执行，不能将历史 404 或本轮 HTTP 单测算作浏览器验收。

B 试验 HTTP 边界与隔离回归位于 [`tests/test_plan_b_trial_isolation.py`](../../tests/test_plan_b_trial_isolation.py)。定向验证同一 payload/seed 的完整结果相等、试验前后模块全局 `random` 状态完全相等、四个 dummy 对手均显式无技能且运行时无注册技能；另通过临时真实 HTTP 服务发送 52 次 `set_state` 的 DSL 超限请求，确认 HTTP 200 响应明确报告 `budget_exhausted`，且试验没有写入 `heroes.json` 或创建 `hero_packages.json`。该文件及 C 消融/隐私回归合跑命令：

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/root/sanguosha_ai_person_integrated_20261019 /root/sanguosha_ai_person/.venv/bin/python -m pytest -q tests/test_plan_b_trial_isolation.py tests/test_plan_c_ai_ablation.py tests/test_plan_c_ai_privacy.py --tb=short -p no:cacheprovider
```

结果：**11 passed in 0.86s**，退出码 0。该 HTTP 定向测试覆盖真实 handler 路由及超限诊断，不代替 UI 负责人执行的四场景浏览器流程。

其它限制：另 21 项的缺失机制与工程成本估计仍列在 JSON；估计只用于排期，不承诺全部 DSL 化。没有逐项客户端规则核验。固定场景之外的条件拒绝、异步中止、死亡交叉和多技能交互仍需后续分批认证。

## C 规则 AI 消融与隐私回归（第一小批）

策略入口固定为 `game_config['ai_ablation']={'skill_strategy': bool, 'target_strategy': bool}`；缺省两项均启用当前增强策略。四种对照由 [`scripts/verify_ai_strategy_ablation.py`](../../scripts/verify_ai_strategy_ablation.py) 调用同一个 `AIDecision.simple_choice_decision`：baseline 为 false/false，skill-only 为 true/false，target-only 为 false/true，both 为 true/true。该脚本不包含或复制生产策略，也不发模型请求。

固定种子 `20261020, 20261123, 20261226, 20261329`，每组四局，共 16 局标准牌堆。各模式使用相同的种子、武将、初始身份及配置；策略改变选择后，后续牌序会分叉，不声称回合间完全同抽牌。完整逐局记录和统计见 [`20261019_ai_ablation_small.json`](20261019_ai_ablation_small.json)。

| 模式 | 胜者（主公/反贼/内奸/和局） | 平均回合 | 技能发动 | 救援 | 治疗 | 非法动作 | 中止/和局 | 牌守恒异常 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 1/2/1/0 | 24.50 | 68 | 1 | 36 | 0 | 0/0 | 0 |
| Skill-only | 2/2/0/0 | 20.75 | 73 | 0 | 39 | 0 | 0/0 | 0 |
| Target-only | 1/2/1/0 | 24.50 | 68 | 1 | 36 | 0 | 0/0 | 0 |
| Both | 2/2/0/0 | 20.75 | 73 | 0 | 39 | 0 | 0/0 | 0 |

这是暴露错误的小样本，不作胜率显著性判断。当前样本里 target-only 与 baseline 的行为计数相同；skill-only 与 both 各多 5 次技能发动并缩短平均回合，且内奸本组未胜。由于每模式只有四局，这些差异用于定位后续样本与场景，不作为平衡结论。救援只计引擎明确记录的公开 `dying_rescue` 事件，不从暗手牌推断。

[`tests/test_plan_c_ai_ablation.py`](../../tests/test_plan_c_ai_ablation.py) 覆盖四种开关组合与缺省增强策略入口；[`tests/test_plan_c_ai_privacy.py`](../../tests/test_plan_c_ai_privacy.py) 的两项配对回归在公开目标状态不变时替换暗身份和暗手牌，确认目标选择不变且 AI 视角中没有这些私密字段。单独定向结果曾为 **7 passed in 0.27s**；与新增 B 隔离/HTTP 边界测试合跑为 **11 passed in 0.86s**。

## D 公开局面快照契约（离线构建器）

新增 [`game_engine/public_situation.py`](../../game_engine/public_situation.py)，提供只读 `build_public_situation`、`build_private_situation` 和稳定 JSON `compact_public_situation`。公开快照含 16 位 SHA-256 内容版本、权威日志/牌移动序号、公开牌区摘要、逐席公开信息、存活者距离与武器攻击范围；距离委托给 `RulesEngine.get_distance` 和 `SkillManager.modify_distance`。暗手牌内容及未揭身份不进入公开版本。私有快照只包含指定 viewer 的手牌/木牛储牌和其 `CognitiveNotes.view` 输出。

固定局面回归位于 [`tests/test_plan_d_public_situation.py`](../../tests/test_plan_d_public_situation.py)，覆盖同状态重复版本稳定、公开字段及两个序号变化可更新版本、暗牌/暗身份置换不改变公开快照、距离修正委托、阵亡者不进入距离图、弃牌洗回牌堆后当前摘要清空，以及 viewer 私有字段隔离。定向命令：

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/root/sanguosha_ai_person_integrated_20261019 /root/sanguosha_ai_person/.venv/bin/python -m pytest -q tests/test_plan_d_public_situation.py tests/test_plan_c_ai_privacy.py --tb=short -p no:cacheprovider
```

结果：**15 passed in 0.27s**，退出码 0；模块与测试 `py_compile` 通过。当前仅增加可复用构建器，出牌/响应/选择三类模型 prompt 的接线及真实 Provider 仍待主代理集成/验收。
