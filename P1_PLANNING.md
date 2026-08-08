# 🎯 AI三国杀酒馆 - P1阶段任务策划书

**文档版本：** v1.0  
**策划日期：** 2026-08-04 19:15  
**策划者：** AI总设计师（小万）  
**当前基线：** P0任务完成，完整版牌堆上线，27将54技能验收通过

---

## 📋 一、执行摘要

### 1.1 阶段目标

P1阶段聚焦于**游戏体验完整性与视觉反馈增强**，基于P0已完成的核心玩法和完整牌堆系统，实现：

1. **真人回合外响应与托管系统**：让玩家可自主选择是否响应（闪、无懈等），支持托管模式切换
2. **AI牌面视觉优化**：使用完整版noname卡牌资源优化AI出牌显示
3. **武将皮肤系统**：紧凑武将牌布局，支持皮肤切换、本地资源扫描、图片导入

### 1.2 优先级决策依据

**参考CHRONICLE第十三章用户反馈：**
- P0-1（日志移动）：已完成 ✅
- P0-2（手动弃牌）：暂缓至P2，因需完整版牌堆支撑
- **P1-1（回合外响应）：** 高优先级，直接影响策略深度（卖血、骗无懈）
- **P1-2（AI牌面优化）：** 中优先级，提升AI对局可读性
- **P1-3（皮肤系统）：** 中优先级，提升视觉辨识度

### 1.3 成功标准

| 指标 | 目标 | 验收方式 |
|------|------|---------|
| **回合外响应率** | 100%覆盖（闪、无懈、桃） | 自动化测试+真人对局 |
| **托管切换** | <500ms | 性能测试 |
| **AI出牌识别** | 牌面清晰可见 | 真人可读性测试 |
| **皮肤切换** | 支持379个皮肤 | UI交互测试 |
| **无回归** | 54技能全部保持运作 | 回归测试套件 |

---

## 🏗️ 二、架构设计

### 2.1 系统架构图

```
┌─────────────────────────────────────────────────────────┐
│                    P1 架构层次                          │
├─────────────────────────────────────────────────────────┤
│  前端层 (frontend/)                                      │
│  ├─ 回合外响应UI (response_panel.js)                     │
│  ├─ 托管控制面板 (托管开关+配置选择器)                     │
│  ├─ AI牌面渲染器 (使用完整版卡牌图片)                     │
│  └─ 皮肤管理器 (skin_manager.js + 皮肤选择modal)         │
├─────────────────────────────────────────────────────────┤
│  服务器层 (game_server.py)                              │
│  ├─ 回合外响应协议 (response_required, submit_response)  │
│  ├─ 托管状态管理 (托管模式切换API)                        │
│  └─ 皮肤切换API (switch_skin)                           │
├─────────────────────────────────────────────────────────┤
│  引擎层 (game_engine/)                                   │
│  ├─ 回合外响应管理器 (response_manager.py)               │
│  │  ├─ _wait_for_shan() - 等待真人/AI出闪                │
│  │  ├─ _wait_for_wuxie() - 等待无懈响应                  │
│  │  └─ _wait_for_tao() - 等待濒死救援                    │
│  ├─ 托管决策器 (auto_play_manager.py)                   │
│  │  ├─ 全局AI配置复用                                    │
│  │  ├─ 场上AI镜像                                        │
│  │  └─ 规则脚本兜底                                      │
│  └─ 皮肤配置管理器 (skin_config_manager.py)             │
│     ├─ 本地资源扫描                                      │
│     ├─ 皮肤清单生成                                      │
│     └─ 图片导入验证                                      │
└─────────────────────────────────────────────────────────┘
```

### 2.2 数据流设计

#### 2.2.1 回合外响应流程

