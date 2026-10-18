// WebSocket客户端 - 完整重写
// 协议常量来自自动生成的 protocol.js（页面须先加载）；node 测试环境挂到 globalThis，
// 禁止再用 var Protocol —— 会与 protocol.js 的 const Protocol 在经典脚本全局词法环境冲突。
if (typeof module !== 'undefined' && module.exports) {
    globalThis.Protocol = require('./protocol.js');
}

class GameClient {
    constructor() {
        this.ws = null;
        this.gameId = null;
        this.connected = false;
        // 断线自动重连：页面在对局中时打开；对局结束或主动离开时关闭。
        this.autoReconnect = false;
        this.reconnectAttempts = 0;
        this.reconnectTimer = null;
        if (typeof window !== 'undefined' && window.addEventListener) {
            // 手机从后台切回、网络恢复时立即尝试，不必等退避计时。
            const kick = () => { if (this.autoReconnect && !this.connected) this.reconnectNow(); };
            window.addEventListener('online', kick);
            if (typeof document !== 'undefined') {
                document.addEventListener('visibilitychange', () => {
                    if (document.visibilityState === 'visible') kick();
                });
            }
        }
    }

    /** 立即重连（取消正在等待的退避计时）。 */
    reconnectNow() {
        if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null; }
        if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return;
        this.connect();
    }

    scheduleReconnect() {
        if (!this.autoReconnect || this.reconnectTimer) return;
        // 1s, 2s, 4s, 8s 之后固定每 10s 一次。
        const delay = Math.min(10000, 1000 * Math.pow(2, this.reconnectAttempts));
        this.reconnectAttempts += 1;
        if (this.onReconnecting) this.onReconnecting({ attempt: this.reconnectAttempts, delay: delay });
        this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            this.reconnectNow();
        }, delay);
    }

    connect() {
        const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const wsUrl = `${scheme}://${window.location.hostname || '127.0.0.1'}:8889`;
        console.log('[WS] 连接:', wsUrl);
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onopen = () => {
            this.connected = true;
            this.reconnectAttempts = 0;
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
        
        this.ws.onclose = (event) => {
            const wasConnected = this.connected;
            this.connected = false;
            console.log('[WS] 断开');
            if (this.onDisconnect) this.onDisconnect({ wasConnected: wasConnected, code: event && event.code });
            this.scheduleReconnect();
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
                if (this.onGameCreated) this.onGameCreated(data);
                break;

            case Protocol.OUTBOUND.GAME_RESUMED:
                this.gameId = data.game_id;
                if (this.onGameResumed) this.onGameResumed(data);
                break;

            case Protocol.OUTBOUND.RESUME_FAILED:
                if (this.onResumeFailed) this.onResumeFailed(data);
                break;

            case Protocol.OUTBOUND.GAME_STATE:
                if (this.onStateUpdate) this.onStateUpdate(data.state);
                break;

            case Protocol.OUTBOUND.YOUR_TURN:
                if (this.onYourTurn) this.onYourTurn(data);
                break;

            case Protocol.OUTBOUND.ACTION_RESULT:
                if (this.onActionResult) this.onActionResult(data);
                break;

            case Protocol.OUTBOUND.SELECTION_RESULT:
                if (this.onSelectionResult) this.onSelectionResult(data);
                break;

            case Protocol.OUTBOUND.CARD_MOVED:
                if (this.onCardMoved) this.onCardMoved(data.move);
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
            case Protocol.OUTBOUND.TRUSTEE_STATUS:
                if (this.onTrusteeStatus) this.onTrusteeStatus(data);
                break;
            case 'decision_trace':
                if (this.onDecisionTrace) this.onDecisionTrace(data);
                break;
            case Protocol.OUTBOUND.CHAT_REJECTED:
                if (this.onChatRejected) this.onChatRejected(data);
                break;
            case Protocol.OUTBOUND.COGNITIVE_NOTES:
                if (this.onCognitiveNotes) this.onCognitiveNotes(data);
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

    resumeGame(gameId, profileId) {
        if (!this.connected) return;
        this.send({ type: Protocol.INBOUND.RESUME_GAME, game_id: gameId, profile_id: profileId });
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

    /** 对局中修改设置（本批只有热闹程度）：服务器确认后随 game_state 回到界面。 */
    updateSettings(settings) {
        if (!this.connected || !this.gameId) return;
        this.send({ type: Protocol.INBOUND.UPDATE_SETTINGS, settings: settings });
    }

    setTrustee(enabled, source, playerId, config) {
        if (!this.connected || !this.gameId) return;
        this.send({ type: Protocol.INBOUND.SET_TRUSTEE, enabled: !!enabled,
            source: source || 'rules', player_id: playerId, config: config });
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
GameClient.prototype.onTrusteeStatus = null;
GameClient.prototype.onDecisionTrace = null;
GameClient.prototype.onCognitiveNotes = null;
GameClient.prototype.onEndGameAccepted = null;
GameClient.prototype.onPong = null;
GameClient.prototype.onServerInfo = null;
GameClient.prototype.onGameCreated = null;
GameClient.prototype.onGameResumed = null;
GameClient.prototype.onResumeFailed = null;
GameClient.prototype.onReconnecting = null;

// 全局实例
const gameClient = new GameClient();
if (typeof window !== 'undefined') {
    window.gameClient = gameClient;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = GameClient;
}

GameClient.prototype.onChatRejected = null;
