// 结算页面逻辑
class ResultController {
    constructor() {
        this.resultData = null;
        
        this.init();
    }

    init() {
        // 加载结算数据
        this.resultData = JSON.parse(localStorage.getItem('gameResult') || '{}');
        
        if (!this.resultData.winner) {
            alert('未找到游戏结果');
            window.location.href = 'index.html';
            return;
        }

        // 渲染结算页面
        this.render();

        // 绑定按钮
        document.getElementById('playAgainBtn').addEventListener('click', () => {
            // 保留配置，重新开始
            window.location.href = 'index.html';
        });

        document.getElementById('backToLobbyBtn').addEventListener('click', () => {
            window.location.href = 'index.html';
        });
    }

    identityText(identity) {
        const map = {lord:'主公', loyalist:'忠臣', rebel:'反贼', spy:'内奸', aborted:'主动终止', draw:'平局'};
        return map[identity] || identity || '未知';
    }

    // 渲染结算页面
    render() {
        // 标题
        const isVictory = this.resultData.player_won;
        document.getElementById('resultTitle').textContent = isVictory ? '胜利！' : '失败';
        document.getElementById('resultTitle').style.color = isVictory ? 'var(--success)' : 'var(--danger)';
        document.getElementById('resultSubtitle').textContent = this.resultData.winner === 'aborted' ? (this.resultData.message || '本局已主动结束') : `${this.identityText(this.resultData.winner)}阵营获胜`;

        // 统计信息
        document.getElementById('totalRounds').textContent = this.resultData.total_rounds || 0;
        document.getElementById('gameDuration').textContent = this.formatDuration(this.resultData.duration || 0);
        document.getElementById('yourIdentity').textContent = this.identityText(this.resultData.player_identity);

        // MVP信息（真实统计来自引擎 game_end payload）
        const mvpCard = document.getElementById('mvpCard');
        if (this.resultData.mvp) {
            mvpCard.style.display = '';
            this.renderMVP(this.resultData.mvp);
        } else {
            mvpCard.style.display = 'none';
        }

        // 玩家数据
        this.renderStats();

        // 身份揭示
        this.renderIdentities();

        // 奖励
        this.renderRewards();
    }

    // 格式化时长
    formatDuration(seconds) {
        const total = Math.max(0, Number(seconds) || 0);
        const minutes = Math.floor(total / 60);
        const secs = Math.floor(total % 60);
        return `${minutes}分${secs}秒`;
    }

    // 渲染MVP
    renderMVP(mvp) {
        const mvpInfo = document.getElementById('mvpInfo');
        const heroName = mvp.hero_name ? ` (${mvp.hero_name})` : '';
        mvpInfo.innerHTML = `
            <div class="mvp-hero">
                <img src="assets/heroes/${mvp.hero_id}.jpg" alt="${mvp.hero_name}" onerror="this.style.display='none'">
                <div class="mvp-name">${mvp.player_name}${heroName}</div>
            </div>
            <div class="mvp-stats">
                <div>击杀：${mvp.kills || 0}</div>
                <div>伤害：${mvp.damage_dealt || 0}</div>
                <div>治疗：${mvp.healing || 0}</div>
                <div>出牌：${mvp.cards_played || 0}</div>
            </div>
        `;
    }

    // 渲染每名玩家的真实对局统计
    renderStats() {
        const list = document.getElementById('statsList');
        list.innerHTML = '';
        const players = this.resultData.players || [];
        if (!players.length) return;

        const headers = ['玩家', '伤害', '承伤', '治疗', '击杀', '出牌', '失牌', '技能'];
        const head = document.createElement('div');
        head.className = 'stats-row stats-head';
        headers.forEach(label => {
            const cell = document.createElement('div');
            cell.textContent = label;
            head.appendChild(cell);
        });
        list.appendChild(head);

        players.forEach(player => {
            const stats = player.stats || {};
            const values = [
                player.name + (player.hero_name ? `（${player.hero_name}）` : ''),
                stats.damage_dealt || 0,
                stats.damage_taken || 0,
                stats.healing || 0,
                stats.kills || 0,
                stats.cards_played || 0,
                stats.cards_lost || 0,
                stats.skill_activations || 0
            ];
            const row = document.createElement('div');
            row.className = 'stats-row' + (player.alive ? '' : ' dead');
            values.forEach(value => {
                const cell = document.createElement('div');
                cell.textContent = value;
                row.appendChild(cell);
            });
            list.appendChild(row);
        });
    }

    // 渲染身份揭示
    renderIdentities() {
        const identityList = document.getElementById('identityList');
        identityList.innerHTML = '';

        if (!this.resultData.players) return;

        this.resultData.players.forEach(player => {
            const item = document.createElement('div');
            item.className = 'identity-item';
            
            const identityClass = this.getIdentityClass(player.identity);
            
            item.innerHTML = `
                <div style="font-weight: bold; margin-bottom: 5px;">${player.name}</div>
                <div style="color: var(--text-muted); font-size: 12px;">${player.hero_name}</div>
                <div class="identity-badge identity-${identityClass}">${this.identityText(player.identity)}</div>
                <div style="margin-top: 5px; font-size: 12px;">
                    ${player.alive ? '存活' : '阵亡'}
                </div>
            `;
            
            identityList.appendChild(item);
        });
    }

    // 获取身份CSS类
    getIdentityClass(identity) {
        const classMap = {
            '主公': 'lord',
            'lord': 'lord',
            '忠臣': 'loyalist',
            'loyalist': 'loyalist',
            '反贼': 'rebel',
            'rebel': 'rebel',
            '内奸': 'spy',
            'spy': 'spy',
            '地主': 'lord',
            '农民': 'farmer'
        };
        return classMap[identity] || '';
    }

    // 渲染奖励
    renderRewards() {
        const userData = JSON.parse(localStorage.getItem('userData') || '{}');
        const winStreak = userData.winStreak || 0;

        // 如果刚获得身份卡（连胜2的倍数）
        if (this.resultData.player_won && winStreak > 0 && winStreak % 2 === 0) {
            document.getElementById('rewardSection').style.display = 'block';
        }
    }
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    new ResultController();
});