```
[引擎] 触发响应请求（如：被杀）
   ↓
[引擎] emit('response_required', {
   type: 'shan',
   player_id: 0,
   timeout: 15000,
   allowed_cards: ['shan', ...]
})
   ↓
[服务器] 转发 → WebSocket → 前端
   ↓
[前端] 显示响应面板（手牌高亮+跳过按钮）
   ↓
[用户] 选择：出闪 / 跳过
   ↓
[前端] submit_response({type: 'shan', card_id: 'xxx'}) / skip_response()
   ↓
[服务器] → 引擎 response_manager
   ↓
[引擎] 结算响应结果
```

#### 2.2.2 托管模式决策流程

```
[用户] 点击托管按钮 → 选择模式
   ↓
模式选项：
├─ 全局AI配置（复用当前设置）
├─ 镜像场上AI（选择某个AI武将的配置）
├─ 独立托管配置（预设保守/激进策略）
└─ 规则脚本（完全确定性，无AI调用）
   ↓
[服务器] 更新托管状态
   ↓
[引擎] 真人回合自动决策（auto_play_manager）
```

#### 2.2.3 皮肤切换流程

```
[用户] 点击武将头像 → 打开皮肤选择器
   ↓
[前端] 加载皮肤清单（skin_manifest.json）
   ↓
[用户] 选择皮肤 → 确认
   ↓
[前端] POST /api/switch_skin {hero_id, skin_id}
   ↓
[服务器] 更新皮肤配置（skin_config.json）
   ↓
[前端] 重新加载武将头像
```

---

## 📐 三、详细任务分解

### 任务P1-1：真人回合外响应与托管系统

#### 3.1.1 任务目标
让玩家可以自主决定是否响应回合外牌（闪、无懈、桃），支持托管模式在自动/手动间无缝切换。

#### 3.1.2 技术方案

**引擎层：response_manager.py（新建）**

```python
class ResponseManager:
    """回合外响应管理器"""
    
    async def request_shan(self, player_id: int, attacker_id: int, timeout: int = 15):
        """请求出闪响应"""
        if player_id == 0 and not self.game_state.auto_play:
            # 真人手动响应
            result = await self._wait_player_response('shan', timeout)
            return result.get('card_id') if result else None
        else:
            # AI或托管
            return await self._ai_decide_shan(player_id, attacker_id)
    
    async def request_wuxie(self, player_id: int, target_card, timeout: int = 10):
        """请求无懈可击响应"""
        # 多人轮流无懈时机
        # 实现链式响应机制
        pass
    
    async def request_tao(self, dying_player_id: int, timeout: int = 15):
        """请求濒死救援"""
        # 按座次顺序询问所有玩家
        pass
```

**协议扩展（game_server.py）**

```python
# 新增消息类型
'response_required'   # 引擎 → 前端：要求响应
'submit_response'     # 前端 → 引擎：提交响应
'skip_response'       # 前端 → 引擎：跳过响应
'toggle_auto_play'    # 前端 → 引擎：切换托管
```

**前端UI（response_panel.js）**

```javascript
class ResponsePanel {
    show(type, allowed_cards, timeout) {
        // 显示响应面板
        // 高亮可用手牌
        // 显示倒计时
        // 显示"跳过"按钮
    }
    
    hide() {
        // 隐藏面板
        // 清除高亮
    }
}
```

**托管系统（auto_play_manager.py）**

```python
class AutoPlayManager:
    """托管决策管理器"""
    
    def __init__(self, mode: str = "global_ai"):
        self.mode = mode  # global_ai | mirror_ai | preset | script
        self.mirror_target = None
    
    async def decide_play_card(self, player, hand, actions):
        """托管出牌决策"""
        if self.mode == "global_ai":
            return await self._use_global_ai(player, hand, actions)
        elif self.mode == "mirror_ai":
            return await self._mirror_ai_decision(player, hand, actions)
        elif self.mode == "preset":
            return self._preset_strategy(player, hand, actions)
        else:
            return self._script_fallback(player, hand, actions)
```

#### 3.1.3 测试清单

- [ ] 被杀时可选择出闪或跳过
- [ ] 无懈时机正确触发（使用锦囊时、判定阶段）
- [ ] 濒死时按座次顺序询问
- [ ] 超时自动跳过
- [ ] 托管模式切换流畅
- [ ] 托管决策合理（不送人头）
- [ ] AI回合外响应保持原有逻辑

