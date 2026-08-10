// 全局设置入口：自动注入到所有页面，设置保存在localStorage。
(function () {
    const STORAGE_KEY = 'globalSettings';
    const defaults = {
        animation_ms: 1100,
        show_ai_thinking: true,
        worldbook_enabled: true,
        custom_worldbook_enabled: true,
        default_provider: 'deepseek',
        default_model: 'deepseek-chat',
        default_temperature: 0.8
    };

    window.getGlobalSettings = function () {
        try {
            return Object.assign({}, defaults, JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'));
        } catch (_) {
            return Object.assign({}, defaults);
        }
    };

    window.saveGlobalSettings = function (settings) {
        const merged = Object.assign({}, defaults, settings || {});
        localStorage.setItem(STORAGE_KEY, JSON.stringify(merged));
        window.dispatchEvent(new CustomEvent('global-settings-changed', { detail: merged }));
        return merged;
    };

    function injectStyle() {
        if (document.getElementById('globalSettingsStyle')) return;
        const style = document.createElement('style');
        style.id = 'globalSettingsStyle';
        style.textContent = `
            #globalSettingsLauncher{position:fixed;top:8px;right:8px;z-index:3000;width:34px;height:34px;border-radius:50%;border:2px solid #d4af37;background:rgba(35,26,21,.96);color:#d4af37;font-size:17px;display:flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:0 3px 12px rgba(0,0,0,.4)}
            #globalSettingsOverlay{display:none;position:fixed;inset:0;z-index:5000;background:rgba(0,0,0,.76);padding:12px;align-items:center;justify-content:center;color:#f5e6d3;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
            #globalSettingsOverlay.show{display:flex}
            .gs-card{width:min(94vw,620px);max-height:91vh;overflow:auto;background:#251b17;border:2px solid #d4af37;border-radius:14px;padding:16px;box-shadow:0 18px 55px rgba(0,0,0,.7)}
            .gs-head{display:flex;justify-content:space-between;align-items:center;color:#d4af37;margin-bottom:12px}.gs-head button{border:1px solid #d4af37;background:#17110e;color:#d4af37;border-radius:5px;padding:6px 10px}
            .gs-section{background:rgba(0,0,0,.22);border:1px solid #5c4937;border-radius:8px;padding:11px;margin:10px 0}.gs-section h4{color:#ffd76a;margin-bottom:8px}
            .gs-row{display:grid;grid-template-columns:145px 1fr;gap:8px;align-items:center;margin:8px 0;font-size:13px}.gs-row input,.gs-row select{min-width:0;background:#120e0c;border:1px solid #66513e;color:#f5e6d3;border-radius:5px;padding:8px}
            .gs-stats{display:grid;grid-template-columns:repeat(2,1fr);gap:6px;font-size:12px}.gs-stat{background:#15100d;border-radius:5px;padding:8px}.gs-stat b{color:#7dff9c}
            .gs-actions{display:flex;flex-wrap:wrap;gap:8px;justify-content:flex-end;margin-top:12px}.gs-actions button{border:1px solid #d4af37;background:#693325;color:#fff;border-radius:6px;padding:8px 13px}.gs-actions .secondary{background:#28201b}
            @media(max-width:520px){.gs-row{grid-template-columns:1fr}.gs-card{padding:12px}.gs-stats{grid-template-columns:1fr 1fr}}
        `;
        document.head.appendChild(style);
    }

    function injectDOM() {
        injectStyle();
        if (!document.getElementById('globalSettingsLauncher') && !document.getElementById('sbtn')) {
            const launcher = document.createElement('button');
            launcher.id = 'globalSettingsLauncher';
            launcher.title = '全局设置';
            launcher.textContent = '⚙';
            launcher.onclick = window.openGlobalSettings;
            document.body.appendChild(launcher);
        }
        if (document.getElementById('globalSettingsOverlay')) return;
        const overlay = document.createElement('div');
        overlay.id = 'globalSettingsOverlay';
        overlay.innerHTML = `
            <div class="gs-card">
                <div class="gs-head"><h3>⚙ 全局设置中心</h3><button id="gsClose">关闭</button></div>
                <div class="gs-section">
                    <h4>🎮 游戏与界面</h4>
                    <label class="gs-row"><span>卡牌动画时长</span><select id="gsAnimation"><option value="800">快速 0.8秒</option><option value="1100">标准 1.1秒</option><option value="1600">沉浸 1.6秒</option></select></label>
                    <label class="gs-row"><span>AI思考状态</span><span><input id="gsThinking" type="checkbox"> 在日志/聊天区域显示“正在思考”</span></label>
                </div>
                <div class="gs-section">
                    <h4>🤖 新AI默认参数</h4>
                    <label class="gs-row"><span>Provider</span><select id="gsProvider"></select></label>
                    <label class="gs-row"><span>默认模型</span><input id="gsModel"></label>
                    <label class="gs-row"><span>Temperature</span><input id="gsTemperature" type="number" min="0" max="2" step="0.1"></label>
                </div>
                <div class="gs-section">
                    <h4>📚 世界书与武将数据</h4>
                    <label class="gs-row"><span>启用内置世界书</span><span><input id="gsWorldbook" type="checkbox"> AI决策时注入相关武将、阶段、卡牌条目</span></label>
                    <label class="gs-row"><span>启用自定义条目</span><span><input id="gsCustomWorldbook" type="checkbox"> 注入用户在设置页维护的条目</span></label>
                    <div id="gsDataStats" class="gs-stats"><div class="gs-stat">正在读取数据状态…</div></div>
                </div>
                <div class="gs-actions">
                    <button class="secondary" id="gsOpenManager">打开完整管理页</button>
                    <button id="gsSave">保存全局设置</button>
                </div>
            </div>`;
        document.body.appendChild(overlay);
        document.getElementById('gsClose').onclick = window.closeGlobalSettings;
        overlay.addEventListener('click', e => { if (e.target === overlay) window.closeGlobalSettings(); });
        document.getElementById('gsSave').onclick = saveFromForm;
        document.getElementById('gsOpenManager').onclick = () => { location.href = 'settings.html'; };
    }

    async function loadStats() {
        const box = document.getElementById('gsDataStats');
        if (!box) return;
        let manifest = {};
        try {
            const response = await fetch('/system_manifest.json', { cache: 'no-store' });
            manifest = await response.json();
        } catch (_) {}
        box.innerHTML = `
            <div class="gs-stat">运行时武将：<b>${manifest.runtime_heroes ?? '?'}</b></div>
            <div class="gs-stat">源武将数据：<b>${manifest.source_heroes ?? '?'}</b></div>
            <div class="gs-stat">生成技能类：<b>${manifest.generated_skills ?? '?'}</b></div>
            <div class="gs-stat">世界书卡牌：<b>${manifest.worldbook_cards ?? '?'}</b></div>
            <div class="gs-stat">当前阶段：<b>${manifest.current_phase || 'P0基线'}</b></div>
            <div class="gs-stat">数据状态：<b>${manifest.data_status || '待检测'}</b></div>`;
    }

    // Provider 下拉：以服务端 /api/providers 为准（来源 protocol.py），
    // 拉取完成前/失败时回退到自动生成的 Protocol.PROVIDERS（同源保证一致性）。
    // 失败后不重试——Protocol.PROVIDERS 即同一真相源的导出，功能等价。
    let gsProviderList = null;
    let gsProvidersLoaded = false;
    function fillProviderSelect() {
        const sel = document.getElementById('gsProvider');
        if (!sel) return;
        const list = (gsProviderList && gsProviderList.length) ? gsProviderList : (window.Protocol ? Protocol.PROVIDERS : []);
        sel.innerHTML = list.map(p => `<option value="${p.value}">${p.name}</option>`).join('');
    }
    function restoreProviderSelect() {
        const sel = document.getElementById('gsProvider');
        if (!sel) return;
        sel.value = window.getGlobalSettings().default_provider;
    }
    function loadProviders() {
        if (gsProvidersLoaded) { fillProviderSelect(); restoreProviderSelect(); return; }
        gsProvidersLoaded = true;
        fetch('/api/providers', { cache: 'no-store' })
            .then(r => r.json())
            .then(d => {
                if (d && d.providers && d.providers.length) {
                    gsProviderList = d.providers;
                    fillProviderSelect();
                    restoreProviderSelect();
                }
            })
            .catch(() => {});
    }

    function fillForm() {
        const s = window.getGlobalSettings();
        document.getElementById('gsAnimation').value = String(s.animation_ms);
        document.getElementById('gsThinking').checked = !!s.show_ai_thinking;
        document.getElementById('gsProvider').value = s.default_provider;
        document.getElementById('gsModel').value = s.default_model;
        document.getElementById('gsTemperature').value = s.default_temperature;
        document.getElementById('gsWorldbook').checked = !!s.worldbook_enabled;
        document.getElementById('gsCustomWorldbook').checked = !!s.custom_worldbook_enabled;
        loadStats();
    }

    function saveFromForm() {
        window.saveGlobalSettings({
            animation_ms: Number(document.getElementById('gsAnimation').value) || 1100,
            show_ai_thinking: document.getElementById('gsThinking').checked,
            default_provider: document.getElementById('gsProvider').value,
            default_model: document.getElementById('gsModel').value.trim() || 'deepseek-chat',
            default_temperature: Number(document.getElementById('gsTemperature').value) || 0.8,
            worldbook_enabled: document.getElementById('gsWorldbook').checked,
            custom_worldbook_enabled: document.getElementById('gsCustomWorldbook').checked
        });
        window.closeGlobalSettings();
    }

    window.openGlobalSettings = function () {
        injectDOM();
        fillProviderSelect();
        fillForm();
        loadProviders();
        document.getElementById('globalSettingsOverlay').classList.add('show');
    };
    window.closeGlobalSettings = function () {
        const overlay = document.getElementById('globalSettingsOverlay');
        if (overlay) overlay.classList.remove('show');
    };

    document.addEventListener('DOMContentLoaded', injectDOM);
})();
