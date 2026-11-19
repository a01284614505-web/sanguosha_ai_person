# 主线验收与下一阶段施工计划（2026-11-18）

基线：GitHub `a01284614505-web/sanguosha_ai_person`，`main@e454d03`（2026-10-25 19:06:52 +0800，PR #38）。以主线可运行源码为准；旧路线图的勾选仅作为索引。本文将代码存在、离线验收、真实浏览器验收、实机/真实模型验收分别表述，不互相替代。本次不施工联机、局内 UI 或新背景；仅在独立分支实现皮肤画廊模糊搜索，并增加导入测试。

## 一、完成度核验

| 子系统 | 主线实物与验收 | 判定 / 未完事项 |
|---|---|---|
| 五人身份局 | `MainEngine`、`ModeSpec`、`skill_manager.py`、54 运行技能；`data/heroes.json` 27 名内置武将；标准 108 张、扩展 53 张，军争合计 161；规则 AI 冒烟完整获胜结束 | 离线可玩。不能宣称 27 将逐技能均与十周年同版本客户端一致；认证文件 `rules_version_verified=false` |
| 牌与装备 | 牌堆、`card_system.py`、`card_flow.py`、伤害与响应；`test_b4_equipment`、`test_fire_attack_and_treasure_wuxie` 等通过；包括木牛流马和无懈链 | 已接线而非旧 ROADMAP 6C 的未实现状态；逐牌客户端行为仍需核对。card_kinds 清单为 42，数据记录条数与牌堆实体张数不是同一口径 |
| 选将 | `hero_draft.py` 和 `hero_draft_panel.js`，正式选将/自由选将；锁定内置或启用包的 canonical hero | 已实现，选将隐私与多真人仍未做 |
| AI 行为 | P0–P5：座位上下文、发言、行为账本、认知笔记、策略、称号与战绩；决策/响应/选择合法性与规则兜底测试通过 | 模型实际强度、真实 Provider、时延与缓存费用未验证。`AIGateway.call_ai` 没有 `reasoning_effort` 或提供商思考参数；目前 `thinking` 字段并不等同于真实启用推理能力，不能宣传已支持可调推理强度 |
| 聊天 | Stage T0–T3b，`chat_director.py`、`chat_panel.js`，真实规则事实与发言调度；离线测试通过 | 真实多模型连贯聊天和多人真人仍待验；本局聊天仅一个真人入口 |
| 暂停/离席/重连/存档 | `game_server.py` 的暂停、5 分钟离席、重连、托管、后台结算、`recovery.py`；存档安全点恢复测试通过 | 单人生命周期已实现；任意动作中途无损恢复未覆盖。多人逐席离线、恢复权限尚不存在 |
| 结算和战绩 | `game_stats.py`、`game_history.py`、`result.js`、历史页、公开事件播放器 | 真实结果而非写死；事件播放器不是完整可操作牌桌回放 |
| 多模式 | 后端 `mode_registry.py` 注册五人、八人、2v2、斗地主，F3 规则场景通过；`frontend/js/lobby.js` 的 `OPEN_MODES` 仅五人 | 不能把四种引擎模式说成四种玩家可用模式。其他模式需独立 AI 目标/提示词、UI 与验收后解锁 |
| UI | `game.html` 先后加载 `sgs.css`、`game.css`、`table_v3.css`、`hero_draft.css`、`table_m4.css`；10-25 #37/#38 有模拟移动端浏览器截图及局内响应、模型列表、Key 可见、连接诊断的记录 | 有响应式但非真机覆盖。自动竖屏已经存在，显式布局切换没有；本轮提供重构计划 |
| 皮肤 | `SkinStore` 按档案存图与选择，旧 IndexedDB 迁移；27 个默认原画；固定无名杀提交的候选表 307 项；服务器按需取图、校验 SHA/大小、缓存 | 无名杀固定来源功能已实现，不能写成旧 379 张包已到位；手工单图已有，任意仓库/压缩包批量导入没有 |
| 自定义武将 | `/api/heroes/import`、`/api/heroes/convert`、`/api/heroes/trial`；包启停、原子存储/备份、世界书；DSL 33/54 完整声明可编译，10 项行为对照及 4 补充场景、无已观察分歧 | 可执行受限 DSL，但文本转换默认 data_only，不自动转成运行技；不能以 DSL 表达率代替规则正确性；不支持直接执行无名杀 JS 扩展 |
| 部署与设备 | `start.sh`、`start_windows.ps1`，Linux 运行验证通过 | Windows、Android/Termux、不同内核、真实 TTS 权限未验。仓库合并不等于你手机正在访问的部署已更新 |

