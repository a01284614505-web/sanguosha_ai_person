# A–F 剩余工作与证据台账

日期：2026-10-20（UTC）；基线 `aa258553`。本台账以整合树代码和既有验证报告为准，后续每批补实际命令与退出码。

| 范围 | 已实现且有离线证据 | 待补或待独立验收 |
|---|---|---|
| A | 14 项规则场景、三牌堆 30 局及整合回归 | 逐技能同版本规则核验仍为 0 项，不把通用规则场景算进去 |
| B | 四类真引擎试验、隔离；10 项 Python/DSL 场景及拒绝/取消/死亡/交叉补充；内容和引擎版本指纹认证、管理页逐项展示，临时服务真实 API 浏览器通过 | 同版本客户端逐技能规则核验仍为 0；分支矩阵未穷举 |
| C | 四开关消融、公开轨迹与基础策略；本轮补主动制衡/苦肉、清俭受益者、鬼才/鬼道对三种延时锦囊的公开关系和判定结果判断；独立真实引擎场景 14 项通过、16 局消融复验 | 其他判定种类、牌类与关系组合及足够样本的效果分析；未知关系与未知判定原因保守拒绝 |
| D | 出牌/响应/选择共用权威公开/私有视图；当前弃牌与历史分离；L0/L1 缓存前缀和总/可变字符阈值 | 历史摘要新增压缩时事件序号边界；现有字符阈值触发压缩，超大单条当前状态或稳定前缀可使输入超过阈值，仍需严格预算与真实 Provider 事实/费用/延迟/缓存验收 |
| E | 阵亡三选、只读观战、后台结算/恢复、公开文本事件播放器、ACK 指标；E1 独立复核、E4/E5 页面及多模式真实 WS 浏览器场景已过 | E2 不含完整牌桌回放 |
| F1/F2 | 浏览器本地皮肤、27 张默认图盘点、安全按需复制工具；四模式 `ModeSpec` | 379 张外部资源包未在本机找到，需用户提供；不能把 27 张默认图当 379 皮肤 |
| F3 | 八人身份、2v2、斗地主后端规则、确定性场景、各 10 局完整对局与战绩；前端动态模式接线与临时服务真实 WS 浏览器开局/结算通过 | 规则依据以本仓库冻结契约为准，非同版本客户端逐项证据 |
| F4 | 带版本 JSON 安全点存档、进程重启恢复、旧请求失效、牌一对一校验、幂等结算；独立审查与进程级测试通过 | 仅整回合安全点恢复；未证明任意指令中途零进度丢失或断电持久性 |
| F5 | Linux/Termux 启动脚本及 Windows 路径回退；Linux 依赖预检通过 | Windows、Android/Termux 实机启动、保存、重连、路径和编码待验 |
| F6 | 浏览器独立 TTS 开关、公开事件播报、非阻塞失败回退；模拟浏览器检查通过 | 实机语音与浏览器声音权限待验 |

本轮负责人已执行：

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /root/sanguosha_ai_person/.venv/bin/python -m pytest -q tests/test_plan_c_ai_second_batch.py tests/test_plan_c_ai_ablation.py tests/test_plan_c_ai_privacy.py --tb=short -p no:cacheprovider
退出码 0；9 passed

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /root/sanguosha_ai_person/.venv/bin/python -m pytest -q tests/test_plan_d_ai_context.py tests/test_ai_session_cache.py tests/test_plan_c_ai_second_batch.py --tb=short -p no:cacheprovider
退出码 0；28 passed

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /root/sanguosha_ai_person/.venv/bin/python -m pytest -q tests/test_plan_c_ai_second_batch.py tests/test_plan_c_ai_ablation.py tests/test_plan_c_ai_privacy.py tests/test_plan_a_rules.py --tb=short -p no:cacheprovider
退出码 0；24 passed

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /root/sanguosha_ai_person/.venv/bin/python -m game_engine.skill_parity_certification
退出码 0；report_is_current=True，10 项

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /root/sanguosha_ai_person/.venv/bin/python scripts/verify_project.py --skip-ws
退出码 0；981 passed、50 subtests passed；JS 语法与协议同步通过。完整 stdout：logs/reports/20261020_final_verify_project.log
```

固定端口 8888/8889 被原有服务占用，本轮脚本跳过其 WS 冒烟。上述结果不代表真实模型接口、同版本客户端规则或缺失设备/资源验收。
