// 通过服务端读取当前浏览器 profile_id 下的对局历史。
(function () {
    'use strict';
    const { store, esc, toast } = SGS;
    const id = store.get('profileId', '');
    const summary = document.getElementById('historySummary');
    const list = document.getElementById('historyList');
    const message = document.getElementById('historyMessage');
    const humanTitleControl = document.getElementById('humanTitleControl');
    const aiPlayerList = document.getElementById('aiPlayerList');
    const identity = value => ((SGS.IDENTITY[value] || {}).name) || ({ draw: '平局', aborted: '主动终止' }[value]) || value || '未知';
    const when = value => {
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString();
    };
    const status = row => row.status === 'interrupted' ? '已中止' : row.winner === 'draw' ? '平局' : row.player_won ? '胜' : '负';
    function showError(text) {
        summary.textContent = '无法读取服务端历史';
        message.hidden = false;
        message.textContent = text;
    }
    const titleOptions = (titles, selected) => '<option value="">自动佩戴最高称号</option>' +
        (titles || []).map(t => '<option value="' + esc(t.id) + '"' + (t.id === selected ? ' selected' : '') + '>' +
            esc(t.name) + ' · ' + esc(t.tier) + '</option>').join('');
    const postJSON = (url, body) => SGS.fetchJSON(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    function loadAIPlayers() {
        SGS.fetchJSON('/api/ai-players?profile_id=' + encodeURIComponent(id)).then(data => {
            if (!data || !data.success || !Array.isArray(data.players)) throw new Error('AI 档案不可用');
            aiPlayerList.innerHTML = data.players.map(player => {
                const titles = player.titles || { earned: [], equipped: null };
                const equippedId = (titles.equipped || {}).id || '';
                const games = (player.history || []).slice(0, 6);
                return '<article class="ai-archive-card"><div class="ai-archive-head"><div><b>' + esc(player.name) + '</b><small>固定编号 ' + esc(player.id) + ' · ' +
                    esc(String((player.stats || {}).wins || 0)) + ' 胜 / ' + esc(String((player.stats || {}).total_games || 0)) + ' 局</small></div>' +
                    (titles.equipped ? '<span class="title-badge title-' + esc(titles.equipped.tier) + '">' + esc(titles.equipped.name) + '</span>' : '') + '</div>' +
                    '<label class="field"><span>选手名称</span><input data-ai-name="' + esc(player.id) + '" maxlength="16" value="' + esc(player.name) + '"></label>' +
                    '<label class="field"><span>佩戴称号</span><select data-ai-title="' + esc(player.id) + '">' + titleOptions(titles.earned, equippedId) + '</select></label>' +
                    '<button class="btn small" type="button" data-save-ai="' + esc(player.id) + '">保存档案</button>' +
                    '<p class="muted">已获得：' + (titles.earned || []).map(t => esc(t.name)).join('、') + (titles.earned && titles.earned.length ? '' : '暂无') + '</p>' +
                    '<div class="ai-archive-history">' + (games.length ? games.map(g => '<span>' + esc(g.won ? '胜' : g.winner === 'draw' ? '平' : '负') + ' · ' + esc(identity(g.identity)) + ' · ' + esc(g.hero_name || '未知武将') + '</span>').join('') : '<span>尚无战绩</span>') + '</div></article>';
            }).join('');
            aiPlayerList.querySelectorAll('[data-save-ai]').forEach(button => button.addEventListener('click', async () => {
                const aiId = button.dataset.saveAi;
                try {
                    await postJSON('/api/ai-players/update', {
                        ai_id: aiId,
                        profile_id: id,
                        name: aiPlayerList.querySelector('[data-ai-name="' + aiId + '"]').value.trim(),
                        equipped_title: aiPlayerList.querySelector('[data-ai-title="' + aiId + '"]').value
                    });
                    toast('AI 档案已保存');
                    loadAIPlayers();
                } catch (error) { toast(error.message || '保存失败', { bad: true }); }
            }));
        }).catch(error => { aiPlayerList.innerHTML = '<p class="muted">' + esc(error.message || '暂时无法读取 AI 档案') + '</p>'; });
    }
    loadAIPlayers();
    if (!/^[A-Za-z0-9_-]{1,128}$/.test(id)) {
        showError('尚未创建本地战绩档案。返回大厅后即可初始化。');
        return;
    }
    SGS.fetchJSON('/api/history?profile_id=' + encodeURIComponent(id)).then(data => {
        if (!data || !data.success || !data.profile) throw new Error('服务端暂未返回档案数据。');
        const profile = data.profile;
        summary.textContent = '连胜 ' + (profile.win_streak || 0) + ' 局 · 总对局 ' +
            (profile.total_games || 0) + ' 局 · 身份卡 ' + (profile.identity_cards || 0) + ' 张';
        const titleView = profile.titles || { earned: [], equipped: null };
        humanTitleControl.hidden = false;
        humanTitleControl.innerHTML = '<label class="field"><span>我的佩戴称号</span><select id="humanTitleSelect">' +
            titleOptions(titleView.earned, (titleView.equipped || {}).id || '') + '</select></label>' +
            '<button class="btn small" id="saveHumanTitle" type="button">保存</button><span class="muted">已获得：' +
            (titleView.earned || []).map(t => esc(t.name)).join('、') + (titleView.earned && titleView.earned.length ? '' : '暂无') + '</span>';
        document.getElementById('saveHumanTitle').addEventListener('click', async () => {
            try {
                await postJSON('/api/history/title', { profile_id: id, equipped_title: document.getElementById('humanTitleSelect').value });
                toast('称号已保存');
            } catch (error) { toast(error.message || '保存失败', { bad: true }); }
        });
        const rows = Array.isArray(profile.history) ? profile.history : [];
        if (!rows.length) {
            message.hidden = false;
            message.textContent = '当前档案还没有已结算的对局。';
            return;
        }
        list.innerHTML = '<table class="stats-table"><thead><tr><th>时间</th><th>结果</th><th>身份</th><th>武将</th><th>用时</th></tr></thead><tbody>' +
            rows.map(row => '<tr><td>' + esc(when(row.ended_at)) + '</td><td>' + esc(status(row)) +
                '</td><td>' + esc(identity(row.player_identity)) + '</td><td>' + esc(row.hero_name || '—') +
                '</td><td>' + esc(String(Math.max(0, Number(row.duration) || 0)) + ' 秒') + '</td></tr>').join('') +
            '</tbody></table>';
    }).catch(error => showError(error && error.message ? error.message : '服务端暂不可用，请稍后重试。'));
})();