### 本次独立实测

- `python -m pytest -q` 第一次：1085 passed，3 failed，93 subtests passed。三个失败均在 `test_b6_gateway_http.py`，环境代理要求可选 `socksio`；只对本地测试进程解除继承代理变量后，同三项 3 passed。没有修改引擎来掩盖错误。
- `env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u http_proxy -u HTTPS_PROXY -u https_proxy python scripts/verify_project.py`：1088 passed、93 subtests passed；前端脚本语法、协议同步、两项实际 WS 冒烟通过，`VERIFY_OK`。冒烟完整非中断规则 AI 获胜结算。
- `node tests/hero_search.test.cjs`：通过（中文部分字符、非连续字符，拼音 ID 大小写、空格、全角、许褚旧 ID、无匹配、自定义 ID）。
- `python -m pytest -q tests/test_hero_import_templates.py`：6 passed，使用临时目录真实存入包、启用、注册、实例化引擎、执行，不直接篡改武将代替导入。测试覆盖内置 ID canonical/技能冲突、限定技失去体力、两个分支交替且阶段限次、普通/火/雷伤害。
- 加入新增用例后的整树再次运行 `verify_project.py`：1094 passed、93 subtests passed，模糊搜索 Node 测试、JS 语法、协议同步和真实双 WS 冒烟通过，`VERIFY_OK`。属性伤害样例验证了藤甲火伤 +1 以及属性/非属性伤害的横置状态差别。
- 认证元数据待同步：全量测试自动重算 `data/skill_parity_certification.json`，工作树仅引擎指纹及 `main_engine.py` 哈希两处发生变化，原主线所提交的认证指纹滞后；重算的行为对照仍无观察分歧。为避免将生成元数据误当作本次皮肤修改，未将其纳入提交。认证仍不代表同版本客户端规则正确性。
- 游戏服务已实际启动。尝试 Chromium/Playwright 进行局内设置点击及多视口实测，被执行环境 Chromium `socket() failed: Operation not permitted` 拦截（启动即退出）；不能把未能执行的页面测试标成通过。本轮 UI 结论因此是源码定位 + 已有 10-25 截图证据，不声称已复现或修复你的设备故障。历史报告 `20261025_mobile_bugfix_review.md` 使用 390×844、844×390、768×1024、1280×800；实际手机内核仍未验。

## 二、联机席位：建议技术路线与实施计划（待批准）

产品目标：一个人创建五人身份局房间，通过链接/房间码请好友加入，其余位置填规则 AI 或指定模型 AI。首期 2–5 真人可任意占位，开局后不能换走其他真人的座位。单人仍使用原有流程；选将、响应、技能、聊天、结算、个人战绩必须正常。不做 P2P/每人各运行一份引擎同步，也不先做公开在线匹配、好友账户系统、语音或局中抢座。

### 现有阻塞与改造原则

| 当前假设 | 必须替换 |
|---|---|
| `GameServer.viewers[game_id]=ws`，新连接替换旧连接；`ws_map -> game_id` | 房间和连接独立；同一房间多个 authenticated membership，每连接绑定不可伪造的 seat/player ID，可再有只读 observer |
| `GameState._init_players` 固定 0 真人、1..N-1 AI；`ModeSpec.ai_count=N-1` | `seats[]` 长度固定为 mode.player_count，每席具有 `controller=human/ai`、profile/AI config；保持古版 config 适配到 seat 0 human |
| `main_engine.human_player()` 返回首个非 AI；全局 trustee、离席、阵亡 | 每席 `SeatControl`，明确 `player_id`，各真人独立连接、托管、掉线状态与期限；一个人离开不会销毁其他人对局 |
| `serialize()` 0 号身份可见，`self_hand` 返回首真人，`game_server._client_state` 生成单份快照 | 生成 `serialize_for(viewer_player_id)` 的个性化数据；旁观者只有公共字段。不向多个客户端广播单人私有快照 |
| `do_action` 连接只判当前唯一 viewer；提交响应有 player_id 但默认为 0 | 服务端从认证绑定获取 actor；请求关联 player_id/请求 ID/版本，只允许本人当前合法动作；拒绝过期、重复和他席输入 |
| `game_main.js` `find(!is_ai)` 设置 G.meId，聊天 human 消息全部 `is_self=true` | 带 server-assigned `self_id`；相对坐次计算按本人旋转，消息根据 from_id 判自己；同一房间各设备布局完全独立 |
| `ws_client.js` 推算 HTTP 端口+1，80/443 使用 8889；单 profile/game_id 续局 | 同源 `/ws` (WSS) 反向代理优先、保留本地 8888/8889 fallback；房间凭证与 seat resume token 绑定，不依赖可复制的 profile_id 作访问授权 |

