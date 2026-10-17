// 通过服务端读取当前浏览器 profile_id 下的对局历史。
(function () {
    'use strict';
    const { store, esc } = SGS;
    const id = store.get('profileId', '');
    const summary = document.getElementById('historySummary');
    const list = document.getElementById('historyList');
    const message = document.getElementById('historyMessage');
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
    if (!/^[A-Za-z0-9_-]{1,128}$/.test(id)) {
        showError('尚未创建本地战绩档案。返回大厅后即可初始化。');
        return;
    }
    SGS.fetchJSON('/api/history?profile_id=' + encodeURIComponent(id)).then(data => {
        if (!data || !data.success || !data.profile) throw new Error('服务端暂未返回档案数据。');
        const profile = data.profile;
        summary.textContent = '连胜 ' + (profile.win_streak || 0) + ' 局 · 总对局 ' +
            (profile.total_games || 0) + ' 局 · 身份卡 ' + (profile.identity_cards || 0) + ' 张';
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
