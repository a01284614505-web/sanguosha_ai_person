// 大厅页面逻辑 - 修复溢出版
class LobbyController {
    constructor() {
        this.selectedMode = null;
        this.aiCount = 0;
        this.aiConfigs = [];

        // Provider 清单以服务端 /api/providers 为准（来源 protocol.py）；
        // 拉取失败时回退到自动生成的 Protocol.PROVIDERS，保证一致性。
        this.providers = [];

        this.init();
    }

    init() {
        // 绑定模式选择按钮
        document.querySelectorAll('.mode-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                this.selectMode(e.currentTarget.dataset.mode);
            });
        });

        // 绑定开始游戏按钮
        document.getElementById('startGameBtn').addEventListener('click', () => {
            this.startGame();
        });

        // 绑定身份卡复选框
        document.getElementById('useIdentityCard').addEventListener('change', (e) => {
            document.getElementById('identitySelect').disabled = !e.target.checked;
        });

        // 绑定聊天开关
        document.getElementById('chatEnabled').addEventListener('change', (e) => {
            document.getElementById('chatModelConfig').style.display = e.target.checked ? 'block' : 'none';
        });

        // 加载用户数据
        this.loadUserData();

        // 默认选择5人身份局
        this.selectMode('5人身份局');

        this.loadProviders();
    }

    loadProviders() {
        var self = this;
        function apply(list) {
            self.providers = (list && list.length) ? list : (window.Protocol ? Protocol.PROVIDERS : []);
            // 聊天模型下拉（index.html）与 AI 配置共用同一 Provider 清单
            var cp = document.getElementById('chatProvider');
            if (cp && !cp.options.length) {
                cp.innerHTML = self.providers.map(function (p) {
                    return '<option value="' + p.value + '">' + p.name + '</option>';
                }).join('');
            }
            self.generateAIConfigs();
        }
        fetch('/api/providers', { cache: 'no-store' })
            .then(function (r) { return r.json(); })
            .then(function (d) { apply(d && d.providers); })
            .catch(function () { apply(null); });
    }

    selectMode(mode) {
        this.selectedMode = mode;
        
        document.querySelectorAll('.mode-btn').forEach(btn => {
            btn.classList.toggle('selected', btn.dataset.mode === mode);
        });

        const aiCountMap = {
            '5人身份局': 4,
            '8人身份局': 7,
            '2v2': 3,
            '斗地主': 2
        };
        
        this.aiCount = aiCountMap[mode] || 4;
        document.getElementById('requiredAI').textContent = this.aiCount;

        this.updateIdentityOptions(mode);
        this.generateAIConfigs();
    }

    updateIdentityOptions(mode) {
        const identitySelect = document.getElementById('identitySelect');
        identitySelect.innerHTML = '<option value="">选择身份</option>';

        let identities = [];
        if (mode === '5人身份局') {
            identities = ['主公', '忠臣', '反贼', '内奸'];
        } else if (mode === '8人身份局') {
            identities = ['主公', '忠臣', '反贼', '内奸'];
        } else if (mode === '2v2') {
            identities = ['队伍A', '队伍B'];
        } else if (mode === '斗地主') {
            identities = ['地主', '农民'];
        }

        identities.forEach(identity => {
            const option = document.createElement('option');
            option.value = identity;
            option.textContent = identity;
            identitySelect.appendChild(option);
        });
    }

    generateAIConfigs() {
        // Provider 清单异步加载中（或拉取失败且无回退）时不渲染，
        // 等 loadProviders 完成后重新调用本函数。
        if (!this.providers.length) return;

        const aiList = document.getElementById('aiConfigList');
        aiList.innerHTML = '';

        const aiNames = ['诸葛村夫', '曹操的粉丝', '小乔我老婆', '吕布', '司马懿', '周瑜', '赵云', '关羽'];

        for (let i = 0; i < this.aiCount; i++) {
            const aiItem = document.createElement('div');
            aiItem.className = 'ai-item';
            aiItem.dataset.aiIndex = i;
            
            const globalSettings = window.getGlobalSettings ? getGlobalSettings() : {};
            const preferred = this.providers.find(p => p.value === globalSettings.default_provider);
            const defaultProvider = preferred || this.providers[i % this.providers.length];
            const defaultModel = globalSettings.default_model || defaultProvider.default_model;
            const defaultTemperature = globalSettings.default_temperature ?? 0.8;
            
            aiItem.innerHTML = `
                <div class="ai-item-header">AI ${i + 1}: ${aiNames[i] || 'AI' + (i + 1)}</div>
                <div class="ai-controls">
                    <div class="config-row field-name">
                        <label>AI名称:</label>
                        <input type="text" placeholder="AI名称" value="${aiNames[i] || 'AI' + (i + 1)}" data-field="name">
                    </div>
                    
                    <div class="config-row field-provider">
                        <label>Provider:</label>
                        <select data-field="provider">
                            ${this.providers.map(p => `<option value="${p.value}" ${p.value === defaultProvider.value ? 'selected' : ''}>${p.name}</option>`).join('')}
                        </select>
                    </div>
                    
                    <div class="config-row field-url">
                        <label>API地址:</label>
                        <input type="text" placeholder="API地址" value="${defaultProvider.default_url}" data-field="apiUrl">
                    </div>
                    
                    <div class="config-row field-key">
                        <label>API Key:</label>
                        <input type="password" placeholder="sk-..." value="" data-field="apiKey">
                    </div>
                    
                    <div class="config-row">
                        <label>模型名称:</label>
                        <input type="text" placeholder="模型名" value="${defaultModel}" data-field="model">
                    </div>
                    
                    <div class="config-row">
                        <label>温度(0-2):</label>
                        <input type="number" placeholder="0.8" value="${defaultTemperature}" min="0" max="2" step="0.1" data-field="temperature">
                    </div>
                    
                    <div class="config-row">
                        <label>
                            <input type="checkbox" data-field="thinking"> 启用思考模式
                        </label>
                    </div>
                </div>
                
                <div class="api-sync-section">
                    <span class="api-sync-label">🔗 将此API配置同步给其他AI：</span>
                    <div class="sync-checkboxes" data-sync-target="${i}">
                        <!-- 同步选项将动态生成 -->
                    </div>
                </div>
            `;
            
            aiList.appendChild(aiItem);
            
            // 绑定Provider变化事件
            const providerSelect = aiItem.querySelector('[data-field="provider"]');
            providerSelect.addEventListener('change', (e) => {
                this.onProviderChange(i, e.target.value);
            });

            // 生成同步选项
            this.generateSyncOptions(i);
        }
    }

    onProviderChange(aiIndex, providerValue) {
        const provider = this.providers.find(p => p.value === providerValue);
        if (!provider) return;

        const aiItem = document.querySelector(`[data-ai-index="${aiIndex}"]`);
        aiItem.querySelector('[data-field="apiUrl"]').value = provider.default_url;
        aiItem.querySelector('[data-field="model"]').value = provider.default_model;
    }

    generateSyncOptions(sourceIndex) {
        const syncContainer = document.querySelector(`[data-sync-target="${sourceIndex}"]`);
        syncContainer.innerHTML = '';

        for (let i = 0; i < this.aiCount; i++) {
            if (i === sourceIndex) continue;

            const label = document.createElement('label');
            label.className = 'sync-checkbox-item';
            label.innerHTML = `
                <input type="checkbox" data-sync-from="${sourceIndex}" data-sync-to="${i}">
                AI ${i + 1}
            `;

            label.querySelector('input').addEventListener('change', (e) => {
                if (e.target.checked) {
                    this.syncAPIConfig(sourceIndex, i);
                }
            });

            syncContainer.appendChild(label);
        }
    }

    syncAPIConfig(fromIndex, toIndex) {
        const sourceItem = document.querySelector(`[data-ai-index="${fromIndex}"]`);
        const targetItem = document.querySelector(`[data-ai-index="${toIndex}"]`);

        const apiUrl = sourceItem.querySelector('[data-field="apiUrl"]').value;
        const apiKey = sourceItem.querySelector('[data-field="apiKey"]').value;
        const provider = sourceItem.querySelector('[data-field="provider"]').value;

        targetItem.querySelector('[data-field="apiUrl"]').value = apiUrl;
        targetItem.querySelector('[data-field="apiKey"]').value = apiKey;
        targetItem.querySelector('[data-field="provider"]').value = provider;

        console.log(`✅ 已将 AI ${fromIndex + 1} 的API配置同步到 AI ${toIndex + 1}`);
    }

    collectAIConfigs() {
        const configs = [];
        document.querySelectorAll('.ai-item').forEach((item, index) => {
            const config = {
                name: item.querySelector('[data-field="name"]').value,
                provider: item.querySelector('[data-field="provider"]').value,
                apiUrl: item.querySelector('[data-field="apiUrl"]').value,
                apiKey: item.querySelector('[data-field="apiKey"]').value,
                model: item.querySelector('[data-field="model"]').value,
                temperature: parseFloat(item.querySelector('[data-field="temperature"]').value),
                thinking: item.querySelector('[data-field="thinking"]').checked
            };
            configs.push(config);
        });
        return configs;
    }

    startGame() {
        if (!this.selectedMode) {
            alert('请选择游戏模式');
            return;
        }

        const aiConfigs = this.collectAIConfigs();

        const missingKeys = aiConfigs.filter(ai => !ai.apiKey).map((ai, i) => `AI ${i + 1}: ${ai.name}`);
        if (missingKeys.length > 0) {
            const confirm = window.confirm(
                `以下AI未配置API Key，将无法正常工作：\n${missingKeys.join('\n')}\n\n是否继续？`
            );
            if (!confirm) return;
        }

        const config = {
            mode: this.selectedMode,
            player_name: document.getElementById('playerName').value || '我',
            ais: aiConfigs,
            hero_pool: document.getElementById('heroPool').value,
            chat: {
                enabled: document.getElementById('chatEnabled').checked,
                provider: document.getElementById('chatProvider').value,
                model: document.getElementById('chatModel').value
            },
            global_settings: window.getGlobalSettings ? getGlobalSettings() : {},
            custom_worldbook: JSON.parse(localStorage.getItem('worldbook') || '[]')
        };

        if (document.getElementById('useIdentityCard').checked) {
            const identity = document.getElementById('identitySelect').value;
            if (identity) {
                config.identity_card = {
                    use: true,
                    identity: identity
                };
            }
        }

        console.log('游戏配置:', config);
        
        localStorage.setItem('gameConfig', JSON.stringify(config));
        
        window.location.href = 'select_hero.html';
    }

    loadUserData() {
        const userData = JSON.parse(localStorage.getItem('userData') || '{}');
        
        document.getElementById('winStreak').textContent = userData.winStreak || 0;
        document.getElementById('totalGames').textContent = userData.totalGames || 0;
        document.getElementById('cardCount').textContent = userData.identityCards || 0;

        if (userData.identityCards > 0) {
            document.getElementById('identityCardSection').style.display = 'block';
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new LobbyController();
});