### 数据和消息模型

- 房间服务持有 room_id（随机）、邀请码（短期、限尝试）、mode_id、room_revision、host_id、phase（waiting/draft/running/finished）、座位、ready、是否带入自定义包与牌堆版本。同一房间只运行一个 `MainEngine`，公开信息在服务器权威结算。邀请码用于入房，不是长期鉴权；入房后签发独立的席位会话凭证，密码/密钥不进入 URL 日志。
- 房主选择人/AI、移除未准备的大厅成员、调整牌堆、选将模式、AI 配置、开局；客人仅能加入空真人席、选自己的席、设置昵称与准备。开局锁座与本局资源签名。已有房间观战另发只读凭证，不获取手牌、候选或隐藏身份。
- 示例新增协议：`room_create`/`room_join`/`room_state`/`room_seat_change`/`room_ready`/`room_start`/`room_leave` 与 `room_resume`，原 `PLAYER_ACTION/CHAT/RESUME_GAME` 扩展。消息含 `room_id, game_id, revision, client_action_id`；响应还需服务器签发 `request_id, candidate_version`。每条消息逐连接授权，动作经引擎已有校验后才能修改状态。不要让客户端任意提交 `player_id` 控制别的席。
- 公共事件：牌桌公开牌、公开角色、体力、装备、公开日志、公开聊天。私有事件：自己的手牌/身份、本人选将候选、私人选项、私密牌移动和本人请求。统一事件投影层，默认未分类字段不得发送给他席；`cheat_mode` 正式联机默认关闭且不允许中途开启。AI 秘钥保留服务端执行上下文，绝不进入给好友的状态或日志；真人客户端不能修改他人 AI 费用配置。
- 网络断开只将该席标为 disconnected；定时自动规则托管（可设 30 秒/60 秒，无人为配置时不额外模型费用），复联返回本人最新快照及仍有效待操作。取消整局、暂停及房主迁移策略由房间层做，建议仅房主可提议暂停，开局后离席默认托管，不自动结束整个房间；全部真人长期离线才全局暂停/终止，期限可沿用现有机制。
- 选将维持主公先选、其余座位独立并行候选，正式隐私；同一时刻多个待选请求由 actor 和 request_id 匹配。回合/无懈/救援以引擎既有顺序为准而非网络先到先赢；同局所有事件由单引擎事件循环序列化。动画 ACK 不阻塞规则或等待所有慢设备，使用各客户端本地动画队列，服务器上限短超时；重连跳到最新权威态。
- 结算以 `(game_id, profile_id/seat_id)` 幂等记账，身份卡扣费/退款也按真人各自；日志落盘分公开与当事人私有，API 验证会话权限。恢复快照版本升级要存成员/座位绑定、包指纹、规则状态；密钥不写明文可下载日志。重启区分未开局房间、进行中快照、完成结果。

### 可交付批次与验收闸门

| 批次 | 具体文件 / 施工 | 验收（不通过不得进入下一批） |
|---|---|---|
| M0 | 新 `room_registry.py`、席位与权限契约、`config_validator.py` 单人适配；固定规则 API 不变 | 新旧 config 等价；两个真人、三个 AI；五真人、无 Key 回退；房间人数、配置一致、重复准备、并发抢座 |
| M1 | `state_manager.py`/`main_engine.py` 逐席 controller、请求/响应、选将、托管；多视角序列化 | 每席只看自己的手牌/身份/候选/私密牌移动；顺序保持；两个真人轮流出牌、无懈、救援、可选技、超时取消；旧 1088+ 回归不降 |
| M2 | `game_server.py` 房间路由、身份认证、逐席发送、membership、心跳重连；协议版本及 `gen_protocol_js.py`；同源 WSS | 两个独立 WebSocket 实际 play/response/chat；错误席位、旧请求、重复动作、掉线和重连拒绝/恢复；只读观战；房不会被第二个客户端顶掉 |
| M3 | `lobby.js` 房间页面、席位操作、AI 预设、邀请码；`ws_client.js`、`game_main.js` `self_id`、前端待请求、聊天展示 | 两真实浏览器上下文开局，一桌 2人+3AI，双方看到不同手牌/同一公开状态；手机/PC 混合，交叉发言和响应，个人设置不互相覆盖 |
| M4 | `recovery.py`、`game_history.py` 按席持久化、恢复与结果支付；部署 `/ws`、TLS、会话安全边界 | 断网/后台/刷新/服务重启；房主离开不终止好友；两人最后看到一致胜负；每人仅一次结算；全真人掉线清理 |
| M5 | 长局回归与真模型小样本、资源限制、部署手册 | 至少 20 局 2人+3规则AI、5 局 3–5真人自动客户端压力模拟、不少于 2 局人类实玩、真模型连接和失败降级；记录房间延迟、待请求泄露/重复结算 0 |

