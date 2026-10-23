# 自定义技能 DSL

技能声明是 JSON 数据。服务端通过 `compile_skill()` 验证后，只有 `implementation_status: "active"` 的声明会接入主动动作或事件 hook。`data_only` 与 `partial` 不执行。DSL 不支持 Python 表达式、文件访问或网络访问；所有交互、牌移动和结算都由引擎白名单能力完成。

## 基本结构

```json
{
  "version": 1,
  "trigger": "damage_received",
  "condition": {"op": "gt", "path": "event.amount", "value": 0},
  "cost": [{"interaction": "ask_confirm", "prompt": "是否发动？"}],
  "targets": {"selector": "chosen_players", "candidates": "alive_others", "min": 1, "max": 1},
  "effects": [
    {"type": "draw_cards", "target": "owner", "count": 1, "reason": "技能名"}
  ]
}
```

`trigger` 取自 `game_engine/skill_dsl.py` 的白名单；`triggers` 可将同一声明接到最多四种事件。`condition` 使用 `all`、`any`、`not`、比较、`in` 和 `exists`。路径只从 `owner`、`event`、`game`、`locals`、`state` 开始，并且对象字段也受白名单限制。

`cost` 和效果中的 `interact` 只可使用四个引擎交互原语：`ask_confirm`、`ask_choose_players`、`ask_choose_cards`、`ask_choose_option`。选出的值会在服务端复核候选范围、重复项、牌区和数量。效果序列可使用 `when`、`repeat`、`set_state`、`set_local` 组合状态与分支；交互可把结果保存到 `locals`。`current_turn` 状态在回合边界自动回到默认值。

## 目标、效果与修饰器

目标规则支持自身、事件来源/目标、合法玩家筛选及交互选目标。牌区支持手牌、装备、两者和本次运行的局部牌列表。效果白名单包括：

- 抽牌、转移牌、弃牌、判定、获得判定牌、替换判定牌
- 伤害、回复、失去体力、公告
- 通过标准牌规则检查后使用限定的虚拟牌
- 决斗、取消多目标锦囊中的指定目标、从事件中获取牌
- `repeat`、`interact`、`set_state`、`set_local` 等组合操作

静态修饰器包括手牌上限、距离、杀响应数量、杀次数、无距离限制、目标保护和装备保护。伤害支持 `normal`、`fire`、`thunder`，并可显式设置 `source` 为 `owner`、事件 `source` 或事件 `target`。

## 沙箱限制

编译时限制程序大小、嵌套深度、字段、路径、交互、效果与数值。单次技能运行共享最多 100 步预算；repeat 次数和牌数上限为 52，伤害 / 回复 / 失去体力每项最多 10。技能运行禁止重入；超限会停用对应技能实例并保留对局继续运行。牌转化、目标选择和牌移动都必须通过引擎现有合法性校验。

## 覆盖与等价测试

[`data/skill_dsl_coverage.json`](data/skill_dsl_coverage.json) 保存逐项语义映射与编译定义。测试从 `get_all_skills()` 动态计算分母；当前清单覆盖 33/54 项，即 61.1%。这是“有完整声明且能编译表达”的证据，不表示每一项都已经在 Python 与 DSL 间做逐事件 parity。

五项 Python 行为等价测试位于 `tests/test_skill_dsl_parity.py`：英姿、闭月、克己、替身、连营。龙胆定义按当前引擎实现说明了主动闪当杀与响应桃 / 酒互换；当前引擎没有主动出牌阶段的桃 / 酒互换分支，不能把 DSL 清单解读成补齐该原生缺口。
