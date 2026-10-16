// 全局设置入口：自动注入到所有页面，设置保存在 localStorage。
// 页面若已自带入口按钮（#openGlobalSettings / #sbtn），则不再注入悬浮按钮。
(function () {
    const STORAGE_KEY = 'globalSettings';
    const defaults = {
        animation_ms: 1100,
        show_ai_thinking: true,
        worldbook_enabled: true,
        custom_worldbook_enabled: true,
        default_provider: 'deepseek',
        default_model: 'deepseek-chat',
        default_temperature: 0.8,
        sfx_enabled: true,
        sfx_volume: 0.5
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
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(merged)); } catch (_) {}
        window.dispatchEvent(new CustomEvent('global-settings-changed', { detail: merged }));
        return merged;
    };

    function injectStyle() {
        if (document.getElementById('globalSettingsStyle')) return;
        const style = document.createElement('style');
        style.id = 'globalSettingsStyle';
        style.textContent = `
            #globalSettingsLauncher{position:fixed;top:10px;right:10px;z-index:3000;width:38px;height:38px;border-radius:50%;border:1px solid #c9a35a;background:radial-gradient(circle at 50% 35%,#3b2a1c,#1c140e);color:#f1d898;font-size:18px;display:grid;place-items:center;cursor:pointer;box-shadow:0 3px 10px rgba(0,0,0,.5)}
            #globalSettingsOverlay{display:none;position:fixed;inset:0;z-index:8000;background:rgba(5,3,2,.74);padding:12px;align-items:center;justify-content:center;color:#eadcbf;font-family:"PingFang SC","Microsoft YaHei",sans-serif}
            #globalSettingsOverlay.show{display:flex}
            .gs-card{width:min(94vw,600px);max-height:92dvh;overflow:auto;background:linear-gradient(180deg,#2f2117,#241911);border:1px solid #6e5229;border-radius:8px;padding:18px 20px;box-shadow:inset 0 0 0 3px rgba(0,0,0,.35),inset 0 0 0 4px rgba(201,163,90,.28),0 18px 55px rgba(0,0,0,.7)}
            .gs-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
            .gs-head h3{margin:0;font-family:"STKaiti","KaiTi","Kaiti SC","楷体",serif;font-size:22px;color:#f1d898}
            .gs-head button{width:34px;height:34px;border-radius:50%;border:1px solid #6e5229;background:#1c140e;color:#f1d898;cursor:pointer}
            .gs-section{border-top:1px solid rgba(201,163,90,.22);padding:12px 0 4px}
            .gs-section h4{margin:0 0 6px;font-family:"STKaiti","KaiTi","Kaiti SC","楷体",serif;font-size:16px;color:#f1d898;font-weight:600}
            .gs-row{display:grid;grid-template-columns:130px 1fr;gap:10px;align-items:center;margin:8px 0;font-size:14px}
            .gs-row>span:first-child{color:#d9c7a0}
            .gs-row input:not([type=checkbox]):not([type=range]),.gs-row select{min-width:0;width:100%;background:rgba(8,5,3,.55);border:1px solid #5d4730;color:#eadcbf;border-radius:5px;padding:7px 9px}
            .gs-row input[type=checkbox]{width:16px;height:16px;accent-color:#a8261c;vertical-align:-3px;margin-right:6px}
            .gs-row input[type=range]{width:100%;accent-color:#c9a35a}
            .gs-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;font-size:12px;margin-top:6px}.gs-stat{background:rgba(0,0,0,.25);border-radius:5px;padding:7px;color:#a89577}.gs-stat b{display:block;color:#f1e4c3;font-size:15px}
            .gs-actions{display:flex;flex-wrap:wrap;gap:10px;justify-content:flex-end;margin-top:14px}
            .gs-actions button{min-height:36px;border:1px solid #c9a35a;border-radius:6px;padding:6px 16px;cursor:pointer;font-family:"STKaiti","KaiTi","Kaiti SC","楷体",serif;font-size:15px;font-weight:600;letter-spacing:.1em;color:#2a1a0b;background:linear-gradient(180deg,#d8b25e,#9b7330)}
            .gs-actions .secondary{color:#f1d898;background:linear-gradient(180deg,#3a2a1d,#241911)}
            @media(max-width:520px){.gs-row{grid-template-columns:1fr;gap:4px}.gs-stats{grid-template-columns:1fr 1fr}}
        `;
        document.head.appendChild(style);
    }

    function injectDOM() {
        injectStyle();
        const hasOwnEntry = document.getElementById('openGlobalSettings') || document.getElementById('sbtn');
        if (!document.getElementById('globalSettingsLauncher') && !hasOwnEntry) {
            const launcher = document.createElement('button');
            launcher.id = 'globalSettingsLauncher';
            launcher.title = '全局设置';
            launcher.setAttribute('aria-label', '全局设置');
            launcher.textContent = '⚙';
            launcher.onclick = window.openGlobalSettings;
            document.body.appendChild(launcher);
        }
        if (document.getElementById('globalSettingsOverlay')) return;
        const overlay = document.createElement('div');
        overlay.id = 'globalSettingsOverlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.setAttribute('aria-label', '全局设置');
        overlay.innerHTML = `
            <div class="gs-card">
                <div class="gs-head"><h3>全局设置</h3><button id="gsClose" aria-label="关闭">✕</button></div>
                <div class="gs-section">
                    <h4>对局与界面</h4>
                    <label class="gs-row"><span>出牌动画</span><select id="gsAnimation"><option value="800">轻快 0.8 秒</option><option value="1100">标准 1.1 秒</option><option value="1600">从容 1.6 秒</option></select></label>
                    <label class="gs-row"><span>AI 思考提示</span><span><input id="gsThinking" type="checkbox">在武将框上显示“思考中”，并把思考摘要写进战报</span></label>
                    <label class="gs-row"><span>音效</span><span><input id="gsSfx" type="checkbox">开启出牌、受伤、回复音效</span></label>
                    <label class="gs-row"><span>音量</span><input id="gsVolume" type="range" min="0" max="1" step="0.05"></label>
                </div>
                <div class="gs-section">
                    <h4>新座位的默认模型</h4>
                    <label class="gs-row"><span>提供方</span><select id="gsProvider"></select></label>
                    <label class="gs-row"><span>模型名称</span><input id="gsModel"></label>
                    <label class="gs-row"><span>温度</span><input id="gsTemperature" type="number" min="0" max="2" step="0.1"></label>
                </div>
                <div class="gs-section">
                    <h4>世界书</h4>
                    <label class="gs-row"><span>内置世界书</span><span><input id="gsWorldbook" type="checkbox">AI 决策时注入相关武将、阶段、卡牌条目</span></label>
                    <label class="gs-row"><span>自定义条目</span><span><input id="gsCustomWorldbook" type="checkbox">注入你在设置页维护的条目</span></label>
                    <div id="gsDataStats" class="gs-stats"><div class="gs-stat">正在读取数据状态…</div></div>
                </div>
                <div class="gs-actions">
                    <button class="secondary" id="gsOpenManager">打开设置页</button>
                    <button id="gsSave">保存</button>
                </div>
            </div>`;
        document.body.appendChild(overlay);
        document.getElementById('gsClose').onclick = window.closeGlobalSettings;
        overlay.addEventListener('click', e => { if (e.target === overlay) window.closeGlobalSettings(); });
        document.addEventListener('keydown', e => { if (e.key === 'Escape') window.closeGlobalSettings(); });
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
            <div class="gs-stat">运行时武将<b>${manifest.runtime_heroes ?? '?'}</b></div>
            <div class="gs-stat">技能类<b>${manifest.generated_skills ?? '?'}</b></div>
            <div class="gs-stat">世界书卡牌<b>${manifest.worldbook_cards ?? '?'}</b></div>`;
    }

    // Provider 下拉：以服务端 /api/providers 为准（来源 protocol.py），失败时回退到生成的 Protocol.PROVIDERS。
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
        if (sel) sel.value = window.getGlobalSettings().default_provider;
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
        document.getElementById('gsSfx').checked = s.sfx_enabled !== false;
        document.getElementById('gsVolume').value = String(s.sfx_volume ?? 0.5);
        document.getElementById('gsProvider').value = s.default_provider;
        document.getElementById('gsModel').value = s.default_model;
        document.getElementById('gsTemperature').value = s.default_temperature;
        document.getElementById('gsWorldbook').checked = !!s.worldbook_enabled;
        document.getElementById('gsCustomWorldbook').checked = !!s.custom_worldbook_enabled;
        loadStats();
    }

    function saveFromForm() {
        const temperature = Number(document.getElementById('gsTemperature').value);
        window.saveGlobalSettings({
            animation_ms: Number(document.getElementById('gsAnimation').value) || 1100,
            show_ai_thinking: document.getElementById('gsThinking').checked,
            sfx_enabled: document.getElementById('gsSfx').checked,
            sfx_volume: Number(document.getElementById('gsVolume').value),
            default_provider: document.getElementById('gsProvider').value,
            default_model: document.getElementById('gsModel').value.trim() || 'deepseek-chat',
            default_temperature: Number.isFinite(temperature) ? temperature : 0.8,
            worldbook_enabled: document.getElementById('gsWorldbook').checked,
            custom_worldbook_enabled: document.getElementById('gsCustomWorldbook').checked
        });
        window.closeGlobalSettings();
        if (window.SGS) SGS.toast('设置已保存');
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

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', injectDOM);
    else injectDOM();
})();
