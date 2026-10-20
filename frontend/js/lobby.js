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
            this.aiRoster = DEFAULT_NAMES.map((name, i) => ({ id: 'ai_' + (i + 1), name, titles: { earned: [], equipped: null } }));
            this.assignments = this.aiRoster.map(p => p.id);
            this.pendingProfileSaves = [];
            this.current = 0;
            this.prefs = Object.assign({ playerName: '', chatEnabled: true, aiSpectate: true, chatLevel: 'normal', rememberKeys: false, cheatMode: false, hideDeadIdentity: false }, store.get('lobbyPrefs', {}));
            this.dialog = document.getElementById('aiDialog');
            this.form = document.getElementById('aiForm');
            this.init();
        }

        // 绑定表单与按钮事件，并读取 Provider、牌堆和本机战绩。
        init() {
            const postDeathNotice = store.sget('postDeathNotice', '');
            if (postDeathNotice) {
                store.sset('postDeathNotice', null);
                toast(postDeathNotice, { ms: 6000 });
            }
            const name = document.getElementById('playerName');
            name.value = this.prefs.playerName || '';
            name.addEventListener('input', () => this.savePrefs());
            const chat = document.getElementById('chatEnabled');
            chat.checked = this.prefs.chatEnabled !== false;
            chat.addEventListener('change', () => this.savePrefs());
            const spectate = document.getElementById('aiSpectate');
            spectate.checked = this.prefs.aiSpectate !== false;
            spectate.addEventListener('change', () => this.savePrefs());
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
            this.prefs.aiSpectate = document.getElementById('aiSpectate').checked;
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
            const profileId = this.getProfileId();
            Promise.allSettled([SGS.fetchJSON('/api/providers'), SGS.fetchJSON('/api/ai-players?profile_id=' + encodeURIComponent(profileId))]).then(results => {
                const providers = results[0].status === 'fulfilled' ? results[0].value : null;
                const roster = results[1].status === 'fulfilled' ? results[1].value : null;
                if (roster && roster.success && Array.isArray(roster.players) && roster.players.length === 4) this.aiRoster = roster.players;
                apply(providers && providers.providers, !!providers);
            });
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
            const profileSaved = store.get('lobbyAIProfiles', {});
            const migrateLegacy = !store.get('lobbyAIMigrated', false) && Array.isArray(saved);
            const migrations = [];
            this.assignments = store.get('lobbyAISeats', this.aiRoster.map(p => p.id));
            if (!Array.isArray(this.assignments) || this.assignments.length !== 4 || this.assignments.some(id => !this.aiRoster.some(p => p.id === id))) {
                this.assignments = this.aiRoster.map(p => p.id);
            }
            this.aiConfigs = this.aiRoster.map((profile, i) => {
                const base = this.defaultAI(i);
                const old = (profileSaved && profileSaved[profile.id]) || (Array.isArray(saved) && saved[i]) || {};
                const merged = Object.assign(base, old);
                if (!merged.apiKey && (sessionKeys[profile.id] || (Array.isArray(sessionKeys) && sessionKeys[i]))) merged.apiKey = sessionKeys[profile.id] || sessionKeys[i];
                if (!this.providers.some(p => p.value === merged.provider)) merged.provider = base.provider;
                if (migrateLegacy && old.name) {
                    profile.name = String(old.name).slice(0, 16);
                    const migration = SGS.fetchJSON('/api/ai-players/update', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ profile_id: this.getProfileId(), ai_id: profile.id, name: profile.name }) }).then(() => true).catch(() => false);
                    migrations.push(migration);
                    this.pendingProfileSaves.push(migration);
                }
                merged.name = profile.name || base.name;
                merged.aiId = profile.id;
                merged.title = (profile.titles && profile.titles.equipped) || null;
                return merged;
            });
            if (migrateLegacy) Promise.all(migrations).then(results => store.set('lobbyAIMigrated', results.every(Boolean)));
        }

        // 保存四席配置。Key 默认只放 sessionStorage（关掉标签页即清除）；勾选“记住 Key”才写进 localStorage。
        persistAIConfigs() {
            const remember = !!this.prefs.rememberKeys;
            const profiles = {};
            const keys = {};
            this.aiConfigs.forEach(a => {
                profiles[a.aiId] = Object.assign({}, a, { apiKey: remember ? a.apiKey : '' });
                keys[a.aiId] = a.apiKey || '';
            });
            store.set('lobbyAIProfiles', profiles);
            store.sset('lobbyKeys', keys);
            store.set('lobbyAISeats', this.assignments);
            // 兼容选将页和旧配置恢复逻辑。
            store.set('lobbyAIs', this.assignments.map(id => Object.assign({}, this.aiConfigs.find(a => a.aiId === id), { apiKey: '' })));
        }

        // 渲染“座上宾”四张卡片：显示称呼、提供方/模型，以及是“模型对弈”还是“规则 AI”。
        renderGuests() {
            const row = document.getElementById('guestRow');
            row.innerHTML = this.assignments.map((aiId, i) => {
                const a = this.aiConfigs.find(item => item.aiId === aiId) || this.aiConfigs[i];
                const provider = this.providers.find(p => p.value === a.provider);
                const hasKey = !!(a.apiKey && a.apiKey.trim());
                return '<div class="frame guest"><select class="ai-player-select" data-seat="' + i + '" aria-label="选择' + SEAT_NAMES[i] + '号位 AI 选手">' + this.aiRoster.map(player => '<option value="' + esc(player.id) + '"' + (player.id === aiId ? ' selected' : '') + '>' + esc(player.name) + '</option>').join('') + '</select><button type="button" class="guest-config" data-ai="' + i + '" aria-label="配置' + esc(a.name) + '">' +
                    '<span class="seat-no">' + SEAT_NAMES[i] + '</span>' +
                    '<span><strong>' + esc(a.name) + '</strong>' +
                    '<small>' + esc(provider ? provider.name : a.provider) + ' · ' + esc(a.model || '默认模型') + '</small>' +
                    '<span class="brain' + (hasKey ? ' model' : '') + '"><i></i>' + (hasKey ? '模型对弈' : '规则 AI') + '</span>' + (a.title ? '<span class="title-badge title-' + esc(a.title.tier || '普通') + '">' + esc(a.title.name) + '</span>' : '') + '</span>' +
                    '<span class="edit">配置</span></button></div>';
            }).join('');
            row.querySelectorAll('.ai-player-select').forEach(select => select.addEventListener('change', () => {
                const seat = Number(select.dataset.seat);
                const displacedSeat = this.assignments.findIndex((value, index) => value === select.value && index !== seat);
                if (displacedSeat >= 0) this.assignments[displacedSeat] = this.assignments[seat];
                this.assignments[seat] = select.value;
                this.persistAIConfigs();
                this.renderGuests();
            }));
            row.querySelectorAll('.guest-config').forEach(btn => btn.addEventListener('click', () => this.openDialog(Number(btn.dataset.ai))));
        }

        // 打开某一席的配置弹窗。
        openDialog(index) {
            this.currentSeat = index;
            this.current = Math.max(0, this.aiConfigs.findIndex(a => a.aiId === this.assignments[index]));
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
                thinking: f.thinking.checked,
                aiId: this.aiConfigs[this.current].aiId,
                title: this.aiConfigs[this.current].title
            };
            const profile = this.aiRoster.find(p => p.id === this.aiConfigs[this.current].aiId);
            if (profile && profile.name !== this.aiConfigs[this.current].name) {
                profile.name = this.aiConfigs[this.current].name;
                const pendingSave = SGS.fetchJSON('/api/ai-players/update', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ profile_id: this.getProfileId(), ai_id: profile.id, name: profile.name }) })
                    .then(() => true)
                    .catch(() => { store.set('lobbyAIMigrated', false); toast('名称已保存在本机，服务端档案暂不可用', { bad: true }); return false; });
                this.pendingProfileSaves.push(pendingSave);
            }
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
            return this.assignments.map(aiId => {
                const a = this.aiConfigs.find(item => item.aiId === aiId) || {};
                return {
                name: a.name,
                ai_id: aiId,
                title: a.title || null,
                provider: a.provider,
                apiUrl: a.apiUrl,
                apiKey: a.apiKey,
                model: a.model,
                temperature: a.temperature,
                thinking: !!a.thinking
            };
            });
        }

        // 组装开局配置并进入选将页。带 Key 的完整配置只写 sessionStorage；localStorage 里的副本去掉 Key。
        async startGame() {
            this.savePrefs();
            if (this.dialog.open) this.saveCurrent();
            if (!store.get('lobbyAIMigrated', false)) this.restoreAIConfigs();
            const pending = this.pendingProfileSaves.splice(0);
            if (pending.length && (await Promise.all(pending)).some(ok => !ok)) {
                toast('AI 名称未能保存到档案，请检查连接后重试', { bad: true });
                return;
            }
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
                ai_spectate: document.getElementById('aiSpectate').checked,
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
