// 设置页：默认牌堆（/api/decks、/api/switch_deck）、运行时数据状态、自定义世界书、武将 JSON 预检。
(function () {
    'use strict';
    const { esc, store, toast } = SGS;

    document.getElementById('openGlobalSettings').addEventListener('click', () => window.openGlobalSettings && window.openGlobalSettings());

    // ---------- 运行时数据 ----------
    SGS.fetchJSON('/system_manifest.json').catch(() => ({})).then(data => {
        const items = [
            ['运行时武将', data.runtime_heroes], ['源武将数据', data.source_heroes], ['技能类', data.generated_skills],
            ['已接线技能', data.runtime_skill_implementations], ['卡牌种类', data.card_kinds]
        ];
        document.getElementById('stats').innerHTML = items.map(([k, v]) => '<div>' + k + '<b>' + esc(v ?? '?') + '</b></div>').join('');
    });

    // ---------- 世界书 ----------
    const getEntries = () => { const e = store.get('worldbook', []); return Array.isArray(e) ? e : []; };
    function saveEntries(entries) { store.set('worldbook', entries); renderEntries(); }
    function renderEntries() {
        const list = document.getElementById('worldbookList');
        const entries = getEntries();
        list.innerHTML = entries.length ? entries.map((e, i) =>
            '<div class="wb-entry"><h4>' + esc(e.title || e.id) + '</h4>' +
            '<small>关键词：' + esc((e.keywords || []).join('、') || '无') + (e.constant ? '　·　常驻' : '') + '</small>' +
            '<p>' + esc(e.content || '') + '</p>' +
            '<button class="btn small cancel" type="button" data-del="' + i + '">删除</button></div>').join('')
            : '<p class="muted" style="margin:0">还没有自定义条目。</p>';
        list.querySelectorAll('[data-del]').forEach(b => b.addEventListener('click', () => {
            const all = getEntries();
            all.splice(Number(b.dataset.del), 1);
            saveEntries(all);
            toast('已删除条目');
        }));
    }
    document.getElementById('wbAddBtn').addEventListener('click', () => {
        const title = document.getElementById('wbTitle').value.trim();
        const content = document.getElementById('wbContent').value.trim();
        if (!title || !content) { toast('标题和内容都要填写', { bad: true }); return; }
        const entries = getEntries();
        entries.push({
            id: 'custom_' + Date.now(),
            title: title,
            keywords: document.getElementById('wbKeywords').value.split(/[,，]/).map(x => x.trim()).filter(Boolean),
            content: content,
            constant: document.getElementById('wbConstant').checked
        });
        saveEntries(entries);
        ['wbTitle', 'wbKeywords', 'wbContent'].forEach(id => { document.getElementById(id).value = ''; });
        document.getElementById('wbConstant').checked = false;
        toast('已添加条目');
    });
    renderEntries();

    // ---------- 武将 JSON 预检 ----------
    document.getElementById('heroFile').addEventListener('change', async function () {
        const out = document.getElementById('heroValidation');
        if (!this.files || !this.files[0]) return;
        try {
            const raw = JSON.parse(await this.files[0].text());
            const heroes = Array.isArray(raw) ? raw : (raw.heroes || [raw]);
            const ids = new Set(); const errors = []; let skills = 0;
            heroes.forEach((h, i) => {
                if (!h.id || !h.name || !h.faction || !h.max_hp) errors.push('第' + (i + 1) + '项缺少 id / name / faction / max_hp');
                if (ids.has(h.id)) errors.push('重复 ID：' + h.id);
                ids.add(h.id);
                if (!Array.isArray(h.skills)) errors.push((h.name || h.id) + ' 缺少 skills 数组');
                else skills += h.skills.length;
            });
            out.textContent = '武将数：' + heroes.length + '\n技能数：' + skills + '\n唯一 ID：' + ids.size + '\n结果：' +
                (errors.length ? '未通过\n' + errors.join('\n') : '预检通过（尚未写入服务器运行时数据）');
            if (!errors.length) store.set('imported_heroes_candidate', heroes);
        } catch (e) {
            out.textContent = '解析失败：' + e.message;
        }
    });

    // ---------- 牌堆：选项由服务器 /api/decks 提供 ----------
    async function loadDeckSetting() {
        const box = document.getElementById('deckOptions');
        try {
            const data = await SGS.fetchJSON('/api/decks');
            if (!data.success || !Array.isArray(data.decks)) throw new Error(data.message || '返回格式不正确');
            const checkedId = data.active_deck;
            box.innerHTML = data.decks.map(d =>
                '<label class="deck-option"><input type="radio" name="deck" value="' + esc(d.id) + '"' + (d.id === checkedId ? ' checked' : '') + '>' +
                '<span><b>' + esc(d.name) + '（' + d.cards_count + ' 张）</b><small>' + esc(d.description || '') + '</small></span></label>').join('');
        } catch (e) {
            box.innerHTML = '<p class="muted">牌堆列表读取失败：' + esc(e.message) + '。请确认服务器已启动后刷新本页。</p>';
        }
    }
    document.getElementById('saveDeckBtn').addEventListener('click', () => {
        const selected = document.querySelector('input[name=deck]:checked');
        const status = document.getElementById('deckStatus');
        if (!selected) { status.textContent = '请先选择一个牌堆'; return; }
        fetch('/api/switch_deck', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ deck_id: selected.value })
        }).then(r => r.json()).then(data => {
            if (!data.success) { status.textContent = '切换失败：' + (data.message || '未知错误'); return; }
            const deckId = data.active_deck || selected.value;
            try { localStorage.setItem('active_deck', deckId); } catch (_) {}
            store.remove('active_deck_choice');
            status.textContent = data.message;
            toast('牌堆设置已保存');
        }).catch(e => { status.textContent = '网络错误：' + e.message; });
    });
    loadDeckSetting();
})();