建议先把 M0/M1 的隐私契约建稳；现在直接把 `viewers` 换成数组不是联机，因为手牌和请求会仍按第一真人生成。以上是联机阻塞的核心。首期不解锁八人/2v2/斗地主，以 5 人稳定性为目标。部署可复用你的现有服务器：HTTP+WS 同源反代，好友只开网页；AI 模型仍由房主服务器调用。并发房间数与模型调用上限需独立配置，不能无限开局。

## 三、牌桌 UI：诊断与施工计划（本轮未修改）

### 源码诊断

1. 主题/背景与布局是三个维度，不要混成一个选项。`global_settings.js` 只保存 `theme`（dark/light/system）、`table_palette`、`table_dim`，`sgs_common.js` 处理根 `data-theme`，`game_main.applyTablePalette()` 改 `#battle[data-palette]`；没有手动 `layout_mode`。因此“竖/横 UI 切不过去”目前是缺功能；“夜墨/暖纸切了没变化”则要进一步复现：牌桌背景色是独立 palette，light 只覆盖部分底栏、HUD 和侧栏，外观依旧可能像深色。已有事件接线，不可声称完全不存在主题切换。
2. `game.css`、`table_v3.css`、`table_m4.css` 三份牌桌级联分别定义尺寸、定位、相同断点；每批补丁覆盖旧规则，造成中间尺寸空档和定位耦合。M4 `max-width:600px and orientation:portrait` 已实现四对手上面一行，601–900×800 另作平板补丁；最短竖屏/窄平板或旋转仅靠旧媒体规则，易出现 HUD/武将/区域相撞。
3. `measureSeatRow()` 只在 `renderAll` 后计算 `--seats-b`，resize 监听只 `layoutHand()`。旋转、地址栏缩放、聊天键盘/字体载入引起布局变化，不一定重新测量对手区域与操作条；绝对定位中心区基于固定 64px 操作高度，候选按钮多时实际高度远大于 64px。`#field`/页面 `overflow:hidden` 会裁掉超出的部分。
4. `100dvh`、`aspect-ratio`、`clamp/min/max`、`display:contents`、CSS Grid、`<dialog>.showModal()`、optional chaining 等在旧 WebView 兼容性存在风险；`backdrop-filter` 有 `@supports` 但仍会耗 GPU。`100dvh` 单独使用而无 `100vh` 或实测视口回退，旧浏览器可能无法得到预期布局。M4 约 29–34px 工具按钮及 28px 技能键，小屏触控不达 ROADMAP 44px。实际稳定性需真机核实。
5. `saveGlobalSettings` 捕获 localStorage 写失败却仍 toast“已保存”，刷新后可能恢复旧值；设置主题变化每次 `renderAll`，应保留已选牌、目标、待响应请求和倒计时，避免把界面变化当状态清除。局内“打开设置页”直接导航，也与真正的局内切换不同。
6. 部署版本排查：`game.html` 的静态脚本/样式查询串、HTML no-store、服务端当前 commit 与浏览器实际加载资源需要一致。#38 已特别记录另一台服务可能仍跑旧代码，本仓库最新合并不能证明你手机 URL 已更新。排查先让用户提供访问 URL、系统/WebView 版本、屏幕 CSS 像素、复现步骤/截图、部署 commit；在局内切主题和 palette 各测一次，不同现象分别定位。

### 目标视觉/交互

