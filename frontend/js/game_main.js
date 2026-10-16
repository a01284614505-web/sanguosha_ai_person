// 对局页：渲染引擎状态、采集真人输入。纯 UI —— 合法候选全部来自引擎（your_turn / require_response），
// 提交后由引擎复核；前端只做“候选里选哪个”。
(function () {
    'use strict';
    const { esc, store, toast } = SGS;
    const SEAT_COUNT = 5;

    const G = {
        cfg: null,
        meId: null,
        state: null,
        players: [],
        hand: [],
        turn: null,        // 最近一次 your_turn（仅在我的出牌阶段有效）
        sel: null,         // {kind:'card', index, action, targets} | {kind:'skill', name, cards, action, targets}
        req: null,         // 当前 require_response
        picked: [],        // req 中已选的候选下标
        reqDeadline: 0,
        reqTimer: null,
        prev: {},          // id -> {hp, alive}
        seatEls: {},
        seatSig: {},
        thinking: {},
        animQueue: Promise.resolve(),
        tableSeq: 0,
        ended: false,
        lastTurnKey: ''
    };
    window.GameUI = G;

    // ------------------------------------------------------------------ 配置
    function loadConfig() {
        const cfg = store.sget('gameConfig', null) || store.get('gameConfig', null);
        if (!cfg || !cfg.selected_hero || !cfg.selected_hero.id || !Array.isArray(cfg.ais) || cfg.ais.length !== 4) return null;
        return cfg;
    }

    const settings = () => (window.getGlobalSettings ? getGlobalSettings() : { animation_ms: 1100, show_ai_thinking: true });
    const playerById = (id) => G.players.find(p => p.id === id);
    const playerByName = (name) => G.players.find(p => p.name === name);
    const me = () => playerById(G.meId);
    const isMyPlay = () => !!G.turn && !G.req && !G.ended;

    function sfx(name) { if (window.audioManager) audioManager.play(name); }

    // ------------------------------------------------------------------ 座次
    function seatPos(id) {
        const n = G.players.length || SEAT_COUNT;
        return ((id - (G.meId || 0)) % n + n) % n;
    }

    function frameEl(id) {
        if (id === G.meId) return document.querySelector('#myHero .hero-frame');
        const seat = G.seatEls[id];
        return seat ? seat.querySelector('.seat-frame') : null;
    }
    function seatRoot(id) {
        return id === G.meId ? document.getElementById('myHero') : G.seatEls[id];
    }

    // ------------------------------------------------------------------ 目标选择
    function currentTargeting() {
        // 返回 {valid:Set, chosen:Array, max} 或 null
        if (G.req && G.req.kind === 'choose_players') {
            const valid = new Set();
            (G.req.options || []).forEach(o => { if (Number.isInteger(o.player_id)) valid.add(o.player_id); });
            const chosen = G.picked.map(i => (G.req.options[i] || {}).player_id).filter(Number.isInteger);
            return { valid, chosen, mode: 'req' };
        }
        if (!isMyPlay() || !G.sel || !G.sel.action || !G.sel.action.requires_target) return null;
        const a = G.sel.action;
        const chosen = G.sel.targets;
        let valid = [];
        if (a.target_count === 2) {
            const pairs = a.valid_target_pairs || [];
            if (chosen.length === 0) valid = pairs.map(p => p[0]);
            else if (chosen.length === 1) valid = pairs.filter(p => p[0] === chosen[0]).map(p => p[1]);
        } else if (chosen.length < targetMax()) {
            valid = (a.valid_targets || []).filter(id => !chosen.includes(id));
        }
        return { valid: new Set(valid), chosen, mode: 'play' };
    }

    function targetMax() {
        if (!G.sel || !G.sel.action) return 1;
        if (G.sel.kind === 'skill') return 1;
        const card = G.hand[G.sel.index] || {};
        const rule = card.target_rule || {};
        return Math.max(1, Number(rule.max) || 1);
    }
    function targetMin() {
        if (!G.sel || !G.sel.action) return 1;
        if (G.sel.action.target_count === 2) return 2;
        if (G.sel.kind === 'skill') return 1;
        const rule = (G.hand[G.sel.index] || {}).target_rule || {};
        return Math.max(1, Number(rule.min) || 1);
    }

    function selectionReady() {
        if (!isMyPlay() || !G.sel || !G.sel.action) return false;
        if (!G.sel.action.requires_target) return true;
        if (G.sel.action.target_count === 2) return G.sel.targets.length === 2;
        return G.sel.targets.length >= targetMin() && G.sel.targets.length <= targetMax();
    }

    function onSeatClick(id) {
        const t = currentTargeting();
        if (t && (t.valid.has(id) || t.chosen.includes(id))) {
            if (t.mode === 'req') {
                const idx = (G.req.options || []).findIndex(o => o.player_id === id);
                if (idx >= 0) togglePick(idx);
                return;
            }
            const arr = G.sel.targets;
            const at = arr.indexOf(id);
            if (at >= 0) arr.splice(at, at === 0 && G.sel.action.target_count === 2 ? arr.length : 1);
            else arr.push(id);
            renderAll();
            return;
        }
        if (t && t.mode === 'play') {
            toast('不能选择这名角色', { bad: true });
            return;
        }
        openPlayerInfo(id);
    }

    // ------------------------------------------------------------------ 渲染：座位
    function seatFrameHTML(p, opts) {
        opts = opts || {};
        const hero = p.hero || {};
        const isMe = p.id === G.meId;
        const identity = p.identity && (isMe || p.identity_revealed) ? p.identity : null;
        const judge = (p.judge_area || []).map(name => '<span class="judge-chip" title="' + esc(name) + '">' + esc(SGS.DELAYED[name] || name.charAt(0)) + '</span>').join('');
        const status = G.thinking[p.id] && settings().show_ai_thinking !== false && p.alive
            ? '<div class="s-status thinking">思考中</div>' : '';
        return SGS.heroImgHTML(hero.id, hero.name || p.name) +
            '<div class="s-top">' + SGS.factionSeal(hero.faction) + '<span class="s-name">' + esc(p.name) + '</span>' + SGS.identitySeal(identity) + '</div>' +
            '<div class="s-hero">' + esc((hero.name || p.hero_name || '').replace(/^界/, '')) + '</div>' +
            (opts.hideHand ? '' : '<div class="s-hand" title="手牌数">' + p.hand_count + '</div>') +
            (judge ? '<div class="s-judge">' + judge + '</div>' : '') +
            '<div class="s-hp">' + SGS.hpHTML(p.hp, p.max_hp, { vertical: true }) + '</div>' + status;
    }

    function equipLines(p) {
        const eq = p.equipment || {};
        return SGS.EQUIP_ORDER.filter(slot => eq[slot]).map(slot =>
            '<div class="equip-line" title="' + esc(SGS.EQUIP_SLOT[slot].name + '：' + eq[slot]) + '"><b>' + SGS.EQUIP_SLOT[slot].short + '</b>' + esc(eq[slot]) + '</div>').join('');
    }

    function renderSeats() {
        const box = document.getElementById('opponents');
        const t = currentTargeting();
        const curId = G.state ? G.state.current_player_id : null;
        G.players.forEach(p => {
            if (p.id === G.meId) return;
            let el = G.seatEls[p.id];
            if (!el) {
                el = document.createElement('div');
                el.dataset.id = p.id;
                el.innerHTML = '<div class="seat-frame" role="button" tabindex="0"></div><div class="seat-equips"></div>';
                const frame = el.querySelector('.seat-frame');
                frame.addEventListener('click', () => onSeatClick(p.id));
                frame.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSeatClick(p.id); } });
                box.appendChild(el);
                G.seatEls[p.id] = el;
            }
            const cls = ['seat', 'pos-' + seatPos(p.id), 'faction-' + ((p.hero || {}).faction || '群')];
            if (p.id === curId) cls.push('current');
            if (!p.alive) cls.push('dead');
            if (t) {
                if (t.chosen.includes(p.id)) cls.push('chosen');
                else if (t.valid.has(p.id)) cls.push('targetable');
                else if (t.mode === 'play') cls.push('untargetable');
            }
            // 保留气泡等额外子节点，只在内容变化时重绘框体
            const keep = el.className.split(' ').filter(c => c === 'hurt' || c === 'healed');
            el.className = cls.concat(keep).join(' ');
            const frameHTML = seatFrameHTML(p);
            const equipHTML = equipLines(p);
            const sig = frameHTML + '|' + equipHTML;
            if (G.seatSig[p.id] !== sig) {
                G.seatSig[p.id] = sig;
                el.querySelector('.seat-frame').innerHTML = frameHTML;
                el.querySelector('.seat-equips').innerHTML = equipHTML;
            }
            el.querySelector('.seat-frame').setAttribute('aria-label', p.name + '，' + (p.hero_name || '') + '，体力' + p.hp + '/' + p.max_hp + '，手牌' + p.hand_count);
        });
    }

    // ------------------------------------------------------------------ 渲染：我的区域
    function renderMyArea() {
        const p = me();
        const zones = document.getElementById('myZones');
        const heroBox = document.getElementById('myHero');
        if (!p) return;
        const eq = p.equipment || {};
        const judge = (p.judge_area || []);
        zones.innerHTML = '<h3>装备区</h3>' + SGS.EQUIP_ORDER.map(slot =>
            '<div class="zone-slot' + (eq[slot] ? '' : ' empty') + '"><b>' + SGS.EQUIP_SLOT[slot].short + '</b>' + esc(eq[slot] || SGS.EQUIP_SLOT[slot].name) + '</div>').join('') +
            '<div class="zone-judge">' + (judge.length
                ? '判定区 ' + judge.map(n => '<span class="judge-chip" title="' + esc(n) + '">' + esc(SGS.DELAYED[n] || n.charAt(0)) + '</span>').join('')
                : '判定区 空') + '</div>';

        const hero = p.hero || {};
        const t = currentTargeting();
        const cls = ['my-hero', 'faction-' + (hero.faction || '群')];
        if (G.state && G.state.current_player_id === p.id) cls.push('current');
        if (!p.alive) cls.push('dead');
        if (t) {
            if (t.chosen.includes(p.id)) cls.push('chosen');
            else if (t.valid.has(p.id)) cls.push('targetable');
        }
        const keep = heroBox.className.split(' ').filter(c => c === 'hurt' || c === 'healed');
        heroBox.className = cls.concat(keep).join(' ');

        const readySkills = new Set(isMyPlay() ? (G.turn.actions || []).filter(a => a.type === 'use_skill').map(a => a.skill_name) : []);
        const skills = (hero.skills || []).map(s => typeof s === 'string' ? { name: s } : s);
        const skillHTML = skills.map(s => {
            const ready = readySkills.has(s.name);
            const on = G.sel && G.sel.kind === 'skill' && G.sel.name === s.name;
            return '<button type="button" class="skill-btn' + (ready ? ' ready' : '') + (on ? ' on' : '') + '" data-skill="' + esc(s.name) + '" title="' + esc(s.description || '') + '">' + esc(s.name) + '</button>';
        }).join('');
        const frameHTML = seatFrameHTML(p, { hideHand: true });
        const sig = frameHTML + '|' + skillHTML;
        if (G.seatSig.me !== sig) {
            G.seatSig.me = sig;
            heroBox.innerHTML = '<div class="hero-frame" role="button" tabindex="0" aria-label="我的武将">' + frameHTML + '</div><div class="skill-btns">' + skillHTML + '</div>';
            heroBox.querySelector('.hero-frame').addEventListener('click', () => onSeatClick(p.id));
            heroBox.querySelectorAll('.skill-btn').forEach(b => b.addEventListener('click', () => onSkillClick(b.dataset.skill)));
        }
        document.getElementById('handCount').textContent = '手牌 ' + G.hand.length + ' / 上限 ' + Math.max(0, p.hp);
    }

    // ------------------------------------------------------------------ 渲染：手牌
    function playActionFor(index) {
        if (!isMyPlay()) return null;
        return (G.turn.actions || []).find(a => a.type === 'play_card' && a.card_index === index) || null;
    }

    function skillCandidates() {
        if (!isMyPlay() || !G.sel || G.sel.kind !== 'skill') return [];
        return (G.turn.actions || []).filter(a => a.type === 'use_skill' && a.skill_name === G.sel.name);
    }
    const sortedKey = (arr) => (arr || []).slice().sort((a, b) => a - b).join(',');

    function skillSelectableCards() {
        const chosen = G.sel.cards;
        const set = new Set();
        skillCandidates().forEach(a => {
            const ci = a.card_indices || [];
            if (chosen.every(i => ci.includes(i))) ci.forEach(i => set.add(i));
        });
        return set;
    }
    function skillMatches() {
        const key = sortedKey(G.sel.cards);
        return skillCandidates().filter(a => sortedKey(a.card_indices) === key);
    }

    // 若当前请求的候选全部是“我自己手里的牌”，就直接在手牌上选（与官方一致），不再另开候选托盘。
    // 返回 Map(手牌下标 -> 候选下标)；任何不确定的情况（暗牌、他人的牌、同一张牌对应多个候选）返回 null。
    function reqHandMap() {
        const r = G.req;
        if (!r || r.expired) return null;
        if (r.kind === 'choose_players' || r.kind === 'confirm' || r.kind === 'choose_option') return null;
        if (r.selection && r.selection.zone && r.selection.zone !== 'hand') return null;
        const byId = new Map(G.hand.map((c, i) => [c.id, i]));
        const map = new Map();
        const options = r.options || [];
        for (let i = 0; i < options.length; i++) {
            const o = options[i];
            if (o.is_pass) continue;
            if (o.hidden || !o.card || !o.card.id) return null;
            if (o.owner_id != null && o.owner_id !== G.meId) return null;
            const hi = byId.get(o.card.id);
            if (hi === undefined || map.has(hi)) return null;
            map.set(hi, i);
        }
        return map.size ? map : null;
    }

    function renderHand() {
        const box = document.getElementById('hand');
        const hint = document.getElementById('actionHint');
        if (!G.hand.length) {
            box.innerHTML = '<div class="empty-hand">没有手牌</div>';
            hint.textContent = '';
            return;
        }
        let selectable = null;
        if (isMyPlay() && G.sel && G.sel.kind === 'skill') selectable = skillSelectableCards();
        const reqMap = reqHandMap();
        box.innerHTML = G.hand.map((c, i) => {
            const cls = [];
            let asName = null;
            if (reqMap) {
                const oi = reqMap.get(i);
                if (oi === undefined) cls.push('dim');
                else {
                    cls.push(G.picked.includes(oi) ? 'selected' : 'can');
                    asName = (G.req.options[oi] || {}).as_name;
                }
            } else if (isMyPlay()) {
                if (selectable) {
                    if (G.sel.cards.includes(i)) cls.push('selected');
                    else if (selectable.has(i)) cls.push('can');
                    else cls.push('dim');
                } else {
                    if (G.sel && G.sel.kind === 'card' && G.sel.index === i) cls.push('selected');
                    else if (playActionFor(i)) cls.push('can');
                    else cls.push('dim');
                }
            }
            return SGS.cardHTML(c, { cls: cls.join(' '), asName: asName, attrs: 'data-index="' + i + '" role="button" tabindex="0"' });
        }).join('');
        box.querySelectorAll('.card').forEach(el => {
            const i = Number(el.dataset.index);
            el.addEventListener('click', () => onCardClick(i));
            el.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onCardClick(i); } });
        });
        hint.textContent = reqMap ? '从手牌中选择' : (isMyPlay() ? '轮到你出牌' : '');
        layoutHand();
    }

    function layoutHand() {
        const box = document.getElementById('hand');
        const cards = box.querySelectorAll('.card');
        if (!cards.length) return;
        const w = cards[0].getBoundingClientRect().width || 80;
        const avail = box.clientWidth - 12;
        const n = cards.length;
        const overlap = n > 1 ? Math.min(6, (avail - n * w) / (n - 1)) : 0;
        box.style.setProperty('--overlap', Math.max(-w * 0.72, overlap) + 'px');
    }

    function onCardClick(i) {
        const reqMap = reqHandMap();
        if (reqMap) {
            if (reqMap.has(i)) togglePick(reqMap.get(i));
            else toast('这张牌不能用于此次响应', { bad: true });
            return;
        }
        if (!isMyPlay()) {
            if (G.req) toast('请先在下方操作条里作出选择');
            return;
        }
        if (G.sel && G.sel.kind === 'skill') {
            const sel = G.sel;
            const at = sel.cards.indexOf(i);
            if (at >= 0) sel.cards.splice(at, 1);
            else if (skillSelectableCards().has(i)) sel.cards.push(i);
            else { toast('这张牌不能用于【' + sel.name + '】', { bad: true }); return; }
            refreshSkillAction();
            renderAll();
            return;
        }
        if (G.sel && G.sel.kind === 'card' && G.sel.index === i) {
            G.sel = null;
            renderAll();
            return;
        }
        const action = playActionFor(i);
        if (!action) {
            const c = G.hand[i] || {};
            toast(c.name === '闪' || c.name === '无懈可击' ? '【' + c.name + '】只能在需要时打出' : '【' + (c.name || '这张牌') + '】现在不能使用', { bad: true });
            return;
        }
        G.sel = { kind: 'card', index: i, action: action, targets: [] };
        renderAll();
    }

    function onSkillClick(name) {
        if (!isMyPlay()) {
            const p = me();
            const s = ((p && p.hero && p.hero.skills) || []).find(x => x.name === name);
            if (s) toast('【' + name + '】' + (s.description ? '：' + s.description.slice(0, 40) + (s.description.length > 40 ? '…' : '') : ''), { ms: 3200 });
            return;
        }
        if (G.sel && G.sel.kind === 'skill' && G.sel.name === name) { G.sel = null; renderAll(); return; }
        const cands = (G.turn.actions || []).filter(a => a.type === 'use_skill' && a.skill_name === name);
        if (!cands.length) {
            toast('【' + name + '】现在不能发动（锁定技与触发技由引擎自动结算）');
            return;
        }
        G.sel = { kind: 'skill', name: name, cards: [], action: null, targets: [] };
        refreshSkillAction();
        renderAll();
    }

    function refreshSkillAction() {
        const matches = skillMatches();
        const keep = G.sel.action && matches.includes(G.sel.action) ? G.sel.action : null;
        G.sel.action = keep || (matches.length === 1 ? matches[0] : null);
        if (!G.sel.action) G.sel.targets = [];
    }

    // ------------------------------------------------------------------ 渲染：操作条
    function renderActionBar() {
        const bar = document.getElementById('actionBar');
        const prompt = document.getElementById('abPrompt');
        const opts = document.getElementById('abOptions');
        const ok = document.getElementById('okBtn');
        const cancel = document.getElementById('cancelBtn');
        const end = document.getElementById('endBtn');
        const timer = document.getElementById('abTimer');
        ok.textContent = '确定';
        cancel.textContent = '取消';
        ok.hidden = cancel.hidden = end.hidden = false;
        opts.innerHTML = '';
        timer.classList.toggle('on', !!G.req);

        if (G.ended) {
            bar.className = 'action-bar idle';
            prompt.textContent = '对局已结束';
            return;
        }

        if (G.req) {
            bar.className = 'action-bar';
            renderRequest(prompt, opts, ok, cancel, end);
            return;
        }

        if (isMyPlay()) {
            bar.className = 'action-bar';
            end.disabled = false;
            cancel.disabled = !G.sel;
            ok.disabled = !selectionReady();
            prompt.innerHTML = playPrompt();
            if (G.sel && G.sel.kind === 'skill' && !G.sel.action) {
                const matches = skillMatches();
                if (matches.length > 1) {
                    opts.innerHTML = matches.map((a, i) => '<button type="button" class="opt-chip" data-variant="' + i + '">' + esc(a.description || a.variant || ('方式' + (i + 1))) + '</button>').join('');
                    opts.querySelectorAll('[data-variant]').forEach(b => b.addEventListener('click', () => {
                        G.sel.action = matches[Number(b.dataset.variant)];
                        G.sel.targets = [];
                        renderAll();
                    }));
                }
            }
            return;
        }

        bar.className = 'action-bar idle';
        prompt.textContent = waitingText();
    }

    function playPrompt() {
        if (!G.sel) return '出牌阶段：选择一张牌，或发动技能';
        if (G.sel.kind === 'card') {
            const card = G.hand[G.sel.index] || {};
            const name = '【' + esc(card.name) + '】';
            const a = G.sel.action;
            if (a.requires_target && !selectionReady()) {
                if (a.target_count === 2) {
                    return G.sel.targets.length === 0
                        ? name + '：先选择一名<em>装备着武器</em>的角色'
                        : name + '：再选择他要<em>【杀】</em>的目标';
                }
                const max = targetMax();
                return name + '：选择' + (max > 1 ? '至多 ' + max + ' 名' : '一名') + '<em>目标角色</em>';
            }
            return '点击<em>确定</em>使用' + name + (G.sel.targets.length ? '，目标：' + G.sel.targets.map(id => esc((playerById(id) || {}).name || id)).join('、') : '');
        }
        const name = '【' + esc(G.sel.name) + '】';
        if (!G.sel.action) {
            const sel = skillSelectableCards();
            if (skillMatches().length > 1) return name + '：选择发动方式';
            if (!sel.size) return name + '：选择发动方式';
            // 引擎给出的合法组合决定能选几张（例如制衡：1 张或全部）
            const sizes = Array.from(new Set(skillCandidates()
                .filter(a => G.sel.cards.every(i => (a.card_indices || []).includes(i)))
                .map(a => (a.card_indices || []).length))).sort((a, b) => a - b);
            const need = sizes.length ? '选择 ' + sizes.join(' 或 ') + ' 张牌' : '这几张牌凑不成合法组合，请重选';
            return name + '：' + need + '（已选 ' + G.sel.cards.length + ' 张）';
        }
        const desc = G.sel.action.description ? '<br><small class="muted">' + esc(G.sel.action.description) + '</small>' : '';
        if (G.sel.action.requires_target && !G.sel.targets.length) return name + '：选择一名<em>目标角色</em>' + desc;
        return '点击<em>确定</em>发动' + name + desc;
    }

    function waitingText() {
        const s = G.state;
        if (!s) return '正在连接游戏服务…';
        if (!s.current_name) return '等待开局…';
        const phase = SGS.PHASE[s.phase] || '';
        if (s.current_player_id === G.meId) return '你的' + phase;
        return s.current_name + ' 的' + phase;
    }

    const REQ_TITLE = { dying: '求桃', wuxie: '无懈可击', respond: '响应', choose_cards: '选牌', choose_players: '选择角色', confirm: '请决定', choose_option: '请选择' };

    function renderRequest(prompt, opts, ok, cancel, end) {
        const r = G.req;
        const sel = r.selection || {};
        end.hidden = true;
        prompt.innerHTML = esc(r.prompt || REQ_TITLE[r.kind] || '请响应');
        if (r.expired) {
            prompt.innerHTML = '已超时，由托管代为选择';
            ok.disabled = true; cancel.disabled = true;
            return;
        }
        const options = r.options || [];
        const isLegacy = !r.selection; // respond / wuxie / dying 等旧通道：单选 + 「不响应」
        if (r.kind === 'confirm') {
            ok.textContent = (options[0] && options[0].label) || '是';
            cancel.textContent = (options[1] && options[1].label) || '否';
            ok.disabled = false; cancel.disabled = false;
            return;
        }
        if (r.kind === 'choose_option') {
            opts.innerHTML = options.map((o, i) => '<button type="button" class="opt-chip' + (G.picked.includes(i) ? ' picked' : '') + '" data-opt="' + i + '">' + esc(o.label) + '</button>').join('');
        } else if (r.kind === 'choose_players') {
            opts.innerHTML = options.map((o, i) => '<button type="button" class="opt-chip' + (G.picked.includes(i) ? ' picked' : '') + '" data-opt="' + i + '">' + esc(o.player_name || o.label) + '</button>').join('');
        } else if (!reqHandMap()) {
            opts.innerHTML = options.map((o, i) => {
                if (o.is_pass) return '';
                const label = o.skill_name ? '（' + o.skill_name + '）' : (o.hidden ? '暗置手牌' : (o.detail || ''));
                const owner = o.owner_name && o.owner_id !== G.meId ? o.owner_name + '的' : '';
                return '<div class="opt-wrap">' + SGS.cardHTML(o.hidden ? null : o.card, {
                    cls: G.picked.includes(i) ? 'picked' : '', back: o.hidden || !o.card, asName: o.as_name,
                    attrs: 'data-opt="' + i + '" role="button" tabindex="0" aria-label="' + esc(o.label) + '"'
                }) + ((label || owner) ? '<small>' + esc(owner + label) + '</small>' : '') + '</div>';
            }).join('');
        }
        opts.querySelectorAll('[data-opt]').forEach(el => {
            const i = Number(el.dataset.opt);
            el.addEventListener('click', () => togglePick(i));
            el.addEventListener('dblclick', () => { if (!isMulti()) { G.picked = [i]; submitPicked(); } });
            el.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); togglePick(i); } });
        });
        const n = G.picked.length;
        if (isLegacy) {
            cancel.textContent = r.kind === 'dying' ? '不救' : (r.kind === 'wuxie' ? '不使用' : '不出');
            cancel.disabled = false;
            ok.disabled = n !== 1;
        } else {
            const min = sel.min != null ? Number(sel.min) : 1;
            const max = sel.max != null ? Number(sel.max) : 1;
            ok.disabled = n < min || n > max;
            cancel.hidden = !sel.cancelable;
            cancel.disabled = !sel.cancelable;
            if (max > 1) prompt.innerHTML += '　<small class="muted">已选 ' + n + ' / ' + (min === max ? max : min + '–' + max) + '</small>';
        }
    }

    function isMulti() {
        return !!(G.req && G.req.selection && G.req.selection.mode === 'multi');
    }

    function togglePick(i) {
        if (!G.req || G.req.expired) return;
        const at = G.picked.indexOf(i);
        if (isMulti()) {
            const max = Number(G.req.selection.max || 1);
            if (at >= 0) G.picked.splice(at, 1);
            else if (G.picked.length < max) G.picked.push(i);
            else { toast('最多选择 ' + max + ' 项', { bad: true }); return; }
        } else {
            G.picked = at >= 0 ? [] : [i];
        }
        renderAll();
    }

    // ------------------------------------------------------------------ 提交
    function onOk() {
        if (G.req) {
            if (G.req.expired) return;
            if (G.req.kind === 'confirm') { sendResponse(0); return; }
            submitPicked();
            return;
        }
        if (!selectionReady()) return;
        const sel = G.sel;
        if (sel.kind === 'card') {
            const card = G.hand[sel.index] || {};
            gameClient.playerAction({ type: 'play_card', card_index: sel.index }, sel.targets.slice());
            ChatPanel.addLog('你使用【' + card.name + '】' + targetsText(sel.targets), 'me');
        } else {
            const action = Object.assign({}, sel.action);
            const targets = action.requires_target ? sel.targets.slice() : [];
            gameClient.playerAction(action, targets);
            ChatPanel.addLog('你发动【' + sel.name + '】' + targetsText(targets), 'me');
        }
        G.sel = null;
        G.turn = null; // 等引擎结算后重新下发 your_turn
        renderAll();
    }

    function targetsText(ids) {
        return ids && ids.length ? '，目标：' + ids.map(id => (playerById(id) || {}).name || id).join('、') : '';
    }

    function onCancel() {
        if (G.req) {
            if (G.req.expired) return;
            if (G.req.kind === 'confirm') { sendResponse(1); return; }
            if (!G.req.selection) {
                const passIdx = (G.req.options || []).findIndex(o => o.is_pass);
                sendResponse(passIdx >= 0 ? passIdx : -1);
                return;
            }
            if (G.req.selection.cancelable) sendResponse([]);
            return;
        }
        if (G.sel) { G.sel = null; renderAll(); }
    }

    function onEnd() {
        if (!isMyPlay()) return;
        gameClient.playerAction({ type: 'end_phase' }, []);
        ChatPanel.addLog('你结束了出牌阶段', 'me');
        G.sel = null;
        G.turn = null;
        renderAll();
    }

    function submitPicked() {
        if (!G.req) return;
        if (G.req.selection) {
            if (isMulti()) sendResponse(G.picked.slice());
            else if (G.picked.length === 1) sendResponse(G.picked[0]);
        } else if (G.picked.length === 1) {
            sendResponse(G.picked[0]);
        }
    }

    function sendResponse(selection) {
        const r = G.req;
        if (!r || r.expired) return;
        const action = { type: 'response', request_id: r.request_id };
        if (Array.isArray(selection)) action.option_indices = selection;
        else action.option_index = selection;
        gameClient.playerAction(action, []);
        clearRequest();
    }

    function clearRequest() {
        G.req = null;
        G.picked = [];
        clearInterval(G.reqTimer);
        renderAll();
    }

    function startRequestTimer(seconds) {
        clearInterval(G.reqTimer);
        const total = Math.max(1, Number(seconds) || 30) * 1000;
        G.reqDeadline = Date.now() + total;
        const bar = document.querySelector('#abTimer i');
        const wrap = document.getElementById('abTimer');
        const tick = () => {
            if (!G.req) { clearInterval(G.reqTimer); return; }
            const left = G.reqDeadline - Date.now();
            bar.style.transform = 'scaleX(' + Math.max(0, left / total) + ')';
            wrap.classList.toggle('urgent', left < 5000);
            if (left <= 0) {
                clearInterval(G.reqTimer);
                G.req.expired = true;
                renderAll();
                const r = G.req;
                setTimeout(() => { if (G.req === r) clearRequest(); }, 900);
            }
        };
        tick();
        G.reqTimer = setInterval(tick, 200);
    }

    // ------------------------------------------------------------------ 特效
    function centerOf(el) {
        const r = el.getBoundingClientRect();
        return { x: r.left + r.width / 2, y: r.top + r.height / 2, r: r };
    }

    function floatNumber(id, text, cls) {
        const el = frameEl(id);
        if (!el) return;
        const c = centerOf(el);
        const n = document.createElement('div');
        n.className = 'float-num ' + cls;
        n.textContent = text;
        n.style.left = c.x + 'px';
        n.style.top = (c.y - 10) + 'px';
        document.body.appendChild(n);
        setTimeout(() => n.remove(), 1200);
    }

    function flash(id, cls) {
        const root = seatRoot(id);
        if (!root) return;
        root.classList.remove(cls);
        void root.offsetWidth;
        root.classList.add(cls);
        setTimeout(() => root.classList.remove(cls), 750);
    }

    function skillShout(id, text) {
        const el = frameEl(id);
        const c = el ? centerOf(el) : { x: innerWidth / 2, y: innerHeight / 2 };
        const s = document.createElement('div');
        s.className = 'skill-shout';
        s.textContent = text;
        s.style.left = c.x + 'px';
        s.style.top = c.y + 'px';
        document.body.appendChild(s);
        setTimeout(() => s.remove(), 1400);
    }

    function showBubble(id, text) {
        const root = seatRoot(id);
        if (!root) return;
        root.querySelectorAll('.bubble').forEach(b => b.remove());
        const b = document.createElement('div');
        const pos = id === G.meId ? 'above' : ({ 1: 'left', 2: 'below', 3: 'below', 4: 'right' }[seatPos(id)] || 'below');
        b.className = 'bubble ' + pos;
        b.textContent = text;
        root.appendChild(b);
        setTimeout(() => { b.classList.add('fade'); setTimeout(() => b.remove(), 320); }, 3800);
    }

    function aimLines(fromId, toIds) {
        const svg = document.getElementById('fxLines');
        const from = frameEl(fromId);
        if (!from || !toIds.length) return;
        const base = svg.getBoundingClientRect();
        const a = centerOf(from);
        const parts = toIds.map(id => {
            const el = frameEl(id);
            if (!el || id === fromId) return '';
            const b = centerOf(el);
            return '<line x1="' + (a.x - base.left) + '" y1="' + (a.y - base.top) + '" x2="' + (b.x - base.left) + '" y2="' + (b.y - base.top) + '"/>' +
                '<circle cx="' + (b.x - base.left) + '" cy="' + (b.y - base.top) + '" r="5"/>';
        }).join('');
        if (!parts) return;
        const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        g.innerHTML = parts;
        svg.appendChild(g);
        setTimeout(() => g.remove(), 1000);
    }

    function cardSource(data) {
        if (data.actor_id === G.meId && Number.isInteger(data.card_index)) {
            const el = document.querySelector('#hand .card[data-index="' + data.card_index + '"]');
            if (el) return el.getBoundingClientRect();
        }
        const f = frameEl(data.actor_id);
        if (f) return f.getBoundingClientRect();
        return { left: innerWidth / 2 - 30, top: innerHeight / 2 - 40, width: 60, height: 84 };
    }

    function putOnTable(data) {
        const box = document.getElementById('tableCards');
        const fig = document.createElement('figure');
        fig.className = 'table-card';
        fig.style.margin = '0';
        let caption = data.actor_name || '';
        if (data.reason === 'use' && data.target_name) caption += ' → ' + data.target_name;
        else if (data.reason === 'hand_limit') caption += ' 弃置';
        else if (data.reason && data.reason !== 'use') caption = data.message || caption;
        fig.innerHTML = SGS.cardHTML(data.card || { name: data.card_name }) + '<figcaption>' + esc(caption) + '</figcaption>';
        box.appendChild(fig);
        const all = box.querySelectorAll('.table-card');
        all.forEach((el, i) => el.classList.toggle('old', i < all.length - 1));
        while (box.children.length > 4) box.removeChild(box.firstChild);
        if (Number.isInteger(data.discard_count)) document.getElementById('discardCount').textContent = data.discard_count;
    }

    function clearTable() {
        document.getElementById('tableCards').innerHTML = '';
    }

    function ack(data) {
        if (data.animation_id) gameClient.send({ type: Protocol.INBOUND.CARD_ANIMATION_DONE, animation_id: data.animation_id });
    }

    function animateCard(data) {
        return new Promise(resolve => {
            const total = Math.max(300, Number(settings().animation_ms) || 1100);
            const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
            if (data.reason === 'use') {
                const ids = String(data.target_name || '').split('、').map(n => (playerByName(n) || {}).id).filter(Number.isInteger);
                aimLines(data.actor_id, ids);
            }
            if (document.hidden || reduced) {
                putOnTable(data);
                sfx('card');
                ack(data);
                resolve();
                return;
            }
            const src = cardSource(data);
            const dest = document.getElementById('tableCards').getBoundingClientRect();
            const holder = document.createElement('div');
            holder.className = 'flying-card';
            holder.innerHTML = SGS.cardHTML(data.card || { name: data.card_name });
            const cardEl = holder.firstChild;
            const w = parseFloat(getComputedStyle(document.getElementById('battle')).getPropertyValue('--hand-w')) || 86;
            cardEl.style.setProperty('--w', w + 'px');
            holder.style.left = src.left + 'px';
            holder.style.top = src.top + 'px';
            document.body.appendChild(holder);
            const flyMs = Math.round(total * 0.42);
            const tx = dest.left + dest.width / 2 - w / 2 - src.left;
            const ty = dest.top + dest.height / 2 - w * 0.7 - src.top;
            holder.animate([
                { transform: 'translate(0,0) scale(.9)', opacity: .85 },
                { transform: 'translate(' + tx + 'px,' + ty + 'px) scale(1.08)', opacity: 1 }
            ], { duration: flyMs, easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'forwards' });
            setTimeout(() => {
                holder.remove();
                putOnTable(data);
                sfx('card');
                ack(data);
                // 给观看留一点停顿，再结算下一张
                setTimeout(resolve, Math.round(total * 0.25));
            }, flyMs);
        });
    }

    function enqueueCard(data) {
        G.animQueue = G.animQueue.then(() => animateCard(data)).catch(err => { console.error('卡牌动画失败', err); ack(data); });
    }

    // ------------------------------------------------------------------ 状态差异
    function applyStateEffects(prevMap) {
        G.players.forEach(p => {
            const before = prevMap[p.id];
            if (!before) return;
            const diff = p.hp - before.hp;
            if (diff < 0) {
                flash(p.id, 'hurt');
                floatNumber(p.id, String(diff), 'minus');
                sfx('damage');
            } else if (diff > 0) {
                flash(p.id, 'healed');
                floatNumber(p.id, '+' + diff, 'plus');
                sfx('heal');
            }
            if (before.alive && !p.alive) {
                ChatPanel.addLog(p.name + '（' + (p.hero_name || '') + '）阵亡' + (p.identity ? '，身份是' + ((SGS.IDENTITY[p.identity] || {}).name || p.identity) : ''), 'important');
                toast(p.name + ' 阵亡');
                sfx('die');
            }
        });
    }

    // ------------------------------------------------------------------ 总渲染
    function renderHUD() {
        const s = G.state;
        if (!s) return;
        document.getElementById('rn').textContent = s.round;
        document.getElementById('dc').textContent = s.deck_count;
        document.getElementById('discardCount').textContent = s.discard_count || 0;
        const phase = SGS.PHASE[s.phase] || '';
        document.getElementById('turnText').textContent = s.current_name ? (s.current_player_id === G.meId ? '你的' + phase : s.current_name + ' · ' + phase) : '等待开局';
        document.getElementById('phaseBanner').textContent = s.current_player_id === G.meId && phase ? phase : '';
    }

    function renderAll() {
        renderHUD();
        renderSeats();
        renderMyArea();
        renderHand();
        renderActionBar();
    }

    // ------------------------------------------------------------------ 消息处理
    gameClient.onConnect = function () {
        ChatPanel.addLog('已连接游戏服务，正在开局…');
        const cfg = Object.assign({}, G.cfg);
        const hero = cfg.selected_hero;
        cfg.player = { name: cfg.player_name || '无名客', is_ai: false, hero: hero };
        const deckId = cfg.deck_id || (function () { try { return localStorage.getItem('active_deck') || ''; } catch (_) { return ''; } })();
        if (deckId) cfg.deck_id = deckId;
        // 清除上一局结算快照：中断或刷新后不得展示旧数据。
        store.remove('gameResult');
        gameClient.createGame(cfg);
    };

    gameClient.onGameCreated = function () {
        if (G.cfg.identity_card && G.cfg.identity_card.use) {
            const user = store.get('userData', {}) || {};
            user.identityCards = Math.max(0, (user.identityCards || 0) - 1);
            store.set('userData', user);
            delete G.cfg.identity_card;
            store.sset('gameConfig', G.cfg);
            ChatPanel.addLog('已使用一张身份卡');
        }
        sfx('click');
    };

    gameClient.onStateUpdate = function (s) {
        const prevMap = G.prev;
        G.state = s;
        G.players = s.players || [];
        const human = G.players.find(p => !p.is_ai) || G.players.find(p => p.id === 0);
        if (human) G.meId = human.id;
        if (Array.isArray(s.self_hand)) {
            const oldKey = G.hand.map(c => c.id).join('|');
            const newKey = s.self_hand.map(c => c.id).join('|');
            G.hand = s.self_hand;
            if (oldKey !== newKey && G.sel) G.sel = null;
        }
        if (s.current_player_id !== G.meId || s.phase !== 'play' || s.game_over) {
            G.turn = null;
            G.sel = null;
        }
        const turnKey = s.round + ':' + s.current_player_id;
        if (turnKey !== G.lastTurnKey) {
            G.lastTurnKey = turnKey;
            clearTable();
            if (s.current_name) ChatPanel.addLog('—— ' + (s.current_player_id === G.meId ? '你' : s.current_name) + ' 的回合 ——', 'turn');
        }
        G.prev = {};
        G.players.forEach(p => { G.prev[p.id] = { hp: p.hp, alive: p.alive }; });
        renderAll();
        applyStateEffects(prevMap);
    };

    gameClient.onYourTurn = function (data) {
        const fresh = !G.turn;
        G.turn = data;
        G.hand = data.hand || G.hand;
        G.sel = null;
        renderAll();
        if (fresh) sfx('click');
    };

    gameClient.onActionResult = function (ok) {
        if (!ok) {
            toast('操作没有生效，请重新选择', { bad: true });
            ChatPanel.addLog('上一步操作被引擎判定无效', 'bad');
        }
    };

    gameClient.onRequireResponse = function (data) {
        G.req = data;
        G.picked = [];
        startRequestTimer(data.timeout);
        renderAll();
        sfx('click');
        if (ChatPanel.isDrawer() && ChatPanel.isOpen()) ChatPanel.close();
    };

    gameClient.onChat = function (data) {
        ChatPanel.addMessage(data);
    };

    gameClient.onEventNotification = function (data) {
        if (data.event_kind === 'card_to_discard') {
            ChatPanel.addLog(data.message || ((data.actor_name || '角色') + '使用【' + (data.card_name || '') + '】'));
            enqueueCard(data);
            return;
        }
        if (data.event_kind === 'skill_activation') {
            ChatPanel.addLog(data.message || ((data.actor_name || '角色') + '发动【' + data.skill_name + '】'));
            if (Number.isInteger(data.actor_id)) skillShout(data.actor_id, data.skill_name || '');
            return;
        }
        if (data.message) {
            ChatPanel.addLog(data.message, data.important ? 'important' : (data.trustee ? 'bad' : ''));
            if (data.trustee && data.player_id === G.meId) toast(data.message);
        }
    };

    gameClient.onAIAction = function (data) {
        const p = playerByName(data.player_name);
        if (data.action === 'thinking_start' && p) {
            G.thinking[p.id] = true;
            renderSeats();
        } else if (data.action === 'thinking_end' && p) {
            G.thinking[p.id] = false;
            renderSeats();
            if (settings().show_ai_thinking && data.reasoning && data.reasoning !== '规则AI兜底') {
                ChatPanel.addLog(data.player_name + ' 思考：' + data.reasoning, 'think');
            }
        }
    };

    gameClient.onAIConfigUpdated = function (config) {
        toast('AI 设置已更新，立即生效');
        const dlg = document.getElementById('aiSettingsModal');
        if (dlg.open) dlg.close();
        if (config && Number.isInteger(config.player_id)) {
            const p = playerById(config.player_id);
            if (p) ChatPanel.addLog(p.name + ' 换用 ' + config.provider + ' / ' + config.model);
        }
    };

    gameClient.onEndGameAccepted = function () {
        toast('已请求结束对局，等待结算…');
    };

    gameClient.onGameEnd = function (data) {
        G.ended = true;
        G.turn = null; G.sel = null;
        if (G.req) { G.req = null; clearInterval(G.reqTimer); }
        const state = data.state || G.state || {};
        if (data.state) { G.state = data.state; G.players = data.state.players || G.players; }
        const mine = (state.players || []).find(p => p.id === G.meId) || {};
        const winner = data.winner;
        const side = { lord: ['lord', 'loyalist'], rebel: ['rebel'], spy: ['spy'] }[winner] || [];
        const decided = side.length > 0;
        const won = decided && side.includes(mine.identity);
        const result = {
            winner: winner,
            message: data.message,
            total_rounds: state.round || 0,
            duration: data.duration || 0,
            player_identity: mine.identity || '未知',
            player_id: G.meId,
            player_won: won,
            mvp: data.mvp || null,
            stats: data.stats || null,
            players: state.players || []
        };
        store.set('gameResult', result);
        if (decided) {
            const user = store.get('userData', {}) || {};
            user.totalGames = (user.totalGames || 0) + 1;
            user.winStreak = won ? (user.winStreak || 0) + 1 : 0;
            if (won && user.winStreak % 2 === 0) { user.identityCards = (user.identityCards || 0) + 1; result.reward = 'identity_card'; store.set('gameResult', result); }
            store.set('userData', user);
        }
        renderAll();
        const verdict = document.getElementById('endVerdict');
        verdict.className = 'verdict ' + (decided ? (won ? 'win' : 'lose') : '');
        verdict.textContent = decided ? (won ? '胜' : '败') : '终';
        document.getElementById('endTitle').textContent = decided ? (won ? '旗开得胜' : '惜败一局') : '对局结束';
        const winText = SGS.WINNER[winner] ? (decided ? SGS.WINNER[winner] + '获胜' : '') : '';
        document.getElementById('endMessage').textContent = [winText, winner === 'aborted' || winner === 'draw' ? data.message : ''].filter(Boolean).join('。') || data.message || '';
        document.getElementById('endResult').hidden = false;
        ChatPanel.addLog(data.message || '对局结束', 'important');
        sfx(decided ? (won ? 'win' : 'lose') : 'click');
        setTimeout(() => { const d = document.getElementById('endModal'); if (!d.open) d.showModal(); }, 900);
    };

    gameClient.onError = function (data) {
        const msg = data.message || '服务器错误';
        ChatPanel.addLog(msg, 'bad');
        toast(msg, { bad: true, ms: 3000 });
        if (data.fatal) showFatal('对局异常', msg);
    };

    gameClient.onDisconnect = function (info) {
        if (G.ended) return;
        showFatal('连接已断开', info && info.wasConnected
            ? '与游戏服务的连接断开了，本局无法继续。确认服务器仍在运行后，回到大厅重新开局。'
            : '连不上游戏服务。请先运行 game_server.py，再回到大厅开局。');
    };

    function showFatal(title, message) {
        G.ended = true;
        renderAll();
        document.getElementById('endVerdict').className = 'verdict';
        document.getElementById('endVerdict').textContent = '断';
        document.getElementById('endTitle').textContent = title;
        document.getElementById('endMessage').textContent = message;
        document.getElementById('endResult').hidden = true;
        const d = document.getElementById('endModal');
        if (!d.open) d.showModal();
    }

    // ------------------------------------------------------------------ 武将信息 / AI 设置
    function openPlayerInfo(id) {
        const p = playerById(id);
        if (!p) return;
        const hero = p.hero || {};
        const isMe = id === G.meId;
        const identity = p.identity && (isMe || p.identity_revealed) ? (SGS.IDENTITY[p.identity] || {}).name : '未公开';
        const eq = p.equipment || {};
        const eqText = SGS.EQUIP_ORDER.filter(s => eq[s]).map(s => SGS.EQUIP_SLOT[s].name + '：' + eq[s]).join('　') || '无';
        const judgeText = (p.judge_area || []).join('、') || '无';
        document.getElementById('playerInfoTitle').textContent = p.name + ' · ' + (hero.name || p.hero_name || '');
        document.getElementById('playerInfoBody').innerHTML =
            '<div class="info-grid"><div class="hero-frame faction-' + esc(hero.faction || '群') + '">' + SGS.heroImgHTML(hero.id, hero.name) + '</div>' +
            '<div class="info-lines">' +
            '<div class="row">' + SGS.factionSeal(hero.faction) + SGS.identitySeal(p.identity && (isMe || p.identity_revealed) ? p.identity : null) + '<span>' + esc(identity) + '</span></div>' +
            '<div class="row">' + SGS.hpHTML(p.hp, p.max_hp) + '<span class="muted">体力 ' + p.hp + ' / ' + p.max_hp + '</span></div>' +
            '<div>手牌 ' + p.hand_count + ' 张' + (p.alive ? '' : '　<b style="color:var(--bad)">已阵亡</b>') + '</div>' +
            '<div class="muted">装备　' + esc(eqText) + '</div>' +
            '<div class="muted">判定区　' + esc(judgeText) + '</div>' +
            (p.is_ai && p.ai_config ? '<div class="muted">模型　' + esc(p.ai_config.provider + ' / ' + p.ai_config.model) + '</div>' : '') +
            '</div></div>' +
            '<div class="info-skills">' + (hero.skills || []).map(s => '<div class="info-skill"><b>' + esc(s.name) + '</b>' + esc(s.description || '') + '</div>').join('') + '</div>' +
            (p.is_ai ? '<div class="dialog-actions"><button type="button" class="btn" id="infoAiBtn">调整这名 AI 的模型</button></div>' : '');
        const btn = document.getElementById('infoAiBtn');
        if (btn) btn.addEventListener('click', () => { document.getElementById('playerInfoModal').close(); openAISettings(id); });
        const d = document.getElementById('playerInfoModal');
        if (!d.open) d.showModal();
    }

    let providerList = null;
    function fillProviders() {
        const list = (providerList && providerList.length) ? providerList : (window.Protocol ? Protocol.PROVIDERS : []);
        document.getElementById('aiSettingProvider').innerHTML = list.map(p => '<option value="' + esc(p.value) + '">' + esc(p.name) + '</option>').join('');
    }
    function openAISettings(id) {
        const p = playerById(id);
        if (!p || !p.is_ai) return;
        fillProviders();
        const c = p.ai_config || {};
        document.getElementById('aiSettingsTitle').textContent = '调整 ' + p.name;
        document.getElementById('aiSettingPlayerId').value = p.id;
        document.getElementById('aiSettingProvider').value = c.provider || 'deepseek';
        document.getElementById('aiSettingModel').value = c.model || '';
        document.getElementById('aiSettingUrl').value = c.api_url || '';
        document.getElementById('aiSettingKey').value = '';
        document.getElementById('aiSettingTemperature').value = c.temperature === undefined ? 0.8 : c.temperature;
        document.getElementById('aiSettingThinking').checked = !!c.thinking;
        document.getElementById('aiSettingsModal').showModal();
    }
    function saveAISettings(e) {
        e.preventDefault();
        const t = parseFloat(document.getElementById('aiSettingTemperature').value);
        gameClient.send({
            type: Protocol.INBOUND.UPDATE_AI_CONFIG,
            player_id: parseInt(document.getElementById('aiSettingPlayerId').value, 10),
            config: {
                provider: document.getElementById('aiSettingProvider').value,
                model: document.getElementById('aiSettingModel').value.trim(),
                api_url: document.getElementById('aiSettingUrl').value.trim(),
                api_key: document.getElementById('aiSettingKey').value.trim(),
                temperature: Number.isFinite(t) ? t : 0.8,
                thinking: document.getElementById('aiSettingThinking').checked
            }
        });
    }

    function confirmDialog(title, message, okText) {
        return new Promise(resolve => {
            const d = document.createElement('dialog');
            d.className = 'sgs-dialog';
            d.innerHTML = '<div class="frame dialog-body" style="text-align:center"><h2 class="brush gold-text" style="margin:4px 0 8px;font-size:30px">' + esc(title) + '</h2>' +
                '<p class="muted" style="margin:0">' + esc(message) + '</p><div class="dialog-actions" style="justify-content:center">' +
                '<button class="btn cancel" type="button" data-v="0">再想想</button><button class="btn primary" type="button" data-v="1">' + esc(okText) + '</button></div></div>';
            document.body.appendChild(d);
            const done = (v) => { d.close(); d.remove(); resolve(v); };
            d.addEventListener('click', (e) => { const b = e.target.closest('[data-v]'); if (b) done(b.dataset.v === '1'); });
            d.addEventListener('cancel', (e) => { e.preventDefault(); done(false); });
            d.showModal();
        });
    }

    async function quitGame() {
        if (G.ended) { location.href = 'index.html'; return; }
        const yes = await confirmDialog('结束本局？', '本局会记为主动终止，不计入胜负。', '结束对局');
        if (!yes) return;
        document.getElementById('quitBtn').disabled = true;
        gameClient.send({ type: Protocol.INBOUND.END_GAME, reason: '玩家主动结束游戏' });
    }

    // ------------------------------------------------------------------ 启动
    function bindUI() {
        document.getElementById('okBtn').addEventListener('click', onOk);
        document.getElementById('cancelBtn').addEventListener('click', onCancel);
        document.getElementById('endBtn').addEventListener('click', onEnd);
        document.getElementById('quitBtn').addEventListener('click', quitGame);
        document.getElementById('sbtn').addEventListener('click', () => window.openGlobalSettings && window.openGlobalSettings());
        document.getElementById('aiSettingsForm').addEventListener('submit', saveAISettings);
        document.querySelectorAll('dialog [data-close]').forEach(b => b.addEventListener('click', () => b.closest('dialog').close()));
        document.querySelectorAll('dialog.sgs-dialog').forEach(d => d.addEventListener('click', (e) => { if (e.target === d && d.id !== 'endModal') d.close(); }));
        document.getElementById('endModal').addEventListener('cancel', (e) => e.preventDefault());
        window.addEventListener('resize', layoutHand);
        window.addEventListener('global-settings-changed', () => { G.seatSig = {}; renderAll(); });
        document.addEventListener('keydown', (e) => {
            if (e.target.closest('input, textarea, select') || document.querySelector('dialog[open]')) return;
            if (e.key === 'Enter' && !document.getElementById('okBtn').disabled) { e.preventDefault(); onOk(); }
            else if (e.key === 'Escape') onCancel();
        });
        SGS.fetchJSON('/api/providers').then(d => { if (d && d.providers) providerList = d.providers; }).catch(() => {});
    }

    function boot() {
        G.cfg = loadConfig();
        bindUI();
        ChatPanel.init({
            getPlayers: () => G.players,
            getMeId: () => G.meId,
            send: (msg) => {
                if (!gameClient.connected || !gameClient.gameId) return false;
                gameClient.sendChat(msg);
                return true;
            },
            showBubble: showBubble,
            enabled: !G.cfg || !G.cfg.chat || G.cfg.chat.enabled !== false
        });
        if (!G.cfg) {
            showFatal('还没入席', '对局配置不完整，请从大厅重新开局。');
            document.getElementById('endVerdict').textContent = '席';
            return;
        }
        renderAll();
        gameClient.connect();
    }

    // 兼容旧页面的全局入口
    window.openPlayerInfo = openPlayerInfo;
    window.openAISettings = openAISettings;

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
    else boot();
})();
