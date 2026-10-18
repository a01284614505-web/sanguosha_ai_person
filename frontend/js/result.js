// 结算页：只展示 game_end 下发的真实统计（口径见 game_engine/game_stats.py），不在 UI 层计算。
// 数据来自对局页写入的 localStorage['gameResult']；没有数据时提示去大厅开局。
(function () {
    'use strict';
    const { esc, store } = SGS;

    function identityName(id) {
        return (SGS.IDENTITY[id] || {}).name || ({ aborted: '主动终止', draw: '平局' }[id]) || id || '未知';
    }
    function formatDuration(seconds) {
        const total = Math.max(0, Number(seconds) || 0);
        const m = Math.floor(total / 60);
        const s = Math.floor(total % 60);
        return m ? m + ' 分 ' + s + ' 秒' : s + ' 秒';
    }

    // 胜负印 + 标题 + 轮数/用时/身份 + MVP + 统计表 + 身份卡奖励。
    function render(r) {
        const decided = ['lord', 'rebel', 'spy'].includes(r.winner);
        const verdict = document.getElementById('resultVerdict');
        verdict.className = 'verdict ' + (decided ? (r.player_won ? 'win' : 'lose') : 'neutral');
        verdict.textContent = decided ? (r.player_won ? '胜' : '败') : (r.winner === 'draw' ? '和' : '终');
        document.getElementById('resultTitle').textContent = decided ? (r.player_won ? '旗开得胜' : '惜败一局') : (r.winner === 'draw' ? '握手言和' : '对局终止');
        document.getElementById('resultSubtitle').textContent = decided
            ? SGS.WINNER[r.winner] + '获胜'
            : (r.message || '本局已结束');
        if (r.cheat) document.getElementById('resultSubtitle').textContent += '（作弊局，不计连胜与身份卡）';
        document.getElementById('totalRounds').textContent = r.total_rounds || 0;
        document.getElementById('gameDuration').textContent = formatDuration(r.duration);
        document.getElementById('yourIdentity').textContent = identityName(r.player_identity);
        if (r.profile) {
            const profile = document.getElementById('profileSummary');
            profile.hidden = false;
            profile.textContent = '服务端档案：连胜 ' + (r.profile.win_streak || 0) + ' 局 · 总对局 ' +
                (r.profile.total_games || 0) + ' 局 · 身份卡 ' + (r.profile.identity_cards || 0) + ' 张';
        }
        if (r.history_error) {
            const error = document.getElementById('historySaveError');
            error.hidden = false;
            error.textContent = r.history_error + '；本局结果仍可查看，请稍后在大厅检查历史。';
        }

        if (r.mvp) {
            const m = r.mvp;
            document.getElementById('mvpCard').hidden = false;
            document.getElementById('mvpInfo').innerHTML =
                '<div class="mvp-portrait">' + SGS.heroImgHTML(m.hero_id, m.hero_name) + '</div>' +
                '<h3>' + esc(m.player_name) + '</h3><div class="muted">' + esc(m.hero_name || '') + '</div>' +
                '<div class="mvp-nums">' +
                '<div>伤害 <b>' + (m.damage_dealt || 0) + '</b></div><div>击杀 <b>' + (m.kills || 0) + '</b></div>' +
                '<div>治疗 <b>' + (m.healing || 0) + '</b></div><div>出牌 <b>' + (m.cards_played || 0) + '</b></div></div>';
        }
        renderStats(r);
        if (r.reward === 'identity_card') {
            document.getElementById('rewardSection').hidden = false;
            document.getElementById('rewardCard').innerHTML = SGS.identityCardHTML({});
        }
    }

    // 每名玩家一行：头像、身份印与七项统计；自己的一行高亮，阵亡的变灰。
    function renderStats(r) {
        const box = document.getElementById('statsList');
        const players = r.players || [];
        if (!players.some(p => p && p.stats)) {
            box.innerHTML = '<p class="muted">本局没有统计数据（对局未完成结算或为旧版存档）。</p>';
            return;
        }
        const cols = [['damage_dealt', '伤害'], ['damage_taken', '承伤'], ['healing', '治疗'], ['kills', '击杀'], ['cards_played', '出牌'], ['cards_lost', '失牌'], ['skill_activations', '技能']];
        const mvpId = r.mvp ? r.mvp.player_id : null;
        box.innerHTML = '<table class="stats-table"><thead><tr><th>角色</th><th>身份</th>' + cols.map(c => '<th>' + c[1] + '</th>').join('') + '</tr></thead><tbody>' +
            players.map(p => {
                const s = p.stats || {};
                const hero = p.hero || {};
                const isMe = p.id === r.player_id || (r.player_id == null && !p.is_ai);
                return '<tr class="' + (isMe ? 'me ' : '') + (p.alive ? '' : 'dead') + '">' +
                    '<td><div class="who"><div class="mini-portrait">' + SGS.heroImgHTML(hero.id, hero.name || p.hero_name) + '</div>' +
                    '<div><b>' + esc((p.seat ? p.seat + '号 ' : '') + p.name) + (isMe ? '（你）' : '') + (p.id === mvpId ? ' <span style="color:var(--cinnabar-hi)">MVP</span>' : '') + '</b><small>' + esc(p.hero_name || '') + (p.alive ? '' : ' · 阵亡') + '</small></div></div></td>' +
                    '<td>' + SGS.identitySeal(p.identity) + '</td>' +
                    cols.map(c => '<td data-label="' + c[1] + '">' + (s[c[0]] || 0) + '</td>').join('') + '</tr>';
            }).join('') + '</tbody></table>';
    }

    const result = store.get('gameResult', null);
    if (!result || !result.winner) {
        document.getElementById('resultMain').innerHTML =
            '<div class="frame" style="padding:40px 20px;text-align:center;margin-top:30px">' +
            '<h1 class="brush gold-text" style="margin:0 0 10px">暂无战绩</h1>' +
            '<p class="muted">还没有完成的对局。去大厅开一局吧。</p>' +
            '<a class="btn primary" href="index.html" style="text-decoration:none;margin-top:12px">去大厅</a></div>';
        return;
    }
    render(result);
    // 再来一局：沿用上局配置（Key 仅在本标签页 sessionStorage 中），直接回到选将。
    document.getElementById('playAgainBtn').addEventListener('click', () => {
        const cfg = store.sget('gameConfig', null);
        location.href = cfg && Array.isArray(cfg.ais) ? 'select_hero.html' : 'index.html';
    });
    document.getElementById('backToLobbyBtn').addEventListener('click', () => { location.href = 'index.html'; });
    // 本局日志（服务端自动保存；无痕模式时没有）。
    const logBtn = document.getElementById('viewLogBtn');
    if (logBtn) {
        if (result.game_id && result.log_saved) logBtn.href = 'logs.html?game=' + encodeURIComponent(result.game_id);
        else logBtn.hidden = true;
    }
})();
