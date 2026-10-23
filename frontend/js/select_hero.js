// 选将页：读取 /data/heroes.json（与 data/heroes.json 同源），选中后写回开局配置并进入对局。
// 单击选中、双击直接出战；右侧显示武将全部技能。
(function () {
    'use strict';
    const { esc, store, toast } = SGS;

    const SKILL_TAG = { lord: '主公技', locked: '锁定技', limited: '限定技', awaken: '觉醒技', active: '主动技', trigger: '被动' };
    let heroes = [];
    let faction = '';
    let selected = null;

    // 开局配置：本标签页的 sessionStorage 优先（含 Key），其次 localStorage（不含 Key）。
    function readConfig() {
        return store.sget('gameConfig', null) || store.get('gameConfig', null);
    }

    // 按势力筛选渲染武将卡（立绘 + 势力印 + 勾玉 + 名字）。
    function render() {
        const grid = document.getElementById('heroGrid');
        const list = heroes.filter(h => !faction || h.faction === faction);
        if (!list.length) {
            grid.innerHTML = '<div class="empty-pick">这个势力暂无武将</div>';
            return;
        }
        grid.innerHTML = list.map(h =>
            '<button type="button" class="hero-card faction-' + esc(h.faction) + '" data-id="' + esc(h.id) + '" aria-pressed="' + (selected && selected.id === h.id) + '" aria-label="' + esc(h.name) + '">' +
            SGS.heroImgHTML(h.id, h.name) +
            SGS.factionSeal(h.faction) +
            '<span class="hc-hp">' + SGS.hpHTML(h.max_hp, h.max_hp, { vertical: true }) + '</span>' +
            '<span class="hc-name">' + esc(h.name) + '</span></button>').join('');
        grid.querySelectorAll('.hero-card').forEach(btn => {
            btn.addEventListener('click', () => select(btn.dataset.id));
            btn.addEventListener('dblclick', () => { select(btn.dataset.id); confirm(); });
        });
    }

    // 选中武将：高亮卡片，并在右侧显示称号、体力与全部技能。
    function select(id) {
        selected = heroes.find(h => h.id === id) || null;
        document.querySelectorAll('.hero-card').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.id === id)));
        const box = document.getElementById('heroDetail');
        if (!selected) return;
        const h = selected;
        box.innerHTML =
            '<div class="hd-top">' +
            '<div class="hd-portrait">' + SGS.heroImgHTML(h.id, h.name) + '</div>' +
            '<div><h2>' + esc(h.name) + '</h2>' +
            '<div class="hd-title">' + esc(h.title || '') + '</div>' +
            '<div class="row">' + SGS.factionSeal(h.faction) + SGS.hpHTML(h.max_hp, h.max_hp) + '<span class="muted" style="font-size:13px">体力 ' + h.max_hp + '</span></div></div>' +
            '</div>' +
            '<div class="skill-list">' + (h.skills || []).map(s =>
                '<div class="skill-item"><b>' + esc(s.name) + '</b>' +
                (SKILL_TAG[s.type] && s.type !== 'trigger' ? '<span class="tag">' + SKILL_TAG[s.type] + '</span>' : '') +
                '<div>' + esc(s.description || '') + '</div></div>').join('') + '</div>' +
            '<button type="button" class="btn primary big" id="confirmBtn">出战</button>';
        document.getElementById('confirmBtn').addEventListener('click', confirm);
        if (window.matchMedia('(max-width: 960px)').matches) box.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    // 出战：把武将写回开局配置（session 与 local 两份），进入对局页。
    function confirm() {
        if (!selected) { toast('请先选择一位武将', { bad: true }); return; }
        const cfg = readConfig();
        if (!cfg || !Array.isArray(cfg.ais)) {
            toast('开局配置丢失，正在返回大厅', { bad: true });
            setTimeout(() => { location.href = 'index.html'; }, 900);
            return;
        }
        cfg.selected_hero = selected;
        store.sset('gameConfig', cfg);
        const local = store.get('gameConfig', {}) || {};
        local.selected_hero = selected;
        store.set('gameConfig', local);
        location.href = 'game.html';
    }

    document.getElementById('factionTabs').addEventListener('click', (e) => {
        const btn = e.target.closest('button[data-faction]');
        if (!btn) return;
        faction = btn.dataset.faction;
        document.querySelectorAll('#factionTabs button').forEach(b => b.setAttribute('aria-pressed', String(b === btn)));
        render();
    });

    SGS.fetchJSON('/api/heroes').then(data => {
        heroes = Array.isArray(data) ? data : (data.heroes || []);
        render();
        const cfg = readConfig();
        if (cfg && cfg.selected_hero && cfg.selected_hero.id) select(cfg.selected_hero.id);
    }).catch(err => {
        document.getElementById('heroGrid').innerHTML =
            '<div class="empty-pick">武将数据加载失败（' + esc(err.message) + '）。<br>请确认游戏服务已启动，然后<a href="">刷新页面</a>。</div>';
    });
})();
