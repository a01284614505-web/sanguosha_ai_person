// 大厅：入席设置、四席 AI 配置、牌堆选择。纯 UI：配置的合法性由引擎 normalize_config 复核。
// 开局配置格式（交给 select_hero → game）：
//   { mode, player_name, ais:[{name,provider,apiUrl,apiKey,model,temperature,thinking}],
//     hero_pool, deck_id, chat:{enabled,provider,model}, global_settings, custom_worldbook, identity_card? }
(function () {
    'use strict';
    const { esc, store, toast } = SGS;

    const SEAT_NAMES = ['二', '三', '四', '五'];
    const DEFAULT_NAMES = ['诸葛村夫', '曹操的粉丝', '小乔我老婆', '酒馆常客'];
    const MODE = '5人身份局';

    class LobbyController {
        // 大厅控制器：一个页面只有一个实例（window.lobby）。
        constructor() {
            this.providers = [];
            this.aiConfigs = [];
            this.current = 0;
            this.prefs = Object.assign({ playerName: '', chatEnabled: true, chatLevel: 'normal', rememberKeys: false, cheatMode: false, hideDeadIdentity: false }, store.get('lobbyPrefs', {}));
            this.dialog = document.getElementById('aiDialog');
            this.form = document.getElementById('aiForm');
            this.init();
        }

        // 绑定表单与按钮事件，并读取 Provider、牌堆和本机战绩。
        init() {
            const name = document.getElementById('playerName');
            name.value = this.prefs.playerName || '';
            name.addEventListener('input', () => this.savePrefs());
            const chat = document.getElementById('chatEnabled');
            chat.checked = this.prefs.chatEnabled !== false;
            chat.addEventListener('change', () => this.savePrefs());
            const level = document.getElementById('chatLevel');
            level.value = ['quiet', 'normal', 'lively'].includes(this.prefs.chatLevel) ? this.prefs.chatLevel : 'normal';
            level.addEventListener('change', () => this.savePrefs());
            ['cheatMode', 'hideDeadIdentity'].forEach(id => {
                const box = document.getElementById(id);
                box.checked = !!this.prefs[id];
                box.addEventListener('change', () => this.savePrefs());
            });
            document.getElementById('rememberKeys').checked = !!this.prefs.rememberKeys;

            document.getElementById('useIdentityCard').addEventListener('change', (e) => {
                document.getElementById('identitySelect').disabled = !e.target.checked;
                this.renderIdentityCard();
            });
            document.getElementById('identitySelect').addEventListener('change', () => this.renderIdentityCard());
            // 身份卡：点右侧身份印选择/取消；点卡面本身在已选时取消。
            document.getElementById('idCardChoices').addEventListener('click', (e) => {
                const b = e.target.closest('[data-identity]');
                if (b) this.pickIdentity(b.dataset.identity);
            });
            document.getElementById('idCardArt').addEventListener('click', () => {
                if (document.getElementById('useIdentityCard').checked) this.pickIdentity(null);
                else toast('点右边的身份印，本局就以该身份入席');
            });
            this.cardCount = 0;
            document.getElementById('startGameBtn').addEventListener('click', () => this.startGame());
            document.getElementById('openGlobalSettings').addEventListener('click', () => window.openGlobalSettings && window.openGlobalSettings());
            document.getElementById('deckSelect').addEventListener('change', (e) => {
                if (e.target.value) store.set('active_deck_choice', e.target.value);
                this.updateDeckLabel();
            });

            this.dialog.querySelector('[data-close]').addEventListener('click', () => this.dialog.close());
            this.dialog.addEventListener('click', (e) => { if (e.target === this.dialog) this.dialog.close(); });
            this.form.addEventListener('submit', (e) => { e.preventDefault(); this.saveCurrent(); this.dialog.close(); toast('已保存'); });
            this.form.elements.provider.addEventListener('change', (e) => this.onProviderChange(e.target.value));
            const f = this.form.elements;
            this.modelPicker = SGS.attachModelPicker(f.model, () => ({
                provider: f.provider.value, api_url: f.apiUrl.value.trim(), api_key: f.apiKey.value.trim()
            }));
            ['provider', 'apiUrl', 'apiKey'].forEach(n => f[n].addEventListener('change', () => this.modelPicker && this.modelPicker.reset()));
            document.getElementById('syncBtn').addEventListener('click', () => this.syncAPIConfig());

            this.loadUserData();
            this.loadProviders();
            this.loadDecks();
        }

        // 保存“称呼 / 席间聊天 / 记住 Key”等偏好到 localStorage['lobbyPrefs']。
        savePrefs() {
            this.prefs.playerName = document.getElementById('playerName').value.trim();
            this.prefs.chatEnabled = document.getElementById('chatEnabled').checked;
            this.prefs.chatLevel = document.getElementById('chatLevel').value;
            this.prefs.cheatMode = document.getElementById('cheatMode').checked;
            this.prefs.hideDeadIdentity = document.getElementById('hideDeadIdentity').checked;
            this.prefs.rememberKeys = document.getElementById('rememberKeys').checked;
            store.set('lobbyPrefs', this.prefs);
        }

        // Provider 清单以服务端 /api/providers 为准（来源 protocol.py）；拉取失败时回退到生成的 Protocol.PROVIDERS。
        loadProviders() {
            const apply = (list, online) => {
                this.providers = (list && list.length) ? list : (window.Protocol ? Protocol.PROVIDERS : []);
                this.setConnection(online);
                this.form.elements.provider.innerHTML = this.providers.map(p => '<option value="' + esc(p.value) + '">' + esc(p.name) + '</option>').join('');
                this.restoreAIConfigs();
                this.renderGuests();
            };
            SGS.fetchJSON('/api/providers')
                .then(d => apply(d && d.providers, true))
                .catch(() => apply(null, false));
        }

        // 开始按钮下方的小绿点：能读到 /api/providers 就算服务已就绪。
        setConnection(ok) {
            document.getElementById('connDot').className = 'conn-dot ' + (ok ? 'ok' : 'bad');
            document.getElementById('connText').textContent = ok ? '游戏服务已就绪' : '连不上游戏服务，请先运行 game_server.py';
        }

        // 牌堆下拉框：选项来自服务器 /api/decks；优先恢复上次在大厅的选择，其次是设置页保存的默认牌堆。
        loadDecks() {
            const select = document.getElementById('deckSelect');
            SGS.fetchJSON('/api/decks').then(data => {
                if (!data.success || !Array.isArray(data.decks)) throw new Error('bad');
                const chosen = store.get('active_deck_choice', null) || localStorage.getItem('active_deck') || data.active_deck;
                const known = data.decks.some(d => d.id === chosen);
                select.innerHTML = data.decks.map(d => '<option value="' + esc(d.id) + '">' + esc(d.name) + '（' + d.cards_count + ' 张）</option>').join('');
                select.value = known ? chosen : data.active_deck;
                this.updateDeckLabel();
            }).catch(() => {
                select.innerHTML = '<option value="">服务器默认</option>';
                this.updateDeckLabel();
            });
        }

        // 把当前牌堆名同步到左侧牌匾上的“牌堆 xxx”。
        updateDeckLabel() {
            const select = document.getElementById('deckSelect');
            const opt = select.options[select.selectedIndex];
            document.getElementById('deckLabel').textContent = opt ? opt.textContent : '服务器默认';
        }

        // 第 i 席的默认配置：优先用全局设置里的默认提供方/模型，否则按提供方列表轮流分配。
        defaultAI(i) {
            const globalSettings = window.getGlobalSettings ? getGlobalSettings() : {};
            const preferred = this.providers.find(p => p.value === globalSettings.default_provider);
            const defaultProvider = preferred || this.providers[i % this.providers.length] || { value: 'deepseek', default_url: '', default_model: 'deepseek-chat' };
            return {
                name: DEFAULT_NAMES[i] || ('AI' + (i + 1)),
                provider: defaultProvider.value,
                apiUrl: defaultProvider.default_url,
                apiKey: '',
                model: globalSettings.default_model || defaultProvider.default_model,
                temperature: globalSettings.default_temperature ?? 0.8,
                thinking: false
            };
        }

        // 恢复四席配置：localStorage 里的配置（不含 Key）+ 本标签页 sessionStorage 里的 Key。
        restoreAIConfigs() {
            const saved = store.get('lobbyAIs', []);
            const sessionKeys = store.sget('lobbyKeys', []);
            this.aiConfigs = [0, 1, 2, 3].map(i => {
                const base = this.defaultAI(i);
                const old = Array.isArray(saved) && saved[i] ? saved[i] : {};
                const merged = Object.assign(base, old);
                if (!merged.apiKey && sessionKeys[i]) merged.apiKey = sessionKeys[i];
                if (!this.providers.some(p => p.value === merged.provider)) merged.provider = base.provider;
                return merged;
            });
        }

        // 保存四席配置。Key 默认只放 sessionStorage（关掉标签页即清除）；勾选“记住 Key”才写进 localStorage。
        persistAIConfigs() {
            const remember = !!this.prefs.rememberKeys;
            store.set('lobbyAIs', this.aiConfigs.map(a => Object.assign({}, a, { apiKey: remember ? a.apiKey : '' })));
            store.sset('lobbyKeys', this.aiConfigs.map(a => a.apiKey || ''));
        }

        // 渲染“座上宾”四张卡片：显示称呼、提供方/模型，以及是“模型对弈”还是“规则 AI”。
        renderGuests() {
            const row = document.getElementById('guestRow');
            row.innerHTML = this.aiConfigs.map((a, i) => {
                const provider = this.providers.find(p => p.value === a.provider);
                const hasKey = !!(a.apiKey && a.apiKey.trim());
                return '<button type="button" class="frame guest" data-ai="' + i + '" aria-label="配置' + esc(a.name) + '">' +
                    '<span class="seat-no">' + SEAT_NAMES[i] + '</span>' +
                    '<span><strong>' + esc(a.name) + '</strong>' +
                    '<small>' + esc(provider ? provider.name : a.provider) + ' · ' + esc(a.model || '默认模型') + '</small>' +
                    '<span class="brain' + (hasKey ? ' model' : '') + '"><i></i>' + (hasKey ? '模型对弈' : '规则 AI') + '</span></span>' +
                    '<span class="edit">配置</span></button>';
            }).join('');
            row.querySelectorAll('.guest').forEach(btn => btn.addEventListener('click', () => this.openDialog(Number(btn.dataset.ai))));
        }

        // 打开某一席的配置弹窗。
        openDialog(index) {
            this.current = index;
            this.renderTabs();
            this.fillForm();
            if (!this.dialog.open) this.dialog.showModal();
        }

        // 弹窗顶部的席位标签，以及“同步给”勾选框（不包括当前席）。
        renderTabs() {
            const tabs = document.getElementById('aiTabs');
            tabs.innerHTML = this.aiConfigs.map((a, i) =>
                '<button type="button" role="tab" aria-selected="' + (i === this.current) + '" data-tab="' + i + '">' + SEAT_NAMES[i] + '号位 · ' + esc(a.name) + '</button>').join('');
            tabs.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
                this.saveCurrent();
                this.current = Number(b.dataset.tab);
                this.renderTabs();
                this.fillForm();
            }));
            const targets = document.getElementById('syncTargets');
            targets.innerHTML = this.aiConfigs.map((a, i) => i === this.current ? '' :
                '<label class="check"><input type="checkbox" data-sync-to="' + i + '"> ' + SEAT_NAMES[i] + '号位</label>').join('');
        }

        // 把当前席的配置填进表单。
        fillForm() {
            if (this.modelPicker) this.modelPicker.reset();
            const a = this.aiConfigs[this.current];
            const f = this.form.elements;
            f.name.value = a.name;
            f.provider.value = a.provider;
            f.apiUrl.value = a.apiUrl || '';
            f.apiKey.value = a.apiKey || '';
            f.model.value = a.model || '';
            f.temperature.value = a.temperature ?? 0.8;
            f.thinking.checked = !!a.thinking;
        }

        // 从表单读回当前席的配置（温度限制在 0~2），保存并刷新卡片。
        saveCurrent() {
            const f = this.form.elements;
            const t = parseFloat(f.temperature.value);
            this.aiConfigs[this.current] = {
                name: f.name.value.trim() || DEFAULT_NAMES[this.current],
                provider: f.provider.value,
                apiUrl: f.apiUrl.value.trim(),
                apiKey: f.apiKey.value.trim(),
                model: f.model.value.trim(),
                temperature: Number.isFinite(t) ? Math.max(0, Math.min(2, t)) : 0.8,
                thinking: f.thinking.checked
            };
            this.savePrefs();
            this.persistAIConfigs();
            this.renderGuests();
        }

        // 切换提供方时，自动填入该提供方的默认 API 地址与模型名。
        onProviderChange(providerValue) {
            const provider = this.providers.find(p => p.value === providerValue);
            if (!provider) return;
            this.form.elements.apiUrl.value = provider.default_url;
            this.form.elements.model.value = provider.default_model;
        }

        // 把当前席的连接配置（提供方 / 地址 / Key / 模型）复制给勾选的其他席。
        syncAPIConfig() {
            this.saveCurrent();
            const source = this.aiConfigs[this.current];
            const targets = Array.from(document.querySelectorAll('[data-sync-to]:checked')).map(el => Number(el.dataset.syncTo));
            if (!targets.length) { toast('先勾选要同步的座位', { bad: true }); return; }
            targets.forEach(i => {
                Object.assign(this.aiConfigs[i], { provider: source.provider, apiUrl: source.apiUrl, apiKey: source.apiKey, model: source.model });
            });
            this.persistAIConfigs();
            this.renderGuests();
            this.renderTabs();
            toast('已同步给 ' + targets.map(i => SEAT_NAMES[i] + '号位').join('、'));
        }

        // 整理成服务器 normalize_config 认识的格式（apiUrl / apiKey 会在引擎侧规范化）。
        collectAIConfigs() {
            return this.aiConfigs.map(a => ({
                name: a.name,
                provider: a.provider,
                apiUrl: a.apiUrl,
                apiKey: a.apiKey,
                model: a.model,
                temperature: a.temperature,
                thinking: !!a.thinking
            }));
        }

        // 组装开局配置并进入选将页。带 Key 的完整配置只写 sessionStorage；localStorage 里的副本去掉 Key。
        startGame() {
            this.savePrefs();
            const ais = this.collectAIConfigs();
            const deckId = document.getElementById('deckSelect').value;
            const first = this.providers.find(p => p.value === (ais[0] && ais[0].provider));
            const config = {
                mode: MODE,
                player_name: document.getElementById('playerName').value.trim() || '无名客',
                ais: ais,
                hero_pool: document.getElementById('heroPool').value,
                chat: {
                    enabled: document.getElementById('chatEnabled').checked,
                    provider: first ? first.value : 'deepseek',
                    model: (ais[0] && ais[0].model) || (first ? first.default_model : 'deepseek-chat')
                },
                global_settings: window.getGlobalSettings ? getGlobalSettings() : {},
                chat_level: document.getElementById('chatLevel').value,
                cheat_mode: document.getElementById('cheatMode').checked,
                hide_dead_identity: document.getElementById('hideDeadIdentity').checked,
                custom_worldbook: store.get('worldbook', []),
                // 默认模型托管沿用大厅第一席的连接配置，Key 只随 sessionStorage 传给本局。
                trustee_default: ais[0] ? Object.assign({}, ais[0]) : null
            };
            config.profile_id = this.getProfileId();
            if (deckId) {
                config.deck_id = deckId;
                try { localStorage.setItem('active_deck', deckId); } catch (_) {}
            }
            if (document.getElementById('useIdentityCard').checked) {
                const identity = document.getElementById('identitySelect').value;
                if (!identity) { toast('请选择要使用的身份', { bad: true }); return; }
                config.identity_card = { use: true, identity: identity };
            }
            // 带 Key 的完整配置只放在本标签页的 sessionStorage；localStorage 中的副本去掉 Key。
            store.sset('gameConfig', config);
            const localConfig = Object.assign({}, config, {
                ais: ais.map(a => Object.assign({}, a, { apiKey: '' })),
                trustee_default: config.trustee_default ? Object.assign({}, config.trustee_default, { apiKey: '' }) : null
            });
            store.set('gameConfig', localConfig);
            window.location.href = 'select_hero.html';
        }

        getProfileId() {
            let id = store.get('profileId', '');
            if (!/^[A-Za-z0-9_-]{1,128}$/.test(id)) {
                id = (window.crypto && crypto.randomUUID)
                    ? crypto.randomUUID().replace(/-/g, '_')
                    : 'p_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2);
                store.set('profileId', id);
            }
            return id;
        }

        /** 选中某个身份（再点一次同一个则取消）；name 为 null 表示取消使用身份卡。 */
        pickIdentity(name) {
            const use = document.getElementById('useIdentityCard');
            const sel = document.getElementById('identitySelect');
            const same = use.checked && sel.value === name;
            if (!name || same) {
                use.checked = false;
                sel.value = '';
                sel.disabled = true;
            } else {
                use.checked = true;
                sel.disabled = false;
                sel.value = name;
            }
            this.renderIdentityCard();
        }

        /** 按当前选择重绘身份卡牌面、身份印状态与提示。 */
        renderIdentityCard() {
            const KEY = { '主公': 'lord', '忠臣': 'loyalist', '反贼': 'rebel', '内奸': 'spy' };
            const use = document.getElementById('useIdentityCard').checked;
            const name = document.getElementById('identitySelect').value;
            const chosen = use && KEY[name] ? KEY[name] : null;
            document.getElementById('idCardArt').innerHTML = SGS.identityCardHTML({ identity: chosen, count: this.cardCount });
            document.querySelectorAll('#idCardChoices [data-identity]').forEach(b =>
                b.setAttribute('aria-checked', String(!!chosen && b.dataset.identity === name)));
            document.getElementById('idCardHint').innerHTML = chosen
                ? '本局以 <b>' + esc(name) + '</b> 入席，开局时消耗 1 张'
                : '点一个身份，本局就用身份卡指定';
        }

        // 战绩与身份卡以服务端档案为准；旧 userData 只显示迁移提示。
        loadUserData() {
            const legacy = store.get('userData', null);
            const notice = document.getElementById('legacyRecordNotice');
            if (notice) notice.hidden = !legacy;
            const profileId = this.getProfileId();
            SGS.fetchJSON('/api/history?profile_id=' + encodeURIComponent(profileId))
                .then(data => {
                    if (!data || !data.success || !data.profile) throw new Error('history unavailable');
                    const profile = data.profile;
                    document.getElementById('winStreak').textContent = profile.win_streak || 0;
                    document.getElementById('totalGames').textContent = profile.total_games || 0;
                    document.getElementById('cardCount').textContent = profile.identity_cards || 0;
                    document.getElementById('identityCardSection').hidden = !(profile.identity_cards > 0);
                    this.cardCount = profile.identity_cards || 0;
                    this.renderIdentityCard();
                    const status = document.getElementById('recordStatus');
                    if (status) status.textContent = '已同步服务端战绩';
                })
                .catch(() => {
                    document.getElementById('winStreak').textContent = '—';
                    document.getElementById('totalGames').textContent = '—';
                    document.getElementById('cardCount').textContent = '—';
                    document.getElementById('identityCardSection').hidden = true;
                    const status = document.getElementById('recordStatus');
                    if (status) status.textContent = '服务端战绩暂不可用';
                });
        }
    }

    document.addEventListener('DOMContentLoaded', () => { window.lobby = new LobbyController(); });
})();
