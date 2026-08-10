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