- 竖屏：上方 4 位固定相对座序（上家开始顺时针），各自相同宽度，略呈弧形方向感但不严重高低错位；本人的武将与手牌在下方，对手和本人视觉上围绕中央牌桌。顶部 HUD 薄化、中央区域留足出牌、判定、亮牌池；响应操作独立于牌池、位于本人区域上方。设备越窄越采用紧凑标签/抽屉，不牺牲体力、身份、手牌数量、当前行动者、判定及木牛信息。四位并排时不要求全名都完整，但点击武将能看到完整状态。
- 横屏：2 位上方，左右近座分别靠两侧，自己底部；中间牌桌真正围桌；足够宽时聊天常驻，否则抽屉；自己的手牌可以横向拖动/查看，不被侧栏压缩到无法触摸。桌面布局不因手机布局切换而改变。
- 背景建议：用低饱和暗青绿/暖墨茶的木质桌边、轻微织物或宣纸质感与中心留白形成实体牌桌，而非重复高斯模糊的满屏远山。背景图放在卡片下面，人物与牌面不做高频纹理；弱光源集中于牌桌中心、暗化边缘。保留夜墨/暖纸 UI 主题及独立的背景选择，增加一套关纹理的低性能模式；用户可调压暗。先交付设计稿确认再接线，不盲改所有大厅页面。
- 选择 `layout_mode: auto | portrait | landscape`，auto 根据实际容器宽高；手动选模式即时更新 UI，无需重新开局或刷新连接。Web 页面不能保证锁定手机旋转方向：横版需要足够宽高时提示旋转，不使用 CSS 强行旋转整张 DOM（键盘/触摸/弹窗会错位），不足时可临时回退且说明。用户锁定方向与主题独立存储；浏览器 resize/视觉视口变化局内实时 reflow。

### 施工及验收顺序

| 批次 | 范围 | 验收 |
|---|---|---|
| U0 | 复现实际部署、收集计算样式/错误与版本；修复局内主题保存/应用/回填/刷新，建立设置和布局独立状态 | 夜墨↔暖纸、三个 palette、 dim、auto→手动重新切，共 20 次切换仍同 game_id、原手牌/目标/倒计时、无 DOM 异常；写入失败给提示 |
| U1 | 以 `game.html` 单套语义元素统一布局，提取 CSS tokens，收敛 CSS 冲突；绘制竖/横两个设计稿与背景三档 | 每个设备同一游戏DOM，四对手在上方和自己下方清晰可见；横屏围桌；不改引擎协议 |
| U2 | 保留 100vh 回退，enhance 100dvh；visualViewport/ResizeObserver 触发布局测量和手牌排布；中心区用 CSS Grid/flex 分配而非固定绝对高度；旧设备 dialog/原生 JS/图片与 blur 降级 | 320×568、360×640、390×844、412×915、844×390、667×375、768×1024、1280×800、1440×900；所有点击主热区≥44 CSS px（极小设备空间不足时用抽屉或全幅列表），无横向溢出、不遮住确定/取消 |
| U3 | 背景、名牌和动效接线，减少 GPU 成本，动画遵守 reduced motion；聊天抽屉、待响应、卡图、技能 tooltip 安全 | 真杀/闪/桃、无懈、五谷丰登、装备、木牛、判定、阵亡、托管、技能多选、聊天键盘打开、暂停、连接恢复逐项浏览器验证；界面切换不发任何额外游戏动作 |
| U4 | 实机回归（Android 10 旧 WebView/Chrome、Windows Edge/Chrome；可选 iOS Safari）；发布资源版本变更与兼容性检查 | 真机 2.6/4 英寸、常见手机/平板/桌面，CSS 像素与旋转各测；内存/帧率/首次加载/触控；发现不支持明确降级；记录独立截图和浏览器错误 |

UI 和联机可共享 `self_id`、相对座位、独立设置接口，但分支隔离：先 U0/布局契约，M1 只改变状态视角；U1–U4 再基于同一接口落地。切忌在 UI 修复里改技能规则。

## 四、导入排查、已改进及后续

### 皮肤

已实现的搜索修复：原 `skins_gallery.js:renderGrid()` 仅中文 name/title 的连续 `includes`，故输入英文 hero ID 或名字非连续片段不会匹配；现在 `hero_search.js` 使用 NFKC、大小写、去空格/下划线/连字符等分隔符、子串与顺序子序列，并含许褚 `xuchu/xuzhu` 别名。曹操可搜「曹」「界操」「CAO」「cao cao」「cc」，许褚可搜 `XUZHU`；自定义武将可按中文名、称号和既有英文字母 ID 查。搜索只用于候选筛选，绑定仍由点击的真实 `hero_id` 决定，不会自动把重名图套错将。未承诺任意中文自动转拼音或历史英文译名，后续结构化 alias 可补。

