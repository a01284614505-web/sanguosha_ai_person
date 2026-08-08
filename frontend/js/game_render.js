// 游戏状态渲染器
class GameRenderer {
    constructor() {
        this.gameState = null;
        this.playerId = null;
        this.selectedCards = [];
        this.selectedTargets = [];
    }

    // 更新游戏状态
    updateGameState(state) {
        this.gameState = state;
        this.playerId = state.player_id;
        this.render();
    }

    // 完整渲染
    render() {
        if (!this.gameState) return;

        this.renderGameInfo();
        this.renderOpponents();
        this.renderPlayer();
        this.renderDeckInfo();
        this.updateActionButtons();
    }

    // 渲染游戏信息
    renderGameInfo() {
        document.getElementById('roundNum').textContent = this.gameState.round_number || 1;
        document.getElementById('currentPhase').textContent = this.getPhaseText(this.gameState.current_phase);
    }

    // 获取阶段文本
    getPhaseText(phase) {
        const phaseMap = {
            'PREPARE': '准备阶段',
            'JUDGE': '判定阶段',
            'DRAW': '摸牌阶段',
            'PLAY': '出牌阶段',
            'DISCARD': '弃牌阶段',
            'END': '结束阶段'
        };
        return phaseMap[phase] || phase;
    }

    // 渲染对手
    renderOpponents() {
        const opponentsList = document.getElementById('opponentsList');
        opponentsList.innerHTML = '';

        const opponents = this.gameState.players.filter(p => p.id !== this.playerId);

        opponents.forEach(player => {
            const opponentCard = this.createOpponentCard(player);
            opponentsList.appendChild(opponentCard);
        });
    }

    // 创建对手卡片
    createOpponentCard(player) {
        const card = document.createElement('div');
        card.className = 'opponent-card';
        card.dataset.playerId = player.id;

        // 当前回合高亮
        if (player.id === this.gameState.current_turn) {
            card.classList.add('current-turn');
        }

        // 死亡状态
        if (!player.alive) {
            card.classList.add('dead');
        }

        // 身份显示
        let identityDisplay = '？';
        let identityClass = '';
        if (player.identity_revealed || player.identity === '主公') {
            identityDisplay = this.getIdentityIcon(player.identity);
            identityClass = 'identity-' + this.getIdentityClass(player.identity);
        }

        card.innerHTML = `
            <div class="opponent-identity ${identityClass}">${identityDisplay}</div>
            <div class="opponent-avatar">
                <img src="assets/heroes/${player.hero.id}.jpg" alt="${player.hero.name}" onerror="this.style.display='none'">
                ${!player.hero ? this.getHeroIcon(player.faction) : ''}
            </div>
            <div class="opponent-name">${player.name}</div>
            <div class="opponent-hp">${this.renderHP(player.hp, player.max_hp)}</div>
            <div class="opponent-handcount">🃏 ${player.hand_count || 0}</div>
            <div class="opponent-equipment">${this.renderEquipmentIcons(player.equipment)}</div>
        `;

        return card;
    }

    // 渲染体力
    renderHP(hp, maxHp) {
        return `${'❤️'.repeat(hp)}${'🖤'.repeat(maxHp - hp)} ${hp}/${maxHp}`;
    }

    // 渲染装备图标
    renderEquipmentIcons(equipment) {
        if (!equipment || Object.keys(equipment).length === 0) {
            return '';
        }

        const icons = {
            '武器': '⚔️',
            '防具': '🛡️',
            '+1马': '🐴',
            '-1马': '🐎'
        };

        return Object.keys(equipment)
            .map(type => `<div class="equipment-icon" title="${equipment[type].name}">${icons[type] || '📦'}</div>`)
            .join('');
    }

    // 获取身份图标
    getIdentityIcon(identity) {
        const icons = {
            '主公': '👑',
            '忠臣': '🛡️',
            '反贼': '⚔️',
            '内奸': '🗡️',
            '地主': '💰',
            '农民': '🌾'
        };
        return icons[identity] || '？';
    }

