// =============================================================================
// 三国杀酒馆 · 前端公共工具（纯 UI，不含任何规则判断）
// -----------------------------------------------------------------------------
// 提供给所有页面：
//   - 牌面渲染 cardHTML()、牌名/花色/点数文本
//   - 勾玉（阴阳鱼）体力 hpHTML()、势力/身份印章
//   - 线描图标（<span class="ic" data-icon="gear"> 自动填充）
//   - 主题：夜墨 / 暖纸 / 跟随系统（对局页锁定夜墨）
//   - 详情浮窗：电脑悬停、手机长按卡牌或技能时显示说明
//   - 安全存储（隐私模式下不抛错）、提示条、fetchJSON
// 依赖：card_info.js（可选，提供卡牌说明与插画表；缺失时仍能渲染牌面）
// =============================================================================
(function (global) {
    'use strict';

    // ------------------------------------------------------------------ 常量表
    const SUIT = {
        spade: { sym: '♠', red: false, name: '黑桃' },
        heart: { sym: '♥', red: true, name: '红桃' },
        club: { sym: '♣', red: false, name: '梅花' },
        diamond: { sym: '♦', red: true, name: '方块' }
    };
    const RANK = { 1: 'A', 11: 'J', 12: 'Q', 13: 'K' };

    // 卡牌插画与说明来自 card_info.js；这里保留最小兜底，防止脚本加载顺序出错时整页白屏。
    const CARD_ART = global.SGS_CARD_ART || { '杀': 'sha', '闪': 'shan', '桃': 'tao' };
    const CARD_INFO = global.SGS_CARD_INFO || {};
    // 属性杀：牌名仍是“杀”，属性来自牌的 nature 字段（fire / thunder）。牌面写“火杀 / 雷杀”。
    const NATURE_INFO = global.SGS_NATURE_INFO || {
        fire: { name: '火杀', type: '基本', text: '' }, thunder: { name: '雷杀', type: '基本', text: '' }
    };
    const NATURE_SHORT = { fire: '火', thunder: '雷' };
    /** 只有【杀】带属性；返回 'fire' / 'thunder' / ''。 */
    function natureOf(card) {
        return card && card.name === '杀' && NATURE_INFO[card.nature] ? card.nature : '';
    }
    /** 日志用的带括号牌名：火【杀】、雷【杀】、【闪】。 */
    function bracketName(card) {
        const n = natureOf(card);
        return (n ? NATURE_SHORT[n] : '') + '【' + ((card && card.name) || '') + '】';
    }
    /** 牌面/日志用的显示名：火杀、雷杀，其余原样。 */
    function displayName(card) {
        const n = natureOf(card);
        return n ? NATURE_INFO[n].name : ((card && card.name) || '');
    }

    // 延时锦囊在判定区里显示的单字
    const DELAYED = { '乐不思蜀': '乐', '兵粮寸断': '兵', '闪电': '电' };
    const EQUIP_SLOT = {
        weapon: { short: '武', name: '武器' },
        armor: { short: '防', name: '防具' },
        plus_horse: { short: '+1', name: '防御马' },
        minus_horse: { short: '-1', name: '进攻马' }
    };
    const EQUIP_ORDER = ['weapon', 'armor', 'plus_horse', 'minus_horse'];

    const IDENTITY = {
        lord: { short: '主', name: '主公' },
        loyalist: { short: '忠', name: '忠臣' },
        rebel: { short: '反', name: '反贼' },
        spy: { short: '内', name: '内奸' }
    };
    const WINNER = { lord: '主公与忠臣', rebel: '反贼', spy: '内奸', draw: '平局', aborted: '对局终止' };
    const PHASE = { prepare: '准备阶段', judge: '判定阶段', draw: '摸牌阶段', play: '出牌阶段', discard: '弃牌阶段', end: '结束阶段', none: '' };
    // 阶段栏用的单字与顺序
    const PHASE_ORDER = ['prepare', 'judge', 'draw', 'play', 'discard', 'end'];
    const PHASE_SHORT = { prepare: '准', judge: '判', draw: '摸', play: '出', discard: '弃', end: '结' };

    const SKILL_TAG = { lord: '主公技', locked: '锁定技', limited: '限定技', awaken: '觉醒技', active: '主动技', trigger: '触发技' };

    // ------------------------------------------------------------------ 文本工具
    /** HTML 转义：所有来自服务器或用户输入的文字在拼接进 innerHTML 前都必须经过它。 */
    function esc(value) {
        return String(value == null ? '' : value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    }

    /** 点数显示：1→A，11→J，12→Q，13→K。 */
    function rankText(rank) {
        const n = Number(rank);
        return RANK[n] || (Number.isFinite(n) && n > 0 ? String(n) : '');
    }

    function suitInfo(suit) { return SUIT[suit] || { sym: '', red: false, name: '' }; }

    /** “♠7 杀”这样的一行文字，用于日志与无障碍标签。 */
    function cardLabel(card) {
        if (!card) return '';
        const s = suitInfo(card.suit);
        return s.sym + rankText(card.rank) + ' ' + displayName(card);
    }

    function cardArtURL(name) {
        const key = CARD_ART[name];
        return key ? 'assets/cards/' + key + '.png' : '';
    }

    // ------------------------------------------------------------------ 牌面
    /**
     * 渲染一张牌，返回 HTML 字符串。
     * opts:
     *   cls      追加的 class（selected / can / dim / picked …）
     *   asName   技能转化后的牌名（如“当杀”），会显示一条腰封
     *   back     画牌背（暗置的牌）
     *   attrs    追加到根元素上的原始属性字符串
     *   mini     小号牌
     *   noDetail 不挂详情浮窗的数据属性
     */
    function cardHTML(card, opts) {
        opts = opts || {};
        const cls = ['card'];
        if (opts.mini) cls.push('mini');
        if (opts.cls) cls.push(opts.cls);
        const attrs = opts.attrs || '';
        if (opts.back || !card) {
            cls.push('back');
            return '<div class="' + cls.join(' ') + '" ' + attrs + '></div>';
        }
        const name = card.name || '?';
        const nature = natureOf(card);
        const shown = nature ? NATURE_INFO[nature].name : name;
        if (nature) cls.push('nat-' + nature);
        const s = suitInfo(card.suit);
        const art = cardArtURL(name);
        let typeTag = '';
        if (nature) typeTag = '<span class="c-nature ' + nature + '">' + NATURE_SHORT[nature] + '</span>';
        else if (DELAYED[name]) typeTag = '<span class="c-type delay">延时</span>';
        else if (card.card_type === 'trick') typeTag = '<span class="c-type trick">锦囊</span>';
        else if (card.card_type === 'equipment') typeTag = '<span class="c-type equipment">装备</span>';
        const artHTML = art
            ? '<div class="c-art" style="background-image:url(' + art + ')"></div>'
            : '<div class="c-art text-art">' + esc(name.charAt(0)) + '</div>';
        const corner = s.sym
            ? '<div class="c-corner ' + (s.red ? 'red' : 'black') + '"><span>' + esc(rankText(card.rank)) + '</span><span class="suit">' + s.sym + '</span></div>'
            : '';
        const asTag = opts.asName && opts.asName !== name ? '<div class="c-as">当' + esc(opts.asName) + '</div>' : '';
        const detail = opts.noDetail ? '' : cardDetailAttrs(card);
        return '<div class="' + cls.join(' ') + '" ' + attrs + ' ' + detail + ' aria-label="' + esc(cardLabel(card)) + '">' +
            artHTML + corner + typeTag + asTag +
            '<div class="c-name' + (shown.length > 3 ? ' long' : '') + '">' + esc(shown) + '</div></div>';
    }

    /** 详情浮窗需要的数据属性（牌名、花色、点数）。 */
    function cardDetailAttrs(card) {
        if (!card || !card.name) return '';
        return 'data-card-name="' + esc(card.name) + '"' +
            (natureOf(card) ? ' data-card-nature="' + natureOf(card) + '"' : '') +
            (card.suit ? ' data-card-suit="' + esc(card.suit) + '"' : '') +
            (card.rank ? ' data-card-rank="' + esc(card.rank) + '"' : '');
    }

    // ------------------------------------------------------------------ 勾玉（阴阳鱼）
    // 太极图的一半：起点在顶部，沿右侧大弧到底部，再用两段小弧做出“鱼头”和“鱼尾”。
    const GOUYU_FISH = 'M6 .4A5.6 5.6 0 0 1 6 11.6A2.8 2.8 0 0 1 6 6A2.8 2.8 0 0 0 6 .4Z';
    const GOUYU_EYE = '<circle class="eye" cx="6" cy="8.8" r="1"/>';

    /** 往页面里注入一次勾玉渐变定义（绿 / 黄 / 红）。 */
    function ensureGouyuDefs() {
        if (document.getElementById('sgsGouyuDefs')) return;
        const holder = document.createElement('div');
        holder.innerHTML = '<svg id="sgsGouyuDefs" width="0" height="0" style="position:absolute" aria-hidden="true"><defs>' +
            '<radialGradient id="gy-green" cx="35%" cy="70%" r="75%"><stop offset="0" stop-color="#d6ffc8"/><stop offset=".45" stop-color="#57c05a"/><stop offset="1" stop-color="#1d5a1f"/></radialGradient>' +
            '<radialGradient id="gy-yellow" cx="35%" cy="70%" r="75%"><stop offset="0" stop-color="#fff6c4"/><stop offset=".45" stop-color="#e4c24a"/><stop offset="1" stop-color="#7a5c10"/></radialGradient>' +
            '<radialGradient id="gy-red" cx="35%" cy="70%" r="75%"><stop offset="0" stop-color="#ffd0c4"/><stop offset=".45" stop-color="#d8422f"/><stop offset="1" stop-color="#6a130a"/></radialGradient>' +
            '</defs></svg>';
        document.body.appendChild(holder.firstChild);
    }

    /** 体力比例对应的颜色：> 2/3 绿，> 1/3 黄，其余（含只剩 1 点）红。 */
    function hpColor(hp, max) {
        if (max <= 0) return 'r';
        const ratio = hp / max;
        if (hp <= 1 || ratio <= 1 / 3) return 'r';
        if (ratio <= 2 / 3) return 'y';
        return 'g';
    }

    /**
     * 体力条 HTML。体力上限超过 opts.limit（默认 5）时改为“1 颗勾玉 + 数字”，避免一长串。
     * opts.vertical 为 true 时竖排（武将框右侧用）。
     */
    function hpHTML(hp, max, opts) {
        opts = opts || {};
        hp = Math.max(0, Number(hp) || 0);
        max = Math.max(0, Number(max) || 0);
        const col = hpColor(hp, max);
        const one = (c) => '<svg class="gouyu ' + c + '" viewBox="0 0 12 12" aria-hidden="true"><path class="fish" d="' + GOUYU_FISH + '"/>' + GOUYU_EYE + '</svg>';
        const label = '体力 ' + hp + '/' + max;
        const cls = 'hp' + (opts.vertical ? ' vertical' : '');
        if (max > (opts.limit || 5)) {
            return '<span class="' + cls + '" role="img" aria-label="' + label + '">' + one(col) + '<span class="hp-num">' + hp + '/' + max + '</span></span>';
        }
        let html = '';
        for (let i = 0; i < max; i++) html += one(i < hp ? col : 'lost');
        return '<span class="' + cls + '" role="img" aria-label="' + label + '">' + html + '</span>';
    }

    // ------------------------------------------------------------------ 印章与立绘
    function identitySeal(identity, extraCls) {
        const info = IDENTITY[identity];
        const cls = 'seal ' + (info ? 'id-' + identity : 'id-unknown') + (extraCls ? ' ' + extraCls : '');
        return '<span class="' + cls + '" title="' + (info ? info.name : '身份未知') + '">' + (info ? info.short : '?') + '</span>';
    }
    function factionSeal(faction, extraCls) {
        const f = faction || '群';
        return '<span class="seal faction faction-' + esc(f) + (extraCls ? ' ' + extraCls : '') + '" title="' + esc(f) + '势力">' + esc(f) + '</span>';
    }
    function heroImageURL(heroId) { return heroId ? 'assets/heroes/' + encodeURIComponent(heroId) + '.jpg' : ''; }
    /** 武将立绘；图片缺失时用书法首字兜底（见 imgFallback）。 */
    function heroImgHTML(heroId, name, cls) {
        const fallback = esc(String(name || '?').replace(/^界/, '').charAt(0) || '?');
        if (!heroId) return '<div class="hero-fallback ' + esc(cls || '') + '">' + fallback + '</div>';
        return '<img class="' + esc(cls || '') + '" src="' + heroImageURL(heroId) + '" alt="' + esc(name || '') +
            '" data-fallback="' + fallback + '" loading="lazy" onerror="SGS.imgFallback(this)">';
    }
    function imgFallback(img) {
        const div = document.createElement('div');
        div.className = 'hero-fallback ' + (img.className || '');
        div.textContent = img.dataset.fallback || '?';
        img.replaceWith(div);
    }

    // ------------------------------------------------------------------ 线描图标
    // 24×24 视框，统一 1.6 线宽，颜色跟随文字（currentColor）。
    const ICONS = {
        gear: '<circle cx="12" cy="12" r="3.2"/><path d="M12 2.8l1.4 2.6 2.9-.8.7 2.9 2.9.8-.8 2.9 2.6 1.4-2.6 1.4.8 2.9-2.9.8-.7 2.9-2.9-.8L12 21.2l-1.4-2.6-2.9.8-.7-2.9-2.9-.8.8-2.9L2.8 12l2.6-1.4-.8-2.9 2.9-.8.7-2.9 2.9.8z"/>',
        exit: '<path d="M14 4h4.5a1.5 1.5 0 0 1 1.5 1.5v13a1.5 1.5 0 0 1-1.5 1.5H14"/><path d="M10 8l-4 4 4 4"/><path d="M6 12h10"/>',
        chat: '<path d="M4.5 5.5h15a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H11l-4.5 3.5V16.5h-2a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1z"/><path d="M8 10.2h8M8 13h5"/>',
        close: '<path d="M6 6l12 12M18 6L6 18"/>',
        back: '<path d="M15 5l-7 7 7 7"/>',
        sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6"/>',
        moon: '<path d="M19.5 14.5A8 8 0 1 1 9.5 4.5a6.5 6.5 0 0 0 10 10z"/>',
        book: '<path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H11v15H5.5A1.5 1.5 0 0 0 4 20.5z"/><path d="M20 5.5A1.5 1.5 0 0 0 18.5 4H13v15h5.5a1.5 1.5 0 0 1 1.5 1.5z"/>',
        scroll: '<path d="M7 4h11a2 2 0 0 1 0 4h-1v10a2 2 0 0 1-2 2H6a2 2 0 0 1 0-4h1z"/><path d="M10 9h4M10 12.5h4"/>'
    };
    function icon(name) {
        return '<span class="ic" aria-hidden="true"><svg viewBox="0 0 24 24">' + (ICONS[name] || '') + '</svg></span>';
    }
    /** 把页面里所有 <span class="ic" data-icon="xxx"></span> 填上 SVG。 */
    function hydrateIcons(root) {
        (root || document).querySelectorAll('.ic[data-icon]').forEach(el => {
            if (el.firstChild) return;
            el.innerHTML = '<svg viewBox="0 0 24 24">' + (ICONS[el.dataset.icon] || '') + '</svg>';
            el.setAttribute('aria-hidden', 'true');
        });
    }

    // ------------------------------------------------------------------ 主题
    /** 读取设置里的主题：dark（夜墨）/ light（暖纸）/ system（跟随系统）。 */
    function themeSetting() {
        try { return (JSON.parse(localStorage.getItem('globalSettings') || '{}').theme) || 'dark'; } catch (_) { return 'dark'; }
    }
    function resolveTheme(setting) {
        if (setting === 'system') return window.matchMedia && matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
        return setting === 'light' ? 'light' : 'dark';
    }
    /** 应用主题；对局页（<html data-theme-lock>）始终保持夜墨。 */
    function applyTheme(setting) {
        const root = document.documentElement;
        if (root.hasAttribute('data-theme-lock')) { root.dataset.theme = 'dark'; return; }
        const theme = resolveTheme(setting || themeSetting());
        root.dataset.theme = theme;
        const meta = document.querySelector('meta[name="theme-color"]');
        if (meta) meta.content = theme === 'light' ? '#ebe1c8' : '#17110c';
        document.querySelectorAll('[data-theme-toggle]').forEach(btn => {
            btn.innerHTML = icon(theme === 'light' ? 'moon' : 'sun');
            btn.setAttribute('aria-label', theme === 'light' ? '切换到夜墨主题' : '切换到暖纸主题');
            btn.title = btn.getAttribute('aria-label');
        });
    }
    /** 主题按钮：在夜墨与暖纸之间切换，并写回全局设置。 */
    function toggleTheme() {
        const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
        try {
            const s = JSON.parse(localStorage.getItem('globalSettings') || '{}');
            s.theme = next;
            localStorage.setItem('globalSettings', JSON.stringify(s));
        } catch (_) {}
        applyTheme(next);
    }

    // ------------------------------------------------------------------ 详情浮窗
    // 电脑：鼠标停留 350ms 显示，移开消失。
    // 手机：手指按住 450ms 显示（并吞掉松手时的那次点击，避免误出牌），松手 1.6 秒后消失。
    const Detail = {
        el: null,
        timer: null,
        hideTimer: null,
        swallowClick: false,
        current: null,

        init() {
            const fine = window.matchMedia && matchMedia('(hover: hover) and (pointer: fine)').matches;
            if (fine) {
                document.addEventListener('mouseover', (e) => {
                    const t = e.target.closest('[data-card-name],[data-skill-name]');
                    if (t === this.current) return;
                    this.hide();
                    if (!t) return;
                    this.current = t;
                    this.timer = setTimeout(() => this.show(t), 350);
                });
                document.addEventListener('mousedown', () => this.hide(), true);
            }
            document.addEventListener('pointerdown', (e) => {
                if (e.pointerType === 'mouse') return;
                const t = e.target.closest('[data-card-name],[data-skill-name]');
                this.hide();
                if (!t) return;
                const x0 = e.clientX, y0 = e.clientY;
                const cancel = () => { clearTimeout(this.timer); document.removeEventListener('pointermove', move); };
                const move = (ev) => { if (Math.abs(ev.clientX - x0) > 10 || Math.abs(ev.clientY - y0) > 10) cancel(); };
                document.addEventListener('pointermove', move);
                document.addEventListener('pointerup', () => {
                    cancel();
                    if (this.el) this.hideTimer = setTimeout(() => this.hide(), 1600);
                }, { once: true });
                this.timer = setTimeout(() => { this.swallowClick = true; this.show(t); if (navigator.vibrate) navigator.vibrate(12); }, 450);
            }, { passive: true });
            // 长按之后松手产生的 click 不应触发出牌/选择
            document.addEventListener('click', (e) => {
                if (!this.swallowClick) return;
                this.swallowClick = false;
                e.stopPropagation();
                e.preventDefault();
            }, true);
            document.addEventListener('contextmenu', (e) => {
                if (e.target.closest('[data-card-name],[data-skill-name]')) e.preventDefault();
            });
            window.addEventListener('scroll', () => this.hide(), true);
        },

        hide() {
            clearTimeout(this.timer);
            clearTimeout(this.hideTimer);
            this.current = null;
            if (this.el) { this.el.remove(); this.el = null; }
        },

        /** 在元素旁边显示详情；优先放在上方，空间不够放下方，并夹在视口内。 */
        show(target) {
            const html = this.content(target);
            if (!html) return;
            if (this.el) this.el.remove();
            const pop = document.createElement('div');
            pop.className = 'detail-pop';
            pop.setAttribute('role', 'tooltip');
            pop.innerHTML = html;
            document.body.appendChild(pop);
            this.el = pop;
            const r = target.getBoundingClientRect();
            const pr = pop.getBoundingClientRect();
            let top = r.top - pr.height - 8;
            if (top < 8) top = Math.min(window.innerHeight - pr.height - 8, r.bottom + 8);
            let left = r.left + r.width / 2 - pr.width / 2;
            left = Math.max(8, Math.min(window.innerWidth - pr.width - 8, left));
            pop.style.top = Math.max(8, top) + 'px';
            pop.style.left = left + 'px';
        },

        content(t) {
            if (t.dataset.cardName) return cardDetailHTML(t.dataset.cardName, t.dataset.cardSuit, t.dataset.cardRank, t.dataset.cardNature);
            if (t.dataset.skillName) return skillDetailHTML(t.dataset.skillName, t.dataset.skillDesc, t.dataset.skillType);
            return '';
        }
    };

    /** 卡牌详情：小牌面 + 名称 + 类型/射程 + 效果；引擎未实现的特效如实注明。 */
    function cardDetailHTML(name, suit, rank, nature) {
        const nat = natureOf({ name: name, nature: nature });
        // 火杀 / 雷杀：标题与说明用属性杀自己的条目，没有时退回普通【杀】
        const info = (nat && NATURE_INFO[nat].text) ? NATURE_INFO[nat] : (CARD_INFO[name] || {});
        const title = nat ? NATURE_INFO[nat].name : name;
        const s = suitInfo(suit);
        const face = cardHTML({ name: name, nature: nat, suit: suit, rank: rank, card_type: info.type === '基本' ? 'basic' : (/武器|防具|坐骑|宝物/.test(info.type || '') ? 'equipment' : 'trick') }, { noDetail: true });
        const tags = [info.type ? '<span class="dp-tag">' + esc(info.type) + '</span>' : ''];
        if (info.range) tags.push('<span class="dp-tag">攻击范围 ' + info.range + '</span>');
        if (info.horse) tags.push('<span class="dp-tag">距离 ' + esc(info.horse) + '</span>');
        const meta = s.sym ? s.name + ' ' + rankText(rank) : '';
        return '<div class="dp-head">' + face + '<div><h4>' + esc(title) + '</h4><div>' + tags.join('') + '</div>' +
            (meta ? '<div class="dp-meta">' + esc(meta) + '</div>' : '') + '</div></div>' +
            '<div>' + esc(info.text || '暂无说明。') + '</div>' +
            (info.pending ? '<div class="dp-note">本项目引擎暂未实现这件装备的特效' + (info.range ? '，目前只生效攻击范围' : '') + '。</div>' : '');
    }

    function skillDetailHTML(name, desc, type) {
        const tag = SKILL_TAG[type] ? '<span class="dp-tag">' + SKILL_TAG[type] + '</span>' : '';
        return '<div class="dp-head"><div><h4>【' + esc(name) + '】</h4>' + tag + '</div></div><div>' + esc(desc || '暂无技能说明。') + '</div>';
    }

    // ------------------------------------------------------------------ 存储
    // 隐私窗口或禁用存储时 localStorage 会抛错，这里统一吞掉并返回默认值。
    function read(storage, key, fallback) {
        try {
            const raw = storage.getItem(key);
            return raw == null ? fallback : JSON.parse(raw);
        } catch (_) { return fallback; }
    }
    function write(storage, key, value) {
        try { storage.setItem(key, JSON.stringify(value)); return true; } catch (_) { return false; }
    }
    const store = {
        get: (k, f) => read(localStorage, k, f),
        set: (k, v) => write(localStorage, k, v),
        remove: (k) => { try { localStorage.removeItem(k); } catch (_) {} },
        sget: (k, f) => read(sessionStorage, k, f),   // 本标签页内有效（放带 API Key 的开局配置）
        sset: (k, v) => write(sessionStorage, k, v),
        sremove: (k) => { try { sessionStorage.removeItem(k); } catch (_) {} }
    };

    // ------------------------------------------------------------------ 提示条
    /** 屏幕上方的横幅提示；opts.bad 为错误色，opts.ms 为停留时间。最多同时 4 条。 */
    function toast(text, opts) {
        if (!text) return;
        opts = opts || {};
        let stack = document.getElementById('toastStack');
        if (!stack) {
            stack = document.createElement('div');
            stack.id = 'toastStack';
            stack.className = 'toast-stack';
            stack.setAttribute('role', 'status');
            stack.setAttribute('aria-live', 'polite');
            document.body.appendChild(stack);
        }
        const el = document.createElement('div');
        el.className = 'toast' + (opts.bad ? ' bad' : '');
        el.textContent = text;
        stack.appendChild(el);
        while (stack.children.length > 4) stack.removeChild(stack.firstChild);
        setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 260); }, opts.ms || 1800);
    }

    /** 不缓存的 JSON 请求；HTTP 错误会抛出，便于调用方显示“请确认服务器已启动”。 */
    async function fetchJSON(url, init) {
        const r = await fetch(url, Object.assign({ cache: 'no-store' }, init || {}));
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
    }


    /**
     * 给“模型名称”输入框加一个【拉取】按钮：向服务器请求该服务商的模型列表，
     * 结果显示在输入框下方，点选即可填入；仍可手动输入任意模型名。
     * getParams() 返回 {provider, api_url, api_key, ...}，调用时才读取，保证用的是表单当前值。
     */
    function attachModelPicker(input, getParams) {
        if (!input || input.dataset.modelPicker) return;
        input.dataset.modelPicker = '1';
        const wrap = document.createElement('span');
        wrap.className = 'model-pick';
        input.parentNode.insertBefore(wrap, input);
        wrap.appendChild(input);
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn small model-pick-btn';
        btn.textContent = '拉取';
        btn.title = '从服务商拉取可用模型列表';
        wrap.appendChild(btn);
        const list = document.createElement('div');
        list.className = 'model-list';
        list.hidden = true;
        list.setAttribute('role', 'listbox');
        wrap.appendChild(list);
        let models = [];
        let filterOn = false;

        function render() {
            const q = filterOn ? input.value.trim().toLowerCase() : '';
            const shown = q ? models.filter(m => m.toLowerCase().includes(q)) : models;
            if (!shown.length) { list.hidden = true; return; }
            list.innerHTML = shown.slice(0, 300).map(m =>
                '<button type="button" role="option" class="model-opt' + (m === input.value.trim() ? ' on' : '') +
                '" data-model="' + esc(m) + '">' + esc(m) + '</button>').join('');
            list.hidden = false;
        }
        function hide() { list.hidden = true; }

        btn.addEventListener('click', async (e) => {
            e.preventDefault();
            btn.disabled = true;
            btn.textContent = '拉取中…';
            try {
                const data = await fetchJSON('/api/models', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(getParams() || {})
                });
                if (!data.success) { toast(data.message || '拉取失败，请手动填写', { bad: true, ms: 3200 }); hide(); return; }
                models = data.models || [];
                filterOn = false;
                render();
                toast('拉取到 ' + models.length + ' 个模型，点选即可');
            } catch (err) {
                toast('连不上游戏服务，无法拉取模型', { bad: true });
            } finally {
                btn.disabled = false;
                btn.textContent = '拉取';
            }
        });
        list.addEventListener('click', (e) => {
            const opt = e.target.closest('[data-model]');
            if (!opt) return;
            e.preventDefault();
            input.value = opt.dataset.model;
            input.dispatchEvent(new Event('change', { bubbles: true }));
            hide();
        });
        input.addEventListener('input', () => { if (models.length) { filterOn = true; render(); } });
        input.addEventListener('focus', () => { if (models.length) { filterOn = false; render(); } });
        input.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !list.hidden) { e.stopPropagation(); e.preventDefault(); hide(); } });
        document.addEventListener('pointerdown', (e) => { if (!wrap.contains(e.target)) hide(); });
        input.addEventListener('picker-reset', () => { models = []; hide(); });
        // 换了服务商/地址/Key，旧列表就不再可信。
        return { reset() { models = []; hide(); } };
    }

    /**
     * 身份卡牌面：暗红漆底 + 暗金双线描边、四角卷草纹、中央圆形纹章。
     * opts.identity：选中的身份（lord/loyalist/rebel/spy），没有则显示“令”；opts.count：右下角张数。
     */
    let idCardSeq = 0;
    function identityCardHTML(opts) {
        opts = opts || {};
        const n = ++idCardSeq;
        const g = 'idcGold' + n, c = 'idcCorner' + n, cl = 'idcCloud' + n;
        const info = IDENTITY[opts.identity];
        const corner = '<g id="' + c + '" fill="none" stroke="url(#' + g + ')" stroke-linecap="round">' +
            '<path stroke-width="1.1" d="M8 34 C8 20 13 12 27 9"/>' +
            '<path stroke-width=".9" d="M8 22 C11 22 14 19 14 14 C14 10 16 8 21 8"/>' +
            '<path stroke-width=".8" d="M15 18 c3 -1 6 1 5 4 c-1 2 -4 2 -4 -.5"/>' +
            '<path stroke-width=".8" d="M19 14 q5 -1 8 -6"/><path stroke-width=".7" d="M24 15 q4 0 7 -3"/>' +
            '<path stroke-width=".8" fill="url(#' + g + ')" fill-opacity=".35" d="M22 12 q5 -2 7 -6 q-6 1 -7 6 z"/>' +
            '<circle cx="11" cy="11" r="1.6" fill="url(#' + g + ')" stroke="none"/></g>';
        const svg = '<svg class="idc-frame" viewBox="0 0 100 140" aria-hidden="true" focusable="false"><defs>' +
            '<linearGradient id="' + g + '" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#f0d48c"/>' +
            '<stop offset=".35" stop-color="#b58a3e"/><stop offset=".6" stop-color="#6b4c22"/><stop offset="1" stop-color="#d2ad62"/></linearGradient>' +
            '<pattern id="' + cl + '" width="24" height="16" patternUnits="userSpaceOnUse">' +
            '<path d="M2 12 q4 -7 9 -2 q3 -5 7 0 q3 -2 5 1" fill="none" stroke="#d9b35e" stroke-opacity=".10" stroke-width=".8"/></pattern>' +
            corner + '</defs>' +
            '<rect x="6" y="6" width="88" height="128" rx="3" fill="url(#' + cl + ')"/>' +
            '<rect x="2.5" y="2.5" width="95" height="135" rx="7" fill="none" stroke="url(#' + g + ')" stroke-width="1.8"/>' +
            '<rect x="6.5" y="6.5" width="87" height="127" rx="3.5" fill="none" stroke="url(#' + g + ')" stroke-width=".6" stroke-opacity=".8"/>' +
            // 内圈一串金珠：0 长度虚线 + 圆头 = 等距小圆点
            '<rect x="9.5" y="9.5" width="81" height="121" rx="2" fill="none" stroke="url(#' + g + ')" stroke-width="1.1" stroke-linecap="round" stroke-dasharray="0 3.2" stroke-opacity=".75"/>' +
            '<use href="#' + c + '" transform="scale(1.22)"/><use href="#' + c + '" transform="translate(100 0) scale(-1.22 1.22)"/>' +
            '<use href="#' + c + '" transform="translate(0 140) scale(1.22 -1.22)"/><use href="#' + c + '" transform="translate(100 140) scale(-1.22 -1.22)"/>' +
            '<path d="M50 3.2 l2.6 3.3 l-2.6 3.3 l-2.6 -3.3 z M50 130.2 l2.6 3.3 l-2.6 3.3 l-2.6 -3.3 z M3.2 70 l3.3 -2.6 l3.3 2.6 l-3.3 2.6 z M90.2 70 l3.3 -2.6 l3.3 2.6 l-3.3 2.6 z" fill="url(#' + g + ')"/>' +
            '<circle cx="50" cy="62" r="25" fill="rgba(0,0,0,.28)" stroke="url(#' + g + ')" stroke-width="1.2"/>' +
            '<circle cx="50" cy="62" r="21" fill="none" stroke="url(#' + g + ')" stroke-width=".5" stroke-dasharray="1.6 1.8"/>' +
            '<path d="M24 62 h-8 M76 62 h8 M50 36 v-6 M50 88 v6" stroke="url(#' + g + ')" stroke-width=".7"/>' +
            '<path d="M26 108 h48 l-4 5 l4 5 h-48 l4 -5 z" fill="rgba(0,0,0,.35)" stroke="url(#' + g + ')" stroke-width=".7"/>' +
            '</svg>';
        return '<div class="id-card' + (info ? ' chosen id-' + opts.identity : '') + '" role="img" aria-label="身份卡' + (info ? '：' + info.name : '') + '">' +
            svg + '<span class="idc-face">' + (info ? info.short : '令') + '</span>' +
            '<span class="idc-label">' + (info ? info.name : '身份卡') + '</span>' +
            (Number.isFinite(opts.count) ? '<span class="idc-count">×' + opts.count + '</span>' : '') +
            '<span class="idc-sheen" aria-hidden="true"></span></div>';
    }

    // ------------------------------------------------------------------ 导出与初始化
    const SGS = {
        SUIT, CARD_ART, CARD_INFO, DELAYED, EQUIP_SLOT, EQUIP_ORDER, IDENTITY, WINNER, PHASE, PHASE_ORDER, PHASE_SHORT, SKILL_TAG,
        esc, rankText, suitInfo, cardLabel, cardArtURL, cardHTML, cardDetailAttrs, hpHTML, hpColor, ensureGouyuDefs,
        identitySeal, factionSeal, heroImageURL, heroImgHTML, imgFallback, icon, hydrateIcons,
        applyTheme, toggleTheme, Detail, cardDetailHTML, natureOf, displayName, bracketName, NATURE_INFO, skillDetailHTML, store, toast, fetchJSON, attachModelPicker, identityCardHTML
    };
    global.SGS = SGS;

    if (typeof document !== 'undefined') {
        // 主题越早应用越好（本脚本放在 <head> 时可避免闪一下夜墨）
        applyTheme();
        if (window.matchMedia) {
            const mq = matchMedia('(prefers-color-scheme: light)');
            const onChange = () => { if (themeSetting() === 'system') applyTheme('system'); };
            if (mq.addEventListener) mq.addEventListener('change', onChange);
        }
        window.addEventListener('global-settings-changed', (e) => applyTheme(e.detail && e.detail.theme));
        const ready = () => {
            ensureGouyuDefs();
            hydrateIcons();
            applyTheme();
            Detail.init();
            document.querySelectorAll('[data-theme-toggle]').forEach(b => b.addEventListener('click', toggleTheme));
        };
        if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready);
        else ready();
    }
})(typeof window !== 'undefined' ? window : globalThis);
