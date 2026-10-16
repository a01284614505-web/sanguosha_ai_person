// 大厅：入席设置、四席 AI 配置、牌堆选择。纯 UI：配置的合法性由引擎 normalize_config 复核。
// 开局配置格式（交给 select_hero → game）：
//   { mode, player_name, ais:[{name,provider,apiUrl,apiKey,model,temperature,thinking}],
//     hero_pool, deck_id, chat:{enabled,provider,model}, global_settings, custom_worldbook, identity_card? }
(function () {
    'use strict';
    const { esc, store, toast } = SGS;

    const SEAT_NAMES = ['二', '三', '四', '五'];
    const DEFAULT_NAMES = ['诸葛村夫', '曹操的粉丝', '小乔我老婆', '吕布'];
    const MODE = '5人身份局';

    class LobbyController {
        constructor() {
            this.providers = [];
            this.aiConfigs = [];
            this.current = 0;
            this.prefs = Object.assign({ playerName: '', chatEnabled: true, rememberKeys: false }, store.get('lobbyPrefs', {}));
            this.dialog = document.getElementById('aiDialog');
            this.form = document.getElementById('aiForm');
            this.init();
        }

        init() {
            const name = document.getElementById('playerName');
            name.value = this.prefs.playerName || '';
            name.addEventListener('input', () => this.savePrefs());
            const chat = document.getElementById('chatEnabled');
            chat.checked = this.prefs.chatEnabled !== false;
            chat.addEventListener('change', () => this.savePrefs());
            document.getElementById('rememberKeys').checked = !!this.prefs.rememberKeys;

            document.getElementById('useIdentityCard').addEventListener('change', (e) => {
                document.getElementById('identitySelect').disabled = !e.target.checked;
            });
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
            document.getElementById('syncBtn').addEventListener('click', () => this.syncAPIConfig());

            this.loadUserData();
            this.loadProviders();
            this.loadDecks();
        }

        savePrefs() {
            this.prefs.playerName = document.getElementById('playerName').value.trim();
            this.prefs.chatEnabled = document.getElementById('chatEnabled').checked;
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

        setConnection(ok) {
            document.getElementById('connDot').className = 'conn-dot ' + (ok ? 'ok' : 'bad');
            document.getElementById('connText').textContent = ok ? '游戏服务已就绪' : '连不上游戏服务，请先运行 game_server.py';
        }

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

        updateDeckLabel() {
            const select = document.getElementById('deckSelect');
            const opt = select.options[select.selectedIndex];
            document.getElementById('deckLabel').textContent = opt ? opt.textContent : '服务器默认';
        }

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

        persistAIConfigs() {
            const remember = !!this.prefs.rememberKeys;
            store.set('lobbyAIs', this.aiConfigs.map(a => Object.assign({}, a, { apiKey: remember ? a.apiKey : '' })));
            store.sset('lobbyKeys', this.aiConfigs.map(a => a.apiKey || ''));
        }

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

        openDialog(index) {
            this.current = index;
            this.renderTabs();
            this.fillForm();
            if (!this.dialog.open) this.dialog.showModal();
        }

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

        fillForm() {
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

        onProviderChange(providerValue) {
            const provider = this.providers.find(p => p.value === providerValue);
            if (!provider) return;
            this.form.elements.apiUrl.value = provider.default_url;
            this.form.elements.model.value = provider.default_model;
        }

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
                custom_worldbook: store.get('worldbook', [])
            };
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
            store.set('gameConfig', Object.assign({}, config, { ais: ais.map(a => Object.assign({}, a, { apiKey: '' })) }));
            window.location.href = 'select_hero.html';
        }

        loadUserData() {
            const userData = store.get('userData', {}) || {};
            document.getElementById('winStreak').textContent = userData.winStreak || 0;
            document.getElementById('totalGames').textContent = userData.totalGames || 0;
            document.getElementById('cardCount').textContent = userData.identityCards || 0;
            document.getElementById('identityCardSection').hidden = !(userData.identityCards > 0);
        }
    }

    document.addEventListener('DOMContentLoaded', () => { window.lobby = new LobbyController(); });
})();
