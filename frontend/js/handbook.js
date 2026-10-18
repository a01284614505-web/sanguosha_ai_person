// 图鉴页：列出全部 42 种卡牌（说明来自 card_info.js）与 27 名武将（来自 /data/heroes.json）。
// 纯展示，不影响对局。
(function () {
    'use strict';
    const { esc } = SGS;

    // ---------- 标签页切换 ----------
    function showTab(which) {
        const cards = which === 'cards';
        document.getElementById('tabCards').setAttribute('aria-selected', String(cards));
        document.getElementById('tabHeroes').setAttribute('aria-selected', String(!cards));
        document.getElementById('paneCards').hidden = !cards;
        document.getElementById('paneHeroes').hidden = cards;
        try { history.replaceState(null, '', cards ? '#cards' : '#heroes'); } catch (_) {}
    }
    document.getElementById('tabCards').addEventListener('click', () => showTab('cards'));
    document.getElementById('tabHeroes').addEventListener('click', () => showTab('heroes'));
    if (location.hash === '#heroes') showTab('heroes');

    // ---------- 卡牌 ----------
    // 图鉴里的牌没有具体花色点数，只画牌面与名称；类型签按 card_info 的分类换算成 card_type。
    function cardType(info) {
        if (!info) return 'basic';
        if (info.type === '基本') return 'basic';
        if (/武器|防具|坐骑|宝物/.test(info.type)) return 'equipment';
        return 'trick';
    }
    function renderCards() {
        const pane = document.getElementById('paneCards');
        pane.innerHTML = SGS_CARD_GROUPS.map(([group, names]) =>
            '<div class="hb-group"><h2 class="section-title">' + esc(group) + '</h2><div class="hb-cards">' +
            names.map(name => {
                // 火杀 / 雷杀不是独立牌名，是带属性的【杀】：说明取 NATURE_INFO，牌面按 nature 画
                const nature = Object.keys(SGS.NATURE_INFO).find(k => SGS.NATURE_INFO[k].name === name) || '';
                const info = nature ? SGS.NATURE_INFO[nature] : (SGS_CARD_INFO[name] || {});
                const tags = ['<span class="hb-tag">' + esc(info.type || '') + '</span>'];
                if (info.range) tags.push('<span class="hb-tag">攻击范围 ' + info.range + '</span>');
                if (info.horse) tags.push('<span class="hb-tag">距离 ' + esc(info.horse) + '</span>');
                return '<article class="frame hb-card">' +
                    SGS.cardHTML({ name: nature ? '杀' : name, nature: nature, card_type: cardType(info) }, { noDetail: true }) +
                    '<div><h3>' + esc(name) + '</h3>' + tags.join('') +
                    '<p>' + esc(info.text || '') + '</p>' +
                    (info.pending ? '<div class="hb-note">引擎暂未实现此装备特效' + (info.range ? '，目前只生效攻击范围' : '') + '。</div>' : '') +
                    '</div></article>';
            }).join('') + '</div></div>').join('');
    }
    renderCards();

    // ---------- 武将 ----------
    let heroes = [];
    let faction = '';
    function renderHeroes() {
        const q = document.getElementById('heroSearch').value.trim();
        const list = heroes.filter(h => (!faction || h.faction === faction) &&
            (!q || h.name.includes(q) || (h.title || '').includes(q) || (h.skills || []).some(s => s.name.includes(q) || (s.description || '').includes(q))));
        const box = document.getElementById('heroList');
        if (!list.length) { box.innerHTML = '<p class="muted">没有符合条件的武将。</p>'; return; }
        box.innerHTML = list.map(h =>
            '<article class="frame hb-hero faction-' + esc(h.faction) + '">' +
            '<div class="hb-portrait">' + SGS.heroImgHTML(h.id, h.name) + '</div>' +
            '<div><h3>' + SGS.factionSeal(h.faction) + esc(h.name) + ' <small>' + esc(h.title || '') + '</small></h3>' +
            '<div class="row" style="margin:4px 0">' + SGS.hpHTML(h.max_hp, h.max_hp) + '<span class="muted" style="font-size:12.5px">体力 ' + h.max_hp + '</span></div>' +
            (h.skills || []).map(s => '<div class="skill-item"><b>' + esc(s.name) + '</b>' +
                (SGS.SKILL_TAG[s.type] && s.type !== 'trigger' ? '<span class="tag">' + SGS.SKILL_TAG[s.type] + '</span>' : '') +
                '<div>' + esc(s.description || '') + '</div></div>').join('') +
            '</div></article>').join('');
    }
    document.getElementById('heroSearch').addEventListener('input', renderHeroes);
    document.getElementById('heroFaction').addEventListener('click', (e) => {
        const btn = e.target.closest('button[data-faction]');
        if (!btn) return;
        faction = btn.dataset.faction;
        document.querySelectorAll('#heroFaction button').forEach(b => b.setAttribute('aria-pressed', String(b === btn)));
        renderHeroes();
    });
    SGS.fetchJSON('/data/heroes.json').then(data => {
        heroes = Array.isArray(data) ? data : (data.heroes || []);
        renderHeroes();
    }).catch(err => {
        document.getElementById('heroList').innerHTML = '<p class="muted">武将数据读取失败（' + esc(err.message) + '），请确认游戏服务已启动。</p>';
    });
})();
