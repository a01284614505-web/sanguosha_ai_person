# B5–B7 Luna 交接与技能规则覆盖台账

核对日期：2026-10-17。目标按任务约定采用三国杀十周年电脑版；官方公开资料未能覆盖全部当前十周年电脑版将池，因此逐条实装以仓库 `data/heroes.json` 与对应引擎规则为项目基准；下文官方资料只证明其明确覆盖的技能/版本，不外推到整个将池。十周年版本精确差异无可核实资料的项目规则继续冻结，避免凭外部版本臆测。

## 全将池覆盖

| 势力 | 武将 | 技能（仓库当前文本） | 运行状态 | 场景证据入口 |
|---|---|---|---|---|
| 魏 | 界曹操 (`caocao`) | 奸雄、护驾 | active、active | `tests/test_b5_wei_optional_skills.py` |
| 魏 | 界司马懿 (`simayi`) | 反馈、鬼才 | active、active | `tests/test_b5_wei_optional_skills.py` |
| 魏 | 界夏侯惇 (`xiahoudun`) | 刚烈、清俭 | active、active | `tests/test_b5_wei_optional_skills.py` |
| 魏 | 界张辽 (`zhangliao`) | 突袭 | active | `tests/test_b5_wei_optional_skills.py` |
| 魏 | 界许褚 (`xuchu`) | 裸衣 | active | `tests/test_b5_wei_optional_skills.py` |
| 魏 | 界郭嘉 (`guojia`) | 天妒、遗计 | active、active | `tests/test_b5_wei_optional_skills.py` |
| 魏 | 界甄姬 (`zhenji`) | 洛神、倾国 | active、active | `tests/test_b5_wei_optional_skills.py` |
| 蜀 | 界刘备 (`liubei`) | 仁德、激将 | active、active | `tests/test_b5_shu_choices.py` |
| 蜀 | 界关羽 (`guanyu`) | 武圣、义绝 | active、active | `tests/test_b5_shu_choices.py` |
| 蜀 | 界张飞 (`zhangfei`) | 咆哮、替身 | active、active | `tests/test_b5_shu_choices.py` |
| 蜀 | 界诸葛亮 (`zhugeliang`) | 观星、空城 | active、active | `tests/test_b5_shu_choices.py` |
| 蜀 | 界赵云 (`zhaoyun`) | 龙胆、涯角 | active、active | `tests/test_b5_shu_choices.py` |
| 蜀 | 界马超 (`machao`) | 马术、铁骑 | active、active | `tests/test_b5_shu_choices.py` |
| 蜀 | 界黄月英 (`huangyueying`) | 集智、奇才 | active、active | `tests/test_b5_shu_choices.py` |
| 吴 | 界孙权 (`sunquan`) | 制衡、救援 | active、active | `tests/test_b5_wu_choice_triggers.py` |
| 吴 | 界甘宁 (`ganning`) | 奇袭、奋威 | active、active | `tests/test_b5_wu_choice_triggers.py` |
| 吴 | 界吕蒙 (`lvmeng`) | 克己、勤学、博图 | active、active、active | `tests/test_b5_wu_choice_triggers.py` |
| 吴 | 界黄盖 (`huanggai`) | 苦肉、诈降 | active、active | `tests/test_b5_wu_choice_triggers.py` |
| 吴 | 界周瑜 (`zhouyu`) | 英姿、反间 | active、active | `tests/test_b5_wu_choice_triggers.py` |
| 吴 | 界大乔 (`daqiao`) | 国色、流离 | active、active | `tests/test_b5_wu_choice_triggers.py` |
| 吴 | 界陆逊 (`luxun`) | 谦逊、连营 | active、active | `tests/test_b5_wu_choice_triggers.py` |
| 群 | 界华佗 (`huatuo`) | 急救、青囊 | active、active | `tests/test_b5_qun_optional_triggers.py` |
| 群 | 界吕布 (`lvbu`) | 无双、利驭 | active、active | `tests/test_b5_qun_optional_triggers.py` |
| 群 | 界貂蝉 (`diaochan`) | 离间、闭月 | active、active | `tests/test_b5_qun_optional_triggers.py` |
| 群 | 界华雄 (`huaxiong`) | 耀武、势斩 | active、active | `tests/test_b5_qun_optional_triggers.py` |
| 群 | 界袁绍 (`yuanshao`) | 乱击、血裔 | active、active | `tests/test_b5_qun_optional_triggers.py` |
| 群 | 界张角 (`zhangjiao`) | 雷击、鬼道、黄天 | active、active、active | `tests/test_b5_qun_optional_triggers.py` |

