/* Isolated, offline skill trial UI. A successful single run is evidence, not certification. */
(function () {
    'use strict';

    const labels = {
        success: '试运行完成', declined: '合法拒绝', not_triggered: '未触发',
        compile_error: '编译失败', runtime_error: '运行失败',
        budget_exhausted: '预算耗尽', aborted: '试验中止'
    };

    function escapeHtml(value) {
        return String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        })[ch]);
    }

    function card(title, content) {
        return '<section class="trial-result-card"><h3>' + escapeHtml(title) +
            '</h3><pre>' + escapeHtml(content || '无记录') + '</pre></section>';
    }

    function lines(items, render) {
        return Array.isArray(items) && items.length ? items.map((item, i) => (i + 1) + '. ' + render(item)).join('\n') : '无记录';
    }

    function display(value) {
        return typeof value === 'string' ? value : JSON.stringify(value);
    }

    function narrowHero(source) {
        if (!source || typeof source !== 'object' || Array.isArray(source)) {
            throw new Error('请先在输出 JSON 中填写一个武将对象。');
        }
        const hero = {};
        ['id', 'name', 'faction', 'max_hp', 'skills'].forEach(key => {
            if (Object.prototype.hasOwnProperty.call(source, key)) hero[key] = source[key];
        });
        if (!Array.isArray(hero.skills)) throw new Error('武将 JSON 的 skills 必须是数组。');
        return hero;
    }

    function packageDraft() {
        const id = document.getElementById('packageId').value.trim() || 'trial_draft';
        const name = document.getElementById('packageName').value.trim() || '试验草稿';
        return { id, name, version: '1.0' };
    }

    async function run() {
        const status = document.getElementById('trialStatus');
        const output = document.getElementById('trialOutput');
        const selected = document.querySelector('.trial-scenario[aria-pressed="true"]');
        const seed = Number(document.getElementById('trialSeed').value);
        try {
            const hero = narrowHero(JSON.parse(document.getElementById('outputJSON').value));
            if (!selected) throw new Error('请选择一个预设场景。');
            if (!Number.isInteger(seed) || seed < 0 || seed > 2147483647) {
                throw new Error('随机种子必须是 0 到 2147483647 之间的整数。');
            }
            status.dataset.kind = '';
            status.textContent = '正在创建隔离试验…';
            output.replaceChildren();
            const response = await fetch('/api/heroes/trial', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ package: packageDraft(), hero,
                    scenario_id: selected.dataset.scenario, seed })
            });
            let data;
            try { data = await response.json(); }
            catch (_) { throw new Error('试验接口返回了无法读取的响应（HTTP ' + response.status + '）。'); }
            const trial = data && data.trial;
            if (!response.ok || !data.success || !trial) {
                if (trial) renderTrial(trial, output);
                const message = (data && data.message) || (trial && trial.summary) || ('HTTP ' + response.status);
                status.dataset.kind = 'error';
                status.textContent = '试验未成功：' + message;
                return;
            }
            renderTrial(trial, output);
            status.dataset.kind = trial.outcome === 'success' ? 'success' : 'error';
            status.textContent = (labels[trial.outcome] || trial.outcome || '试验已返回') +
                ' · seed ' + trial.seed + ' · 单次试跑不等于完整认证';
        } catch (error) {
            status.dataset.kind = 'error';
            status.textContent = '试验未运行：' + error.message;
            output.replaceChildren();
        }
    }

    function renderTrial(trial, root) {
        root.innerHTML = '';
        const heading = document.createElement('div');
        heading.className = 'trial-result-card';
        heading.innerHTML = '<h3>' + escapeHtml(labels[trial.outcome] || trial.outcome || '试验结果') +
            '</h3><p style="margin:0;color:var(--text-light)">' + escapeHtml(trial.summary || '') +
            '</p><small style="color:var(--text-muted)">场景：' + escapeHtml(trial.scenario_id || '') +
            ' · seed：' + escapeHtml(trial.seed) + ' · schema v' + escapeHtml(trial.schema_version) +
            '</small>';
        root.appendChild(heading);
        root.insertAdjacentHTML('beforeend', card('诊断', lines(trial.diagnostics, d =>
            '[' + (d.level || 'info') + '/' + (d.code || '诊断') + '] ' + (d.skill_name ? d.skill_name + '：' : '') + (d.message || ''))));
        root.insertAdjacentHTML('beforeend', card('触发与选择轨迹', lines(trial.trace, t =>
            '#' + (t.seq == null ? '?' : t.seq) + ' ' + (t.event || '事件') +
            (t.skill_name ? ' · ' + t.skill_name : '') +
            (t.actor_id != null ? ' · 角色 ' + t.actor_id : '') +
            (Array.isArray(t.target_ids) && t.target_ids.length ? ' → ' + t.target_ids.join('、') : '') +
            (t.detail ? ' · ' + display(t.detail) : ''))));
        root.insertAdjacentHTML('beforeend', card('选择结果', lines(trial.choices, c =>
            (c.prompt || '选择') + '：' + (c.cancelled ? '已取消' : display(c.selected)))));
        root.insertAdjacentHTML('beforeend', card('牌移动', lines(trial.card_moves, m =>
            (m.card_name || m.card_id || '牌') + '：' + (m.from || '?') + ' → ' + (m.to || '?') +
            (m.reason ? ' · ' + m.reason : ''))));
        root.insertAdjacentHTML('beforeend', card('状态差异', lines(trial.state_diff, d =>
            d.path + '：' + display(d.before) + ' → ' + display(d.after))));
        if (trial.final_state) {
            const state = trial.final_state;
            const players = lines(state.players, p => (p.name || ('角色 ' + p.id)) +
                ' · 体力 ' + p.hp + '/' + p.max_hp + ' · 手牌 ' + p.hand_count + (p.alive ? '' : ' · 阵亡'));
            root.insertAdjacentHTML('beforeend', card('最终公开状态', '轮次 ' + (state.round == null ? '-' : state.round) +
                ' · 牌堆 ' + (state.deck_count == null ? '-' : state.deck_count) +
                ' · 弃牌 ' + (state.discard_count == null ? '-' : state.discard_count) +
                ' · 当前角色 ' + (state.current_player_id == null ? '-' : state.current_player_id) + '\n' + players));
        }
    }

    document.querySelectorAll('.trial-scenario').forEach(button => button.addEventListener('click', () => {
        document.querySelectorAll('.trial-scenario').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
    }));
    document.getElementById('runSkillTrial').addEventListener('click', run);
})();
