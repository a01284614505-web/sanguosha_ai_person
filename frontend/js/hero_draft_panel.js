// =============================================================================
// 正式选将面板（对局页中央）
// -----------------------------------------------------------------------------
// 数据来源只有两路，面板自己不推断任何规则：
//   1. require_response（kind = choose_hero）：只发给本人，带自己的候选 heroes、自己的身份 draft.identity、
//      主公已公开的武将 draft.lord_hero、时限 timeout；
//   2. game_state.hero_draft：公开状态（阶段、主公座位、还在选的座位），任何人都能看到，不含候选。
// 提交走现有响应通道：{type:'response', request_id, option_index}，服务器复核后才生效。
// 非本人的候选从不下发，所以这里也没有任何别人候选的数据。
//
// 与 game_main.js 的接口（只有四个钩子）：
//   HeroDraftPanel.onRequest(data)       收到 choose_hero 请求
//   HeroDraftPanel.onState(state)        每次 game_state
//   HeroDraftPanel.onActionResult(r)     提交回执（被拒绝时让面板可重选）
//   HeroDraftPanel.active()              面板是否占用着中央（game_main 可据此少画一些提示）
// =============================================================================
(function (global) {
    'use strict';
    const SGS = global.SGS;
    const esc = SGS.esc;

    const IDENTITY_TEXT = { lord: '主公', loyalist: '忠臣', rebel: '反贼', spy: '内奸' };
    const SKILL_TAG = { lord: '主公技', locked: '锁定技', limited: '限定技', awaken: '觉醒技', active: '主动技' };

    const S = {
        req: null,          // 当前 choose_hero 请求（含候选）
        picked: -1,         // 点选的候选下标
        submitted: false,   // 已提交，等待服务器 / 其他角色
        deadline: 0,
        timer: null,
        state: null,        // 最近一份 game_state
        root: null,
        sig: ''             // 上一次渲染的内容签名：没变化就不重绘（避免立绘闪烁、点选丢失）
    };

    function root() {
        if (!S.root) S.root = document.getElementById('heroDraft');
        return S.root;
    }

    function me() {
        const st = S.state;
        if (!st) return null;
        return (st.players || []).find(p => !p.is_ai) || null;
    }

    /** 主公已公开的武将：优先用请求里带的完整技能说明，其次从公开状态里的座位取。 */
    function lordHero() {
        if (S.req && S.req.draft && S.req.draft.lord_hero) return S.req.draft.lord_hero;
        const st = S.state;
        const hd = st && st.hero_draft;
        if (!hd || hd.lord_id == null) return null;
        const lord = (st.players || []).find(p => p.id === hd.lord_id);
        return lord && lord.hero && lord.hero.id ? lord.hero : null;
    }

    function isActive() {
        const hd = S.state && S.state.hero_draft;
        return !!((hd && hd.active) || (S.req && !S.submitted));
    }

    // ------------------------------------------------------------------ 渲染
    function skillTags(hero) {
        return (hero.skills || []).map(s =>
            '<span class="hd-sk' + (s.lord_skill || s.type === 'lord' ? ' lord' : '') + '">' + esc(s.name) + '</span>').join('');
    }

    function lordRow() {
        const hero = lordHero();
        const iAmLord = S.req ? (S.req.draft && S.req.draft.identity === 'lord')
            : !!(me() && me().identity === 'lord');
        if (iAmLord && !hero) return '';
        if (!hero) {
            return '<div class="hd-lord wait"><span class="hd-lord-k">主公</span><span class="hd-lord-v">正在选将…</span></div>';
        }
        return '<div class="hd-lord">' +
            '<span class="hd-lord-art">' + SGS.heroImgHTML(hero.id, hero.name) + '</span>' +
            '<span class="hd-lord-txt"><span class="hd-lord-k">主公已选</span>' +
            '<b class="hd-lord-name">' + esc(hero.name) + '</b>' +
            '<span class="hd-lord-sk">' + skillTags(hero) + '</span></span>' +
            SGS.factionSeal(hero.faction) + '</div>';
    }

    function cardHTML(hero, index, bonus) {
        const on = index === S.picked;
        return '<button type="button" class="hd-card faction-' + esc(hero.faction) + (on ? ' on' : '') + '" data-i="' + index +
            '" aria-pressed="' + on + '" aria-label="' + esc(hero.name) + '，' + esc(hero.faction) + '，体力' + (hero.max_hp + bonus) + '">' +
            '<span class="hd-art">' + SGS.heroImgHTML(hero.id, hero.name) + '</span>' +
            '<span class="hd-c-seal">' + SGS.factionSeal(hero.faction) + '</span>' +
            '<span class="hd-c-hp">' + SGS.hpHTML(hero.max_hp + bonus, hero.max_hp + bonus, { vertical: true, limit: 6 }) + '</span>' +
            '<span class="hd-c-name">' + esc(String(hero.name).replace(/^界/, '')) + '</span></button>';
    }

    function detailHTML(hero, bonus) {
        if (!hero) {
            return '<div class="hd-detail empty">点一张武将牌，查看技能说明</div>';
        }
        const hp = hero.max_hp + bonus;
        return '<div class="hd-detail">' +
            '<div class="hd-d-head"><b class="hd-d-name">' + esc(hero.name) + '</b>' +
            (hero.title ? '<span class="hd-d-title">' + esc(hero.title) + '</span>' : '') +
            '<span class="hd-d-meta">' + esc(hero.faction) + ' · 体力 ' + hp + (bonus ? '（含主公 +' + bonus + '）' : '') + '</span></div>' +
            '<div class="hd-d-skills">' + (hero.skills || []).map(s =>
                '<p class="hd-d-skill"><b>【' + esc(s.name) + '】</b>' +
                (SKILL_TAG[s.lord_skill ? 'lord' : s.type] ? '<i class="hd-tag' + (s.lord_skill ? ' lord' : '') + '">' + SKILL_TAG[s.lord_skill ? 'lord' : s.type] + '</i>' : '') +
                esc(s.description || '') + '</p>').join('') + '</div></div>';
    }

    function headHTML(identity, seat, hint) {
        return '<header class="hd-head">' +
            '<div class="hd-who">' + SGS.identitySeal(identity) +
            '<span class="hd-who-txt"><b>你的身份：' + esc(IDENTITY_TEXT[identity] || '未知') + '</b>' +
            (seat ? '<span>' + seat + ' 号位</span>' : '') + '</span></div>' +
            '<div class="hd-timer" id="hdTimer" aria-label="剩余时间"><span class="hd-sec">–</span></div>' +
            '</header><p class="hd-hint">' + hint + '</p>';
    }

    function render() {
        const el = root();
        if (!el) return;
        const hd = S.state && S.state.hero_draft;
        const over = S.state && S.state.game_over;
        const choosing = !!(S.req && !S.submitted && !over);
        const waiting = !choosing && !!(hd && hd.active) && !over;
        if (!choosing && !waiting) {
            if (!el.hidden) { el.hidden = true; el.innerHTML = ''; S.sig = ''; document.body.classList.remove('hd-open'); }
            clearInterval(S.timer);
            return;
        }
        const mine = me();
        let sig;
        if (choosing) {
            sig = ['c', S.req.request_id, S.picked, S.req.expired ? 'x' : '', lordHero() ? lordHero().id : ''].join('|');
        } else {
            const left = hd.pending_ids ? hd.pending_ids.length : 0;
            sig = ['w', hd.stage, left, mine ? mine.hero_name : '', lordHero() ? lordHero().id : ''].join('|');
        }
        el.hidden = false;
        document.body.classList.add('hd-open');
        if (sig === S.sig) return;
        S.sig = sig;

        if (choosing) {
            const d = S.req.draft || {};
            const heroes = S.req.heroes || [];
            const bonus = d.hp_bonus || 0;
            const hint = d.stage === 'lord'
                ? '你是主公，先选武将。选定后全桌可见，其余角色再各自挑选。'
                : '主公已公开所选武将，请从下面的候选里选一名。其他角色的候选你看不到。';
            const cols = heroes.length <= 5 ? heroes.length : Math.ceil(heroes.length / 2);
            el.innerHTML =
                '<div class="hd-sheet" role="group" aria-label="选将">' +
                headHTML(d.identity, d.seat, hint) +
                (d.stage === 'lord' ? '' : lordRow()) +
                '<div class="hd-grid" style="--cols:' + Math.max(1, cols) + '">' +
                heroes.map((h, i) => cardHTML(h, i, bonus)).join('') + '</div>' +
                detailHTML(S.picked >= 0 ? heroes[S.picked] : null, bonus) +
                '<footer class="hd-foot"><button type="button" class="btn confirm hd-ok" id="hdOk"' +
                (S.picked < 0 || S.req.expired ? ' disabled' : '') + '>' + (S.req.expired ? '时间到' : '确定') + '</button></footer>' +
                '</div>';
            el.querySelectorAll('.hd-card').forEach(btn => btn.addEventListener('click', () => pick(Number(btn.dataset.i))));
            const ok = el.querySelector('#hdOk');
            if (ok) ok.addEventListener('click', submit);
            paintTimer();
        } else {
            const iAmLord = mine && mine.identity === 'lord';
            const left = (hd.pending_ids || []).length;
            let hint;
            if (hd.stage === 'lord') hint = iAmLord ? '' : '主公正在选将，请稍候。';
            else hint = '其他角色选将中' + (left ? '（还有 ' + left + ' 位）' : '') + '，马上开局。';
            // 别人选完前自己的武将不在公开状态里：提交后用本地记住的所选候选兜底（断线重连后再没有，则不显示这一行）
            const own = mine && mine.hero && mine.hero.id ? mine.hero
                : (S.submitted && S.req && S.picked >= 0 ? (S.req.heroes || [])[S.picked] : null);
            el.innerHTML =
                '<div class="hd-sheet waiting" role="status">' +
                headHTML(mine && mine.identity, mine && mine.seat, hint) +
                lordRow() +
                (own ? '<div class="hd-mine"><span class="hd-lord-k">你选择了</span><b>' + esc(own.name) + '</b>' +
                    '<span class="hd-lord-sk">' + skillTags(own) + '</span></div>' : '') +
                '<div class="hd-dots" aria-hidden="true"><i></i><i></i><i></i></div></div>';
            clearInterval(S.timer);
        }
    }

    // ------------------------------------------------------------------ 倒计时
    function paintTimer() {
        const wrap = document.getElementById('hdTimer');
        if (!wrap || !S.req) return;
        const total = Math.max(1, Number(S.req.timeout) || 120) * 1000;
        const left = S.deadline - Date.now();
        wrap.style.setProperty('--p', (Math.max(0, Math.min(1, left / total)) * 100).toFixed(2) + '%');
        const sec = wrap.querySelector('.hd-sec');
        if (sec) sec.textContent = String(Math.max(0, Math.ceil(left / 1000)));
        wrap.classList.toggle('urgent', left < 10000);
    }

    function startTimer() {
        clearInterval(S.timer);
        S.timer = setInterval(() => {
            if (!S.req || S.submitted) { clearInterval(S.timer); return; }
            paintTimer();
            if (S.deadline - Date.now() <= 0 && !S.req.expired) {
                // 服务器会在同一时刻随机替你选一名；这里只让按钮失效并提示，等下一份状态收起面板。
                S.req.expired = true;
                S.sig = '';
                render();
                const hint = root() && root().querySelector('.hd-hint');
                if (hint) hint.textContent = '时间到，系统已随机替你选择武将。';
            }
        }, 250);
    }

    // ------------------------------------------------------------------ 交互
    function pick(index) {
        if (!S.req || S.submitted || S.req.expired) return;
        S.picked = index;
        render();
        // 小屏上点选后让技能说明可见（面板内部滚动，不影响整页）
        const detail = root().querySelector('.hd-detail');
        if (detail && detail.scrollIntoView) detail.scrollIntoView({ block: 'nearest' });
    }

    function submit() {
        if (!S.req || S.submitted || S.picked < 0 || S.req.expired) return;
        S.submitted = true;
        S.sig = '';
        const rid = S.req.request_id;
        global.gameClient.playerAction({ type: 'response', request_id: rid, option_index: S.picked }, []);
        render();
    }

    // ------------------------------------------------------------------ 对外接口
    const Panel = {
        onRequest(data) {
            S.req = data;
            S.picked = -1;
            S.submitted = false;
            S.sig = '';
            S.deadline = Date.now() + Math.max(1, Number(data.timeout) || 120) * 1000;
            startTimer();
            render();
        },
        onState(state) {
            S.state = state;
            const hd = state && state.hero_draft;
            const mine = me();
            // 请求之后的状态里自己已不在"还在选"名单里：被托管 / 超时代选了，收起选择区。
            if (S.req && hd && hd.active && mine && !(hd.pending_ids || []).includes(mine.id)) {
                S.submitted = true;
            }
            if (!hd || !hd.active) { S.req = null; S.submitted = false; }
            render();
        },
        onActionResult(receipt) {
            // 提交被拒绝（索引无效等）：回到可重选；已过期 / 已应答的回执不处理。
            if (S.req && S.submitted && receipt && receipt.success === false &&
                receipt.status !== 'duplicate' && receipt.status !== 'game_ended' && receipt.status !== 'stale') {
                S.submitted = false;
                S.sig = '';
                render();
            }
        },
        active: isActive,
        _state: S   // 供浏览器自测读取
    };
    global.HeroDraftPanel = Panel;
})(window);