现有候选目录源为 `libccy/noname` 固定 `c9f9424...`，307 个条目，缓存按图，不是实时浏览任意 GitHub 仓库，也不是旧 379 张来源。`SkinStore` 校验图片魔数和宽高（64–2048）、单图上传 2 MiB、每档案 40 张/40 MiB，下载候选校验 git blob SHA。浏览器支持本地单图，服务器档案级同步。对真实 GitHub 连通性、所有 307 张能否从你的机器拉取，本轮未逐图验证；旧版本授权证明也不能直接推定每张图片商业再分发权。

后续改进：统一导入向导 `source_type: bundled_noname | github_repo | local_files | zip`；列出仓库/提交/路径和图片清单（GitHub owner/repo+ref，应解析到固定 commit，只读取支持的图片数据，不执行仓库代码），上传单图/多文件/ZIP，解析可选 `skin_manifest.json`（hero_id, aliases, path, label, source/license, hash）。先扫描出图数量/体积，图与将做匹配预览：精确 ID/已知 alias 优先，规范化中文连续匹配次之、模糊条目列候选，低置信度或多候选必须用户手动确认。不认识的图片可留待匹配。选择确认时才当作资源导入，默认不覆盖已选皮肤；错误不污染原映射，可以撤销导入批次。

存储建议引入资源 `asset_hash` 和批次 `pack_id/source_ref`；公共候选和自定义上传分别隔离，仍复用现有 profile→hero→skin 选择；分页、懒加载、缩略图、批量进度/取消、失败重试、有界资源配额。仓库/ZIP 导入采用服务端限定 GitHub API/raw 域名、固定 ref、强制图片体积/总数/压缩解包限制、验证路径、禁止执行脚本与归档内链接、原子写入。验收：两个同名将、不同拼音 ID、xuchu/xuzhu、歧义、未知将、损坏图、超限、断网重试、不覆盖旧选择、跨设备档案同步、批量撤销。

### 武将：现有转换机制与实测结论

1. 内置武将不是导入包自动生成的：`HeroRegistry` 直接载入 `data/heroes.json`，选将只信任 ID 并重建体力/势力/技能，运行技能来自已有注册处理器。若重新导入 ID `caocao`，会被拒绝；重名技能「奸雄」也会被拒绝，即便使用另一个 custom ID。不会自动复用已存在技能，也不能覆盖内置定义。
2. `hero_manager.html` 的文本转换仅把输入拆成技能名、描述、类型并标 `data_only`；它的类型识别仅覆盖主公、锁定、限定、觉醒，未识别转换技；技能描述里的多个冒号易被截断。AI 路径 `/api/heroes/convert` 的 prompt 明确要求 `implementation_status=data_only` 且不要生成 DSL，所以不是编译器，只是元数据转换。模型 JSON 对象需再校验，转换成功不代表技能可玩。
3. `/api/heroes/import` 只接受 package+hero JSON（每次一个），包默认关闭，需启用；`HeroPackageStore._validate_hero` 对 active 强制需要可编译 DSL。导入文本或 partial/data_only 只用于显示与世界书，不进入动作/事件；均不能声称为完整可玩武将。已启用 active DSL 能从注册表被引擎调用，不需要人工写 Python；测试已覆盖真实导入后技能执行。它编译 JSON 白名单，绝不会把任意自然语言或 JS 当代码执行。
4. `skill_dsl.py` 支持 16 个 trigger、四种交互、次数域 game/round/current_turn/phase/actor_turn、条件/状态/限次、普通火雷伤害；有受限 card_as/conversions、静态修饰器、判定等。转换技（阴阳）可用状态分支实现，但并非 UI 原生转换标签、自定义标记/觉醒技都自动支持。遇到超出白名单的时机/牌区/效果，应标明缺口并拒绝启用而不是让模型擅猜实现。

建议增加专用 `compile_draft` 路径，保留现有元数据转换：输入自然语言 → 明确规则槽位（时机/主体/次数/代价/目标/效果/取消语义） → 检索内置规则引用或按受限 DSL 模板生成 → 编译诊断 → 隔离真引擎试验（正例、取消、重复、错误目标、濒死/复联等） → 用户确认 → 标 active 并导入。原文、DSL、依据、试验 results 与引擎版本指纹关联；没有可执行覆盖的技能保持 `data_only` 并提示，不自动误启用。已有技能匹配须按稳定 `native_skill_id` 严格版本引用且经人工确认；不要以模糊名称匹配直接覆盖原生代码。官方版本导入时先找 canonical ID 或能力复用，若是其他版本应独立名称/ID，扩展能力不扰动 27 将旧规则。增加批量 JSON 武将包、预览逐将逐技能状态、拒绝原因与包整体原子导入；对无名杀特定 JSON 数据可适配，不直接执行其 JS 扩展。

