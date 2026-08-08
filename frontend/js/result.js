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

        // MVP信息
        if (this.resultData.mvp) {
            this.renderMVP(this.resultData.mvp);
        }

        // 身份揭示
        this.renderIdentities();

        // 奖励
        this.renderRewards();
    }

    // 格式化时长
    formatDuration(seconds) {
        const minutes = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${minutes}分${secs}秒`;
    }

    // 渲染MVP
    renderMVP(mvp) {
        const mvpInfo = document.getElementById('mvpInfo');
        
        mvpInfo.innerHTML = `
            <div class="mvp-hero">
                <img src="assets/heroes/${mvp.hero_id}.jpg" alt="${mvp.hero_name}" onerror="this.style.display='none'">
                <div class="mvp-name">${mvp.player_name} (${mvp.hero_name})</div>
            </div>
            <div class="mvp-stats">
                <div>击杀：${mvp.kills || 0}</div>
                <div>伤害：${mvp.damage || 0}</div>
                <div>治疗：${mvp.healing || 0}</div>
                <div>出牌：${mvp.cards_played || 0}</div>
            </div>
        `;
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
