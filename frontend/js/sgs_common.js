// 三国杀酒馆 · 前端公共工具（纯 UI，不含任何规则判断）
// 牌面、勾玉、身份/势力印章、安全存储、提示条。所有页面共用。
(function (global) {
    'use strict';

    const SUIT = {
        spade: { sym: '♠', red: false, name: '黑桃' },
        heart: { sym: '♥', red: true, name: '红桃' },
        club: { sym: '♣', red: false, name: '梅花' },
        diamond: { sym: '♦', red: true, name: '方块' }
    };
    const RANK = { 1: 'A', 11: 'J', 12: 'Q', 13: 'K' };

    // 有插画资源的牌（frontend/assets/cards/*.png）
    const CARD_ART = {
        '杀': 'sha', '闪': 'shan', '桃': 'tao', '酒': 'jiu',
        '过河拆桥': 'guohe', '顺手牵羊': 'shunshou', '决斗': 'juedou', '铁索连环': 'tiesuo',
        '南蛮入侵': 'nanman', '五谷丰登': 'wugu', '借刀杀人': 'jiedao', '无懈可击': 'wuxie',
        '桃园结义': 'taoyuan', '万箭齐发': 'wanjian', '兵粮寸断': 'bingliang', '火攻': 'huogong'
    };
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

    function esc(value) {
        return String(value == null ? '' : value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    }

    function rankText(rank) {
        const n = Number(rank);
        return RANK[n] || (Number.isFinite(n) && n > 0 ? String(n) : '');
    }

    function suitInfo(suit) { return SUIT[suit] || { sym: '', red: false, name: '' }; }

    function cardLabel(card) {
        if (!card) return '';
        const s = suitInfo(card.suit);
        return s.sym + rankText(card.rank) + ' ' + (card.name || '');
    }

    /**
     * 渲染一张牌。opts: { cls, asName, back, attrs, mini }
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
        const s = suitInfo(card.suit);
        const art = CARD_ART[name];
        let typeTag = '';
        if (DELAYED[name]) typeTag = '<span class="c-type delay">延时</span>';
        else if (card.card_type === 'trick') typeTag = '<span class="c-type trick">锦囊</span>';
        else if (card.card_type === 'equipment') typeTag = '<span class="c-type equipment">装备</span>';
        const artHTML = art
            ? '<div class="c-art" style="background-image:url(assets/cards/' + art + '.png)"></div>'
            : '<div class="c-art text-art">' + esc(name.charAt(0)) + '</div>';
        const corner = s.sym
            ? '<div class="c-corner ' + (s.red ? 'red' : 'black') + '"><span>' + esc(rankText(card.rank)) + '</span><span class="suit">' + s.sym + '</span></div>'
            : '';
        const asTag = opts.asName && opts.asName !== name ? '<div class="c-as">当' + esc(opts.asName) + '</div>' : '';
        return '<div class="' + cls.join(' ') + '" ' + attrs + ' title="' + esc(cardLabel(card)) + '">' +
            artHTML + corner + typeTag + asTag +
            '<div class="c-name' + (name.length > 3 ? ' long' : '') + '">' + esc(name) + '</div></div>';
    }

    // ---------- 勾玉 ----------
    const GOUYU_PATH = 'M5.6 .6a4.2 4.2 0 1 1-4.2 6.3c.6 2.8 2.3 4.7 4.6 6.5C2.2 12.6.4 9.7.4 5.6A5 5 0 0 1 5.6.6z';
    function ensureGouyuDefs() {
        if (document.getElementById('sgsGouyuDefs')) return;
        const holder = document.createElement('div');
        holder.innerHTML = '<svg id="sgsGouyuDefs" width="0" height="0" style="position:absolute" aria-hidden="true"><defs>' +
            '<radialGradient id="gy-green" cx="40%" cy="30%" r="80%"><stop offset="0" stop-color="#d6ffc8"/><stop offset=".45" stop-color="#57c05a"/><stop offset="1" stop-color="#1d5a1f"/></radialGradient>' +
            '<radialGradient id="gy-yellow" cx="40%" cy="30%" r="80%"><stop offset="0" stop-color="#fff6c4"/><stop offset=".45" stop-color="#e4c24a"/><stop offset="1" stop-color="#7a5c10"/></radialGradient>' +
            '<radialGradient id="gy-red" cx="40%" cy="30%" r="80%"><stop offset="0" stop-color="#ffd0c4"/><stop offset=".45" stop-color="#d8422f"/><stop offset="1" stop-color="#6a130a"/></radialGradient>' +
            '</defs></svg>';
        document.body.appendChild(holder.firstChild);
    }
    function hpColor(hp, max) {
        if (max <= 0) return 'r';
        const ratio = hp / max;
        if (hp <= 1 || ratio <= 1 / 3) return 'r';
        if (ratio <= 2 / 3) return 'y';
        return 'g';
    }
    function hpHTML(hp, max, opts) {
        opts = opts || {};
        hp = Math.max(0, Number(hp) || 0);
        max = Math.max(0, Number(max) || 0);
        const col = hpColor(hp, max);
        const one = (c) => '<svg class="gouyu ' + c + '" viewBox="0 0 11 14" aria-hidden="true"><path d="' + GOUYU_PATH + '"/></svg>';
        const label = '体力 ' + hp + '/' + max;
        if (max > (opts.limit || 5)) {
            return '<span class="hp' + (opts.vertical ? ' vertical' : '') + '" role="img" aria-label="' + label + '">' + one(col) + '<span class="hp-num">' + hp + '/' + max + '</span></span>';
        }
        let html = '';
        for (let i = 0; i < max; i++) html += one(i < hp ? col : 'lost');
        return '<span class="hp' + (opts.vertical ? ' vertical' : '') + '" role="img" aria-label="' + label + '">' + html + '</span>';
    }

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
    function heroImgHTML(heroId, name, cls) {
        const fallback = esc(String(name || '?').replace(/^界/, '').charAt(0) || '?');
        if (!heroId) return '<div class="hero-fallback ' + (cls || '') + '">' + fallback + '</div>';
        return '<img class="' + esc(cls || '') + '" src="' + heroImageURL(heroId) + '" alt="' + esc(name || '') +
            '" data-fallback="' + fallback + '" loading="lazy" onerror="SGS.imgFallback(this)">';
    }
    function imgFallback(img) {
        const div = document.createElement('div');
        div.className = 'hero-fallback ' + (img.className || '');
        div.textContent = img.dataset.fallback || '?';
        img.replaceWith(div);
    }

    // ---------- 存储（隐私窗口/禁用存储时不抛错） ----------
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
        sget: (k, f) => read(sessionStorage, k, f),
        sset: (k, v) => write(sessionStorage, k, v),
        sremove: (k) => { try { sessionStorage.removeItem(k); } catch (_) {} }
    };

    // ---------- 提示条 ----------
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

    async function fetchJSON(url, init) {
        const r = await fetch(url, Object.assign({ cache: 'no-store' }, init || {}));
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
    }

    const SGS = {
        SUIT, CARD_ART, DELAYED, EQUIP_SLOT, EQUIP_ORDER, IDENTITY, WINNER, PHASE,
        esc, rankText, suitInfo, cardLabel, cardHTML, hpHTML, hpColor, ensureGouyuDefs,
        identitySeal, factionSeal, heroImageURL, heroImgHTML, imgFallback, store, toast, fetchJSON
    };
    global.SGS = SGS;
    if (typeof document !== 'undefined') {
        if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ensureGouyuDefs);
        else ensureGouyuDefs();
    }
})(typeof window !== 'undefined' ? window : globalThis);
