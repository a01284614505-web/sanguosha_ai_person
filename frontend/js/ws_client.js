// WebSocket客户端 - 完整重写
// 协议常量来自自动生成的 protocol.js（页面须先加载）；node 测试环境直接 require。
if (typeof module !== 'undefined' && module.exports) {
    var Protocol = require('./protocol.js');
}

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
            case Protocol.OUTBOUND.GAME_CREATED:
                this.gameId = data.game_id;
                console.log('[游戏] 已创建:', this.gameId);
                break;

            case Protocol.OUTBOUND.GAME_STATE:
                if (this.onStateUpdate) this.onStateUpdate(data.state);
                break;

            case Protocol.OUTBOUND.YOUR_TURN:
                if (this.onYourTurn) this.onYourTurn(data);
                break;

            case Protocol.OUTBOUND.ACTION_RESULT:
                if (this.onActionResult) this.onActionResult(data.success);
                break;

            case Protocol.OUTBOUND.GAME_END:
                if (this.onGameEnd) this.onGameEnd(data);
                break;

            case Protocol.OUTBOUND.CHAT:
                if (this.onChat) this.onChat(data);
                break;

            case Protocol.OUTBOUND.AI_ACTION:
                if (this.onAIAction) this.onAIAction(data);
                break;

            case Protocol.OUTBOUND.REQUIRE_RESPONSE:
                if (this.onRequireResponse) this.onRequireResponse(data);
                break;
            case Protocol.OUTBOUND.EVENT_NOTIFICATION:
                if (this.onEventNotification) this.onEventNotification(data);
                break;
            case Protocol.OUTBOUND.AI_CONFIG_UPDATED:
                if (this.onAIConfigUpdated) this.onAIConfigUpdated(data.config);
                break;
            case Protocol.OUTBOUND.END_GAME_ACCEPTED:
                if (this.onEndGameAccepted) this.onEndGameAccepted(data);
                break;
            case Protocol.OUTBOUND.ERROR:
                console.error('[服务器错误]', data.message);
                if (this.onError) this.onError(data);
                break;
            case Protocol.OUTBOUND.PONG:
                if (this.onPong) this.onPong(data);
                break;
            case Protocol.OUTBOUND.SERVER_INFO:
                if (this.onServerInfo) this.onServerInfo(data);
                break;
        }
    }

    createGame(config) {
        if (!this.connected) { console.error('[WS] 未连接'); return; }
        this.send({ type: Protocol.INBOUND.CREATE_GAME, config: config });
    }

    playerAction(action, targetIds) {
        if (!this.connected || !this.gameId) return;
        targetIds = targetIds || [];
        console.log('[操作]', action.type);
        this.send({ type: Protocol.INBOUND.PLAYER_ACTION, action: action, target_ids: targetIds });
    }

    sendChat(msg) {
        if (!this.connected || !this.gameId) return;
        this.send({ type: Protocol.INBOUND.CHAT, message: msg });
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
GameClient.prototype.onPong = null;
GameClient.prototype.onServerInfo = null;

// 全局实例
const gameClient = new GameClient();

if (typeof module !== 'undefined' && module.exports) {
    module.exports = GameClient;
}