共 27 名武将；按数据文件中的实现状态逐技能列出。表内“场景证据入口”表示该势力测试套件，并不代表其中每一个锁定技/被动技都有独立 B5 点击场景。

## Luna 迁移技能及场景证据

逐条测试函数名称可由下列文件读取。测试覆盖发起/拒绝/取消/边界组合；强制或锁定效果不增加虚假的“拒绝”路径。

| 势力 | 已迁移/审计技能 | 独立场景文件 |
|---|---|---|
| 魏 | 奸雄、反馈、刚烈、清俭、遗计、突袭、鬼才、天妒、洛神（自动体验例外） | `tests/test_b5_wei_optional_skills.py` |
| 吴 | 奋威、流离、克己、博图、连营、勤学、救援 | `tests/test_b5_wu_choice_triggers.py` |
| 群 | 利驭、鬼道、雷击、闭月 | `tests/test_b5_qun_optional_triggers.py` |
| 蜀 | 替身、观星、铁骑等父任务并行迁移项 | `tests/test_b5_shu_choices.py` |

### 交互契约与边界

- 可选触发先询问持有者 `ask_confirm(..., default=False)`；AI 无 Key 时规则脚本保守拒绝。
- 成本牌和目标先分别征询；取消不移动牌、不消耗次数。选择后检查 `game_aborted` 再提交效果。
- 锁定效果不询问是否发动；其中规则指定由其他角色作主的选择交给该角色。利驭按项目采纳的官方 FAQ 由受伤者决定是否发动，吕布选取并获得目标牌。
- 鬼才/鬼道替换判定保留当前判定架构的直接替换：公共牌区尚无 processing/judgment-in-flight 区，提前把替换牌移入弃牌区会造成最终判定牌重复弃置。该架构限制需由引擎任务后续消除。
- 洛神保持当前项目指定的自动体验；勤学觉醒本身强制，觉醒后回复/摸牌由玩家选择。
- 清俭依据当前项目技能文本实现可交出任意张牌、交给一名其他角色，并按牌类别不同数增加本回合手牌上限。

## 版本资料与差异

网络核对日期：2026-10-17。官方可公开查询的页面主要是“三国杀OL”及历史官方攻略/公告，未找到完整、可锁定构建号的十周年电脑版现行 27 将规则数据库。故将它们作为交叉核验资料，并标注来源版本，不作为十周年逐条证明。

