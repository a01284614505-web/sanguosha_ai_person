// 对局日志页：列表、查看、下载、删除（单条 / 多选 / 全部）。数据来自服务端 /api/logs。
// 手机上长按一条进入多选；电脑上点“选择”按钮进入多选。
(function () {
    'use strict';
    const { esc, store, toast, fetchJSON } = SGS;
    const profileId = store.get('profileId', '');
    const view = { logs: [], selecting: false, selected: new Set(), current: null,
        timeline: [], timelineIndex: -1, timelineTimer: null, timelineSpeed: 1 };

    const $ = (id) => document.getElementById(id);

    function fmtTime(iso) {
        if (!iso) return '';
        const d = new Date(iso);
        if (isNaN(d)) return iso;
        const pad = (n) => String(n).padStart(2, '0');
        return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
    }
    function fmtDuration(sec) {
        const s = Math.max(0, Number(sec) || 0);
        return s >= 60 ? Math.floor(s / 60) + ' 分 ' + (s % 60) + ' 秒' : s + ' 秒';
    }
    function verdictOf(item) {
        if (!['lord', 'rebel', 'spy'].includes(item.winner)) return item.winner === 'draw' ? '和' : '终';
        const id = item.identity;
        const won = (item.winner === 'lord' && (id === 'lord' || id === 'loyalist')) || item.winner === id;
        return won ? '胜' : '败';
    }

    function diagnosticText(value) {
        if (value === null || value === undefined || value === '') return '';
        const text = typeof value === 'string' ? value : JSON.stringify(value);
        return esc(text.length > 240 ? text.slice(0, 237) + '…' : text);
    }

    function situationDiagnostics(situation) {
        if (!situation || typeof situation !== 'object') return '';
        const rows = [];
        const add = (label, value) => {
            if (value === null || value === undefined || value === '') return;
            rows.push('<span><b>' + esc(label) + '</b> ' + diagnosticText(value) + '</span>');
        };
        add('状态版本', situation.state_version);
        add('轮次', situation.round);
        add('阶段', situation.phase);
        add('事件序号', situation.event_seq);
        add('牌移动序号', situation.card_move_seq);
        const discard = situation.discard;
        if (discard && typeof discard === 'object') {
            const names = Array.isArray(discard.latest) ? discard.latest : [];
            const byName = discard.by_name && typeof discard.by_name === 'object'
                ? Object.entries(discard.by_name).map(([name, count]) => name + ' ×' + count).join('、') : '';
            const details = [Number.isFinite(discard.count) ? '共 ' + discard.count + ' 张' : '',
                byName ? '累计：' + byName : '', names.length ? '最近：' + names.join('、') : ''].filter(Boolean).join('；');
            add('弃牌摘要', details);
        }
        if (!rows.length) return '';
        return '<section class="log-diagnostics" aria-label="公开状态诊断"><h3 class="section-title">公开状态诊断</h3>' +
            '<div class="diagnostic-facts">' + rows.join('') + '</div></section>';
    }

    function decisionDiagnostics(decisions) {
        const fields = [
            ['situation_version', '状态版本'], ['selection_kind', '选择类型'],
            ['candidates_summary', '候选摘要'], ['chosen_summary', '最终选择'],
            ['validation_status', '引擎复核'], ['fallback_reason', '降级原因']
        ];
        const rows = (decisions || []).map(d => {
            if (!d || typeof d !== 'object' || !fields.some(([key]) => Object.prototype.hasOwnProperty.call(d, key))) return '';
            const facts = fields.filter(([key]) => Object.prototype.hasOwnProperty.call(d, key)).map(([key, label]) => {
                const value = d[key];
                const shown = value === null || value === '' ? (key === 'fallback_reason' ? '无' : '') : diagnosticText(value);
                return shown ? '<span><b>' + esc(label) + '</b> ' + shown + '</span>' : '';
            }).filter(Boolean).join('');
            if (!facts) return '';
            return '<article class="decision-diagnostic"><b>' + esc(d.player_name || '决策') +
                (d.round ? ' · 第 ' + esc(d.round) + ' 轮' : '') + '</b><div class="diagnostic-facts">' + facts + '</div></article>';
        }).filter(Boolean);
        if (!rows.length) return '';
        return '<section class="log-diagnostics" aria-label="AI 选择诊断"><h3 class="section-title">AI 选择诊断</h3>' + rows.join('') + '</section>';
    }

    /** 自绘确认框，返回 Promise<boolean>。 */
    function confirmBox(title, text, okText) {
        return new Promise(resolve => {
            const d = document.createElement('dialog');
            d.className = 'sgs-dialog';
            d.innerHTML = '<div class="frame dialog-body" style="text-align:center"><h2 class="brush gold-text" style="margin:4px 0 8px">' + esc(title) + '</h2>' +
                '<p class="muted" style="margin:0">' + esc(text) + '</p><div class="dialog-actions" style="justify-content:center">' +
                '<button class="btn cancel" type="button" data-v="0">取消</button><button class="btn primary" type="button" data-v="1">' + esc(okText || '确定') + '</button></div></div>';
            document.body.appendChild(d);
            d.addEventListener('click', (e) => {
                const b = e.target.closest('[data-v]');
                if (!b && e.target !== d) return;
                d.close(); d.remove();
                resolve(!!b && b.dataset.v === '1');
            });
            d.showModal();
        });
    }

    async function load() {
        if (!profileId) { $('logSummary').textContent = '还没有档案，先去大厅开一局吧。'; return; }
        try {
            const data = await fetchJSON('/api/logs?profile_id=' + encodeURIComponent(profileId));
            view.logs = data.logs || [];
        } catch (_) {
            $('logSummary').textContent = '连不上游戏服务，请先运行 game_server.py';
            return;
        }
        renderList();
        const want = new URLSearchParams(location.search).get('game');
        if (want && view.logs.some(l => l.game_id === want)) openDetail(want);
    }

    function renderList() {
        $('logSummary').textContent = view.logs.length ? '共 ' + view.logs.length + ' 局' : '还没有保存的对局日志。';
        $('deleteAllBtn').disabled = !view.logs.length;
        $('selectModeBtn').disabled = !view.logs.length;
        $('logItems').innerHTML = view.logs.map(item => {
            const v = verdictOf(item);
            const idName = (SGS.IDENTITY[item.identity] || {}).name || '';
            const checked = view.selected.has(item.game_id);
            return '<div class="log-item' + (checked ? ' checked' : '') + '" role="listitem" tabindex="0" data-id="' + esc(item.game_id) + '">' +
                (view.selecting ? '<span class="log-check" aria-hidden="true">' + (checked ? '✓' : '') + '</span>' : '') +
                '<span class="log-verdict v-' + (v === '胜' ? 'win' : v === '败' ? 'lose' : 'neutral') + '">' + v + '</span>' +
                '<span class="log-main"><b>' + esc(item.hero || '未知武将') + (idName ? ' · ' + esc(idName) : '') + '</b>' +
                '<small>' + esc(fmtTime(item.ended_at)) + ' · ' + esc(String(item.rounds || 0)) + ' 轮 · ' + esc(fmtDuration(item.duration)) +
                (item.cheat ? ' · <em>作弊局</em>' : '') + '</small>' +
                '<small class="faint">' + esc(item.message || '') + '</small></span>' +
                '</div>';
        }).join('');
        $('normalBar').hidden = view.selecting;
        $('selectBar').hidden = !view.selecting;
        $('selectedCount').textContent = '已选 ' + view.selected.size + ' 局';
        $('deleteSelectedBtn').disabled = !view.selected.size;
    }

    function setSelecting(on) {
        view.selecting = on;
        if (!on) view.selected.clear();
        renderList();
    }

    function stopTimelinePlayback() {
        if (view.timelineTimer) clearTimeout(view.timelineTimer);
        view.timelineTimer = null;
        const play = $('timelinePlayBtn');
        if (play) { play.textContent = '播放'; play.setAttribute('aria-label', '播放轨迹'); }
    }

    function selectTimelineEvent(index) {
        const events = view.timeline;
        if (!events.length) return;
        view.timelineIndex = Math.max(0, Math.min(events.length - 1, index));
        const nodes = $('detailBody').querySelectorAll('[data-timeline-index]');
        nodes.forEach(node => node.classList.toggle('tl-active', Number(node.dataset.timelineIndex) === view.timelineIndex));
        const active = $('detailBody').querySelector('[data-timeline-index="' + view.timelineIndex + '"]');
        if (active) {
            const parent = active.closest('details');
            if (parent) parent.open = true;
            active.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
        const item = events[view.timelineIndex];
        $('timelineStatus').textContent = '轨迹 ' + (view.timelineIndex + 1) + ' / ' + events.length +
            (item.round ? ' · 第 ' + item.round + ' 轮' : '') + (item.kind ? ' · ' + item.kind : '');
        $('timelineFirstBtn').disabled = view.timelineIndex === 0;
        $('timelinePrevBtn').disabled = view.timelineIndex === 0;
        $('timelineNextBtn').disabled = view.timelineIndex >= events.length - 1;
        $('timelineLastBtn').disabled = view.timelineIndex >= events.length - 1;
    }

    function scheduleTimelineStep() {
        stopTimelineTimerOnly();
        if (view.timelineIndex >= view.timeline.length - 1) { stopTimelinePlayback(); return; }
        const delay = 1000 / view.timelineSpeed;
        view.timelineTimer = setTimeout(() => {
            view.timelineTimer = null;
            selectTimelineEvent(view.timelineIndex + 1);
            if (view.timelineIndex < view.timeline.length - 1) scheduleTimelineStep();
            else stopTimelinePlayback();
        }, delay);
    }

    function stopTimelineTimerOnly() {
        if (view.timelineTimer) clearTimeout(view.timelineTimer);
        view.timelineTimer = null;
    }

    function toggleTimelinePlayback() {
        if (!view.timeline.length) return;
        if (view.timelineTimer) { stopTimelinePlayback(); return; }
        if (view.timelineIndex < 0 || view.timelineIndex >= view.timeline.length - 1) selectTimelineEvent(0);
        const play = $('timelinePlayBtn');
        play.textContent = '暂停'; play.setAttribute('aria-label', '暂停轨迹');
        scheduleTimelineStep();
    }

    function renderTimelinePlayer(timeline) {
        stopTimelinePlayback();
        view.timeline = (Array.isArray(timeline) ? timeline : []).filter(t => t && typeof t === 'object').map((item, originalIndex) => ({
            round: item.round, kind: item.kind, text: item.text, seq: item.seq, originalIndex
        }));
        if (view.timeline.every(item => typeof item.seq === 'number' && Number.isFinite(item.seq))) {
            view.timeline.sort((a, b) => Number(a.seq) - Number(b.seq) || a.originalIndex - b.originalIndex);
        }
        view.timelineIndex = -1;
        view.timelineSpeed = Number($('timelineSpeed') && $('timelineSpeed').value) || 1;
        const disabled = view.timeline.length ? '' : ' disabled';
        return '<section class="timeline-player" aria-label="公开事件播放器"><div class="timeline-controls">' +
            '<button class="btn small" type="button" id="timelineFirstBtn" aria-label="首条" title="首条（Home）"' + disabled + '>|‹</button>' +
            '<button class="btn small" type="button" id="timelinePrevBtn" aria-label="上条" title="上条（←）"' + disabled + '>‹</button>' +
            '<button class="btn small confirm" type="button" id="timelinePlayBtn" aria-label="播放轨迹" title="播放/暂停（空格）"' + disabled + '>播放</button>' +
            '<button class="btn small" type="button" id="timelineNextBtn" aria-label="下条" title="下条（→）"' + disabled + '>›</button>' +
            '<button class="btn small" type="button" id="timelineLastBtn" aria-label="末条" title="末条（End）"' + disabled + '>›|</button>' +
            '<label class="timeline-speed">速度 <select id="timelineSpeed" aria-label="播放速度"' + disabled + '><option value="0.5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option></select></label>' +
            '</div><p id="timelineStatus" class="muted" role="status" aria-live="polite">' +
            (view.timeline.length ? '共 ' + view.timeline.length + ' 条公开事件' : '没有可播放的公开事件轨迹') + '</p></section>';
    }
    function toggleSelect(id) {
        if (view.selected.has(id)) view.selected.delete(id); else view.selected.add(id);
        renderList();
    }

    async function remove(ids, all) {
        try {
            const res = await fetchJSON('/api/logs/delete', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ profile_id: profileId, game_ids: ids || [], all: !!all })
            });
            if (!res.success) throw new Error(res.message);
            toast('已删除 ' + res.removed + ' 局日志');
        } catch (err) {
            toast('删除失败：' + (err.message || ''), { bad: true });
        }
        view.selected.clear();
        view.selecting = false;
        showList();
        await load();
    }

    // ------------------------------------------------------------ 长按进入多选
    function bindLongPress(container) {
        let timer = null, startX = 0, startY = 0, longPressed = false, targetId = null;
        container.addEventListener('pointerdown', (e) => {
            const item = e.target.closest('.log-item');
            if (!item) return;
            targetId = item.dataset.id;
            longPressed = false;
            startX = e.clientX; startY = e.clientY;
            clearTimeout(timer);
            timer = setTimeout(() => {
                longPressed = true;
                if (navigator.vibrate) navigator.vibrate(20);
                if (!view.selecting) { view.selecting = true; view.selected.clear(); }
                toggleSelect(targetId);
            }, 520);
        });
        const cancel = () => clearTimeout(timer);
        container.addEventListener('pointermove', (e) => {
            if (Math.abs(e.clientX - startX) > 10 || Math.abs(e.clientY - startY) > 10) cancel();
        });
        container.addEventListener('pointerup', cancel);
        container.addEventListener('pointercancel', cancel);
        container.addEventListener('contextmenu', (e) => { if (e.target.closest('.log-item')) e.preventDefault(); });
        container.addEventListener('click', (e) => {
            const item = e.target.closest('.log-item');
            if (!item) return;
            if (longPressed) { longPressed = false; return; }
            if (view.selecting) toggleSelect(item.dataset.id);
            else openDetail(item.dataset.id);
        });
        container.addEventListener('keydown', (e) => {
            const item = e.target.closest('.log-item');
            if (item && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); item.click(); }
        });
    }

    // ------------------------------------------------------------ 详情
    function showList() {
        stopTimelinePlayback();
        view.timeline = [];
        view.timelineIndex = -1;
        $('detailView').hidden = true;
        $('listView').hidden = false;
        view.current = null;
        history.replaceState(null, '', 'logs.html');
    }

    async function openDetail(id) {
        stopTimelinePlayback();
        let data;
        try {
            data = await fetchJSON('/api/logs/' + encodeURIComponent(id) + '?profile_id=' + encodeURIComponent(profileId));
        } catch (_) {
            toast('读取日志失败', { bad: true });
            return;
        }
        const log = data.log;
        const timelinePlayerHTML = renderTimelinePlayer(log.timeline);
        view.current = id;
        $('listView').hidden = true;
        $('detailView').hidden = false;
        $('downloadBtn').href = '/api/logs/' + encodeURIComponent(id) + '?profile_id=' + encodeURIComponent(profileId) + '&download=1';
        history.replaceState(null, '', 'logs.html?game=' + encodeURIComponent(id));
        const players = (log.players || []).map(p =>
            '<tr class="' + (p.alive ? '' : 'dead') + '"><td><b>' + esc((p.seat ? p.seat + '号 ' : '') + (p.name || '')) + '</b><small>' + esc(p.hero || '') + '</small></td>' +
            '<td>' + SGS.identitySeal(p.identity) + '</td>' +
            '<td>' + esc(p.is_ai ? ((p.model || '规则 AI') + '') : '你') + '</td>' +
            '<td>' + esc(String((p.stats || {}).damage_dealt || 0)) + ' / ' + esc(String((p.stats || {}).kills || 0)) + '</td></tr>').join('');
        // 时间线、聊天、决策按轮次合并展示。
        const rounds = {};
        // 按 seq（发生先后）排序后再分轮，时间线、聊天、思考穿插显示；旧日志没有 seq 时退回原顺序。
        const entries = [];
        const push = (r, html, seq) => entries.push({ r: r || 0, html: html, seq: Number.isFinite(seq) ? seq : entries.length * 1e-6 });
        view.timeline.forEach((t, timelineIndex) => {
            const eventClass = t.kind === 'skill_decision' ? ' tl-skill-decision' :
                t.kind === 'dying_rescue' ? ' tl-rescue' : '';
            const label = t.kind === 'skill_decision' ? '<small>技能选择 · </small>' :
                t.kind === 'dying_rescue' ? '<small>濒死救援 · </small>' : '';
            push(t.round, '<div class="tl-line timeline-event-row' + eventClass + '" data-timeline-index="' + timelineIndex + '">' + label + esc(t.text) + '</div>', t.seq);
        });
        (log.chat || []).forEach(c => push(c.round, '<div class="tl-line tl-chat">💬 <b>' + esc((c.seat ? c.seat + '号 ' : '') + (c.from || '')) + '</b>：' + esc(c.message || '') + '</div>', c.seq));
        (log.blocked_chat || []).forEach(c => push(c.round, '<div class="tl-line">发言被拦截：<b>' +
            esc(c.name) + '</b>：' + esc(c.text) + ' · ' + esc(c.detail) + '</div>', c.seq));
        (log.plan_snapshots || []).forEach(t => push(t.round, '<div class="tl-line">' + esc(String(t.seat)) +
            '号打法：' + esc(t.plan.style) + ' · ' + esc(t.plan.why)));
        (log.decisions || []).forEach(d => {
            // 选项下标（如 [0]）对人没有意义，去掉；“合法目标=[…]”这类引擎内部信息也去掉。
            d = Object.assign({}, d, { choice: /^\[[\d, ]*\]$/.test(String(d.choice || '')) ? '' : String(d.choice || '').replace(/，合法目标(对)?=\[[^\]]*\]/g, '') });
            if (!d.reason && !d.choice) return;
            push(d.round, '<div class="tl-line tl-think">💭 <b>' + esc(d.player_name || '') + '</b>' + (d.model ? '<small>（' + esc(d.model) + '）</small>' : '') +
                (d.reason ? '：' + esc(d.reason) : '') + (d.choice ? '<small class="faint"> → ' + esc(d.choice) + '</small>' : '') + '</div>', d.seq);
        });
        entries.sort((a, b) => a.seq - b.seq).forEach(e => (rounds[e.r] = rounds[e.r] || []).push(e.html));
        const roundHTML = Object.keys(rounds).map(Number).sort((a, b) => a - b).map(r =>
            '<details class="tl-round"' + (r <= 1 ? ' open' : '') + '><summary>' + (r ? '第 ' + r + ' 轮' : '开局') + '<small> · ' + rounds[r].length + ' 条</small></summary>' + rounds[r].join('') + '</details>').join('');
        // Token 消耗：行=AI，列=决策/响应/选择/聊天；没有任何调用数据时整张表不显示。
        const tuKinds = [['decision', '决策'], ['response', '响应'], ['choice', '选择'], ['chat', '聊天']];
        const tuRows = (log.token_usage || []).filter(r => tuKinds.some(([k]) => ((r.kinds || {})[k] || {}).calls > 0));
        const tokenTable = tuRows.length ? '<h3 class="section-title">Token 消耗</h3>' +
            '<div class="table-wrap"><table class="stats-table log-tokens"><thead><tr><th>AI</th>' +
            tuKinds.map(([, label]) => '<th>' + label + '</th>').join('') + '</tr></thead><tbody>' +
            tuRows.map(r => '<tr><td><b>' + esc(r.name || '') + '</b><small>' + esc(r.model || '') + '</small></td>' +
                tuKinds.map(([k]) => {
                    const c = (r.kinds || {})[k] || {};
                    if (!c.calls) return '<td class="faint">—</td>';
                    const extra = (c.failures ? ' · 失败 ' + c.failures : '') + (c.unknown_usage_calls ? ' · 缺用量 ' + c.unknown_usage_calls : '');
                    return '<td>' + esc(String(c.calls)) + ' 次<small>入 ' + esc(String(c.prompt_tokens || 0)) + ' / 出 ' + esc(String(c.completion_tokens || 0)) + esc(extra) + '</small></td>';
                }).join('') + '</tr>').join('') +
            '</tbody></table></div>' : '';
        const opts = log.options || {};
        const diagnostics = situationDiagnostics(log.public_situation) + decisionDiagnostics(log.decisions);
        const prompts = (log.prompt_traces || []).map(t =>
            '<details class="prompt-trace"><summary>' + esc(String(t.seat)) + '号 · 第' + esc(String(t.round)) +
            '轮 · ' + esc(t.kind) + ' · 完整 prompt</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' +
            esc(JSON.stringify(t.messages, null, 2)) + '</pre></details>').join('');
        $('detailBody').innerHTML =
            '<h2 class="section-title">' + esc(log.message || '对局结束') + '</h2>' +
            '<p class="muted">' + esc(fmtTime(log.ended_at)) + ' · ' + esc(String(log.rounds || 0)) + ' 轮 · ' + esc(fmtDuration(log.duration)) +
            (opts.cheat_mode ? ' · 作弊局' : '') + (opts.hide_dead_identity ? ' · 阵亡暗置' : '') +
            (opts.include_thinking ? '' : ' · 未记录思考过程') + '</p>' +
            '<div class="table-wrap"><table class="stats-table log-players"><thead><tr><th>角色</th><th>身份</th><th>模型</th><th>伤害/击杀</th></tr></thead><tbody>' + players + '</tbody></table></div>' +
            diagnostics + tokenTable + prompts +
            '<h3 class="section-title">时间线</h3>' + timelinePlayerHTML + (roundHTML || '<p class="muted">没有记录。</p>');
        if (view.timeline.length) selectTimelineEvent(0);
        window.scrollTo(0, 0);
    }

    // ------------------------------------------------------------ 绑定
    bindLongPress($('logItems'));
    $('selectModeBtn').addEventListener('click', () => setSelecting(true));
    $('cancelSelectBtn').addEventListener('click', () => setSelecting(false));
    $('selectAllBtn').addEventListener('click', () => {
        if (view.selected.size === view.logs.length) view.selected.clear();
        else view.logs.forEach(l => view.selected.add(l.game_id));
        renderList();
    });
    $('deleteSelectedBtn').addEventListener('click', async () => {
        const n = view.selected.size;
        if (n && await confirmBox('删除日志', '删除选中的 ' + n + ' 局日志？删除后无法恢复。', '删除')) remove(Array.from(view.selected), false);
    });
    $('deleteAllBtn').addEventListener('click', async () => {
        if (await confirmBox('全部删除', '删除全部 ' + view.logs.length + ' 局日志？删除后无法恢复。', '全部删除')) remove([], true);
    });
    $('backBtn').addEventListener('click', showList);
    $('detailBody').addEventListener('click', event => {
        const button = event.target.closest('[id^="timeline"]');
        if (!button) return;
        if (button.id === 'timelineFirstBtn') { stopTimelinePlayback(); selectTimelineEvent(0); }
        else if (button.id === 'timelinePrevBtn') { stopTimelinePlayback(); selectTimelineEvent(view.timelineIndex - 1); }
        else if (button.id === 'timelineNextBtn') { stopTimelinePlayback(); selectTimelineEvent(view.timelineIndex + 1); }
        else if (button.id === 'timelineLastBtn') { stopTimelinePlayback(); selectTimelineEvent(view.timeline.length - 1); }
        else if (button.id === 'timelinePlayBtn') toggleTimelinePlayback();
    });
    $('detailBody').addEventListener('change', event => {
        if (event.target.id === 'timelineSpeed') {
            view.timelineSpeed = Number(event.target.value) || 1;
            if (view.timelineTimer) scheduleTimelineStep();
        }
    });
    document.addEventListener('keydown', event => {
        if ($('detailView').hidden || event.target.closest('input, textarea, select') || document.querySelector('dialog[open]')) return;
        if (event.code === 'Space') { event.preventDefault(); toggleTimelinePlayback(); }
        else if (event.key === 'ArrowLeft') { event.preventDefault(); stopTimelinePlayback(); selectTimelineEvent(view.timelineIndex - 1); }
        else if (event.key === 'ArrowRight') { event.preventDefault(); stopTimelinePlayback(); selectTimelineEvent(view.timelineIndex + 1); }
        else if (event.key === 'Home') { event.preventDefault(); stopTimelinePlayback(); selectTimelineEvent(0); }
        else if (event.key === 'End') { event.preventDefault(); stopTimelinePlayback(); selectTimelineEvent(view.timeline.length - 1); }
    });
    $('deleteOneBtn').addEventListener('click', async () => {
        if (view.current && await confirmBox('删除日志', '删除这一局的日志？删除后无法恢复。', '删除')) remove([view.current], false);
    });
    load();
})();