### 通用技能提示词（可直接复制使用）

> 将三国杀技能文本转为当前仓库 SKILL_DSL v1 的声明草稿。原文不能补写规则；逐项提取触发时机、锁定/可选、限定/觉醒/转换、次数范围、发动者、消耗、合法目标、效果顺序、取消后果、伤害来源与属性、状态/标记、跨回合复位、边界条件；无依据请返回 `unsupported` 和解释，不虚构字段。输出 `name/description/type/implementation_status/dsl` 草稿与应通过的确定性场景。只有 `compile_skill` 和隔离引擎试跑通过、经用户确认的可执行技能才能设为 active。不要生成 Python/JS；不要对其他三国杀版本的规则做隐式替换。

用户可按如下格式填写，也可把完整官方技能原文粘进去：

```text
武将 ID：custom_example；名称：例将；势力：群；体力：4
技能名：示例技（限定技/转换技/锁定技/可选技）
时机：出牌阶段/准备阶段开始/受到伤害后（每次或每点，必须说明）
次数：每阶段/每回合/每轮/整局限 N 次（未发动或取消是否计次）
条件与代价：是否发动？弃何种牌/失去体力多少？
目标：自身/一名其他存活角色/伤害来源/受伤角色（数量约束）
效果顺序：摸 N 张；失去 N 点体力；或由指定来源造成 N 点普通/火焰/雷电伤害；是否有回复/判定
状态：初始阴或阳；成功后何时切换；持续多久；是否公开标记；取消是否保留状态
正例/反例：初始体力、手牌、阶段、选择、期望牌区变化/次数变化/事件顺序
```

常用 DSL 映射（以下片段使用 JSON 语义，放入实际 `dsl` 对象）：

| 文字 | 对应机制 |
|---|---|
| 限定技、整局一次 | `usage:{"scope":"game","limit":1}`，测试消耗及重复不可用 |
| 出牌阶段限 2 次 | `trigger:"play_action", usage:{"scope":"phase","limit":2}`（与每回合 current_turn 区分） |
| 每回合/每轮限一次 | `usage.scope:"current_turn"` / `"round"` |
| 失去 1 点体力 | `{"type":"lose_hp","target":"owner","amount":1}`，不同于伤害，不指定伤害属性 |
| 受到/造成一点伤害 | 若主动结算 `damage`，明确 `source`/`target`；若监听已受到伤害用 `damage_received` 及 `event.amount` 条件（每点伤害需另写重复语义，不能等同每次事件） |
| 普通、火、雷属性 | `{ "type":"damage", "target":"targets", "source":"owner", "amount":1, "damage_type":"normal" }`（替换为 fire / thunder；不要伪造冰属性） |
| 选择一名其他角色 | `targets:{"selector":"chosen_players","candidates":"alive_others","min":1,"max":1}` |
| 可选发动而非锁定 | `cost:[{"interaction":"ask_confirm","prompt":"是否发动？"}]`，锁定不加此交互 |
| 阴/阳转换 | `state.mode` 保存到 `locals.old_mode`，全部分支按旧值处理，成功后选一个方向写入 `set_state`（不能按刚写入的新值触发第二方向）；配 `usage`；见本次已验证的 `tests/test_hero_import_templates.py` |
| 牌转化 | `conversions` 限定来源 names/color/suits 与目标 as；不是阴阳转换技。目标牌及响应/主动合法性遵循 DSL 白名单和引擎规则 |

示例，整局限一次的技能「消耗体力」：

```json
{"version":1,"trigger":"play_action","usage":{"scope":"game","limit":1},"effects":[{"type":"lose_hp","target":"owner","amount":1}]}
```

试运行应包括：初始 4 血第一次→3 血，整局第二次不可用，非出牌阶段不可用；若技能声称受到伤害时触发，失去体力不能误当伤害。转换技做阴→阳→阴、取消不切换、达到阶段次数上限不可继续；属性伤害测试普通/火/雷单独走正确结算，并增加防具、连环、濒死的正式规则回归。本文 6 个专项用例只证明样例在导入后真实可执行，不等价于全部上述边界均已验证。

### 推荐实施优先级

