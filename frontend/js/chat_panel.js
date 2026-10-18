// 席间面板：聊天 + 战报。纯 UI 模块，由 game_main.js 注入数据来源与发送函数。
// 设计成独立模块，便于后续扩展（私聊、@某人、AI 回复聊天等）而不动对局逻辑。
(function (global) {
    'use strict';
    const { esc } = SGS;

    const QUICK_PHRASES = [
        '快点吧，等得花儿都谢了',
        '主公，我是忠臣！',
        '别打我，我是好人',
        '这牌打得漂亮',
        '合作愉快',
        '你们是不是商量好的？',
        '稳住，我们能赢',
        '承让了'
    ];
    const MAX_ITEMS = 200;

    const ChatPanel = {
        opts: null,
        activeTab: 'chat',
        unread: { chat: false, log: false },

        // 初始化：opts.getPlayers / getMeId 提供玩家信息，opts.send 负责真正发送，opts.showBubble 在座位上冒气泡。
        init(opts) {
            this.opts = Object.assign({
                getPlayers: () => [],
                getMeId: () => null,
                send: () => false,
                showBubble: () => {},
                enabled: true
            }, opts || {});
            this.panel = document.getElementById('sidePanel');
            this.chatList = document.getElementById('chatList');
            this.logList = document.getElementById('log');
            this.toggleBtn = document.getElementById('chatToggle');

            document.getElementById('tabChat').addEventListener('click', () => this.showTab('chat'));
            document.getElementById('tabLog').addEventListener('click', () => this.showTab('log'));
            document.getElementById('sideClose').addEventListener('click', () => this.close());
            this.toggleBtn.addEventListener('click', () => this.isOpen() ? this.close() : this.open());
            document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && this.isOpen()) this.close(); });

            const quick = document.getElementById('quickPhrases');
            quick.innerHTML = QUICK_PHRASES.map(p => '<button type="button">' + esc(p) + '</button>').join('');
            quick.addEventListener('click', (e) => {
                const b = e.target.closest('button');
                if (b) this.submit(b.textContent);
            });
            const form = document.getElementById('chatForm');
            const input = document.getElementById('chatInput');
            form.addEventListener('submit', (e) => {
                e.preventDefault();
                if (this.submit(input.value)) input.value = '';
            });

            this.chatList.innerHTML = '<div class="chat-empty">' + (this.opts.enabled
                ? '席间还很安静。<br>AI 们会在对局中插话，你也可以先开口。'
                : '你在大厅关闭了席间聊天，AI 不会主动说话。<br>你仍然可以发言。') + '</div>';
        },

        // 发送一条聊天（截断到 200 字，与服务器上限一致）。没连上时提示并返回 false。
        submit(text) {
            const msg = String(text || '').trim().slice(0, 200);
            if (!msg) return false;
            const ok = this.opts.send(msg);
            if (!ok) SGS.toast('还没连上对局，稍后再说', { bad: true });
            return ok;
        },

        // 抽屉是否展开（只在窄屏有意义）。
        isOpen() { return this.panel.classList.contains('open'); },
        isDrawer() { return getComputedStyle(this.toggleBtn).display !== 'none'; },
        // 展开抽屉，可顺便切换到指定标签。
        open(tab) {
            if (tab) this.showTab(tab);
            this.panel.classList.add('open');
            this.toggleBtn.setAttribute('aria-expanded', 'true');
            this.markRead(this.activeTab);
        },
        close() {
            this.panel.classList.remove('open');
            this.toggleBtn.setAttribute('aria-expanded', 'false');
        },
        // 某个标签此刻是否真的被看见（宽屏常驻；窄屏需抽屉展开）。看不见时才标未读。
        visible(tab) {
            return this.activeTab === tab && (!this.isDrawer() || this.isOpen());
        },

        // 切换“席间 / 战报”标签。
        showTab(tab) {
            this.activeTab = tab;
            document.getElementById('tabChat').setAttribute('aria-selected', String(tab === 'chat'));
            document.getElementById('tabLog').setAttribute('aria-selected', String(tab === 'log'));
            document.getElementById('chatPane').hidden = tab !== 'chat';
            document.getElementById('logPane').hidden = tab !== 'log';
            this.markRead(tab);
            const list = tab === 'chat' ? this.chatList : this.logList;
            list.scrollTop = list.scrollHeight;
        },

        markRead(tab) {
            this.unread[tab] = false;
            document.getElementById(tab === 'chat' ? 'chatUnread' : 'logUnread').hidden = true;
            if (!this.unread.chat) document.getElementById('chatUnread').hidden = true;
        },
        markUnread(tab) {
            if (this.visible(tab)) return;
            this.unread[tab] = true;
            if (tab === 'log') document.getElementById('logUnread').hidden = false;
            if (tab === 'chat') document.getElementById('chatUnread').hidden = false;
        },

        // 根据 from_id / from 找到说话的玩家；服务器回显真人发言时 from 为真人名字（旧版服务器为“玩家”）。
        resolveSpeaker(data) {
            const players = this.opts.getPlayers() || [];
            const meId = this.opts.getMeId();
            let p = null;
            if (Number.isInteger(data.from_id)) p = players.find(x => x.id === data.from_id);
            if (!p && data.from) p = players.find(x => x.name === data.from);
            if (!p && (data.from === '玩家' || data.is_self)) p = players.find(x => x.id === meId);
            return p;
        },

        // 追加一条聊天：左侧头像 + 名字 + 气泡；自己的发言靠右。同时在座位上冒气泡。
        // data.kind：human 真人 / ai AI / spectator 观战 / system 系统。系统消息走灰色居中样式，
        // 真人（自己）靠右深漆底，AI 与观战为左侧宣纸气泡；缺 kind 的旧消息按 AI 处理。
        addMessage(data) {
            if (data.kind === 'system') { this.addSystem(data.message); return; }
            const p = this.resolveSpeaker(data);
            const meId = this.opts.getMeId();
            const isMe = !!p && p.id === meId;
            const name = p ? p.name : (data.from || '旁观者');
            const hero = p && p.hero ? p.hero : {};
            const empty = this.chatList.querySelector('.chat-empty');
            if (empty) empty.remove();
            const row = document.createElement('div');
            const kind = ['human', 'spectator'].includes(data.kind) ? data.kind : 'ai';
            // P5 provides the public 1-based seat on the player and chat event;
            // never derive it from the internal player id (which can be zero).
            const seat = p && Number.isInteger(p.seat) && p.seat > 0
                ? p.seat
                : (Number.isInteger(data.seat) && data.seat > 0 ? data.seat : null);
            const seatLabel = seat === null ? '' : seat + '号 ';
            row.className = 'msg kind-' + kind + (isMe ? ' me' : '');
            row.innerHTML = '<div class="avatar">' + SGS.heroImgHTML(hero.id, hero.name || name) + '</div>' +
                '<div><div class="who"><b>' + esc(seatLabel + name) + (kind === 'spectator' ? '（观战）' : '') + '</b>' + esc(p && p.hero_name ? p.hero_name : '') + '</div>' +
                '<div class="text">' + esc(data.message) + '</div></div>';
            this.append(this.chatList, row);
            if (p) this.opts.showBubble(p.id, data.message);
            if (!isMe) this.markUnread('chat');
        },

        // 聊天区里的一行系统提示（居中灰字）。
        addSystem(text) {
            const empty = this.chatList.querySelector('.chat-empty');
            if (empty) empty.remove();
            const row = document.createElement('div');
            row.className = 'msg system';
            row.textContent = text;
            this.append(this.chatList, row);
        },

        // 追加一行战报。cls：turn 回合分隔 / me 我的操作 / important 关键事件 / bad 错误 / think AI 思考。
        addLog(text, cls) {
            if (!text) return;
            const line = document.createElement('div');
            line.className = 'log-line' + (cls ? ' ' + cls : '');
            line.textContent = text;
            this.append(this.logList, line);
            if (cls === 'important' || cls === 'bad') this.markUnread('log');
        },

        // 追加到列表并限制最多 200 条；用户正在往上翻看时不强行滚到底。
        append(list, el) {
            const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 60;
            list.appendChild(el);
            while (list.children.length > MAX_ITEMS) list.removeChild(list.firstChild);
            if (nearBottom || list.children.length < 4) list.scrollTop = list.scrollHeight;
        }
    };

    global.ChatPanel = ChatPanel;
})(window);
