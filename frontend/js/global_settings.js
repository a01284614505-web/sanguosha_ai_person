// =============================================================================
// 全局设置：自动注入到所有页面，设置保存在 localStorage['globalSettings']。
// -----------------------------------------------------------------------------
// - getGlobalSettings() / saveGlobalSettings() 供其他脚本读写；保存时广播
//   'global-settings-changed' 事件（sgs_common.js 据此切换主题，对局页据此重绘）。
// - 页面若已自带入口按钮（#openGlobalSettings / #sbtn），则不再注入右上角悬浮按钮。
// - theme：dark 夜墨 / light 暖纸 / system 跟随系统；对局页始终是夜墨。
// =============================================================================
(function () {
    const STORAGE_KEY = 'globalSettings';
    const defaults = {
        animation_ms: 1100,
        show_ai_thinking: true,
        show_decision_trace: true,
        worldbook_enabled: true,
        custom_worldbook_enabled: true,
        default_provider: 'deepseek',
        default_model: 'deepseek-chat',
        default_temperature: 0.8,
        sfx_enabled: true,
        sfx_volume: 0.5,
        speech_enabled: false,
        theme: 'dark',
        log_incognito: false,
        log_include_thinking: true
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
            .gs-head button{width:34px;height:34px;display:grid;place-items:center;border-radius:50%;border:1px solid #6e5229;background:#1c140e;color:#f1d898;cursor:pointer}
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
        const hasOwnEntry = document.getElementById('openGlobalSettings') || document.getElementById('sbtn') || document.getElementById('globalSettingsLauncher') || document.querySelector('[data-gs-launcher]');
        if (!hasOwnEntry) {
            const gearIcon = window.SGS ? SGS.icon('gear') : '⚙';
            const nav = document.querySelector('.topbar nav');
            const launcher = document.createElement('button');
            launcher.id = 'globalSettingsLauncher';
            launcher.type = 'button';
            launcher.title = '全局设置';
            launcher.setAttribute('aria-label', '全局设置');
            launcher.innerHTML = gearIcon;
            launcher.onclick = window.openGlobalSettings;
            if (nav) {
                // 有顶栏的页面：放进导航里，和主题按钮并排，不再悬浮遮挡
                launcher.className = 'icon-btn';
                launcher.removeAttribute('id');
                launcher.dataset.gsLauncher = '1';
                nav.appendChild(launcher);
            } else {
                document.body.appendChild(launcher);
            }
        }
        if (document.getElementById('globalSettingsOverlay')) return;
        const overlay = document.createElement('div');
        overlay.id = 'globalSettingsOverlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.setAttribute('aria-label', '全局设置');
        overlay.innerHTML = `
            <div class="gs-card">
                <div class="gs-head"><h3>全局设置</h3><button id="gsClose" aria-label="关闭">${window.SGS ? SGS.icon('close') : '×'}</button></div>
                <div class="gs-section">
                    <h4>对局与界面</h4>
                    <label class="gs-row"><span>界面主题</span><select id="gsTheme"><option value="dark">夜墨（深色）</option><option value="light">暖纸（浅色）</option><option value="system">跟随系统</option></select></label>
                    <label class="gs-row"><span>出牌动画</span><select id="gsAnimation"><option value="800">轻快 0.8 秒</option><option value="1100">标准 1.1 秒</option><option value="1600">从容 1.6 秒</option></select></label>
                    <label class="gs-row"><span>AI 思考提示</span><span><input id="gsThinking" type="checkbox">在武将框上显示“思考中”，并把思考摘要写进战报</span></label>
                    <label class="gs-row"><span>决策轨迹</span><span><input id="gsDecisionTrace" type="checkbox">在战报中显示可展开的简略与完整决策记录</span></label>
                    <label class="gs-row"><span>音效</span><span><input id="gsSfx" type="checkbox">开启出牌、受伤、回复音效</span></label>
                    <label class="gs-row"><span>语音播报</span><span><input id="gsSpeech" type="checkbox">朗读公开对局事件（仅此设备播放，默认关闭）<small class="muted" style="display:block;margin-top:4px">依赖浏览器语音合成和设备已安装的中文语音；无可用语音时静默跳过，不连接外部语音服务。</small></span></label>
                    <label class="gs-row"><span>音量</span><input id="gsVolume" type="range" min="0" max="1" step="0.05"></label>
                </div>
                <div class="gs-section" id="gsChatSection" hidden>
                    <h4>席间聊天（本局）</h4>
                    <label class="gs-row"><span>热闹程度</span><select id="gsChatLevel"><option value="quiet">安静</option><option value="normal">正常</option><option value="lively">热闹</option></select></label>
                </div>
                <div class="gs-section">
                    <h4>对局日志</h4>
                    <label class="gs-row"><span>无痕模式</span><span><input id="gsLogIncognito" type="checkbox">对局结束后不保存日志（开局时的设置生效）</span></label>
                    <label class="gs-row"><span>思考过程</span><span><input id="gsLogThinking" type="checkbox">日志里包含 AI 每一步的理由</span></label>
                    <div class="gs-actions" style="justify-content:flex-start;margin-top:4px"><button class="secondary" id="gsOpenLogs" type="button">管理对局日志</button></div>
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
        document.getElementById('gsOpenLogs').onclick = () => {
            // 对局中离开页面会打断观看（对局本身在服务器上继续），先确认。
            if (document.getElementById('battle') && !confirm('离开对局页去看日志？对局会在后台继续，可从大厅回来。')) return;
            location.href = 'logs.html';
        };
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
            <div class="gs-stat">卡牌种类<b>${manifest.card_kinds ?? '?'}</b></div>`;
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
        document.getElementById('gsTheme').value = s.theme || 'dark';
        document.getElementById('gsAnimation').value = String(s.animation_ms);
        document.getElementById('gsThinking').checked = !!s.show_ai_thinking;
        document.getElementById('gsDecisionTrace').checked = s.show_decision_trace !== false;
        document.getElementById('gsSfx').checked = s.sfx_enabled !== false;
        document.getElementById('gsSpeech').checked = s.speech_enabled === true;
        document.getElementById('gsVolume').value = String(s.sfx_volume ?? 0.5);
        document.getElementById('gsProvider').value = s.default_provider;
        document.getElementById('gsModel').value = s.default_model;
        document.getElementById('gsTemperature').value = s.default_temperature;
        document.getElementById('gsWorldbook').checked = !!s.worldbook_enabled;
        document.getElementById('gsCustomWorldbook').checked = !!s.custom_worldbook_enabled;
        document.getElementById('gsLogIncognito').checked = !!s.log_incognito;
        document.getElementById('gsLogThinking').checked = s.log_include_thinking !== false;
        // 热闹程度只在对局页出现；显示的是服务器确认过的当前档位（window.currentChatLevel 由对局页随状态更新）。
        const inGame = !!document.getElementById('battle');
        document.getElementById('gsChatSection').hidden = !inGame;
        if (inGame) document.getElementById('gsChatLevel').value = window.currentChatLevel || 'normal';
        loadStats();
    }

    function saveFromForm() {
        const temperature = Number(document.getElementById('gsTemperature').value);
        window.saveGlobalSettings({
            theme: document.getElementById('gsTheme').value,
            animation_ms: Number(document.getElementById('gsAnimation').value) || 1100,
            show_ai_thinking: document.getElementById('gsThinking').checked,
            show_decision_trace: document.getElementById('gsDecisionTrace').checked,
            sfx_enabled: document.getElementById('gsSfx').checked,
            sfx_volume: Number(document.getElementById('gsVolume').value),
            speech_enabled: document.getElementById('gsSpeech').checked,
            default_provider: document.getElementById('gsProvider').value,
            default_model: document.getElementById('gsModel').value.trim() || 'deepseek-chat',
            default_temperature: Number.isFinite(temperature) ? temperature : 0.8,
            worldbook_enabled: document.getElementById('gsWorldbook').checked,
            custom_worldbook_enabled: document.getElementById('gsCustomWorldbook').checked,
            log_incognito: document.getElementById('gsLogIncognito').checked,
            log_include_thinking: document.getElementById('gsLogThinking').checked
        });
        const levelSection = document.getElementById('gsChatSection');
        if (levelSection && !levelSection.hidden) {
            const level = document.getElementById('gsChatLevel').value;
            if (level !== (window.currentChatLevel || 'normal')) {
                window.dispatchEvent(new CustomEvent('chat-level-request', { detail: { level: level } }));
            }
        }
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
