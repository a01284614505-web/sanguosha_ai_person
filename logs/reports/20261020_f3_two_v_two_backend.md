# F3 2v2 后端实现与验证

日期：2026-10-20（UTC）

## 接口与规则

- 模式 ID：`2v2`；`MainEngine.server_info().supported_modes` 现为 `5人身份局 / 8人身份局 / 2v2`。
- 四席固定为 `team_a / team_b / team_a / team_b`，不洗身份；`assigned["first_player"]` 明确返回 0 号 A 队首席，避免重复队伍身份返回列表时产生歧义。
- 四人队伍身份从开局起全部公开；每人初始 4 牌；无主公体力加成。
- 任一队全部阵亡时另一队胜，赢家字段为 `team_a` 或 `team_b`。
- 击杀不触发身份局的反贼摸三张或主公误杀忠臣弃牌。
- 2v2 不接受身份卡；配置严格要求 3 个 AI。
- 首席阵亡但队友存活时，轮次锚点顺时针移到下一存活座位，保证轮数、按轮技能和认知快照继续推进。

`ModeSpec` 新增 `assignment / identities_public / victory` 三个声明字段。五人、八人继续使用
`shuffle / false / identity`，原行为不变；2v2 使用 `fixed / true / team_elimination`。

## 确定性场景

- 后端元数据、3 AI 配置、固定交叉座次、四人身份公开、A 首席先行动。
- A 队全灭、B 队全灭和双方仍存活三种胜负状态。
- 击杀后手牌不增加、不触发身份惩罚。
- A 首席阵亡后轮次锚点迁移并正常增加轮数。

## 十局完整自动对局

固定种子 `20262020 + index * 89`，标准 108 牌堆，全员规则 AI：

| 局 | 胜方 | 完成回合 | 轮数 | 实体牌 |
|---:|---|---:|---:|---:|
| 0 | team_a | 15 | 6 | 108 |
| 1 | team_b | 49 | 22 | 108 |
| 2 | team_a | 33 | 13 | 108 |
| 3 | team_a | 12 | 4 | 108 |
| 4 | team_a | 26 | 12 | 108 |
| 5 | team_a | 34 | 14 | 108 |
| 6 | team_b | 26 | 12 | 108 |
| 7 | team_a | 21 | 8 | 108 |
| 8 | team_a | 23 | 8 | 108 |
| 9 | team_b | 48 | 23 | 108 |

10 局全部正常结束，7 局 A 队、3 局 B 队、0 判和；每局 108 个实体牌 ID 唯一，0 非法动作，`game_end` 恰好一次。

## 验证命令与退出码

```text
python -m pytest -q tests/test_plan_f2_mode_foundation.py \
  tests/test_plan_f3_eight_player.py tests/test_plan_f3_two_v_two.py \
  tests/test_p5_ai_titles.py --tb=short -p no:cacheprovider

48 passed in 10.18s
exit 0
```

旧五人完整回归：

```text
python scripts/verify_b7_games.py

games=30, normal=30, draw=0, declined_skills=2, ai_heroes_covered=27
exit 0
```

八人十局完整回归包含在上述 pytest 中，逐局牌守恒与非法动作断言继续通过。
