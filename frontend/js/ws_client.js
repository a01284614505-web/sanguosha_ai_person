// WebSocket客户端 - 完整重写
class GameClient {
    constructor() {
        this.ws = null;
        this.gameId = null;
        this.connected = false;
    }
    
    connect() {
        const wsUrl = `ws://${window.location.hostname}:8889`;
        console.log('[WS] 连接:', wsUrl);
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onopen = () => {
            this.connected = true;
            console.log('[WS] 已连接');
            if (this.onConnect) this.onConnect();
        };
        
        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.handleMessage(data);
            } catch (e) {
                console.error('[WS] 解析失败:', e);
            }
        };
        
        this.ws.onclose = () => {
            this.connected = false;
            console.log('[WS] 断开');
            if (this.onDisconnect) this.onDisconnect();
        };
        
        this.ws.onerror = (e) => {
            console.error('[WS] 错误:', e);
        };
    }
    
    handleMessage(data) {
        switch (data.type) {
            case 'game_created':
                this.gameId = data.game_id;
                console.log('[游戏] 已创建:', this.gameId);
                break;
            
            case 'game_state':
                if (this.onStateUpdate) this.onStateUpdate(data.state);
                break;
            
            case 'your_turn':
                if (this.onYourTurn) this.onYourTurn(data);
                break;
            
            case 'action_result':
                if (this.onActionResult) this.onActionResult(data.success);
                break;
            
            case 'game_end':
                if (this.onGameEnd) this.onGameEnd(data);
                break;
            
            case 'chat':
                if (this.onChat) this.onChat(data);
                break;
            
            case 'ai_action':
                if (this.onAIAction) this.onAIAction(data);
                break;
            
            case 'require_response':
                if (this.onRequireResponse) this.onRequireResponse(data);
                break;
            case 'event_notification':
                if (this.onEventNotification) this.onEventNotification(data);
                break;
            case 'ai_config_updated':
                if (this.onAIConfigUpdated) this.onAIConfigUpdated(data.config);
                break;
            case 'end_game_accepted':
                if (this.onEndGameAccepted) this.onEndGameAccepted(data);
                break;
            case 'error':
                console.error('[服务器错误]', data.message);
                if (this.onError) this.onError(data);
                break;
        }
    }
    
    createGame(config) {
        if (!this.connected) { console.error('[WS] 未连接'); return; }
        this.send({ type: 'create_game', config: config });
    }
    
    playerAction(action, targetIds) {
        if (!this.connected || !this.gameId) return;
        targetIds = targetIds || [];
        console.log('[操作]', action.type);
        this.send({ type: 'player_action', action: action, target_ids: targetIds });
    }
    
    sendChat(msg) {
        if (!this.connected || !this.gameId) return;
        this.send({ type: 'chat', message: msg });
    }
    
    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        }
    }
}

// 回调（由页面设置）
GameClient.prototype.onConnect = null;
GameClient.prototype.onDisconnect = null;
GameClient.prototype.onStateUpdate = null;
GameClient.prototype.onYourTurn = null;
GameClient.prototype.onActionResult = null;
GameClient.prototype.onGameEnd = null;
GameClient.prototype.onChat = null;
GameClient.prototype.onAIAction = null;
GameClient.prototype.onRequireResponse = null;
GameClient.prototype.onEventNotification = null;
GameClient.prototype.onError = null;
GameClient.prototype.onAIConfigUpdated = null;
GameClient.prototype.onEndGameAccepted = null;

// 全局实例
const gameClient = new GameClient();

if (typeof module !== 'undefined' && module.exports) {
    module.exports = GameClient;
}