#### 3.1.4 文件修改清单

**新建文件：**
1. `game_engine/response_manager.py`
2. `game_engine/auto_play_manager.py`
3. `frontend/js/response_panel.js`

**修改文件：**
1. `game_engine/main_engine.py` - 集成response_manager
2. `game_engine/card_system.py` - 调用response_manager
3. `game_server.py` - 添加响应协议
4. `frontend/game.html` - 响应面板UI
5. `frontend/js/ws_client.js` - 响应事件监听

---

### 任务P1-2：AI牌面视觉优化

#### 3.2.1 任务目标
使用P0-3提取的完整版noname卡牌资源，优化AI出牌时的视觉显示，让玩家清晰看到AI使用了什么牌。

#### 3.2.2 技术方案

**前端渲染优化（game_render.js）**

```javascript
function renderAICardPlay(player_id, card_name, card_suit, card_rank) {
    // 使用完整牌面图片
    const card_img_path = `/assets/cards/${card_name}.png`;
    
    // 创建飞行动画
    const card_el = createCardElement(card_img_path, card_suit, card_rank);
    animateCardFly(card_el, from=player_id, to='center');
    
    // 显示牌名+花色点数
    showCardInfo(card_name, card_suit, card_rank);
}
```

**牌面映射表（card_display_map.json）**

```json
{
  "sha": {"zh": "杀", "color": "red"},
  "shan": {"zh": "闪", "color": "green"},
  "tao": {"zh": "桃", "color": "pink"},
  "jiu": {"zh": "酒", "color": "yellow"},
  "tiesuo": {"zh": "铁索连环", "color": "gray"},
  "bingliang": {"zh": "兵粮寸断", "color": "purple"}
}
```

**动画增强：**
- AI出牌时显示完整牌面（500ms）
- 飞行到中央弃牌堆
- 淡出消失

#### 3.2.3 测试清单

- [ ] AI出杀显示完整牌面
- [ ] AI使用锦囊可清晰识别
- [ ] 花色点数显示正确
- [ ] 动画流畅不卡顿
- [ ] 真人手牌显示不受影响

#### 3.2.4 文件修改清单

**新建文件：**
1. `frontend/js/card_display_map.json`

**修改文件：**
1. `frontend/js/game_render.js` - AI出牌渲染逻辑
2. `frontend/game.html` - CSS动画样式

---

### 任务P1-3：武将皮肤系统

#### 3.3.1 任务目标
实现武将皮肤切换系统，支持379个noname皮肤，紧凑武将牌布局，提升视觉辨识度。

#### 3.3.2 技术方案

**皮肤配置管理器（skin_config_manager.py）**

```python
class SkinConfigManager:
    """皮肤配置管理器"""
    
    def scan_local_skins(self) -> Dict:
        """扫描本地皮肤资源"""
        skins = {}
        for hero_dir in (self.skin_root / "heroes").iterdir():
            hero_id = hero_dir.name
            skin_files = list(hero_dir.glob("*.jpg"))
            skins[hero_id] = [
                {"id": f.stem, "path": str(f)}
                for f in skin_files
            ]
        return skins
    
    def switch_skin(self, hero_id: str, skin_id: str) -> bool:
        """切换武将皮肤"""
        # 更新skin_config.json
        # 验证皮肤文件存在
        pass
    
    def import_custom_skin(self, hero_id: str, image_path: str) -> bool:
        """导入自定义皮肤"""
        # 验证图片格式
        # 复制到皮肤目录
        # 更新清单
        pass
```

**皮肤清单生成器**

```python
def generate_skin_manifest():
    """生成皮肤清单JSON"""
    manifest = {
        "heroes": {}
    }
    
    # 遍历extracted_resources/heroes
    for hero_dir in Path("extracted_resources/heroes").iterdir():
        hero_id = hero_dir.name
        skins = []
        for skin_file in hero_dir.glob("*.jpg"):
            skins.append({
                "id": skin_file.stem,
                "name": skin_file.stem.replace(hero_id, "").strip("_"),
                "path": f"/assets/heroes/{hero_id}/{skin_file.name}"
            })
        manifest["heroes"][hero_id] = skins
    
    return manifest
```