    // 获取身份CSS类
    getIdentityClass(identity) {
        const classMap = {
            '主公': 'lord',
            '忠臣': 'loyalist',
            '反贼': 'rebel',
            '内奸': 'spy',
            '地主': 'lord',
            '农民': 'farmer'
        };
        return classMap[identity] || '';
    }

    // 获取武将图标
    getHeroIcon(faction) {
        const icons = {
            '魏': '⚔️',
            '蜀': '🐉',
            '吴': '🦅',
            '群': '⭐'
        };
        return icons[faction] || '👤';
    }

    // 渲染玩家自己
    renderPlayer() {
        const player = this.gameState.players.find(p => p.id === this.playerId);
        if (!player) return;

        // 武将信息
        document.getElementById('playerHeroName').textContent = player.hero.name;
        const playerAvatar = document.getElementById('playerAvatar');
        playerAvatar.querySelector('img').src = `assets/heroes/${player.hero.id}.jpg`;

        // 体力
        document.getElementById('playerHP').textContent = `${player.hp}/${player.max_hp}`;
        this.renderPlayerHearts(player.hp, player.max_hp);

        // 身份
        let identityDisplay = '？';
        if (player.identity_revealed || player.identity === '主公') {
            identityDisplay = player.identity;
        }
        document.getElementById('playerIdentity').innerHTML = 
            `<span class="identity-badge identity-${this.getIdentityClass(player.identity)}">${identityDisplay}</span>`;

        // 装备
        this.renderPlayerEquipment(player.equipment);

        // 手牌
        this.renderPlayerHand(player.hand);
    }

    // 渲染玩家体力心形
    renderPlayerHearts(hp, maxHp) {
        const heartsDiv = document.getElementById('playerHearts');
        heartsDiv.innerHTML = '';

        for (let i = 0; i < maxHp; i++) {
            const heart = document.createElement('div');
            heart.className = 'hp-heart';
            if (i >= hp) {
                heart.classList.add('lost');
            }
            heartsDiv.appendChild(heart);
        }
    }

    // 渲染玩家装备
    renderPlayerEquipment(equipment) {
        const equipmentDiv = document.getElementById('playerEquipment');
        equipmentDiv.innerHTML = '';

        const slots = ['武器', '防具', '+1马', '-1马'];
        
        slots.forEach(slot => {
            const slotDiv = document.createElement('div');
            slotDiv.className = 'equipment-slot';
            
            if (equipment && equipment[slot]) {
                const card = equipment[slot];
                slotDiv.innerHTML = `<div class="equipment-card">${card.name}</div>`;
                slotDiv.title = card.name;
            } else {
                slotDiv.textContent = slot;
            }
            
            equipmentDiv.appendChild(slotDiv);
        });
    }

    // 渲染玩家手牌
    renderPlayerHand(hand) {
        const handCardsDiv = document.getElementById('handCards');
        handCardsDiv.innerHTML = '';
        
        document.getElementById('handCount').textContent = hand ? hand.length : 0;

        if (!hand || hand.length === 0) {
            return;
        }

        hand.forEach((card, index) => {
            const cardDiv = this.createCardElement(card, index);
            handCardsDiv.appendChild(cardDiv);
        });
    }

    // 创建卡牌元素
    createCardElement(card, index) {
        const cardDiv = document.createElement('div');
        cardDiv.className = `card ${this.getCardClass(card)}`;
        cardDiv.dataset.cardIndex = index;
        cardDiv.dataset.cardId = card.id;

        cardDiv.innerHTML = `
            <div class="card-suit ${this.getSuitClass(card.suit)}"></div>
            <div class="card-rank">${this.getRankText(card.rank)}</div>
            <div class="card-name">${card.name}</div>
            <div class="card-type">${card.type}</div>
        `;

        cardDiv.addEventListener('click', () => {
            this.onCardClick(index, card);
        });

        return cardDiv;
    }

