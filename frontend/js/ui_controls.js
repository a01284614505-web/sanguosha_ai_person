// 游戏UI控制器 - 增强版（支持真实AI聊天）
class GameUIController {
    constructor() {
        this.availableActions = [];
        this.currentAction = null;
        this.targetSelectionMode = false;
        this.gameConfig = null;
        
        this.init();
    }

    init() {
        // 加载游戏配置
        this.gameConfig = JSON.parse(localStorage.getItem('gameConfig') || '{}');
        
        // 连接WebSocket
        wsClient.connect().then(() => {
            console.log('游戏已连接到服务器');
            
            // 发送游戏配置到服务器
            wsClient.send({
                type: 'init_game',
                config: this.gameConfig
            });
            
            // 请求游戏状态
            wsClient.send({
                type: 'request_game_state'
            });
        });

        // 注册消息处理器
        wsClient.on('game_state_update', (data) => {
            gameRenderer.updateGameState(data.state);
        });

        wsClient.on('available_actions', (data) => {
            this.availableActions = data.actions;
            this.updateAvailableActions();
        });

        wsClient.on('event_notification', (data) => {
            this.handleEvent(data);
        });

        wsClient.on('game_end', (data) => {
            this.handleGameEnd(data);
        });

        // 绑定按钮事件
        this.bindButtons();

        // 设置为全局对象
        window.gameUI = this;
    }

    bindButtons() {
        // 结束阶段
        document.getElementById('endPhaseBtn').addEventListener('click', () => {
            this.endPhase();
        });

        // 使用技能
        document.getElementById('useSkillBtn').addEventListener('click', () => {
            this.showSkillMenu();
        });

        // 取消
        document.getElementById('cancelBtn').addEventListener('click', () => {
            this.cancelAction();
        });

        // 菜单按钮
        document.getElementById('menuBtn').addEventListener('click', () => {
            document.getElementById('menuPanel').style.display = 'flex';
        });

        document.getElementById('resumeBtn').addEventListener('click', () => {
            document.getElementById('menuPanel').style.display = 'none';
        });

        document.getElementById('surrenderBtn').addEventListener('click', () => {
            if (confirm('确定要投降吗？')) {
                wsClient.send({ type: 'surrender' });
            }
        });

        document.getElementById('exitBtn').addEventListener('click', () => {
            if (confirm('确定要退出游戏吗？')) {
                window.location.href = 'index.html';
            }
        });

        // 目标确认按钮
        document.getElementById('confirmTargetBtn').addEventListener('click', () => {
            this.confirmTargets();
        });

        document.getElementById('cancelTargetBtn').addEventListener('click', () => {
            this.cancelTargetSelection();
        });
    }

    updateAvailableActions() {
        const hasEndPhase = this.availableActions.some(a => a.type === 'end_phase');
        const hasUseSkill = this.availableActions.some(a => a.type === 'use_skill');

        document.getElementById('endPhaseBtn').disabled = !hasEndPhase;
        document.getElementById('useSkillBtn').disabled = !hasUseSkill;
    }

    onCardSelected(selectedCards) {
        if (selectedCards.length === 0) {
            document.getElementById('cancelBtn').disabled = true;
            return;
        }

        document.getElementById('cancelBtn').disabled = false;

        const canPlayCard = this.availableActions.some(a => a.type === 'play_card');
        
        if (canPlayCard) {
            this.preparePlayCard(selectedCards[0]);
        }
    }

    preparePlayCard(cardIndex) {
        const player = gameRenderer.gameState.players.find(p => p.id === gameRenderer.playerId);
        const card = player.hand[cardIndex];

        if (card.target_rule && card.target_rule.target_count > 0) {
            this.startTargetSelection(cardIndex, card);
        } else {
            this.playCard(cardIndex, []);
        }
    }

    startTargetSelection(cardIndex, card) {
        this.currentAction = {
            type: 'play_card',
            cardIndex: cardIndex,
            card: card
        };

        this.targetSelectionMode = true;
        
        document.getElementById('targetOverlay').style.display = 'flex';
        document.getElementById('targetPromptText').textContent = 
            `请为【${card.name}】选择${card.target_rule.target_count}个目标`;

        gameRenderer.enableTargetSelection(card.target_rule.target_count);
    }

    onTargetSelected(selectedTargets) {
        if (!this.currentAction) return;

        const requiredCount = this.currentAction.card.target_rule.target_count;
        
        document.getElementById('confirmTargetBtn').disabled = 
            selectedTargets.length !== requiredCount;
    }

    confirmTargets() {
        if (!this.currentAction) return;

        const targets = gameRenderer.selectedTargets;
        this.playCard(this.currentAction.cardIndex, targets);

        this.cancelTargetSelection();
    }

    cancelTargetSelection() {
        this.targetSelectionMode = false;
        this.currentAction = null;
        
        document.getElementById('targetOverlay').style.display = 'none';
        
        gameRenderer.clearSelection();
        
        document.querySelectorAll('.opponent-card.targetable').forEach(card => {
            card.classList.remove('targetable');
        });
    }

    playCard(cardIndex, targetIds) {
        wsClient.send({
            type: 'select_action',
            action: {
                type: 'play_card',
                card_index: cardIndex,
                target_ids: targetIds
            }
        });

        gameRenderer.clearSelection();
    }

    endPhase() {
        wsClient.send({
            type: 'select_action',
            action: {
                type: 'end_phase'
            }
        });
    }

    showSkillMenu() {
        const player = gameRenderer.gameState.players.find(p => p.id === gameRenderer.playerId);
        
        if (!player.hero.skills || player.hero.skills.length === 0) {
            alert('当前没有可用技能');
            return;
        }

        const skills = player.hero.skills.join('\n');
        const skillName = prompt(`可用技能：\n${skills}\n\n请输入要使用的技能名：`);
        
        if (skillName) {
            this.useSkill(skillName);
        }
    }

    useSkill(skillName) {
        wsClient.send({
            type: 'select_action',
            action: {
                type: 'use_skill',
                skill_name: skillName
            }
        });
    }

    cancelAction() {
        gameRenderer.clearSelection();
        this.cancelTargetSelection();
        document.getElementById('cancelBtn').disabled = true;
    }

    handleEvent(data) {
        const message = this.formatEventMessage(data);
        const important = data.important || false;
        
        gameRenderer.addEventLog(message, important);
    }

    formatEventMessage(data) {
        if (data.message) {
            return data.message;
        }

        return `${data.source_name || '某人'} 对 ${data.target_name || '某人'} 使用了 ${data.card_name || '某操作'}`;
    }

    handleGameEnd(data) {
        localStorage.setItem('gameResult', JSON.stringify(data));

        const userData = JSON.parse(localStorage.getItem('userData') || '{}');
        userData.totalGames = (userData.totalGames || 0) + 1;
        
        if (data.winner === data.player_team) {
            userData.winStreak = (userData.winStreak || 0) + 1;
            
            if (userData.winStreak % 2 === 0) {
                userData.identityCards = (userData.identityCards || 0) + 1;
            }
        } else {
            userData.winStreak = 0;
        }
        
        localStorage.setItem('userData', JSON.stringify(userData));

        setTimeout(() => {
            window.location.href = 'result.html';
        }, 2000);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new GameUIController();
});
