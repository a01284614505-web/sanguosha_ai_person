// =============================================================================
// 对局页主逻辑
// -----------------------------------------------------------------------------
// 架构铁律：引擎自驱 / 服务器纯消息泵 / 前端纯 UI。
// 本文件只做两件事：
//   1. 把服务器推来的消息渲染成牌桌（座位、手牌、阶段栏、判定框、动画、日志）；
//   2. 在引擎给出的合法候选里采集真人的选择并提交。
// 任何“能不能出 / 能不能选”的判断都来自 your_turn.actions 或 require_response.options，
// 提交后服务器端还会再复核一遍，前端从不自己推断规则。
//
// 收到的消息（见 ws_client.js / protocol.js）：
//   game_state         整份可见状态（含自己的手牌 self_hand、各人判定区 judge_area）
//   your_turn          我的出牌阶段：手牌 + 合法操作列表
//   require_response   场外响应 / 选牌 / 选角色 / 是否
//   event_notification 事件：出牌动画(card_to_discard)、判定(judge)、阶段(phase)、技能发动等
//   ai_action / chat / game_end / error …
// =============================================================================
(function () {
    'use strict';
    const { esc, store, toast } = SGS;
    const SEAT_COUNT = 5;

    // ------------------------------------------------------------------ 页面状态
    // 所有可变状态集中放在 G 里，方便在浏览器控制台用 GameUI 查看调试。
    const G = {
        cfg: null,          // 开局配置（来自大厅，sessionStorage 优先）
        meId: null,         // 真人玩家的座位 id
        state: null,        // 最近一次 game_state
        players: [],        // state.players 的快捷引用
        hand: [],           // 我的手牌（self_hand 或 your_turn.hand）
        turn: null,         // 最近一次 your_turn；只在我的出牌阶段非空
        sel: null,          // 当前选择：{kind:'card', index, action, targets} | {kind:'skill', name, cards, action, targets}
        req: null,          // 当前 require_response
        picked: [],         // req 中已选的候选下标
        reqDeadline: 0,     // 响应倒计时截止时间（毫秒时间戳）
        reqTimer: null,
        prev: {},           // 上一份状态里各人的 {hp, alive}，用于做受伤/回复/阵亡特效
        seatEls: {},        // 对手座位 DOM（按玩家 id）
        seatSig: {},        // 座位内容签名：内容没变就不重绘，避免图片闪烁
        thinking: {},       // 正在思考的 AI（按玩家 id）
        marks: {},          // 我对各座位身份的手动标记（按玩家 id，只存本标签页）
        thoughts: {},       // 作弊模式下各 AI 最近的公开理由（按玩家 id）
        phase: { playerId: null, phase: '', skipped: new Set() },  // 阶段栏
        animQueue: Promise.resolve(),   // 出牌/判定动画串行队列
        ended: false,
        trustee: null,
        idleSince: 0,
        idleWarningTimer: null,
        lastTurnKey: '',    // “轮次:当前玩家”，用于识别换人
        pool: null,         // 正在显示的临时展示池（五谷丰登）；结算结束后保留片刻再收起
        poolTimer: null
    };
    window.GameUI = G;

    // ------------------------------------------------------------------ 配置与小工具
    /** 读取开局配置；缺武将或 AI 数量不对时返回 null（页面会提示回大厅）。 */
    function loadConfig() {
        const cfg = store.sget('gameConfig', null) || store.get('gameConfig', null);
        if (!cfg || !cfg.selected_hero || !cfg.selected_hero.id || !Array.isArray(cfg.ais) || cfg.ais.length !== 4) return null;
        return cfg;
    }

    const settings = () => (window.getGlobalSettings ? getGlobalSettings() : { animation_ms: 1100, show_ai_thinking: true });
    const playerById = (id) => G.players.find(p => p.id === id);
    const playerByName = (name) => G.players.find(p => p.name === name);
    const me = () => playerById(G.meId);
    /** 现在是否轮到我出牌（且没有挂起的响应请求、对局未结束）。 */
    const isMyPlay = () => !!G.turn && !G.req && !G.ended;

    function sfx(name) { if (window.audioManager) audioManager.play(name); }

    // ------------------------------------------------------------------ 座次
    /**
     * 座位相对位置：0 = 我，1 = 下家（右侧），2 = 右上，3 = 左上，4 = 上家（左侧）。
     * 引擎按 id 递增轮转，下家坐在右边，与官方一致。
     */
    function seatPos(id) {
        const n = G.players.length || SEAT_COUNT;
        return ((id - (G.meId || 0)) % n + n) % n;
    }

    /** 某玩家的武将框元素（做特效、画指向线时用）。 */
    function frameEl(id) {
        if (id === G.meId) return document.querySelector('#myHero .hero-frame');
        const seat = G.seatEls[id];
        return seat ? seat.querySelector('.seat-frame') : null;
    }
    /** 某玩家的座位根元素（气泡、受伤闪烁挂在这里）。 */
    function seatRoot(id) {
        return id === G.meId ? document.getElementById('myHero') : G.seatEls[id];
    }

    // ------------------------------------------------------------------ 目标选择
    /**
     * 当前是否处于“点武将选目标”的状态。
     * 返回 {valid:Set<id> 可点的人, chosen:id[] 已选, mode:'play'|'req'}，不在选目标时返回 null。
     *   - mode 'req'：引擎在问“选择角色”（choose_players），可点的人来自候选；
     *   - mode 'play'：我选了一张需要目标的牌/技能，可点的人来自 valid_targets；
     *     借刀杀人（target_count = 2）分两步：先选持武器者，再按 valid_target_pairs 选他要杀的人。
     */
    function currentTargeting() {
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
        if (Array.isArray(a.valid_target_groups)) {
            valid = a.valid_target_groups
                .filter(group => chosen.every((id, i) => group[i] === id) && group.length > chosen.length)
                .map(group => group[chosen.length]);
        } else if (a.target_count === 2) {
            const pairs = a.valid_target_pairs || [];
            if (chosen.length === 0) valid = pairs.map(p => p[0]);
            else if (chosen.length === 1) valid = pairs.filter(p => p[0] === chosen[0]).map(p => p[1]);
        } else if (chosen.length < targetMax()) {
            valid = (a.valid_targets || []).filter(id => !chosen.includes(id));
        }
        return { valid: new Set(valid), chosen, mode: 'play' };
    }

    /** 本次最多/最少选几名目标：来自手牌的 target_rule（如铁索连环可选 1~2 人），技能固定 1 人。 */
    function targetMax() {
        if (!G.sel || !G.sel.action) return 1;
        if (Array.isArray(G.sel.action.valid_target_groups)) {
            return Math.max(1, ...G.sel.action.valid_target_groups.map(group => group.length));
        }
        if (G.sel.kind === 'skill') return 1;
        const rule = (G.hand[G.sel.index] || {}).target_rule || {};
        return Math.max(1, Number(rule.max) || 1);
    }
    function targetMin() {
        if (!G.sel || !G.sel.action) return 1;
        if (Array.isArray(G.sel.action.valid_target_groups)) {
            return Math.min(...G.sel.action.valid_target_groups.map(group => group.length));
        }
        if (G.sel.action.target_count === 2) return 2;
        if (G.sel.kind === 'skill') return 1;
        const rule = (G.hand[G.sel.index] || {}).target_rule || {};
        return Math.max(1, Number(rule.min) || 1);
    }

    /** “确定”按钮是否可点：已选中合法操作，且目标数量满足要求。 */
    function selectionReady() {
        if (!isMyPlay() || !G.sel || !G.sel.action) return false;
        if (!G.sel.action.requires_target) return true;
        if (Array.isArray(G.sel.action.valid_target_groups)) {
            return G.sel.action.valid_target_groups.some(group => group.length === G.sel.targets.length
                && group.every((id, i) => id === G.sel.targets[i]));
        }
        if (G.sel.action.target_count === 2) return G.sel.targets.length === 2;
        return G.sel.targets.length >= targetMin() && G.sel.targets.length <= targetMax();
    }

    /** 点击武将框：选目标时切换选中；否则打开武将信息。 */
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
            // 借刀杀人取消第一步的人时，第二步一并清掉
            if (at >= 0) arr.splice(at, Array.isArray(G.sel.action.valid_target_groups)
                || (at === 0 && G.sel.action.target_count === 2) ? arr.length : 1);
            else {
                const next = arr.concat([id]);
                const groups = G.sel.action.valid_target_groups;
                if (Array.isArray(groups) && !groups.some(group => next.every((target, i) => group[i] === target))) {
                    toast('不能选择这组目标', { bad: true });
                    return;
                }
                arr.push(id);
            }
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
    /** 判定区的延时锦囊小方块（带插画，长按/悬停可看说明）。 */
    function judgeTilesHTML(names) {
        return (names || []).map(name => {
            const art = SGS.cardArtURL(name);
            return '<span class="judge-tile" ' + SGS.cardDetailAttrs({ name: name }) + ' title="' + esc(name) + '">' +
                (art ? '<i style="background-image:url(' + art + ')"></i>' : '') +
                '<b>' + esc(SGS.DELAYED[name] || name.charAt(0)) + '</b></span>';
        }).join('');
    }

    /** 武将框内部：立绘、名字条、势力/身份印、竖排武将名、手牌数、判定区、勾玉、思考中。 */
    function seatFrameHTML(p, opts) {
        opts = opts || {};
        const hero = p.hero || {};
        const isMe = p.id === G.meId;
        const identity = p.identity && (isMe || p.identity_revealed) ? p.identity : null;
        const judge = judgeTilesHTML(p.judge_area);
        const status = G.thinking[p.id] && settings().show_ai_thinking !== false && p.alive
            ? '<div class="s-status thinking">思考中</div>' : '';
        // 身份未公开的座位：问号身份牌可以点开，手动标记“我猜他是谁”（和官方一样，只有自己看得到）。
        let idSeal = SGS.identitySeal(identity);
        if (!identity && !isMe) {
            const m = G.marks[p.id];
            const info = m ? SGS.IDENTITY[m] : null;
            idSeal = '<span class="seal id-mark ' + (info ? 'id-' + m + ' marked' : 'id-unknown') + '" data-mark-seat="' + p.id +
                '" role="button" tabindex="0" title="' + (info ? '你的标记：' + info.name + '（点一下修改）' : '点一下标记身份') + '">' +
                (info ? info.short : '?') + '</span>';
        }
        const cheatPeek = G.state && G.state.cheat_mode && p.is_ai && !isMe
            ? '<button class="cheat-peek" type="button" data-peek-seat="' + p.id + '" title="看这名 AI 的思考" aria-label="看 ' + esc(p.name) + ' 的思考">›</button>' : '';
        return SGS.heroImgHTML(hero.id, hero.name || p.name) +
            '<div class="s-top">' + SGS.factionSeal(hero.faction) + '<span class="s-name">' + esc(p.name) + '</span>' + idSeal + '</div>' + cheatPeek +
            '<div class="s-hero">' + esc((hero.name || p.hero_name || '').replace(/^界/, '')) + '</div>' +
            (opts.hideHand ? '' : '<div class="s-hand" title="手牌数">' + p.hand_count + '</div>') +
            (judge ? '<div class="s-judge">' + judge + '</div>' : '') +
            (p.chained ? '<div class="s-chain" title="横置（铁索连环）：受到属性伤害会传导">连环</div>' : '') +
            '<div class="s-hp">' + SGS.hpHTML(p.hp, p.max_hp, { vertical: true }) + '</div>' + status;
    }

    /** 武将框下方的装备栏（只列出已装备的格子）。 */
    function equipLines(p) {
        const eq = p.equipment || {};
        return SGS.EQUIP_ORDER.filter(slot => eq[slot]).map(slot =>
            '<div class="equip-line" ' + SGS.cardDetailAttrs({ name: eq[slot] }) + '><b>' + SGS.EQUIP_SLOT[slot].short + '</b>' + esc(eq[slot]) + '</div>').join('');
    }

    /** 渲染四名对手。座位 DOM 只建一次，之后按签名增量更新，气泡/特效不会被冲掉。 */
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
                frame.addEventListener('click', (e) => {
                    const mark = e.target.closest('[data-mark-seat]');
                    if (mark) { e.stopPropagation(); openMarkMenu(p.id, mark); return; }
                    const peek = e.target.closest('[data-peek-seat]');
                    if (peek) { e.stopPropagation(); openThoughts(p.id); return; }
                    onSeatClick(p.id);
                });
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
            // 正在播放的受伤/回复动画 class 不能被这次重绘抹掉
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
    /** 左侧装备区与判定区、右侧我的武将框和技能按钮。 */
    function renderMyArea() {
        const p = me();
        const zones = document.getElementById('myZones');
        const heroBox = document.getElementById('myHero');
        if (!p) return;
        const eq = p.equipment || {};
        const judge = p.judge_area || [];
        zones.innerHTML = '<h3>装备区</h3>' + SGS.EQUIP_ORDER.map(slot =>
            '<div class="zone-slot' + (eq[slot] ? '' : ' empty') + '" ' + (eq[slot] ? SGS.cardDetailAttrs({ name: eq[slot] }) : '') + '><b>' +
            SGS.EQUIP_SLOT[slot].short + '</b>' + esc(eq[slot] || SGS.EQUIP_SLOT[slot].name) + '</div>').join('') +
            (p.treasure_count ? '<div class="zone-slot treasure-zone" title="木牛流马扣置的牌不计入手牌"><b>木</b>扣置 ' + p.treasure_count + ' 张</div>' : '') +
            '<div class="zone-judge"><span>判定区</span>' + (judge.length ? judgeTilesHTML(judge) : '<span class="faint">空</span>') + '</div>';

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

        // 技能按钮：引擎给了 use_skill 候选的技能会亮起（ready），正在发动的为 on。
        // 每个按钮都带说明数据，悬停/长按可看技能全文。
        const readySkills = new Set(isMyPlay() ? (G.turn.actions || []).filter(a => a.type === 'use_skill').map(a => a.skill_name) : []);
        const skills = (hero.skills || []).map(s => typeof s === 'string' ? { name: s } : s);
        const skillHTML = skills.map(s => {
            const ready = readySkills.has(s.name);
            const on = G.sel && G.sel.kind === 'skill' && G.sel.name === s.name;
            return '<button type="button" class="skill-btn' + (ready ? ' ready' : '') + (on ? ' on' : '') + '" data-skill="' + esc(s.name) + '"' +
                ' data-skill-name="' + esc(s.name) + '" data-skill-desc="' + esc(s.description || '') + '" data-skill-type="' + esc(s.type || '') + '">' + esc(s.name) + '</button>';
        }).join('');
        const frameHTML = seatFrameHTML(p, { hideHand: true });
        const sig = frameHTML + '|' + skillHTML;
        if (G.seatSig.me !== sig) {
            G.seatSig.me = sig;
            heroBox.innerHTML = '<div class="hero-frame" role="button" tabindex="0" aria-label="我的武将">' + frameHTML + '</div><div class="skill-btns">' + skillHTML + '</div>';
            heroBox.querySelector('.hero-frame').addEventListener('click', () => onSeatClick(p.id));
            heroBox.querySelectorAll('.skill-btn').forEach(b => b.addEventListener('click', () => onSkillClick(b.dataset.skill, b)));
        }
        // 手牌上限以引擎下发为准（含英姿、血裔、清俭等技能修正）；旧服务器没有该字段时才退回体力值。
        const limit = typeof p.hand_limit === 'number' ? p.hand_limit : Math.max(0, p.hp);
        document.getElementById('handCount').textContent = '手牌 ' + G.hand.length + ' / 上限 ' + limit;
    }

    // ------------------------------------------------------------------ 渲染：阶段栏
    /**
     * 顶部阶段栏：准 判 摸 出 弃 结。
     * 引擎每进入一个阶段都会发 event_kind = 'phase' 的事件（含 skipped），这里据此“跳”到对应格子；
     * 已经过的阶段变暗，被跳过的阶段划掉。
     */
    function renderPhaseTrack() {
        const track = document.getElementById('phaseTrack');
        const owner = playerById(G.phase.playerId);
        const curIdx = SGS.PHASE_ORDER.indexOf(G.phase.phase);
        track.querySelector('.pt-owner').textContent = owner ? (owner.id === G.meId ? '你' : owner.name) : '';
        track.querySelectorAll('.pt-step').forEach((el, i) => {
            const key = SGS.PHASE_ORDER[i];
            el.classList.toggle('on', i === curIdx);
            el.classList.toggle('done', curIdx >= 0 && i < curIdx);
            el.classList.toggle('skip', G.phase.skipped.has(key));
            el.setAttribute('aria-current', i === curIdx ? 'step' : 'false');
        });
        track.classList.toggle('mine', !!owner && owner.id === G.meId);
    }

    /** 收到阶段事件：换人时清空跳过记录；切到新阶段时让对应格子弹一下。 */
    function onPhaseEvent(data) {
        if (data.player_id !== G.phase.playerId) {
            G.phase = { playerId: data.player_id, phase: '', skipped: new Set() };
        }
        G.phase.phase = data.phase;
        if (data.skipped) G.phase.skipped.add(data.phase);
        renderPhaseTrack();
        const idx = SGS.PHASE_ORDER.indexOf(data.phase);
        const step = document.querySelectorAll('#phaseTrack .pt-step')[idx];
        if (step) { step.classList.remove('pop'); void step.offsetWidth; step.classList.add('pop'); }
        // 我的回合里每个阶段都在牌桌中央写一下；别人的回合只提示被跳过的阶段
        const mine = data.player_id === G.meId;
        if (data.skipped) flashBanner((mine ? '你' : data.player_name) + ' 跳过' + (SGS.PHASE[data.phase] || ''));
        else if (mine) flashBanner(SGS.PHASE[data.phase] || '');
    }

    /** 牌桌中央的阶段横幅：淡入，停留约 1.2 秒，淡出。 */
    function flashBanner(text) {
        const b = document.getElementById('phaseBanner');
        b.textContent = text;
        b.classList.remove('show');
        void b.offsetWidth;
        b.classList.add('show');
    }

    // ------------------------------------------------------------------ 渲染：手牌
    /** 出牌阶段里，某张手牌对应的合法 play_card 操作（没有就是这张牌现在不能出）。 */
    function playActionFor(index) {
        if (!isMyPlay()) return null;
        return (G.turn.actions || []).find(a => a.type === 'play_card' && a.card_index === index) || null;
    }

    /** 当前技能的全部候选操作（同一技能可能有多种发动方式/多种用牌组合）。 */
    function skillCandidates() {
        if (!isMyPlay() || !G.sel || G.sel.kind !== 'skill') return [];
        return (G.turn.actions || []).filter(a => a.type === 'use_skill' && a.skill_name === G.sel.name);
    }
    const sortedKey = (arr) => (arr || []).slice().sort((a, b) => a - b).join(',');

    /** 技能模式下还能继续选的手牌：在“包含已选牌”的候选组合里出现过的牌。 */
    function skillSelectableCards() {
        const chosen = G.sel.cards;
        const set = new Set();
        skillCandidates().forEach(a => {
            const ci = a.card_indices || [];
            if (chosen.every(i => ci.includes(i))) ci.forEach(i => set.add(i));
        });
        return set;
    }
    /** 与已选牌完全一致的候选组合。 */
    function skillMatches() {
        const key = sortedKey(G.sel.cards);
        return skillCandidates().filter(a => sortedKey(a.card_indices) === key);
    }

    /**
     * 若当前请求的候选全部是“我自己手里的牌”，就直接在手牌上选（与官方一致），不另开候选托盘。
     * 返回 Map(手牌下标 -> 候选下标)；任何不确定的情况（暗牌、他人的牌、同一张牌对应多个候选）返回 null。
     */
    function reqHandMap() {
        const r = G.req;
        if (!r || r.expired) return null;
        if (r.kind === 'choose_players' || r.kind === 'confirm' || r.kind === 'choose_option') return null;
        const requiredZone = r.selection && r.selection.zone;
        if (requiredZone && !['hand', 'treasure'].includes(requiredZone)) return null;
        const byId = new Map(G.hand.map((c, i) => [c.id, i]).filter(([id, i]) => !requiredZone || (G.hand[i] || {}).zone === requiredZone));
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

    /**
     * 渲染手牌。每张牌的状态：
     *   can      可以出 / 可以选（绿边）
     *   dim      现在不能用（压暗）
     *   selected 已选中（上浮 + 金边）
     */
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
            if (c.zone === 'treasure') cls.push('treasure-card');
            let asName = null;
            if (reqMap) {
                // 响应模式：只有候选里的牌可选，并显示技能转化（如“当杀”）
                const oi = reqMap.get(i);
                if (oi === undefined) cls.push('dim');
                else {
                    cls.push(G.picked.includes(oi) ? 'selected' : 'can');
                    asName = (G.req.options[oi] || {}).as_name;
                }
            } else if (isMyPlay()) {
                if (selectable) {
                    // 技能模式
                    if (G.sel.cards.includes(i)) cls.push('selected');
                    else if (selectable.has(i)) cls.push('can');
                    else cls.push('dim');
                } else {
                    // 普通出牌
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

    /** 手牌太多放不下时自动叠起来：按容器宽度算出每张牌的负边距。 */
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

    /** 点手牌：响应模式 → 选候选；技能模式 → 增减用牌；普通出牌 → 选中/取消这张牌。 */
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

    /** 点技能按钮：轮到我且引擎给了候选 → 进入技能模式；否则弹出技能说明。 */
    function onSkillClick(name, btn) {
        if (!isMyPlay()) {
            if (btn) SGS.Detail.show(btn);
            return;
        }
        if (G.sel && G.sel.kind === 'skill' && G.sel.name === name) { G.sel = null; renderAll(); return; }
        const cands = (G.turn.actions || []).filter(a => a.type === 'use_skill' && a.skill_name === name);
        if (!cands.length) {
            if (btn) SGS.Detail.show(btn);
            toast('【' + name + '】现在不能主动发动（锁定技与触发技由引擎自动结算）');
            return;
        }
        G.sel = { kind: 'skill', name: name, cards: [], action: null, targets: [] };
        refreshSkillAction();
        renderAll();
    }

    /** 已选牌恰好对应唯一一种发动方式时自动选定；有多种时留给玩家在操作条里选。 */
    function refreshSkillAction() {
        const matches = skillMatches();
        const keep = G.sel.action && matches.includes(G.sel.action) ? G.sel.action : null;
        G.sel.action = keep || (matches.length === 1 ? matches[0] : null);
        if (!G.sel.action) G.sel.targets = [];
    }

    // ------------------------------------------------------------------ 渲染：操作条
    /** 操作条三种形态：响应请求 / 我的出牌阶段 / 等待（只显示一行提示）。 */
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
        timer.classList.toggle('on', !!G.req || !!G.turn);

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
            // 同一组牌有多种发动方式（如国色：当乐不思蜀 / 弃牌移除乐不思蜀）时，列出来让玩家选
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

    /** 出牌阶段的提示语，随选择进度变化。 */
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

    /** 不是我操作时操作条上的一行字。 */
    function waitingText() {
        const s = G.state;
        if (!s) return '正在连接游戏服务…';
        if (!s.current_name) return '等待开局…';
        const phase = SGS.PHASE[G.phase.playerId === s.current_player_id && G.phase.phase ? G.phase.phase : s.phase] || '';
        if (s.current_player_id === G.meId) return '你的' + phase;
        return s.current_name + ' 的' + phase;
    }

    const REQ_TITLE = { dying: '求桃', wuxie: '无懈可击', respond: '响应', choose_cards: '选牌', choose_players: '选择角色', confirm: '请决定', choose_option: '请选择' };

    /**
     * 渲染响应请求。两种协议：
     *   旧通道（无 selection 字段）：respond / wuxie / dying，单选 + 「不响应」候选；
     *   交互原语（有 selection）：choose_cards / choose_players / confirm / choose_option，
     *     selection 里给出 mode(single|multi)、min、max、zone、cancelable。
     */
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
        const isLegacy = !r.selection;
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
        } else if (poolRequestMap() && G.pool) {
            // 五谷丰登：在展示池面板里点选，操作条只留提示和确定按钮
            opts.innerHTML = '<span class="muted">在上方【五谷丰登】面板中点选一张牌，再按确定（双击可直接确定）</span>';
        } else if (!reqHandMap()) {
            // 候选不全在我手里（他人的牌等）→ 在操作条里列出候选牌
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

    /** 选中/取消一个候选；多选时不超过 max。 */
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
    /** “确定”：响应请求时提交所选候选；出牌阶段时提交所选的牌/技能与目标。 */
    function onOk() {
        if (G.req) {
            if (G.req.expired) return;
            noteHumanActivity();
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
            // 技能：原样提交引擎给的候选对象（引擎按 skill_name / variant / card_indices 复核）
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

    /** “取消 / 不出 / 不救 / 否”。 */
    function onCancel() {
        if (G.req) {
            if (G.req.expired) return;
            noteHumanActivity();
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

    /** “结束出牌”。 */
    function onEnd() {
        if (!isMyPlay()) return;
        noteHumanActivity();
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

    /** 提交响应：单选用 option_index，多选用 option_indices（协议约定）。 */
    function sendResponse(selection) {
        const r = G.req;
        if (!r || r.expired) return;
        noteHumanActivity();
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

    /** 响应倒计时条；时间到了显示“托管代选”，引擎那边会自动按规则托管。 */
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

    // The engine enforces the five-minute watchdog; this client timer only warns 30 seconds ahead.
    function beginIdleWatch() {
        if (G.idleWarningTimer || (G.trustee && G.trustee.enabled) || G.ended) return;
        G.idleSince = Date.now();
        G.idleWarningTimer = setTimeout(() => {
            G.idleWarningTimer = null;
            if (!G.ended && !(G.trustee && G.trustee.enabled)) {
                toast('你已离席约 4 分 30 秒；若继续无操作，对局将在约 30 秒后结束。请进行任意游戏操作或开启托管。', { bad: true, ms: 12000 });
            }
        }, 270000);
    }
    function clearIdleWatch() {
        if (G.idleWarningTimer) clearTimeout(G.idleWarningTimer);
        G.idleWarningTimer = null;
        G.idleSince = 0;
    }
    function noteHumanActivity() { clearIdleWatch(); }

    // ------------------------------------------------------------------ 特效
    function centerOf(el) {
        const r = el.getBoundingClientRect();
        return { x: r.left + r.width / 2, y: r.top + r.height / 2, r: r };
    }

    /** 武将框上飘出的数字（-1 红色 / +1 绿色）。 */
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

    /** 给座位加一次性的动画 class（hurt 受伤抖动 / healed 回复绿光）。 */
    function flash(id, cls) {
        const root = seatRoot(id);
        if (!root) return;
        root.classList.remove(cls);
        void root.offsetWidth;
        root.classList.add(cls);
        setTimeout(() => root.classList.remove(cls), 750);
    }

    /** 技能发动时在头像上写出技能名（书法大字）。 */
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

    /** 聊天气泡：对手座位按方位朝向牌桌中央，我的气泡在头像上方。 */
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

    /** 出牌时从使用者画金线指向目标。 */
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

    /** 飞牌起点：我自己出的牌从手牌位置飞出，别人的从武将框飞出。 */
    function cardSource(data) {
        if (data.actor_id === G.meId && Number.isInteger(data.card_index)) {
            const el = document.querySelector('#hand .card[data-index="' + data.card_index + '"]');
            if (el) return el.getBoundingClientRect();
        }
        const f = frameEl(data.actor_id);
        if (f) return f.getBoundingClientRect();
        return { left: innerWidth / 2 - 30, top: innerHeight / 2 - 40, width: 60, height: 84 };
    }

    /** 把牌放进中央处理区（最多保留 4 张，旧的变淡），下方写“谁 → 谁”。 */
    function putOnTable(data, captionOverride) {
        const box = document.getElementById('tableCards');
        const fig = document.createElement('figure');
        fig.className = 'table-card';
        fig.style.margin = '0';
        let caption = data.actor_name || '';
        if (captionOverride) caption = captionOverride;
        else if (data.reason === 'use' && data.target_name) caption += ' → ' + data.target_name;
        else if (data.reason === 'hand_limit') caption += ' 弃置';
        else if (data.reason && data.reason !== 'use') caption = data.message || caption;
        fig.innerHTML = SGS.cardHTML(data.card || { name: data.card_name }) + '<figcaption title="' + esc(caption) + '">' + esc(caption) + '</figcaption>';
        box.appendChild(fig);
        const all = box.querySelectorAll('.table-card');
        all.forEach((el, i) => el.classList.toggle('old', i < all.length - 1));
        while (box.children.length > 4) box.removeChild(box.firstChild);
        if (Number.isInteger(data.discard_count)) document.getElementById('discardCount').textContent = data.discard_count;
    }

    function clearTable() {
        document.getElementById('tableCards').innerHTML = '';
    }

    /** 告诉服务器“这段动画播完了”，引擎收到后才继续结算（服务器最多等 2.5 秒）。 */
    function ack(data) {
        if (data.animation_id) gameClient.send({ type: Protocol.INBOUND.CARD_ANIMATION_DONE, animation_id: data.animation_id });
    }

    const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    /** 出牌动画：指向线 → 牌从起点飞到处理区 → 落地后 ACK → 稍停再放下一张。 */
    function animateCard(data) {
        return new Promise(resolve => {
            const total = Math.max(300, Number(settings().animation_ms) || 1100);
            if (data.reason === 'use') {
                const ids = String(data.target_name || '').split('、').map(n => (playerByName(n) || {}).id).filter(Number.isInteger);
                aimLines(data.actor_id, ids);
            }
            // 页面在后台或用户要求减少动态：直接落地，立刻 ACK，不拖慢引擎
            if (document.hidden || reducedMotion()) {
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
            holder.innerHTML = SGS.cardHTML(data.card || { name: data.card_name }, { noDetail: true });
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
                setTimeout(resolve, Math.round(total * 0.25));
            }, flyMs);
        });
    }

    /**
     * 判定框：牌桌中央弹出“【乐不思蜀】判定”，牌背翻成判定牌，再盖“生效 / 失效”印。
     * 印盖下后立即 ACK（服务器 2.5 秒超时内），判定框再停留片刻后淡出，判定牌留在处理区。
     */
    function animateJudge(data) {
        return new Promise(resolve => {
            const owner = data.actor_id === G.meId ? '你' : (data.actor_name || '');
            const verdict = data.effective === true ? '生效' : (data.effective === false ? '失效' : '');
            ChatPanel.addLog(data.message || (owner + '进行判定'), data.effective ? 'important' : '');
            const finish = () => {
                putOnTable(data, owner + ' 判定' + (verdict ? '·' + verdict : ''));
                ack(data);
            };
            if (document.hidden || reducedMotion()) { finish(); resolve(); return; }

            const layer = document.getElementById('fxLayer');
            const box = document.createElement('div');
            box.className = 'judge-box';
            box.innerHTML =
                '<div class="jb-title"><b>【' + esc(data.judge_for || '判定') + '】</b>判定 · ' + esc(owner) + '</div>' +
                '<div class="jb-flip"><div class="jb-inner">' +
                '<div class="jb-face jb-back">' + SGS.cardHTML(null, { back: true }) + '</div>' +
                '<div class="jb-face jb-front">' + SGS.cardHTML(data.card || { name: data.card_name }) + '</div>' +
                '</div></div>' +
                (verdict ? '<div class="jb-verdict ' + (data.effective ? 'hit' : 'miss') + '">' + verdict + '</div>' : '') +
                (data.result_text ? '<div class="jb-text">' + esc(data.result_text) + '</div>' : '');
            layer.appendChild(box);
            sfx('judge');
            // 0.35s 后翻牌，0.95s 盖印并 ACK，2.1s 淡出
            setTimeout(() => box.classList.add('flipped'), 350);
            setTimeout(() => { box.classList.add('stamped'); finish(); }, 950);
            setTimeout(() => box.classList.add('leaving'), 2100);
            setTimeout(() => { box.remove(); resolve(); }, 2450);
        });
    }

    /**
     * 摸牌动画：牌从中央牌堆飞向摸牌者。自己摸的看得到牌面，别人摸的只显示牌背。
     * 落到位后 ACK，引擎再继续结算（和出牌动画同一条队列，顺序一致）。
     */
    function animateDraw(data) {
        return new Promise(resolve => {
            ChatPanel.addLog(data.message || ((data.actor_name || '角色') + '摸了' + (data.count || 0) + '张牌'));
            if (Number.isInteger(data.deck_count)) document.getElementById('dc').textContent = data.deck_count;
            const count = Math.max(1, Math.min(6, Number(data.count) || 1));
            if (document.hidden || reducedMotion()) { ack(data); resolve(); return; }
            const pile = document.getElementById('tableCards').getBoundingClientRect();
            const isMe = data.actor_id === G.meId;
            const destEl = isMe ? document.getElementById('hand') : frameEl(data.actor_id);
            if (!destEl) { ack(data); resolve(); return; }
            const dest = destEl.getBoundingClientRect();
            const w = parseFloat(getComputedStyle(document.getElementById('battle')).getPropertyValue('--hand-w')) || 72;
            const faces = Array.isArray(data.cards) ? data.cards : [];
            const startX = pile.left + pile.width / 2 - w / 2;
            const startY = pile.top + pile.height / 2 - w * 0.7;
            const flyMs = 420, gap = 90;
            for (let i = 0; i < count; i++) {
                const holder = document.createElement('div');
                holder.className = 'flying-card';
                holder.innerHTML = faces[i] ? SGS.cardHTML(faces[i], { noDetail: true }) : SGS.cardHTML(null, { back: true });
                const cardEl = holder.firstChild;
                cardEl.style.setProperty('--w', (isMe ? w : w * 0.7) + 'px');
                holder.style.left = startX + 'px';
                holder.style.top = startY + 'px';
                holder.style.opacity = '0';
                document.body.appendChild(holder);
                const offset = (i - (count - 1) / 2) * (isMe ? w * 0.55 : 10);
                const tx = dest.left + dest.width / 2 - w / 2 + offset - startX;
                const ty = dest.top + dest.height / 2 - w * 0.7 - startY;
                holder.animate([
                    { transform: 'translate(0,0) scale(.85)', opacity: 0 },
                    { transform: 'translate(0,-6px) scale(.95)', opacity: 1, offset: .2 },
                    { transform: 'translate(' + tx + 'px,' + ty + 'px) scale(' + (isMe ? 1 : .8) + ')', opacity: .9 }
                ], { duration: flyMs, delay: i * gap, easing: 'cubic-bezier(.25,.8,.25,1)', fill: 'forwards' });
                setTimeout(() => holder.remove(), flyMs + i * gap + 30);
            }
            sfx('card');
            setTimeout(() => { ack(data); resolve(); }, flyMs + (count - 1) * gap);
        });
    }

    // ------------------------------------------------------------------ 身份标记
    function marksKey() { return 'idMarks:' + (gameClient.gameId || (store.sget('activeGame', {}) || {}).game_id || ''); }
    function loadMarks() { G.marks = store.sget(marksKey(), {}) || {}; }
    function saveMarks() { store.sset(marksKey(), G.marks); }

    /** 点问号身份牌弹出小菜单：忠 / 反 / 内 / 清除。标记只存在本标签页，不发给服务器。 */
    function openMarkMenu(id, anchor) {
        closeMarkMenu();
        const menu = document.createElement('div');
        menu.className = 'mark-menu';
        menu.id = 'markMenu';
        const opts = [['loyalist', '忠'], ['rebel', '反'], ['spy', '内']];
        menu.innerHTML = opts.map(([key, label]) =>
            '<button type="button" class="seal id-' + key + (G.marks[id] === key ? ' on' : '') + '" data-mark="' + key + '" title="标记为' + SGS.IDENTITY[key].name + '">' + label + '</button>').join('') +
            '<button type="button" class="mark-clear" data-mark="">清除</button>';
        document.body.appendChild(menu);
        const r = anchor.getBoundingClientRect();
        const mw = menu.offsetWidth, mh = menu.offsetHeight;
        menu.style.left = Math.max(6, Math.min(innerWidth - mw - 6, r.left + r.width / 2 - mw / 2)) + 'px';
        menu.style.top = (r.bottom + 6 + mh > innerHeight ? r.top - mh - 6 : r.bottom + 6) + 'px';
        menu.addEventListener('click', (e) => {
            const b = e.target.closest('[data-mark]');
            if (!b) return;
            if (b.dataset.mark) G.marks[id] = b.dataset.mark; else delete G.marks[id];
            saveMarks();
            closeMarkMenu();
            G.seatSig = {};
            renderSeats();
        });
        setTimeout(() => document.addEventListener('pointerdown', onMarkOutside, true), 0);
    }
    function onMarkOutside(e) { if (!e.target.closest('#markMenu')) closeMarkMenu(); }
    function closeMarkMenu() {
        const m = document.getElementById('markMenu');
        if (m) m.remove();
        document.removeEventListener('pointerdown', onMarkOutside, true);
    }

    // ------------------------------------------------------------------ 战报快捷入口与作弊模式
    /** 有 AI 在思考时显示“战报 ›”快捷按钮。 */
    function updatePeekLog() {
        const btn = document.getElementById('peekLog');
        if (!btn) return;
        btn.hidden = !Object.keys(G.thinking).some(id => G.thinking[id]) || G.ended;
    }

    /** 作弊模式：看某个 AI 最近的思考（只有模型主动给出的公开理由，不含手牌与隐藏身份）。 */
    function openThoughts(id) {
        const p = playerById(id);
        if (!p) return;
        let dlg = document.getElementById('thoughtsModal');
        if (!dlg) {
            dlg = document.createElement('dialog');
            dlg.className = 'sgs-dialog';
            dlg.id = 'thoughtsModal';
            dlg.innerHTML = '<div class="frame dialog-body"><div class="dialog-head"><h2 id="thoughtsTitle"></h2>' +
                '<button class="icon-btn" type="button" data-close aria-label="关闭">×</button></div><div class="thought-list" id="thoughtsBody"></div>' +
                '<div class="dialog-actions"><button class="btn" type="button" id="thoughtsToLog">在战报里看全部</button></div></div>';
            document.body.appendChild(dlg);
            dlg.querySelector('[data-close]').addEventListener('click', () => dlg.close());
            dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); });
            dlg.querySelector('#thoughtsToLog').addEventListener('click', () => { dlg.close(); ChatPanel.open('log'); });
        }
        const KIND = { play: '出牌', response: '响应', confirm: '是否发动', choose_cards: '选牌', choose_players: '选人', choose_option: '选项' };
        const tidy = (c) => /^\[[\d, ]*\]$/.test(String(c || '')) ? '' : String(c || '').replace(/，合法目标(对)?=\[[^\]]*\]/g, '');
        const list = (G.thoughts[id] || []).slice(-12).reverse().map(t => Object.assign({}, t, { kind: KIND[t.kind] || t.kind, choice: tidy(t.choice) }));
        dlg.querySelector('#thoughtsTitle').textContent = p.name + ' 的思考';
        dlg.querySelector('#thoughtsBody').innerHTML = list.length
            ? list.map(t => '<div class="thought"><small>第 ' + esc(String(t.round || '-')) + ' 轮 · ' + esc(t.kind || '') +
                (t.model ? ' · ' + esc(t.model) : '') + '</small><p>' + esc(t.reason) + '</p>' +
                (t.choice ? '<small class="faint">→ ' + esc(t.choice) + '</small>' : '') + '</div>').join('')
            : '<p class="muted">这名 AI 还没有给出理由。没填 API Key 的规则 AI 不会有理由。</p>';
        dlg.showModal();
    }

    /** 出牌与判定共用一条队列，保证顺序与引擎结算一致。 */
    function enqueue(fn, data) {
        G.animQueue = G.animQueue.then(() => fn(data)).catch(err => { console.error('动画失败', err); ack(data); });
    }

    // ------------------------------------------------------------------ 状态差异 → 特效
    /** 对比前后两份状态：体力下降 → 受伤；上升 → 回复；存活变阵亡 → 阵亡提示。 */
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
    }

    function renderAll() {
        renderHUD();
        renderPhaseTrack();
        renderSeats();
        renderMyArea();
        renderHand();
        renderActionBar();
        renderShownPool();
    }

    // ------------------------------------------------------------------ 五谷丰登展示池
    // 亮出的牌全桌可见：谁取走了哪张、轮到谁挑都由引擎在 state.shown_pool 里下发。
    // 轮到我时，在面板里直接点牌；提交仍走 require_response 的候选下标，服务器会复核。

    /** 当前请求是不是“从展示池里挑一张”；是则返回 {slot: 候选下标}。 */
    function poolRequestMap() {
        const r = G.req;
        const slots = r && r.context && Array.isArray(r.context.pool_slots) ? r.context.pool_slots : null;
        if (!slots || r.expired) return null;
        const map = {};
        slots.forEach((slot, i) => { map[slot] = i; });
        return map;
    }

    /** 收到新状态时更新面板数据：池子消失后保留最后一帧 1.6 秒，让人看清最后一张被谁拿走。 */
    function syncShownPool(s) {
        const pool = s && s.shown_pool;
        if (pool) {
            clearTimeout(G.poolTimer);
            G.poolTimer = null;
            G.pool = Object.assign({}, pool, { closing: false });
            return;
        }
        if (G.pool && !G.pool.closing) {
            G.pool = Object.assign({}, G.pool, { closing: true, current_id: null });
            clearTimeout(G.poolTimer);
            G.poolTimer = setTimeout(() => { G.pool = null; G.poolTimer = null; renderShownPool(); }, 1600);
        }
    }

    function renderShownPool() {
        const el = document.getElementById('shownPool');
        if (!el) return;
        const pool = G.pool;
        if (!pool || !Array.isArray(pool.cards) || !pool.cards.length) {
            el.hidden = true;
            el.innerHTML = '';
            return;
        }
        const pick = poolRequestMap();
        const current = pool.current_id != null ? playerById(pool.current_id) : null;
        let status;
        if (pool.closing) status = '分配完毕';
        else if (pick) status = '轮到你挑选：点一张牌';
        else if (current) status = '轮到 ' + esc(current.name) + ' 挑选';
        else status = '亮出牌堆顶 ' + pool.cards.length + ' 张';
        const left = pool.cards.filter(c => c.picked_by == null).length;
        el.innerHTML =
            '<header class="sp-head"><b>【' + esc(pool.title || '五谷丰登') + '】</b>' +
            '<span>' + esc(pool.source_name || '') + ' 使用</span>' +
            '<span class="sp-status' + (pick ? ' mine' : '') + '">' + status + '</span>' +
            (pool.closing ? '' : '<span class="sp-left">剩 ' + left + ' 张</span>') + '</header>' +
            '<div class="sp-cards">' + pool.cards.map(entry => {
                const taken = entry.picked_by != null;
                const optIndex = pick && !taken ? pick[entry.slot] : undefined;
                const selectable = optIndex !== undefined;
                const chosen = selectable && G.picked.includes(optIndex);
                const cls = ['sp-card'];
                if (taken) cls.push('taken');
                if (taken && entry.picked_by === G.meId) cls.push('mine');
                if (selectable) cls.push('selectable');
                if (chosen) cls.push('chosen');
                const who = taken ? (entry.picked_by === G.meId ? '你' : esc(entry.picked_name || '')) + ' 取走' : (selectable ? '可选' : '待取');
                const attrs = selectable
                    ? 'data-pool-opt="' + optIndex + '" role="button" tabindex="0" aria-pressed="' + chosen + '"'
                    : '';
                return '<figure class="' + cls.join(' ') + '" ' + attrs + '>' +
                    SGS.cardHTML(entry.card, {}) + '<figcaption>' + who + '</figcaption></figure>';
            }).join('') + '</div>';
        el.hidden = false;
        el.querySelectorAll('[data-pool-opt]').forEach(node => {
            const i = Number(node.dataset.poolOpt);
            node.addEventListener('click', () => togglePick(i));
            node.addEventListener('dblclick', () => { G.picked = [i]; submitPicked(); });
            node.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); togglePick(i); }
            });
        });
    }

    // ------------------------------------------------------------------ 消息处理
    /** 连上服务器后立刻用大厅配置开局。 */
    gameClient.onConnect = function () {
        // 本标签页已有进行中的对局（刷新页面、断线后自动重连）：接回原局，不重新开局。
        const active = store.sget('activeGame', null);
        if (active && active.game_id && active.profile_id && !G.ended) {
            ChatPanel.addLog('已连上游戏服务，正在接回对局…');
            gameClient.resumeGame(active.game_id, active.profile_id);
            return;
        }
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

    /** 开局成功：身份卡已由服务端校验并扣除。 */
    gameClient.onGameCreated = function (data) {
        gameClient.autoReconnect = true;
        if (data && data.game_id && data.profile_id) {
            store.sset('activeGame', { game_id: data.game_id, profile_id: data.profile_id });
        }
        loadMarks();
        if (G.cfg.identity_card && G.cfg.identity_card.use) {
            delete G.cfg.identity_card;
            store.sset('gameConfig', G.cfg);
            ChatPanel.addLog('已使用一张身份卡');
        }
        sfx('click');
    };

    /** 整份状态更新。 */
    gameClient.onStateUpdate = function (s) {
        const prevMap = G.prev;
        G.state = s;
        G.players = s.players || [];
        syncShownPool(s);
        const human = G.players.find(p => !p.is_ai) || G.players.find(p => p.id === 0);
        if (human) G.meId = human.id;
        renderTrusteeStatus();
        // 手牌换了（摸牌、被拆等）时，原来的选择作废
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
        // 换人：清空处理区，写一行“—— X 的回合 ——”
        const turnKey = s.round + ':' + s.current_player_id;
        if (turnKey !== G.lastTurnKey) {
            G.lastTurnKey = turnKey;
            clearTable();
            if (s.current_name) ChatPanel.addLog('—— ' + (s.current_player_id === G.meId ? '你' : s.current_name) + ' 的回合 ——', 'turn');
        }
        // 兜底：老版本服务器没有阶段事件时，用状态里的 phase 驱动阶段栏
        if (s.current_player_id != null && (G.phase.playerId !== s.current_player_id || !G.phase.phase)) {
            G.phase = { playerId: s.current_player_id, phase: s.phase, skipped: new Set() };
        }
        G.prev = {};
        G.players.forEach(p => { G.prev[p.id] = { hp: p.hp, alive: p.alive }; });
        renderAll();
        applyStateEffects(prevMap);
    };

    /** 轮到我出牌：保存合法操作，重置选择。 */
    gameClient.onYourTurn = function (data) {
        const fresh = !G.turn;
        G.turn = data;
        G.hand = data.hand || G.hand;
        G.sel = null;
        renderAll();
        if (fresh) sfx('click');
        beginIdleWatch();
        startTurnTimer(data.timeout);
    };

    gameClient.onActionResult = function (receipt) {
        // 服务器回执是对象 {status, success, message}；旧写法把整个对象当布尔值，拒绝从来不会提示。
        const status = receipt && receipt.status;
        const rejected = receipt === false || (receipt && receipt.success === false
            && status !== 'duplicate' && status !== 'game_ended');
        if (rejected) {
            const msg = (receipt && receipt.message) || '操作没有生效，请重新选择';
            toast(msg, { bad: true });
            ChatPanel.addLog('上一步操作未生效：' + msg, 'bad');
        }
    };

    /** 场外响应 / 选择请求：开倒计时；手机上若开着聊天抽屉就先收起，免得挡住操作。 */
    gameClient.onRequireResponse = function (data) {
        G.req = data;
        G.picked = [];
        beginIdleWatch();
        startRequestTimer(data.timeout);
        renderAll();
        sfx('click');
        if (ChatPanel.isDrawer() && ChatPanel.isOpen()) ChatPanel.close();
    };

    gameClient.onChat = function (data) {
        ChatPanel.addMessage(data);
    };

    /** 各类事件分发。 */
    gameClient.onEventNotification = function (data) {
        switch (data.event_kind) {
            case 'card_to_discard':
                ChatPanel.addLog(data.message || ((data.actor_name || '角色') + '使用【' + (data.card_name || '') + '】'));
                enqueue(animateCard, data);
                return;
            case 'judge':
                enqueue(animateJudge, data);
                return;
            case 'draw':
                enqueue(animateDraw, data);
                return;
            case 'phase':
                onPhaseEvent(data);
                return;
            case 'skill_activation':
                ChatPanel.addLog(data.message || ((data.actor_name || '角色') + '发动【' + data.skill_name + '】'));
                if (Number.isInteger(data.actor_id)) skillShout(data.actor_id, data.skill_name || '');
                return;
            default:
                if (data.message) {
                    ChatPanel.addLog(data.message, data.important ? 'important' : (data.trustee ? 'bad' : ''));
                    if (data.trustee && data.player_id === G.meId) toast(data.message);
                }
        }
    };

    gameClient.onTrusteeStatus = function (status) {
        G.trustee = status || null;
        if (status && status.enabled) clearIdleWatch();
        else if (G.turn || G.req) beginIdleWatch();
        renderTrusteeStatus();
    };

    gameClient.onDecisionTrace = function (trace) {
        // 作弊模式：AI 的公开理由进思考列表，并写进战报。
        if (trace.cheat && trace.reason && Number.isInteger(trace.player_id) && trace.player_id !== G.meId) {
            const arr = G.thoughts[trace.player_id] || (G.thoughts[trace.player_id] = []);
            arr.push({ round: G.state ? G.state.round : null, kind: trace.kind, model: trace.model, reason: trace.reason, choice: trace.final_choice });
            if (arr.length > 60) arr.shift();
            const who = playerById(trace.player_id);
            ChatPanel.addLog('💭 ' + (who ? who.name : '') + '：' + trace.reason, 'think');
        }
        if (settings().show_decision_trace === false) return;
        const list = document.getElementById('decisionTraceList');
        const panel = document.getElementById('decisionTracePanel');
        const count = document.getElementById('decisionTraceCount');
        if (!list || !panel) return;
        const summary = document.createElement('summary');
        const row = document.createElement('details');
        row.className = 'decision-trace-row';
        const player = playerById(trace.player_id);
        const name = player ? player.name : ('角色 ' + trace.player_id);
        const kind = trace.kind || '决策';
        const model = trace.model ? ' · ' + trace.model : '';
        summary.textContent = name + ' · ' + kind + model;
        row.appendChild(summary);
        const full = document.createElement('div');
        full.className = 'decision-trace-full';
        const facts = [
            ['理由', trace.reason], ['最终选择', trace.final_choice],
            ['校验', trace.validation], ['来源', trace.source],
            ['候选数', trace.candidate_count], ['候选概览', trace.candidate_summary],
            ['世界书规则', trace.worldbook_hits],
            ['耗时', Number.isFinite(trace.elapsed_ms) ? trace.elapsed_ms + ' ms' : null]
        ];
        full.textContent = facts.filter(([, value]) => value !== undefined && value !== null && value !== '')
            .map(([label, value]) => label + '：' + (typeof value === 'object' ? JSON.stringify(value) : String(value)))
            .join('\n');
        row.appendChild(full);
        list.prepend(row);
        while (list.children.length > 100) list.lastElementChild.remove();
        count.textContent = String(list.children.length);
        panel.hidden = settings().show_decision_trace === false;
    };

    /** AI 的回合事件：思考中提示、思考摘要。 */
    gameClient.onAIAction = function (data) {
        const p = playerByName(data.player_name);
        if (data.action === 'thinking_start' && p) {
            G.thinking[p.id] = true;
            renderSeats();
            updatePeekLog();
        } else if (data.action === 'thinking_end' && p) {
            G.thinking[p.id] = false;
            renderSeats();
            updatePeekLog();
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

    /** 对局结束：保存结算快照（结算页读取）、更新本机战绩与身份卡、弹出胜负印。 */
    gameClient.onGameEnd = function (data) {
        G.ended = true;
        gameClient.autoReconnect = false;
        store.sset('activeGame', null);
        setReconnectBanner('');
        G.turn = null; G.sel = null;
        if (G.req) { G.req = null; clearInterval(G.reqTimer); }
        const state = data.state || G.state || {};
        if (data.state) { G.state = data.state; G.players = data.state.players || G.players; syncShownPool(data.state); }
        const winner = data.winner;
        const decided = ['lord', 'rebel', 'spy'].includes(winner);
        const result = {
            winner: winner,
            message: data.message,
            total_rounds: state.round || 0,
            duration: data.duration || 0,
            player_identity: data.player_identity || '未知',
            player_id: G.meId,
            player_won: data.player_won === true,
            mvp: data.mvp || null,
            stats: data.stats || null,
            players: state.players || [],
            profile: data.profile || null,
            reward: data.reward || null,
            history_error: data.history_error || null,
            game_id: gameClient.gameId || ((store.sget('activeGame', {}) || {}).game_id) || null,
            log_saved: data.log_saved === true,
            cheat: data.cheat === true
        };
        store.set('gameResult', result);
        updatePeekLog();
        renderAll();
        const verdict = document.getElementById('endVerdict');
        verdict.className = 'verdict ' + (decided ? (result.player_won ? 'win' : 'lose') : '');
        verdict.textContent = decided ? (result.player_won ? '胜' : '败') : '终';
        document.getElementById('endTitle').textContent = decided ? (result.player_won ? '旗开得胜' : '惜败一局') : '对局结束';
        const winText = SGS.WINNER[winner] ? (decided ? SGS.WINNER[winner] + '获胜' : '') : '';
        document.getElementById('endMessage').textContent = [winText, winner === 'aborted' || winner === 'draw' ? data.message : ''].filter(Boolean).join('。') || data.message || '';
        document.getElementById('endResult').hidden = false;
        ChatPanel.addLog(data.message || '对局结束', 'important');
        sfx(decided ? (result.player_won ? 'win' : 'lose') : 'click');
        // 稍等动画收尾再弹窗，让玩家看到最后一张牌
        setTimeout(() => { const d = document.getElementById('endModal'); if (!d.open) d.showModal(); }, 900);
    };

    gameClient.onError = function (data) {
        const msg = data.message || '服务器错误';
        ChatPanel.addLog(msg, 'bad');
        toast(msg, { bad: true, ms: 3000 });
        if (data.fatal) showFatal('对局异常', msg);
    };

    /** 断线：服务器会把对局保留 5 分钟，这里自动重连；超过 5 分钟仍连不上才判定本局结束。 */
    const RECONNECT_GIVE_UP_MS = 5 * 60 * 1000;
    gameClient.onDisconnect = function (info) {
        if (G.ended) return;
        if (!gameClient.autoReconnect) {
            showFatal('连不上游戏服务', '请先运行 game_server.py，再回到大厅开局。');
            return;
        }
        if (!G.disconnectedAt) G.disconnectedAt = Date.now();
        // 断线期间的倒计时与选择都作废，重连后服务器会重新下发仍在等待的提示。
        G.turn = null; G.sel = null;
        if (G.req) { G.req = null; clearInterval(G.reqTimer); }
        clearIdleWatch();
        renderAll();
        if (Date.now() - G.disconnectedAt > RECONNECT_GIVE_UP_MS) {
            gameClient.autoReconnect = false;
            store.sset('activeGame', null);
            setReconnectBanner('');
            showFatal('连接已断开', '超过 5 分钟没能重新连上，本局已按离席处理。回到大厅可以重新开局。');
            return;
        }
        setReconnectBanner('断线重连中…对局保留 5 分钟');
    };

    gameClient.onReconnecting = function (info) {
        if (G.ended) return;
        setReconnectBanner('断线重连中（第 ' + info.attempt + ' 次）…对局保留 5 分钟');
    };

    gameClient.onGameResumed = function (data) {
        G.disconnectedAt = 0;
        loadMarks();
        gameClient.autoReconnect = !data.finished;
        setReconnectBanner('');
        G.turn = null; G.sel = null;
        if (G.req) { G.req = null; clearInterval(G.reqTimer); }
        renderAll();
        if (!data.finished) {
            ChatPanel.addLog('已重新连上，对局继续', 'important');
            toast('已重新连上，对局继续');
        }
    };

    gameClient.onResumeFailed = function (data) {
        gameClient.autoReconnect = false;
        store.sset('activeGame', null);
        setReconnectBanner('');
        showFatal('对局已结束', (data && data.message) || '这局已经不在服务器上了，回到大厅可以重新开局。');
    };

    function setReconnectBanner(text) {
        let bar = document.getElementById('reconnectBanner');
        if (!text) { if (bar) bar.hidden = true; return; }
        if (!bar) {
            bar = document.createElement('div');
            bar.id = 'reconnectBanner';
            bar.className = 'reconnect-banner';
            bar.setAttribute('role', 'status');
            document.body.appendChild(bar);
        }
        bar.textContent = text;
        bar.hidden = false;
    }

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
    /** 武将信息弹窗：身份、体力、手牌数、装备与判定区（含说明）、全部技能。 */
    function openPlayerInfo(id) {
        const p = playerById(id);
        if (!p) return;
        const hero = p.hero || {};
        const isMe = id === G.meId;
        const identity = p.identity && (isMe || p.identity_revealed) ? (SGS.IDENTITY[p.identity] || {}).name : '未公开';
        const eq = p.equipment || {};
        const eqItems = SGS.EQUIP_ORDER.filter(s => eq[s]).map(s => {
            const info = SGS.CARD_INFO[eq[s]] || {};
            return '<div class="info-skill"><b>' + esc(eq[s]) + '</b><small class="muted">' + SGS.EQUIP_SLOT[s].name + (info.range ? ' · 攻击范围 ' + info.range : '') + '</small><br>' + esc(info.text || '') + '</div>';
        }).join('');
        const judgeItems = (p.judge_area || []).map(n => '<div class="info-skill"><b>' + esc(n) + '</b>' + esc((SGS.CARD_INFO[n] || {}).text || '') + '</div>').join('');
        const markNames = { pao_tokens: '咆哮次数', hand_limit_bonus: '额外手牌上限', rende_count: '仁德已给牌', cannot_use_hand: '禁用手牌', nonlocked_disabled: '非锁定技失效' };
        const marks = Object.entries(p.marks || {}).filter(([key, value]) => markNames[key] && (value === true || (Number.isFinite(value) && value !== 0)))
            .map(([key, value]) => '<span class="status-mark">' + esc(markNames[key]) + (value === true ? '' : '：' + esc(String(value))) + '</span>').join('');
        document.getElementById('playerInfoTitle').textContent = p.name + ' · ' + (hero.name || p.hero_name || '');
        document.getElementById('playerInfoBody').innerHTML =
            '<div class="info-grid"><div class="hero-frame faction-' + esc(hero.faction || '群') + '">' + SGS.heroImgHTML(hero.id, hero.name) + '</div>' +
            '<div class="info-lines">' +
            '<div class="row">' + SGS.factionSeal(hero.faction) + SGS.identitySeal(p.identity && (isMe || p.identity_revealed) ? p.identity : null) + '<span>' + esc(identity) + '</span></div>' +
            '<div class="row">' + SGS.hpHTML(p.hp, p.max_hp) + '<span class="muted">体力 ' + p.hp + ' / ' + p.max_hp + '</span></div>' +
            '<div>手牌 ' + p.hand_count + ' 张' + (p.treasure_count ? '　木牛扣置 ' + p.treasure_count + ' 张' : '') + (p.alive ? '' : '　<b style="color:var(--bad)">已阵亡</b>') + '</div>' +
            (p.is_ai && p.ai_config ? '<div class="muted">模型　' + (p.ai_config.rule_ai
                ? '规则 AI（未填 Key，不调用模型）'
                : esc(p.ai_config.provider + ' / ' + p.ai_config.model)) + '</div>' : '') +
            (marks ? '<div class="player-marks" aria-label="公开状态标记">' + marks + '</div>' : '') +
            '</div></div>' +
            '<h3 class="info-h">武将技能</h3><div class="info-skills">' + (hero.skills || []).map(s =>
                '<div class="info-skill"><b>' + esc(s.name) + '</b>' + (SGS.SKILL_TAG[s.type] && s.type !== 'trigger' ? '<small class="muted">' + SGS.SKILL_TAG[s.type] + '</small><br>' : '') + esc(s.description || '') + '</div>').join('') + '</div>' +
            (eqItems ? '<h3 class="info-h">装备</h3><div class="info-skills">' + eqItems + '</div>' : '') +
            (judgeItems ? '<h3 class="info-h">判定区</h3><div class="info-skills">' + judgeItems + '</div>' : '') +
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
        const trustee = document.getElementById('trusteeProvider');
        if (trustee) trustee.innerHTML = list.map(p => '<option value="' + esc(p.value) + '">' + esc(p.name) + '</option>').join('');
    }

    function trusteeSourceChanged() {
        const source = document.getElementById('trusteeSource').value;
        document.getElementById('trusteeCopyRow').hidden = source !== 'copy_ai';
        document.getElementById('trusteeCustomFields').hidden = source !== 'custom';
    }
    function renderTrusteeStatus() {
        const status = G.trustee || (G.state && G.state.trustee) || null;
        const indicator = document.getElementById('trusteeIndicator');
        const text = document.getElementById('trusteeStatusText');
        if (!indicator || !text) return;
        indicator.hidden = !(status && status.enabled);
        if (!status || !status.enabled) { text.textContent = '未开启托管'; return; }
        const sources = { rules: '规则托管', default: '默认模型', copy_ai: '复制 AI', custom: '自定义模型' };
        const degraded = status.degraded ? ' · 已降级为规则托管' : '';
        const degradedReason = status.degrade_reason === 'missing_api_key' ? '（大厅第一席未配置 Key）' :
            status.degrade_reason === 'three_failures' ? '（模型连续失败 3 次）' : '';
        const model = status.model ? ' · ' + status.model : '';
        const failures = status.failures ? ' · 连续失败 ' + status.failures + ' 次' : '';
        text.textContent = (sources[status.source] || '已托管') + model + failures + degraded + degradedReason;
        indicator.textContent = '托管中';
    }
    function openTrusteeDialog() {
        fillProviders();
        const source = document.getElementById('trusteeSource');
        const ai = document.getElementById('trusteeCopyPlayer');
        ai.innerHTML = G.players.filter(p => p.is_ai).map(p => '<option value="' + p.id + '">' + esc(p.name) + '</option>').join('');
        trusteeSourceChanged();
        renderTrusteeStatus();
        document.getElementById('trusteeModal').showModal();
    }
    function saveTrustee(e) {
        e.preventDefault();
        const source = document.getElementById('trusteeSource').value;
        let config;
        if (source === 'custom') {
            const apiKey = document.getElementById('trusteeKey').value.trim();
            if (!apiKey) { toast('请输入自定义托管的 API Key', { bad: true }); return; }
            config = { provider: document.getElementById('trusteeProvider').value,
                model: document.getElementById('trusteeModel').value.trim(),
                api_url: document.getElementById('trusteeUrl').value.trim(), api_key: apiKey };
        }
        const playerId = source === 'copy_ai' ? Number(aiValue()) : undefined;
        gameClient.setTrustee(true, source, playerId, config);
        document.getElementById('trusteeKey').value = '';
        document.getElementById('trusteeModal').close();
    }
    function aiValue() { return document.getElementById('trusteeCopyPlayer').value; }
    function startTurnTimer(seconds) {
        clearInterval(G.reqTimer);
        const total = Math.max(1, Number(seconds) || 30) * 1000;
        G.reqDeadline = Date.now() + total;
        const bar = document.querySelector('#abTimer i');
        const wrap = document.getElementById('abTimer');
        const tick = () => {
            if (!G.turn || G.req || G.ended) { clearInterval(G.reqTimer); return; }
            const left = G.reqDeadline - Date.now();
            bar.style.transform = 'scaleX(' + Math.max(0, left / total) + ')';
            wrap.classList.toggle('urgent', left < 5000);
            if (left <= 0) clearInterval(G.reqTimer);
        };
        tick();
        G.reqTimer = setInterval(tick, 200);
    }
    /** 局内调整某个 AI 的模型（update_ai_config，立即生效；Key 留空则保留原 Key）。 */
    function openAISettings(id) {
        const p = playerById(id);
        if (!p || !p.is_ai) return;
        fillProviders();
        const c = p.ai_config || {};
        document.getElementById('aiSettingModel').dispatchEvent(new Event('picker-reset'));
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

    /** 自绘确认框（替代浏览器自带 confirm，风格统一）。返回 Promise<boolean>。 */
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
        // 与服务端战绩规则一致：前两轮内结束不影响连胜，之后结束会清零连胜。
        const round = (G.state && G.state.round) || 0;
        const note = round > 2
            ? '本局会记为中断，不计胜负；已过第 2 轮，结束后连胜会清零。'
            : '本局会记为中断，不计胜负；前两轮内结束不影响连胜。';
        const yes = await confirmDialog('结束本局？', note, '结束对局');
        if (!yes) return;
        document.getElementById('quitBtn').disabled = true;
        gameClient.autoReconnect = false;
        gameClient.send({ type: Protocol.INBOUND.END_GAME, reason: '玩家主动结束游戏' });
    }

    // ------------------------------------------------------------------ 启动
    /** 生成阶段栏的 6 个格子（准 判 摸 出 弃 结）。 */
    function buildPhaseTrack() {
        const track = document.getElementById('phaseTrack');
        track.innerHTML = '<span class="pt-owner"></span>' + SGS.PHASE_ORDER.map(k =>
            '<span class="pt-step" title="' + SGS.PHASE[k] + '">' + SGS.PHASE_SHORT[k] + '</span>').join('');
    }

    function bindUI() {
        buildPhaseTrack();
        document.getElementById('decisionTracePanel').hidden = settings().show_decision_trace === false;
        document.getElementById('okBtn').addEventListener('click', onOk);
        document.getElementById('cancelBtn').addEventListener('click', onCancel);
        document.getElementById('peekLog').addEventListener('click', () => ChatPanel.open('log'));
        document.getElementById('endBtn').addEventListener('click', onEnd);
        document.getElementById('quitBtn').addEventListener('click', quitGame);
        document.getElementById('sbtn').addEventListener('click', () => window.openGlobalSettings && window.openGlobalSettings());
        document.getElementById('trusteeBtn').addEventListener('click', openTrusteeDialog);
        document.getElementById('trusteeSource').addEventListener('change', trusteeSourceChanged);
        document.getElementById('trusteeForm').addEventListener('submit', saveTrustee);
        document.getElementById('trusteeOff').addEventListener('click', () => {
            gameClient.setTrustee(false);
            document.getElementById('trusteeModal').close();
        });
        document.getElementById('aiSettingsForm').addEventListener('submit', saveAISettings);
        const val = id => document.getElementById(id).value.trim();
        const trusteePicker = SGS.attachModelPicker(document.getElementById('trusteeModel'), () => ({
            provider: val('trusteeProvider'), api_url: val('trusteeUrl'), api_key: val('trusteeKey')
        }));
        // 局内调整 AI 时 Key 可留空：服务器按本局 game_id + 座位沿用已保存的 Key（Key 不会回传给页面）。
        const aiPicker = SGS.attachModelPicker(document.getElementById('aiSettingModel'), () => {
            const active = store.sget('activeGame') || {};
            return { provider: val('aiSettingProvider'), api_url: val('aiSettingUrl'), api_key: val('aiSettingKey'),
                game_id: active.game_id || gameClient.gameId, profile_id: active.profile_id,
                player_id: parseInt(val('aiSettingPlayerId'), 10) };
        });
        ['trusteeProvider', 'trusteeUrl', 'trusteeKey'].forEach(id => document.getElementById(id).addEventListener('change', () => trusteePicker && trusteePicker.reset()));
        ['aiSettingProvider', 'aiSettingUrl', 'aiSettingKey'].forEach(id => document.getElementById(id).addEventListener('change', () => aiPicker && aiPicker.reset()));
        document.querySelectorAll('dialog [data-close]').forEach(b => b.addEventListener('click', () => b.closest('dialog').close()));
        document.querySelectorAll('dialog.sgs-dialog').forEach(d => d.addEventListener('click', (e) => { if (e.target === d && d.id !== 'endModal') d.close(); }));
        document.getElementById('endModal').addEventListener('cancel', (e) => e.preventDefault());
        window.addEventListener('resize', layoutHand);
        window.addEventListener('global-settings-changed', () => { G.seatSig = {}; renderAll(); });
        window.addEventListener('global-settings-changed', (event) => {
            const panel = document.getElementById('decisionTracePanel');
            if (panel) panel.hidden = event.detail && event.detail.show_decision_trace === false;
        });
        // 键盘：回车 = 确定，Esc = 取消（输入框里打字时不拦截）
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