    // 获取卡牌类型CSS类
    getCardClass(card) {
        const typeMap = {
            '基本': 'basic',
            '锦囊': 'trick',
            '装备': 'equipment',
            '延时锦囊': 'delayed-trick'
        };
        
        const classes = [typeMap[card.type] || '', this.getSuitClass(card.suit)];
        
        // 特定卡牌类
        if (card.name === '杀') classes.push('sha');
        if (card.name === '闪') classes.push('shan');
        if (card.name === '桃') classes.push('tao');
        if (card.name === '酒') classes.push('jiu');
        
        return classes.join(' ');
    }

    // 获取花色CSS类
    getSuitClass(suit) {
        const suitMap = {
            '黑桃': 'spade',
            '红桃': 'heart',
            '梅花': 'club',
            '方块': 'diamond'
        };
        return suitMap[suit] || '';
    }

    // 获取点数文本
    getRankText(rank) {
        if (rank === 1) return 'A';
        if (rank === 11) return 'J';
        if (rank === 12) return 'Q';
        if (rank === 13) return 'K';
        return rank.toString();
    }

    // 渲染牌堆信息
    renderDeckInfo() {
        document.getElementById('deckCount').textContent = this.gameState.deck_count || 0;
        document.getElementById('discardCount').textContent = this.gameState.discard_count || 0;
    }

    // 卡牌点击事件
    onCardClick(index, card) {
        const cardDiv = document.querySelector(`[data-card-index="${index}"]`);
        
        if (cardDiv.classList.contains('selected')) {
            // 取消选择
            cardDiv.classList.remove('selected');
            this.selectedCards = this.selectedCards.filter(i => i !== index);
        } else {
            // 选择卡牌
            cardDiv.classList.add('selected');
            this.selectedCards.push(index);
        }

        // 通知UI控制器
        if (window.gameUI) {
            window.gameUI.onCardSelected(this.selectedCards);
        }
    }

    // 更新操作按钮状态
    updateActionButtons() {
        // 根据可用操作更新按钮状态
        const isMyTurn = this.gameState.current_turn === this.playerId;
        
        document.getElementById('endPhaseBtn').disabled = !isMyTurn;
        document.getElementById('useSkillBtn').disabled = !isMyTurn;
    }

    // 添加事件日志
    addEventLog(message, important = false) {
        const eventLog = document.getElementById('eventLog');
        const eventItem = document.createElement('div');
        eventItem.className = 'event-item' + (important ? ' important' : '');
        eventItem.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
        
        eventLog.appendChild(eventItem);
        eventLog.scrollTop = eventLog.scrollHeight;

        // 限制日志数量
        while (eventLog.children.length > 50) {
            eventLog.removeChild(eventLog.firstChild);
        }
    }

    // 清除选择
    clearSelection() {
        this.selectedCards = [];
        this.selectedTargets = [];
        
        document.querySelectorAll('.card.selected').forEach(card => {
            card.classList.remove('selected');
        });
        
        document.querySelectorAll('.opponent-card.selected').forEach(card => {
            card.classList.remove('selected');
        });
    }

    // 启用目标选择模式
    enableTargetSelection(targetCount) {
        document.querySelectorAll('.opponent-card').forEach(card => {
            if (!card.classList.contains('dead')) {
                card.classList.add('targetable');
                
                const handler = (e) => {
                    this.onTargetClick(parseInt(card.dataset.playerId));
                    card.removeEventListener('click', handler);
                };
                
                card.addEventListener('click', handler);
            }
        });
    }

    // 目标点击事件
    onTargetClick(playerId) {
        const card = document.querySelector(`[data-player-id="${playerId}"]`);
        
        if (card.classList.contains('selected')) {
            card.classList.remove('selected');
            this.selectedTargets = this.selectedTargets.filter(id => id !== playerId);
        } else {
            card.classList.add('selected');
            this.selectedTargets.push(playerId);
        }

        if (window.gameUI) {
            window.gameUI.onTargetSelected(this.selectedTargets);
        }
    }
}

// 全局渲染器实例
const gameRenderer = new GameRenderer();