**前端皮肤选择器（skin_selector.js）**

```javascript
class SkinSelector {
    async show(hero_id) {
        // 加载该武将的皮肤列表
        const skins = await fetch(`/api/get_skins?hero=${hero_id}`).then(r => r.json());
        
        // 显示modal弹窗
        // 网格展示皮肤缩略图
        // 点击选择
    }
    
    async applySkin(hero_id, skin_id) {
        await fetch('/api/switch_skin', {
            method: 'POST',
            body: JSON.stringify({hero_id, skin_id})
        });
        
        // 刷新头像
        document.querySelector(`#hero-${hero_id} img`).src = newSkinPath;
    }
}
```

**武将牌布局优化（game.html CSS）**

```css
.ai-hero {
    /* 缩减无效空间 */
    padding: 4px;
    
    /* 皮肤成为主体 */
    .hero-avatar {
        width: 80%;  /* 之前可能是50% */
        height: 80%;
    }
    
    /* 武将名小字显示 */
    .hero-name {
        font-size: 12px;
        position: absolute;
        bottom: 2px;
    }
}
```

#### 3.3.3 测试清单

- [ ] 皮肤清单生成正确（379个）
- [ ] 点击武将头像打开皮肤选择器
- [ ] 皮肤切换实时生效
- [ ] 自定义皮肤导入成功
- [ ] 武将牌布局紧凑不拥挤
- [ ] 无名杀资源正确映射

#### 3.3.4 文件修改清单

**新建文件：**
1. `game_engine/skin_config_manager.py`
2. `frontend/js/skin_selector.js`
3. `data/skin_manifest.json` - 皮肤清单
4. `data/skin_config.json` - 当前选择

**修改文件：**
1. `game_server.py` - 皮肤API
2. `frontend/game.html` - 武将牌CSS
3. `frontend/js/game_render.js` - 皮肤加载逻辑

---

## 🔄 四、并发执行方案

### 4.1 任务依赖分析

```
P1-1 (回合外响应)  ←─ 无依赖，可立即开始
   ↓ (部分依赖：托管需要AI决策接口)
   
P1-2 (AI牌面优化) ←─ 依赖P0-3资源 ✅
   ↓ (独立任务)
   
P1-3 (皮肤系统)   ←─ 依赖P0-4资源 ✅
   ↓ (独立任务)
```

### 4.2 并发分配策略

**方案A：三路并行（推荐）**

```
时间轴：
00:00 - 00:10  准备阶段（快照、规划确认）
   ↓
00:10 - 02:00  [并行阶段1] 三路同时开发
   ├─ [Track 1] P1-1 回合外响应（引擎层） - 1.5h
   ├─ [Track 2] P1-2 AI牌面优化（前端层） - 0.5h
   └─ [Track 3] P1-3 皮肤系统（全栈）     - 1.5h
   ↓
02:00 - 03:00  [并行阶段2] 协议集成与联调
   ├─ [Track 1] P1-1 托管系统 + 前端UI
   ├─ [Track 2] P1-2 动画优化
   └─ [Track 3] P1-3 皮肤API + 前端集成
   ↓
03:00 - 04:00  [串行阶段] 集成测试
   ├─ 回合外响应测试
   ├─ AI牌面显示测试
   └─ 皮肤切换测试
   ↓
