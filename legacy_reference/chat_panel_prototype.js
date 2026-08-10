// 聊天引擎 - 增强版（支持真实AI聊天）
class ChatController {
    constructor() {
        this.messages = [];
        this.isCollapsed = false;
        this.gameConfig = null;
        
        this.init();
    }

    init() {
        // 加载游戏配置
        this.gameConfig = JSON.parse(localStorage.getItem('gameConfig') || '{}');
        
        // 绑定聊天输入
        document.getElementById('sendChatBtn').addEventListener('click', () => {
            this.sendMessage();
        });

        document.getElementById('chatInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.sendMessage();
            }
        });

        // 绑定折叠按钮
        document.getElementById('toggleChat').addEventListener('click', () => {
            this.toggleChat();
        });

        // 注册WebSocket消息处理器
        wsClient.on('chat_message', (data) => {
            this.receiveMessage(data);
        });
        
        // 显示AI配置信息
        this.showAIConfigInfo();
    }

    showAIConfigInfo() {
        if (!this.gameConfig.chat || !this.gameConfig.chat.enabled) {
            this.addSystemMessage('⚠️ AI聊天功能未启用');
            return;
        }

        const aiCount = this.gameConfig.ais ? this.gameConfig.ais.length : 0;
        const configuredCount = this.gameConfig.ais ? 
            this.gameConfig.ais.filter(ai => ai.apiKey).length : 0;
        
        if (configuredCount === 0) {
            this.addSystemMessage('⚠️ 所有AI均未配置API Key，无法正常聊天');
        } else if (configuredCount < aiCount) {
            this.addSystemMessage(`✅ 已配置 ${configuredCount}/${aiCount} 个AI的API`);
        } else {
            this.addSystemMessage(`✅ 所有AI已配置完成，可以开始聊天`);
        }
    }

    sendMessage() {
        const input = document.getElementById('chatInput');
        const message = input.value.trim();

        if (!message) return;

        // 发送到服务器（服务器会调用AI API）
        wsClient.send({
            type: 'chat_message',
            message: message
        });

        // 清空输入框
        input.value = '';
    }

    receiveMessage(data) {
        this.messages.push(data);

        const chatMessages = document.getElementById('chatMessages');
        const msgDiv = document.createElement('div');
        msgDiv.className = 'chat-msg';

        const senderDiv = document.createElement('div');
        senderDiv.className = 'chat-msg-sender';
        
        if (data.player_id === gameRenderer.playerId) {
            senderDiv.classList.add('user');
        }
        
        senderDiv.textContent = data.sender_name || '未知';

        const textDiv = document.createElement('div');
        textDiv.className = 'chat-msg-text';
        textDiv.textContent = data.message;

        msgDiv.appendChild(senderDiv);
        msgDiv.appendChild(textDiv);
        chatMessages.appendChild(msgDiv);

        chatMessages.scrollTop = chatMessages.scrollHeight;

        while (chatMessages.children.length > 100) {
            chatMessages.removeChild(chatMessages.firstChild);
        }

        if (this.isCollapsed) {
            this.showNewMessageIndicator();
        }
    }

    toggleChat() {
        const chatArea = document.getElementById('chatArea');
        const toggleBtn = document.getElementById('toggleChat');

        this.isCollapsed = !this.isCollapsed;
        
        if (this.isCollapsed) {
            chatArea.classList.add('collapsed');
            toggleBtn.textContent = '+';
        } else {
            chatArea.classList.remove('collapsed');
            toggleBtn.textContent = '−';
            this.clearNewMessageIndicator();
        }
    }

    showNewMessageIndicator() {
        const toggleBtn = document.getElementById('toggleChat');
        toggleBtn.style.background = 'var(--danger)';
        toggleBtn.textContent = '💬';
    }

    clearNewMessageIndicator() {
        const toggleBtn = document.getElementById('toggleChat');
        toggleBtn.style.background = '';
        toggleBtn.textContent = '−';
    }

    addSystemMessage(message) {
        this.receiveMessage({
            sender_name: '系统',
            message: message,
            player_id: -1
        });
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new ChatController();
});