I0：模糊查找（本分支已实现）；I1：补导入预览/清晰状态/文本解析与现有技能引用/DSL 草稿编译诊断；I2：隔离试验覆盖次数状态、阴阳、目标/代价取消、属性伤害与 UI 显示；I3：批量武将包与仓库/ZIP皮肤向导；I4：真机与真实模型验收。与联机共享的认证和资源快照接口应先定义，再允许联机房间启用非公共武将/皮肤。任何施工前可按独立 PR 的回归结果审查，避免把未验的导入项混成已完成。

## 五、用户补充要求：八人竖屏、实际取消故障与导入语义闸门

### 八人布局是开放条件，不应只为五人重构

- `ModeSpec` 已有八人规则，但 `OPEN_MODES` 仅五人。后续八人解锁必须同时通过八人竖屏与横屏、模式 AI 提示词和实际长局验收。不能以手机不适合为由开放后又隐藏其他座位/强制中断对局。
- 竖屏八人：七名对手优先采用紧凑的 4+3 两行环桌布局（保持顺时针顺序，第二行反向排列以形成环桌方向；显示永久座位号及当前行动高亮），本人在最下方。不可把七将缩成单排，也不通过分页隐藏可选目标。320/360 CSS px 宽可切紧凑头像+体力/手牌/身份/关键标记，详情点开抽屉；中央牌桌留固定最低可用空间，装备与技能详览由抽屉承担。所有座位仍是可靠目标热区，允许辅助目标列表但不隐藏座位。横屏八人建议 3 上、左右各 2、自身下方；5/8/4/3人共享动态 seat layout，而非新增独立页面。以引擎 seat_map 为权威，不因排序、死亡、旋转改变逻辑距离与目标 ID。
- U0–U4 在五人和八人运行时同时测试：无懈多层、救援、多个目标/五谷丰登、8 人装备/判定信息、聊天键盘、小屏旋转与重连，切布局不中止游戏或清除请求。最窄屏只允许视觉降级，禁止改变合法操作。

### 实际 bug：无懈询问点击“不使用”失败

本次用真实 `CardSystem.ask_wuxie` 构造 AI 使用无中生有、真人有一张无懈的局面，经 `submit_action` 发送 `cancel:true`，服务端返回 `accepted`，锦囊未被取消，真人无懈仍在手牌，pending=0。新增真实链测试 `test_wuxie_pass_through_real_chain_preserves_card`，`tests/test_cancel_response.py` 共 5 项通过。故不能把实际设备现象归因于引擎不接受取消。

前端确认存在的缺陷：`game_main.js` 的 `sendCancel()/sendResponse()` 在 WS 发送后立即 `clearRequest()`；`ws_client.js.playerAction()` 若未连接直接 return；`onActionResult` 对拒绝仅显示 toast，未恢复可操作请求。断线、正在切托管、暂停竞争、迟到/未达请求可能令界面关闭而服务端仍等待。未能在用户设备重现具体失败，不断言唯一根因；此复现应加入 UI 修复批次优先项，不能只看旧测试或重新设计背景。

修订 U0：将提交状态分为 editing→sending→accepted/resolved 或 invalid/stale/transport_error；发送成功前不隐藏请求，按 request_id 匹配回执防止旧 ACK 清掉新请求；拒绝时恢复合法操作、已过期时服务器取权威 pending、断线重连恢复待操作及剩余时间；按钮提示“正在提交”，防重复但不吞按键。分别做「不使用」空选、先选牌再取消、真实反无懈、短时断网、服务重启/重连、暂停、服务端拒绝场景，验证同局牌区与进程继续。用户设备与真实部署资源版本记录后做真实浏览器点击，不以协议注入代替真链。

### 自定义武将不是仅验证 JSON 语法

新的 [武将设计与世界书导入规范](../../HERO_DESIGN_SPEC.md) 已提供当前可读 JSON 例、两个样例技能的 DSL v2 提案、非法描述的实测结果与语义闸门、官方版本证据与测试矩阵。用户给的黑闪转火杀首牌伤害+1、无防具且伤害大于1减一，**当前不能完整执行**：缺虚拟火杀属性、使用序号/效果上下文和伤害修正 hook；`damage_received` 是实伤之后。导入器接受了故意冲突的 locked/普通/限定声明，且无法识别语义错误。应优先做能力/字段/类型/生命周期/文案一致性验证，而非让 AI 任意把 unsupported 改成 active；内置官方原文只能引用或准确编译，不能为迁就实现而重写官方规则。