04:00 - 04:30  验收与文档更新
```

**总耗时：** 约4.5小时

**优势：**
- P1-2独立性强，可快速完成
- P1-1和P1-3并行不冲突
- 集成测试统一进行

---

## 🎯 五、验收标准

### 5.1 功能验收

| 功能模块 | 验收项 | 通过标准 |
|---------|-------|---------|
| **回合外响应** | 被杀出闪 | 手牌高亮，可选择/跳过 |
| | 锦囊无懈 | 多人轮流无懈时机正确 |
| | 濒死救援 | 按座次询问，超时跳过 |
| | 托管切换 | <500ms，决策合理 |
| **AI牌面** | 出牌显示 | 完整牌面可见500ms |
| | 动画流畅 | 无卡顿，60fps |
| **皮肤系统** | 皮肤数量 | 379个全部可选 |
| | 切换速度 | <200ms |
| | 自定义导入 | 支持jpg/png |

### 5.2 性能验收

| 指标 | 目标 | 测量方式 |
|------|------|---------|
| 响应超时 | 15s（闪）、10s（无懈） | 前端倒计时 |
| 托管切换 | <500ms | Performance API |
| 皮肤加载 | <200ms | Network面板 |
| 内存增加 | <50MB | Chrome DevTools |

### 5.3 兼容性验收

- [ ] 54技能全部无回归
- [ ] 完整版牌堆正常运作
- [ ] P0-1日志面板不受影响
- [ ] 横竖屏切换正常

---

## 📊 六、风险评估

### 6.1 技术风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 无懈链式响应复杂 | 🟡中 | 🔴高 | 先实现单次无懈，链式响应P2扩展 |
| 托管AI调用超时 | 🟡中 | 🟡中 | 设置3s超时，兜底规则脚本 |
| 皮肤资源占用大 | 🟢低 | 🟡中 | 懒加载，缩略图缓存 |
| 回合外响应卡死 | 🟡中 | 🔴高 | 强制15s超时机制 |

### 6.2 进度风险

- **P1-1复杂度高**：预估1.5h可能不足，预留0.5h缓冲
- **皮肤系统UI细节**：modal弹窗交互需仔细调试

---

## 🔐 七、数据安全与隐私

### 7.1 API密钥使用

- 托管模式调用AI需使用用户提供的临时密钥
- 创建临时配置文件 `/tmp/ai_config_temp.json`
- 测试完成后删除临时文件

### 7.2 自定义皮肤验证

- 仅允许jpg/png格式
- 文件大小限制<5MB
- 验证图片尺寸合理（>100x100）
- 防止路径遍历攻击

---

## 📅 八、里程碑计划

### Milestone 1：引擎层完成（1.5h）
- [ ] response_manager.py实现
- [ ] auto_play_manager.py实现
- [ ] 协议扩展完成

### Milestone 2：前端UI完成（1.5h）
- [ ] 响应面板UI
- [ ] AI牌面优化
- [ ] 皮肤选择器modal

### Milestone 3：集成测试（1h）
- [ ] 回合外响应测试通过
- [ ] AI牌面显示验证
- [ ] 皮肤切换验证

### Milestone 4：文档与交付（0.5h）
- [ ] 更新CHRONICLE
- [ ] 生成测试报告
- [ ] 同步备份

---

## 📝 九、后续P2任务预告

基于P1完成后的系统状态，P2任务初步规划：

1. **P2-1：真人与AI手动弃牌**
   - 依赖：P1-1回合外响应机制
   - 复用：响应面板UI框架

2. **P2-2：延时锦囊完整支持**
   - 兵粮/乐不思蜀可无懈
   - 判定牌改判机制

3. **P2-3：结算界面得分与MVP**
   - 击杀/助攻/存活加权
   - MVP算法实现

---

## ✅ 十、策划书确认

**策划目标明确：** ✅  
**技术方案可行：** ✅  
**资源依赖就绪：** ✅（P0-3、P0-4资源已提取）  
**风险评估完整：** ✅  
**并发方案合理：** ✅  

**准备就绪，等待执行指令。**

---

**附录A：参考文档**
- CHRONICLE第十三章：移动端交互反馈与次日实施方案
- P0-5任务报告：可配置牌堆系统
- skill_runtime_acceptance_20260803.json：技能验收基线

**附录B：工具清单**
- AI模拟测试脚本：test_ai_simulation.py
- 皮肤清单生成器：generate_skin_manifest.py（待开发）
- 响应测试套件：test_response_system.py（待开发）