- 官方界曹操（OL 现行武将页，查询奸雄/护驾）：[sanguosha.com/hero/311](https://www.sanguosha.com/hero/311)
- 官方界司马懿（OL 现行武将页，反馈/鬼才）：[sanguosha.com/hero/312](https://www.sanguosha.com/hero/312)
- 官方界夏侯惇（OL 现行武将页，刚烈/清俭）：[sanguosha.com/hero/313](https://www.sanguosha.com/hero/313)
- 官方界郭嘉（OL 现行武将页，天妒/遗计）：[sanguosha.com/hero/316](https://www.sanguosha.com/hero/316)
- 官方界吕布页面：[sanguosha.com/hero/319](https://www.sanguosha.com/hero/319)
- 官方 2016 界限突破吕布攻略/FAQ（OL 历史资料）：[sanguosha.com/news/20161101_1451_0119](https://www.sanguosha.com/news/20161101_1451_0119)。核对利驭触发决定者、取牌主体及决斗目标限制。
- 官方十周年联动公告（2021；只证明当时公告技能文本）：[sanguosha.com/news/20210524_9650_5514](https://www.sanguosha.com/news/20210524_9650_5514)。
- 官方 2020 十周年相关公告：[sanguosha.com/news/20200927_3115_1712](https://www.sanguosha.com/news/20200927_3115_1712)，非完整技能手册。
- 次级社区规则整理（作者明确说明存在测试稿/不确定内容，只用于发现差异，不作官方证据）：[360 游戏中心规则整理](https://sgsszn.wan.360.cn/home/mxydsznxjxwjdjnjx.html)。

## B6/B7 前端及验证

- 大厅为每个浏览器生成稳定 `profile_id`，结果、身份卡和历史只读取服务端；旧 `userData` 仅显示迁移提示。
- 托管默认连接来自大厅第一席配置，Key 只进入 sessionStorage；copy_ai 可选座位；公开状态仅显示托管模型与服务端原因。
- 决策轨迹折叠展示候选概览、公开世界书命中、理由/最终选择/校验/来源/耗时；私有自定义世界书不应由协议发出。全局设置可关闭。
- 公开奖励/战绩按服务端 `game_end.profile`、`player_won`、`reward` 呈现。
- 真实浏览器验收入口：`scripts/manual/b5_b7_browser_check.cjs`；旧 `b4_browser_check.cjs` 已标记失效（依赖删除的 `window.selectTarget`）。运行及跳过场景另记于下方验证记录。

### 本轮实际验证记录

- `63 passed`：魏/吴/群三套 Luna 专项 B5 场景；包含拒绝/取消/指定牌/指定目标及本轮新增的牌已离区、无合法候选、次数上限、阈值、梅花判定等边界。蜀由父任务并行负责。
- `node --check`：`frontend/js/lobby.js`、`frontend/js/game_main.js`、`scripts/manual/b5_b7_browser_check.cjs` 通过。
- Chromium 实测命令：`PLAYWRIGHT_MODULE=/tmp/b4-browser-check/node_modules/playwright node scripts/manual/b5_b7_browser_check.cjs`，真实页面与真实按钮点击，未伪造 WebSocket。17 项记录：16 项通过（大厅档案与旧数据提示、历史页面、创建对局、座位详情、托管弹窗/复制 AI/自定义/提交、战报页签、轨迹折叠与展开、无页面异常）；“真人回合倒计时及主动技能点击”1 项跳过：15 秒内服务端未下发真人 `your_turn`，没有注入假状态。下一轮服务重启后重跑同一脚本；若仍随机先轮到 AI，等待机制和跳过原因照实记录。

## 逐技能版本与交互证据状态

以下是本次迁移/审计过的每个选择型技能，逐条列出确切 Python 场景函数。`无` 表示专门的正常/拒绝/边界场景尚未覆盖，不能据 `implementation_status=active` 视为验收通过。项目按当前十周年将池实现，但官方公开页面主要是 OL/经典版；页面覆盖到的机制以相应历史版标注，不能据此声称十周年电脑端已逐条证实。

| 技能 | 版本资料（截至 2026-10-17） | 实现与正常场景 | 不发动/取消场景 | 边界场景与缺口 |
|---|---|---|---|---|
| 奸雄 | 官方 OL 界曹操 [hero/311](https://www.sanguosha.com/hero/311)；十周年精确版本未单证 | `test_jianxiong_accept_moves_damage_card_then_draws_once` | `test_jianxiong_decline_leaves_damage_card_and_deck_untouched` | `test_jianxiong_does_not_prompt_if_damage_card_left_discard_pile` |
| 反馈 | 官方 OL 界司马懿 [hero/312](https://www.sanguosha.com/hero/312) | `test_fankui_prompts_and_takes_the_selected_equipment`（选中装备） | `test_fankui_can_decline_without_touching_sources_cards` | `test_fankui_with_source_without_cards_does_not_prompt` |
| 鬼才 | 官方 OL 界司马懿 [hero/312](https://www.sanguosha.com/hero/312) | `test_guicai_accepts_exact_equipment_replacement` | `test_guicai_decline_preserves_the_judgment_and_cost_card` | `test_guicai_with_no_owned_cards_does_not_offer_replacement`、`test_guicai_cancelled_cost_selection_preserves_original_judgment`；替换牌处理受无 processing 区限制，见上文 |
| 刚烈 | 官方 OL 界夏侯惇 [hero/313](https://www.sanguosha.com/hero/313) | `test_ganglie_black_judgment_asks_source_which_equipment_to_discard`（黑判定）、`test_ganglie_red_judgment_damages_source_instead_of_discarding`（红判定） | `test_ganglie_decline_does_not_judge_or_change_source` | 红黑分支均有独立证据；源无牌弃置分支未独立覆盖 |
| 清俭 | 官方 OL 界夏侯惇 [hero/313](https://www.sanguosha.com/hero/313) | `test_qingjian_uses_selected_gained_card_and_recipient` | `test_qingjian_decline_keeps_gained_cards_and_does_not_mark_use` | `test_qingjian_empty_gained_candidates_does_not_prompt`；无其他存活收牌者未独立覆盖 |
| 突袭 | 公开二手技能整理（非官方、规则版本不确定）：[360 游戏中心](https://sgsszn.wan.360.cn/home/mxydsznxjxwjdjnjx.html) | `test_tuxi_takes_the_chosen_hidden_hand_card_and_compensates_one_draw` | `test_tuxi_decline_leaves_draw_phase_to_normal_flow` | `test_tuxi_canceled_player_selection_does_not_activate_skill`、`test_tuxi_with_no_victim_hand_cards_does_not_prompt_and_keeps_draw_phase`；最多目标数受合法候选约束 |
| 天妒 | 官方 OL 界郭嘉 [hero/316](https://www.sanguosha.com/hero/316) | `test_tiandu_can_claim_the_resolved_judgment_card` | `test_tiandu_can_decline_claiming_a_resolved_judgment` | 两者均仅传入已结算判定牌；其他来源牌不属于 `after_judge` 入口，本接口没有额外来源字段可测 |
| 遗计 | 官方 OL 界郭嘉 [hero/316](https://www.sanguosha.com/hero/316) | `test_yiji_asks_owner_to_distribute_both_cards_before_moving_them` | `test_yiji_decline_does_not_draw_or_ask_distribution_targets` | `test_yiji_when_no_other_alive_recipient_keeps_drawn_cards`：无其他存活角色时空选择结果使牌留在郭嘉手中；契约禁止取消，无取消分支 |
| 洛神 | 当前十周年资料无独立公开证据；按用户指定保留自动体验例外 | `test_luoshen_takes_consecutive_black_judgments_then_stops_on_red` | 不适用（自动） | `test_luoshen_with_empty_deck_does_not_add_exemption`、`test_luoshen_stops_at_twelve_black_judgments` 覆盖空牌堆和 12 次上限 |
| 奋威 | 当前十周年精确官方公开资料未找到；按仓库文本 | `test_fenwei_selects_exact_targets_before_spending_limited_skill` | `test_fenwei_decline_does_not_consume_limited_skill` | `test_fenwei_already_spent_does_not_prompt_again`、`test_fenwei_illegal_selected_target_does_not_spend_limited_skill` |
| 流离 | 当前十周年精确官方公开资料未找到；按仓库文本 | `test_liuli_requests_cost_and_target_then_discards_selected_equipment` | `test_liuli_decline_preserves_cost_card_and_original_target` | `test_liuli_without_an_alternative_target_does_not_prompt` |
| 攻心（勤学觉醒后获得） | **非 27 将初始将池技能**，为界吕蒙觉醒后动态获得；版本资料未找到 | `test_gongxin_moves_the_chosen_heart_and_only_then_marks_use` | `test_gongxin_lets_owner_pick_a_heart_and_cancel_uses_no_turn` | 无红桃牌路径不是独立场景；作为额外动态兼容技能，不列入初始全将池覆盖表 |
| 克己 | 当前十周年精确官方公开资料未找到；按仓库文本 | `test_keji_accepts_when_no_sha_and_does_not_prompt_after_sha_use` | `test_keji_can_decline_and_preserves_default_discard_phase` | 接受函数同时验已使用【杀】边界 |
| 博图 | 当前十周年精确官方公开资料未找到；按仓库文本 | `test_botu_accepts_eligible_end_turn_and_respects_round_cap` | `test_botu_decline_does_not_schedule_extra_turn` | 接受函数同时验证每轮上限 |
| 连营 | 当前十周年精确官方公开资料未找到；按仓库文本 | `test_lianying_selects_exact_recipients_after_confirmation`、`test_lianying_multiple_cards_asks_for_matching_number_of_recipients`、`test_hand_card_loss_routes_through_unified_event` | `test_lianying_decline_does_not_draw_for_anyone` | 多张牌一次性传入处理器、最多两名受赠者已覆盖；实际引擎移动事件逐张通知，批量事件入口仍需核心层场景 |
| 勤学 | 当前十周年精确官方公开资料未找到；按仓库文本 | `test_qinxue_choice_is_asked_after_forced_awakening`（摸牌）、`test_qinxue_can_choose_recovery_after_forced_awakening` | 不适用：觉醒强制；不是可拒绝触发 | `test_qinxue_does_not_awaken_at_or_below_hand_minus_hp_threshold` |
| 救援 | 当前十周年精确官方公开资料未找到；按仓库文本 | `test_rescue_reversal_lands_on_crediting_row`（接受改疗并核对账本） | `test_jiuyuan_can_decline_recovery_transfer_and_preserve_normal_recovery` | `test_jiuyuan_ineligible_recovery_does_not_prompt` |
| 利驭 | 官方 2016 OL 界吕布 FAQ [news/20161101_1451_0119](https://www.sanguosha.com/news/20161101_1451_0119)，非当前十周年电脑端文本 | `test_liyu_takes_the_chosen_equipment_and_requests_duel_target` | `test_liyu_decline_does_not_take_a_card` | `test_liyu_without_any_target_card_does_not_prompt`；FAQ 要点已检查：受伤者决定、吕布选牌、决斗目标限制 |
| 鬼道 | 官方张角页 [hero/212](https://www.sanguosha.com/hero/212)（经典/OL文本，非十周年构建号） | `test_guidao_discards_selected_equipment_and_takes_original_judgment` | `test_guidao_decline_preserves_the_original_judgment_card`、`test_guidao_cancelled_cost_selection_keeps_original_and_cost` | 取消保留原判定牌与成本；替换牌区架构限制见上文 |
| 雷击 | 官方张角页 [hero/212](https://www.sanguosha.com/hero/212)（经典/OL文本，非十周年构建号） | `test_leiji_accepts_and_uses_the_selected_target_for_spade_result`、`test_leiji_club_judgment_recovers_and_damages_selected_target` | `test_leiji_decline_does_not_perform_judgment` | `test_leiji_also_prompts_when_lightning_is_used` 覆盖闪电路径；`test_leiji_with_no_living_target_does_not_request_player_choice` 覆盖无目标边界 |
| 闭月 | 当前十周年精确官方公开资料未找到；按仓库文本 | `test_biyue_accepts_and_draws_two_when_hand_is_empty`（空手）及 `test_biyue_draws_one_when_hand_is_not_empty` | `test_biyue_decline_skips_optional_end_phase_draw` | 两个手牌边界已分别覆盖 |

### 全将池技能版本覆盖缺口

上方“全将池覆盖”枚举了 `data/heroes.json` 中 27 名武将及所有 54 个技能的**项目实现状态**。版本核验方面，已找到的官方公开资料只覆盖上表注明的 OL/经典版技能，不存在可引用为“十周年电脑版全部 27 将、当前构建号”的官方公开规则目录。本轮没有对其余池技能逐条宣称官方版本一致；这些技能的准确版本证据均为“未找到/待核”，当前运行以仓库项目文本为准。这是有意明确的验收缺口，不把 active 标记当规则证据。

### Sol 蜀国机制场景补充

下列 14 个蜀国技能按仓库当前文本运行；本批未取得它们各自的十周年电脑版构建号证据。函数名均在 `tests/test_b5_shu_choices.py`，另注明的文件除外。锁定技没有人为添加拒绝选项。

| 技能 | 正常与边界证据 | 尚未单独证明 |
|---|---|---|
| 仁德 | `test_rende_gifts_two_distinct_players_before_virtual_card_becomes_available`；`test_rende_virtual_sha_resolves_after_last_hand_card_is_given`；`test_rende_virtual_card_rejects_stale_target_without_spending_once_per_turn_use`；浏览器真实点仁德、选牌再取消 | 濒死救援中的虚拟桃尚无独立场景 |
| 激将 | `test_jijiang_response_requires_donor_consent_and_card_selection`，首名供牌者拒绝后次名确认；30 局中合法拒绝另计数 | 主动借杀完整命中链 |
| 武圣 | `test_wusheng_and_longdan_offer_only_valid_conversion_cards`；`tests/test_game_stats.py::test_hand_card_loss_routes_through_unified_event` | 方片无距离限制的独立场景 |
| 义绝 | `test_yijue_target_chooses_shown_card_and_owner_can_decline_red_benefits`；`test_yijue_equipment_cost_is_legal_and_cancel_preserves_equipment`；`test_yijue_black_restricts_hand_and_nonlocked_skills_until_turn_end`；`test_yijue_and_tieqi_overlapping_sources_clear_only_their_own_effects` | — |
| 咆哮 | `test_paoxiao_dodges_accumulate_damage_then_spend_tokens`（含回合结束清标记） | — |
| 替身 | `test_tishen_decline_preserves_limited_charge_then_accept_consumes_once` | — |
| 观星 | `test_guanxing_uses_player_order_and_places_remainder_at_bottom`；`test_guanxing_decline_and_short_deck_preserve_cards` | — |
| 空城 | `test_kongcheng_mashu_and_qicai_passive_boundaries`（含暂时失效时仍禁止目标） | — |
| 龙胆 | `test_wusheng_and_longdan_offer_only_valid_conversion_cards`；现有装备交叉见 `tests/test_b4_equipment.py` | 每种响应的实体消耗逐一证明 |
| 涯角 | `test_yajiao_decline_preserves_deck_and_matching_reveal_uses_player_target`；`test_yajiao_mismatched_reveal_discards_selected_nearby_card` | — |
| 马术 | `test_kongcheng_mashu_and_qicai_passive_boundaries` | 特殊距离修改叠加 |
| 铁骑 | `test_tieqi_decline_does_not_judge_or_disable_target`；`test_tieqi_target_may_give_matching_card_to_avoid_extra_damage`；`test_tieqi_without_matching_card_prevents_dodge_and_adds_damage`（真实【杀】结算并在回合结束清理） | — |
| 集智 | `test_jizhi_decline_leaves_draw_pile_and_stats_untouched`；`test_jizhi_accept_draws_and_optional_basic_discard_increases_hand_limit` | 非基本牌摸取及弃牌失败边界 |
| 奇才 | `test_kongcheng_mashu_and_qicai_passive_boundaries`（含兵粮寸断无距离限制） | 装备被其他效果移动的交叉场景 |

## 浏览器与运行记录（最终）

- 实际命令：`SANGUOSHA_HISTORY_PATH=/tmp/sanguosha-b5b7-browser-history.json B5_PROFILE_ID=browser_b5b7_<唯一时间戳> PLAYWRIGHT_MODULE=/tmp/b4-browser-check/node_modules/playwright node scripts/manual/b5_b7_browser_check.cjs`。Seeder 同样要求显式设置临时 `SANGUOSHA_HISTORY_PATH`，拒绝写默认运行时档案。
- 最终实际 profile：`browser_b5b7_1792209926`；数据库在 `/tmp/sanguosha-b5b7-browser-history.json`。此唯一测试档预置两胜和身份卡；浏览器实点大厅“使用身份卡/主公”、选界刘备出战。工作区默认 `logs/runtime/game_history.json` 中此前试验的 3 个 `browser_b5b7_1792209796`、`_1792209826`、`_1792209852` 及其六条 synthetic game 已按唯一 ID 定向删除。
- 最终 Chromium：25 条记录、全部通过、0 跳过、0 pageerror。覆盖档案 ID 持久化/旧记录迁移提示/历史请求、身份卡扣用开局、五人局、120 秒真人回合倒计时可见、4:30 离席提醒计时已挂起、真实【仁德】点击/选手牌/取消/结束阶段、AI 座位详情、托管按钮/复制来源/自定义表单/规则与默认来源下发/关闭、战报页签、决策轨迹默认折叠及展开收起。
- 7A-7 提醒在客户端从首次观察到待操作 `your_turn` 或 `require_response` 起算，并由真人提交输入重启；服务端五分钟 watchdog 仍是唯一权威。浏览器重连时服务端目前未给前端 idle elapsed，不能恢复重连前已耗时间，需协议未来补充后才能完全精准。
- 专项测试（2026-10-17 更新）：`.venv/bin/python -m pytest -q tests/test_b5_wei_optional_skills.py tests/test_b5_wu_choice_triggers.py tests/test_b5_qun_optional_triggers.py`：63 passed。连营批量丢牌已覆盖 handler 的批量输入，但引擎目前通过逐张 `on_card_move` 回调；要验证一次性多牌移动仍需核心事件支持，此处不改核心。
- 更早的扩展回归（蜀场景与 `SkillStatsEdgeTest`）为 66 passed；本轮新增后未重跑该跨势力命令。`py_compile` 浏览器档案 seeder 通过，`node --check` 的游戏页、大厅及 Playwright 脚本通过（均为先前记录）。
