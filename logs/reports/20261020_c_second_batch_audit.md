# C 第二批独立行为审查

日期：2026-10-20

## 结论

本次独立固定场景审查未发现明确的 C 第二批策略缺陷。新增的四项真实入口测试通过，涉及制衡/苦肉成本和濒死安全、清俭选牌/受益者、鬼才/鬼道对延时锦囊判定的接受与拒绝，以及四种策略开关组合。覆盖结果仅证明这些已列场景中的行为；不证明规则实现对所有状态都正确，也不证明策略提高胜率。

## 证据层级与场景

| 项目 | 观察与证据 | 未覆盖部分 |
|---|---|---|
| 制衡 | 真实规则 AI 的 `make_decision`、可用动作和 `execute_action`；选择低价值牌支付，保留高价值牌并摸一张，牌 ID 不重复。 | 未穷举所有牌价值、装备区或特殊牌类组合。 |
| 苦肉 | HP=1 时真实规则入口不选择苦肉；HP=3 时选取低价值牌并执行真实技能，观察到 HP 3→2、弃牌及诈降摸三张，资源区牌 ID 唯一。 | 只覆盖两个生命值边界，未枚举所有濒死救援响应顺序。 |
| 清俭 | 真实 `_ai_choose_choice` 规则决策偏向已知友方；改变隐藏敌方身份及其暗手牌后，遮蔽输入和决策保持一致。另实际触发技能，观察成本牌转移、保留高价值牌、回合标记和唯一性。 | 未穷举所有受益人关系、候选牌规模及触发时点。 |
| 鬼才/鬼道 | 真实 `before_judge`：对已知友方的不利兵粮寸断判定接受替换并选牌；对隐藏目标拒绝。改变隐藏身份、第三方暗手牌后结果保持一致。分别核对鬼才弃置原判定牌、鬼道取得原判定牌及牌区唯一性。 | 只覆盖一个延时锦囊、判定结果及替代牌样本；未穷举其他判定技能、花色/点数和多候选排序。 |
| 消融开关 | 经真实 `_ai_choose_choice` → `make_choice_decision` 路径检查 skill/target 两个布尔开关的四种组合，四种配置均可复现预期选择。 | 这是路由/开关冒烟，不是策略收益比较。 |

上述场景使用离线规则 AI 与真实引擎技能/动作执行；没有调用外部模型提供方。隐藏信息测试验证输入遮蔽下的决策不依赖被置换的秘密值，但不构成对整个代码库无侧信道的证明。

## 小样本消融观测

`scripts/verify_ai_strategy_ablation.py` 完成 16 局（4 个配对种子 × baseline、skill_only、target_only、both），provider calls 为 0。所有配置均为 0 非法动作、0 中止、0 抽牌和 0 牌守恒失败。各模式 4 局的胜方计数分别为 baseline：主公 1、反贼 2、内奸 1；skill_only：反贼 4；target_only 与 baseline 相同；both 与 skill_only 相同。样本很小且会受种子与策略互动影响，这些仅是本次观测，不支持胜率提升或退化结论。

## 可复跑验证

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/root/sanguosha_ai_person_integrated_20261019 /root/sanguosha_ai_person/.venv/bin/python -m pytest -q tests/test_plan_c_second_batch_independent.py tests/test_plan_c_ai_second_batch.py tests/test_plan_c_ai_ablation.py tests/test_plan_c_ai_privacy.py --tb=short -p no:cacheprovider` — 退出码 0，14 passed。
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/root/sanguosha_ai_person_integrated_20261019 /root/sanguosha_ai_person/.venv/bin/python scripts/verify_ai_strategy_ablation.py`（stdout 重定向到临时 JSON）— 退出码 0，16 局完成；摘要见上。
- `git diff --check` — 退出码 0。

新增独立测试：`tests/test_plan_c_second_batch_independent.py`。本次未修改生产代码或既有 C 测试。
