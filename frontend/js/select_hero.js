// 选将页面逻辑
class HeroSelectController {
    constructor() {
        this.gameConfig = null;
        this.availableHeroes = [];
        this.selectedHero = null;
        this.otherPlayers = [];
        this.timeLeft = 60;
        this.timer = null;
        
        this.init();
    }

    init() {
        // 加载游戏配置
        this.gameConfig = JSON.parse(localStorage.getItem('gameConfig') || '{}');
        if (!this.gameConfig.mode) {
            alert('未找到游戏配置，返回大厅');
            window.location.href = 'index.html';
            return;
        }

        // 连接WebSocket
        wsClient.connect().then(() => {
            // 请求可选武将列表
            wsClient.send({
                type: 'request_heroes',
                config: this.gameConfig
            });
        }).catch(err => {
            console.error('连接失败:', err);
            alert('连接服务器失败，请检查服务器是否启动');
        });

        // 注册消息处理器
        wsClient.on('hero_list', (data) => {
            this.availableHeroes = data.heroes;
            this.renderHeroes();
        });

        wsClient.on('other_selections', (data) => {
            this.otherPlayers = data.players;
            this.renderOtherSelections();
        });

        wsClient.on('selection_complete', () => {
            this.startGame();
        });

        // 绑定确认按钮
        document.getElementById('confirmBtn').addEventListener('click', () => {
            this.confirmSelection();
        });

        // 开始倒计时
        this.startTimer();
    }

    // 渲染武将列表
    renderHeroes() {
        const heroList = document.getElementById('heroList');
        heroList.innerHTML = '';

        this.availableHeroes.forEach(hero => {
            const heroCard = document.createElement('div');
            heroCard.className = 'hero-card';
            heroCard.dataset.heroId = hero.id;
            
            heroCard.innerHTML = `
                <div class="hero-avatar">${this.getHeroIcon(hero.faction)}</div>
                <div class="hero-name">${hero.name}</div>
                <div class="hero-faction faction-${hero.faction}">${hero.faction}</div>
                <div class="hero-hp">体力: ${hero.max_hp}</div>
            `;

            heroCard.addEventListener('click', () => {
                this.selectHero(hero);
            });

            heroList.appendChild(heroCard);
        });
    }

    // 获取武将图标（占位符）
    getHeroIcon(faction) {
        const icons = {
            '魏': '⚔️',
            '蜀': '🐉',
            '吴': '🦅',
            '群': '⭐'
        };
        return icons[faction] || '👤';
    }

    // 选择武将
    selectHero(hero) {
        // 移除之前的选中状态
        document.querySelectorAll('.hero-card').forEach(card => {
            card.classList.remove('selected');
        });

        // 添加新的选中状态
        document.querySelector(`[data-hero-id="${hero.id}"]`).classList.add('selected');

        this.selectedHero = hero;

        // 更新选中的武将显示
        const selectedHeroDiv = document.getElementById('selectedHero');
        selectedHeroDiv.innerHTML = `
            <div class="hero-avatar" style="width: 100px; height: 100px; font-size: 40px;">
                ${this.getHeroIcon(hero.faction)}
            </div>
            <div style="margin-top: 10px;">
                <div style="font-size: 20px; font-weight: bold;">${hero.name}</div>
                <div style="color: var(--text-muted);">${hero.faction} | 体力: ${hero.max_hp}</div>
                <div style="margin-top: 10px; font-size: 12px; color: var(--text-muted);">
                    技能: ${hero.skills ? hero.skills.join('、') : '无'}
                </div>
            </div>
        `;

        // 启用确认按钮
        document.getElementById('confirmBtn').disabled = false;
    }

    // 确认选择
    confirmSelection() {
        if (!this.selectedHero) {
            alert('请先选择武将');
            return;
        }

        // 发送选择到服务器
        wsClient.send({
            type: 'select_hero',
            hero_id: this.selectedHero.id
        });

        // 禁用所有武将卡片
        document.querySelectorAll('.hero-card').forEach(card => {
            card.classList.add('disabled');
        });

        document.getElementById('confirmBtn').disabled = true;
        document.getElementById('selectPrompt').textContent = '等待其他玩家选择...';
    }

    // 渲染其他玩家的选择情况
    renderOtherSelections() {
        const otherList = document.getElementById('otherSelections');
        otherList.innerHTML = '';

        this.otherPlayers.forEach(player => {
            const item = document.createElement('div');
            item.className = 'other-item';
            
            const status = player.selected ? '已选择' : '选择中...';
            const heroName = player.hero_name || '未知';
            
            item.innerHTML = `
                <span>${player.name}</span>
                <span style="color: ${player.selected ? 'var(--success)' : 'var(--warning)'}">
                    ${player.selected ? heroName : status}
                </span>
            `;
            
            otherList.appendChild(item);
        });
    }

    // 开始倒计时
    startTimer() {
        this.timer = setInterval(() => {
            this.timeLeft--;
            document.getElementById('timeLeft').textContent = this.timeLeft;

            if (this.timeLeft <= 0) {
                clearInterval(this.timer);
                // 时间到，随机选择一个武将
                if (!this.selectedHero && this.availableHeroes.length > 0) {
                    const randomHero = this.availableHeroes[Math.floor(Math.random() * this.availableHeroes.length)];
                    this.selectHero(randomHero);
                    this.confirmSelection();
                }
            }
        }, 1000);
    }

    // 开始游戏
    startGame() {
        clearInterval(this.timer);
        // 跳转到游戏页面
        setTimeout(() => {
            window.location.href = 'game.html';
        }, 1000);
    }
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    new HeroSelectController();
});
