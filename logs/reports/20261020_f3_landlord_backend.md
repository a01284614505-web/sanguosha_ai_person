# F3 斗地主后端实现与验证

日期：2026-10-20（UTC）

## 具体契约

- 模式 ID：`斗地主`；三席固定为 `landlord / farmer / farmer`，身份不洗牌且全部公开。
- `assigned["first_player"]` 为 0 号地主；地主开局体力与体力上限各加 1；每人初始 4 牌；顺时针行动。
- 地主的每个实际摸牌阶段比普通角色多摸 1。`MainEngine.phase_draw_count(player, base)` 是统一入口：默认摸牌由 2 变 3，英姿由 3 变 4，突袭总获取额度由 2 变 3，裸衣维持亮三张并另摸 1。
- 地主阵亡时赢家为 `farmer`；两个农民均阵亡时赢家为 `landlord`。
- 不触发身份局的击杀反贼摸三张或主公误杀忠臣弃牌；不支持身份卡；配置严格要求 2 个 AI。
- `ModeSpec` 的摸牌声明为 `draw_bonus_identity="landlord"`、`draw_bonus_per_phase=1`；五人、八人和 2v2 均为 `None / 0`。

## 确定性场景

- 模式元数据、固定公开身份、地主首席、初始手牌、配置人数与身份卡拒绝。
- 地主体力/上限加一、地主默认摸 3、农民默认摸 2。
- 地主阵亡、双农民阵亡、双方仍存活三种胜负。
- 击杀农民不产生身份奖励或惩罚。
- 地主英姿摸 4；地主突袭“获得/补摸”合计 3；地主裸衣亮三张后额外摸 1。

## 十局完整自动对局

固定种子 `20263020 + index * 83`，标准 108 牌堆，全员规则 AI：

| 局 | 胜方 | 完成回合 | 轮数 | 地主上限 | 实体牌 |
|---:|---|---:|---:|---:|---:|
| 0 | landlord | 10 | 5 | 5 | 108 |
| 1 | landlord | 12 | 6 | 5 | 108 |
| 2 | landlord | 9 | 5 | 5 | 108 |
| 3 | landlord | 15 | 8 | 5 | 108 |
| 4 | landlord | 22 | 11 | 5 | 108 |
| 5 | landlord | 3 | 2 | 5 | 108 |
| 6 | landlord | 27 | 14 | 5 | 108 |
| 7 | landlord | 3 | 2 | 5 | 108 |
| 8 | landlord | 15 | 8 | 5 | 108 |
| 9 | landlord | 14 | 6 | 5 | 108 |

10 局全部正常结束，0 判和；每局 108 个实体牌 ID 唯一，0 非法动作，`game_end` 恰好一次。该小样本只验证执行链路，不作为模式平衡性结论。

## 验证

```text
python -m pytest -q tests/test_b5_wei_optional_skills.py \
  tests/test_b5_wu_choice_triggers.py tests/test_junzheng_fixes.py \
  tests/test_plan_f2_mode_foundation.py tests/test_plan_f3_eight_player.py \
  tests/test_plan_f3_two_v_two.py tests/test_plan_f3_landlord.py \
  --tb=short -p no:cacheprovider

126 passed in 9.69s
exit 0
```

旧五人完整回归：`scripts/verify_b7_games.py`，30/30 正常结束，0 判和，27 个 AI 武将覆盖，退出码 0。八人和 2v2 各十局完整对局包含在模式 pytest 中，牌守恒与非法动作断言继续通过。
