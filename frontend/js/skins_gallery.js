// =============================================================================
// 皮肤画廊：武将网格 -> 点一名武将 -> 皮肤面板（默认 / 已导入 / noname 候选 / 自定义导入）。
// 所有数据都在服务器档案里；浏览器只认 hero_id + skin_id。不含任何规则判断。
// =============================================================================
(function () {
    'use strict';
    const $ = (id) => document.getElementById(id);
    const esc = SGS.esc;
    const WRITE = { 'X-SGS-Skin': '1' };
    const MAX_BYTES = 2 * 1024 * 1024, MIN_EDGE = 64, MAX_EDGE = 2048;
    const PROFILE_RE = /^[A-Za-z0-9_-]{1,128}$/;

    let heroes = [];
    let catalog = { heroes: {} };
    let catalogError = '';
    let state = { selection: {}, uploads: [] };
    let faction = '', query = '';
    let openId = null, lastFocus = null;
    let busyKey = '', failedKeys = new Set();
    let confirmSwitch = false;

    // ------------------------------------------------------------ 档案
    function profileId() {
        let id = SGS.store.get('profileId', '');
        if (!PROFILE_RE.test(id)) {
            // 与大厅生成档案的方式一致，直接打开皮肤页也能得到可用档案
            id = (window.crypto && crypto.randomUUID) ? crypto.randomUUID().replace(/-/g, '_')
                : 'p_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2);
            SGS.store.set('profileId', id);
        }
        return id;
    }
    const PROFILE = profileId();

    // ------------------------------------------------------------ 请求
    async function api(path, init) {
        let response;
        try { response = await fetch(path, Object.assign({ cache: 'no-store' }, init || {})); }
        catch (_) { throw new Error('连不上游戏服务器，请确认服务器已启动。'); }
        let data = null;
        try { data = await response.json(); } catch (_) {}
        if (!response.ok || !data || data.success === false) throw new Error((data && data.message) || ('服务器返回 ' + response.status));
        return data;
    }
    function postJSON(path, body) {
        return api(path, { method: 'POST', headers: Object.assign({ 'Content-Type': 'application/json' }, WRITE), body: JSON.stringify(body) });
    }

    function applyState(next) {
        state = { selection: next.selection || {}, uploads: next.uploads || [] };
        SGS.setSkinMap(SGS.skinMapFromState(state), PROFILE);   // 头像地址表同步，其它页面立即可用
        renderGrid();
        if (openId) renderPanel();
    }

    // ------------------------------------------------------------ 武将网格
    function heroById(id) { return heroes.find(h => h.id === id); }
    function shortName(h) { return String(h.name || h.id); }
    function renderGrid() {
        const box = $('skHeroGrid');
        const q = query.trim();
        const list = heroes.filter(h => (!faction || h.faction === faction) &&
            (!q || shortName(h).includes(q) || String(h.title || '').includes(q)));
        if (!list.length) { box.innerHTML = '<p class="muted">没有符合条件的武将。</p>'; return; }
        box.innerHTML = list.map(h => {
            const changed = !!state.selection[h.id];
            return '<button type="button" class="sk-hero faction-' + esc(h.faction || '群') + '" data-hero="' + esc(h.id) + '" aria-label="' + esc(shortName(h)) + '，' + esc(h.faction || '群') +
                '势力，打开皮肤' + (changed ? '（已换皮）' : '') + '">' +
                (changed ? '<span class="sk-hero-tag">已换皮</span>' : '') +
                '<span class="sk-hero-art">' + SGS.heroImgHTML(h.id, shortName(h)) + '</span>' +
                '<span class="sk-hero-meta">' + SGS.factionSeal(h.faction) + '<b>' + esc(shortName(h)) + '</b></span></button>';
        }).join('');
    }

    // ------------------------------------------------------------ 面板
    function tilesFor(id) {
        const tiles = [{ skinId: null, label: '默认原画', url: SGS.defaultHeroImageURL(id), kind: 'default' }];
        state.uploads.filter(u => u.hero_id === id).forEach(u => tiles.push({ skinId: u.skin_id, label: u.label || '我的图片', url: u.url, kind: 'upload' }));
        ((catalog.heroes || {})[id] || []).forEach(c => tiles.push({ skinId: c.skin_id, label: c.label, url: c.url, kind: 'noname' }));
        return tiles;
    }
    function currentSkinId(id) { return state.selection[id] ? state.selection[id].skin_id : null; }

    function renderPanel() {
        const h = heroById(openId);
        if (!h) return;
        const current = currentSkinId(openId);
        const tiles = tilesFor(openId);
        const cur = tiles.find(t => t.skinId === current) || tiles[0];
        $('skPanelTitle').textContent = shortName(h);
        $('skPanelSub').textContent = (h.faction || '群') + '势力 · 当前：' + cur.label;
        $('skCurrentArt').innerHTML = '<img src="' + esc(cur.url) + '" alt="' + esc(shortName(h)) + '当前皮肤" onerror="this.onerror=null;this.src=\'' + esc(SGS.defaultHeroImageURL(openId)) + '\'">';
        $('skResetBtn').disabled = current === null;
        const html = tiles.map(t => {
            const on = t.skinId === current;
            const key = openId + '/' + t.skinId;
            const cls = 'sk-tile' + (busyKey === key ? ' busy' : '') + (failedKeys.has(key) ? ' failed' : '');
            const lazy = t.kind === 'default' ? '' : ' loading="lazy" decoding="async"';
            return '<div class="sk-tile-wrap"><button type="button" class="' + cls + '" data-skin="' + esc(t.skinId || '') + '" data-kind="' + t.kind + '" aria-pressed="' + on + '" aria-label="' +
                esc(t.label) + (on ? '，使用中' : '，点一下使用') + '">' +
                '<span class="sk-tile-art">' + (on ? '<span class="sk-badge">✓ 使用中</span>' : '') +
                '<img src="' + esc(t.url) + '" alt=""' + lazy + ' data-tile-url="' + esc(t.url) + '"></span>' +
                '<span class="sk-tile-cap">' + esc(t.label) + '</span></button>' +
                (t.kind === 'upload' ? '<button type="button" class="sk-del" data-del="' + esc(t.skinId) + '" aria-label="删除 ' + esc(t.label) + '"><span class="ic" data-icon="close"></span></button>' : '') + '</div>';
        }).join('') +
            '<div class="sk-tile-wrap"><button type="button" class="sk-tile sk-tile-import' + (busyKey === 'import' ? ' busy' : '') + '" id="skImportTile" aria-label="自定义导入一张本地图片">' +
            '<span class="sk-tile-art">＋</span><span class="sk-tile-cap">自定义导入</span></button></div>';
        const scroller = document.querySelector('.sk-tile-scroll');
        const top = scroller ? scroller.scrollTop : 0;
        $('skTiles').innerHTML = html;
        if (scroller) scroller.scrollTop = top;
        SGS.hydrateIcons($('skTiles'));
        if (catalogError && !$('skPanelStatus').textContent) setStatus(catalogError, true);
    }

    function setStatus(text, bad) {
        const el = $('skPanelStatus');
        el.textContent = text || '';
        el.classList.toggle('bad', !!bad);
    }

    function openPanel(id) {
        if (!heroById(id)) return;
        openId = id;
        lastFocus = document.activeElement;
        setStatus('');
        failedKeys = new Set();
        $('skSheet').hidden = false;
        document.body.classList.add('sk-lock');
        renderPanel();
        $('skSheet').querySelector('.sk-panel').focus({ preventScroll: true });
    }
    function closePanel() {
        $('skSheet').hidden = true;
        document.body.classList.remove('sk-lock');
        openId = null;
        if (lastFocus && lastFocus.isConnected) { try { lastFocus.focus({ preventScroll: true }); } catch (_) {} }
    }

    async function choose(skinId, kind) {
        const id = openId;
        if (!id || busyKey) return;
        if ((currentSkinId(id) || null) === (skinId || null)) { setStatus('这张已经在使用中。'); return; }
        const key = id + '/' + skinId;
        busyKey = key;
        failedKeys.delete(key);
        setStatus(kind === 'noname' ? '正在准备这张图（首次使用时服务器会从 GitHub 下载）…' : '正在保存…');
        renderPanel();
        try {
            const next = await postJSON('/api/skins/select', { profile_id: PROFILE, hero_id: id, skin_id: skinId });
            busyKey = '';
            applyState(next);
            const row = tilesFor(id).find(t => t.skinId === skinId);
            setStatus('已换上：' + (row ? row.label : '新皮肤') + '。');
        } catch (error) {
            busyKey = '';
            if (kind === 'noname') failedKeys.add(key);
            setStatus(error.message, true);
            renderPanel();
        }
    }

    async function resetDefault() {
        const id = openId;
        if (!id || busyKey || currentSkinId(id) === null) return;
        try {
            applyState(await postJSON('/api/skins/select', { profile_id: PROFILE, hero_id: id, skin_id: null }));
            setStatus('已恢复默认原画。');
        } catch (error) { setStatus(error.message, true); }
    }

    async function deleteUpload(skinId) {
        if (!window.confirm('删除这张导入的图片？删除后无法恢复。')) return;
        try {
            applyState(await postJSON('/api/skins/delete', { profile_id: PROFILE, skin_id: skinId }));
            setStatus('已删除。');
        } catch (error) { setStatus(error.message, true); }
    }

    // ------------------------------------------------------------ 自定义导入
    async function inspectFile(file) {
        if (!file) throw new Error('请选择一张本地图片。');
        if (file.size <= 0 || file.size > MAX_BYTES) throw new Error('图片大小必须在 1 字节到 2 MiB 之间。');
        const b = new Uint8Array(await file.slice(0, 16).arrayBuffer());
        let type = '';
        if (b.length >= 8 && b[0] === 0x89 && b[1] === 0x50 && b[2] === 0x4e && b[3] === 0x47) type = 'image/png';
        else if (b.length >= 3 && b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff) type = 'image/jpeg';
        else if (b.length >= 12 && String.fromCharCode(...b.slice(0, 4)) === 'RIFF' && String.fromCharCode(...b.slice(8, 12)) === 'WEBP') type = 'image/webp';
        if (!type) throw new Error('只接受真实的 PNG、JPEG 或 WebP 图片。');
        if (typeof createImageBitmap === 'function') {
            let bitmap;
            try { bitmap = await createImageBitmap(file); } catch (_) { throw new Error('图片无法解码，文件可能已损坏。'); }
            const w = bitmap.width, h = bitmap.height;
            if (bitmap.close) bitmap.close();
            if (w < MIN_EDGE || h < MIN_EDGE || w > MAX_EDGE || h > MAX_EDGE) throw new Error('图片宽高必须各在 64 到 2048 像素之间（这张是 ' + w + '×' + h + '）。');
        }
        return type;       // 没有 createImageBitmap 的老内核：尺寸交给服务器校验
    }

    async function importFile(file) {
        const id = openId;
        if (!id || busyKey) return;
        try {
            setStatus('正在检查图片…');
            const type = await inspectFile(file);
            busyKey = 'import';
            renderPanel();
            setStatus('正在上传…');
            const label = String(file.name || '我的图片').replace(/\.[A-Za-z0-9]{1,5}$/, '').slice(0, 40);
            const next = await api('/api/skins/upload?profile_id=' + encodeURIComponent(PROFILE) + '&hero_id=' + encodeURIComponent(id) +
                '&label=' + encodeURIComponent(label) + '&select=1', { method: 'POST', headers: Object.assign({ 'Content-Type': type }, WRITE), body: file });
            busyKey = '';
            applyState(next);
            setStatus('已导入并设为使用中。');
        } catch (error) {
            busyKey = '';
            setStatus(error.message, true);
            if (openId) renderPanel();
        }
    }

    // 候选缩略图加载失败：向服务器取一次明确原因（<img> 本身拿不到错误信息）
    async function explainTileFailure(img) {
        const tile = img.closest('.sk-tile');
        if (!tile || tile.dataset.kind !== 'noname') return;
        const key = openId + '/' + tile.dataset.skin;
        failedKeys.add(key);
        tile.classList.add('failed');
        try {
            const response = await fetch(img.dataset.tileUrl, { cache: 'no-store' });
            const data = await response.json().catch(() => null);
            setStatus((data && data.message) || '这张候选图暂时打不开。', true);
        } catch (_) { setStatus('连不上游戏服务器，请确认服务器已启动。', true); }
    }

    // ------------------------------------------------------------ 迁移提示
    function showMigration(result) {
        const box = $('skMigrate');
        if (!result || ['no-profile', 'none'].includes(result.state) || (result.state === 'done' && result.already)) { box.hidden = true; return; }
        box.hidden = false;
        if (result.state === 'done') {
            box.innerHTML = '<span>已把此浏览器里的旧皮肤搬到服务器档案：成功 ' + result.uploaded + ' 张' +
                (result.rejected ? '，被服务器拒收 ' + result.rejected + ' 张（格式或尺寸不合规）' : '') + (result.unbound ? '，另有 ' + result.unbound + ' 张未绑定武将的图片没有迁移' : '') + '。</span>';
        } else {
            box.innerHTML = '<span>旧皮肤迁移没有全部完成（' + (result.retry || 0) + ' 张暂未上传），旧数据仍完整保留在此浏览器。</span><button type="button" class="btn small" id="skRetryMigrate">重试迁移</button>';
        }
    }
    async function migrate() {
        const box = $('skMigrate');
        box.hidden = false;
        box.textContent = '正在检查此浏览器里的旧皮肤…';
        const result = await SkinSync.ensureMigrated(p => { box.textContent = '正在把旧皮肤迁移到服务器… ' + p.index + '/' + p.total; });
        showMigration(result);
        try { applyState(await api('/api/skins?profile_id=' + encodeURIComponent(PROFILE))); } catch (_) {}
        refreshLocalClean();
    }
    async function refreshLocalClean() {
        const flag = SkinSync.flag();
        $('skLocalClean').hidden = !(flag && flag.local > 0 && await SkinSync.hasLocalCopy());
    }

    // ------------------------------------------------------------ 档案同步
    function initSync() {
        $('skProfileId').textContent = PROFILE;
        $('skCopyProfile').addEventListener('click', async () => {
            try { await navigator.clipboard.writeText(PROFILE); $('skSyncMsg').textContent = '已复制。'; }
            catch (_) { const r = document.createRange(); r.selectNodeContents($('skProfileId')); const s = getSelection(); s.removeAllRanges(); s.addRange(r); $('skSyncMsg').textContent = '已选中，请长按复制。'; }
        });
        $('skSwitchProfile').addEventListener('click', async () => {
            const value = $('skOtherProfile').value.trim();
            const msg = $('skSyncMsg');
            if (!PROFILE_RE.test(value)) { msg.textContent = '档案 ID 只能包含字母、数字、下划线和短横线（1–128 位）。'; confirmSwitch = false; return; }
            if (value === PROFILE) { msg.textContent = '这已经是当前档案。'; return; }
            if (!confirmSwitch) { confirmSwitch = true; $('skSwitchProfile').textContent = '再点一次确认切换'; msg.textContent = '切换后战绩和 AI 档案也会变成该档案的。'; return; }
            SGS.store.set('profileId', value);
            SGS.store.remove('skinMap');
            location.reload();
        });
        $('skCleanLocal').addEventListener('click', async () => {
            if (!window.confirm('清理此浏览器里的旧版本地皮肤副本？皮肤已在服务器上，清理后不影响使用。')) return;
            const ok = await SkinSync.clearLocal();
            $('skSyncMsg').textContent = ok ? '已清理旧副本。' : '清理失败，请关闭其他打开着游戏的标签页后重试。';
            refreshLocalClean();
        });
    }

    // ------------------------------------------------------------ 事件与启动
    function bind() {
        $('skHeroGrid').addEventListener('click', (e) => { const b = e.target.closest('.sk-hero'); if (b) openPanel(b.dataset.hero); });
        $('skSearch').addEventListener('input', (e) => { query = e.target.value; renderGrid(); });
        $('skFaction').addEventListener('click', (e) => {
            const b = e.target.closest('button[data-faction]');
            if (!b) return;
            faction = b.dataset.faction;
            document.querySelectorAll('#skFaction button').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
            renderGrid();
        });
        $('skSheet').addEventListener('click', (e) => { if (e.target.closest('[data-close]')) closePanel(); });
        $('skClose').addEventListener('click', closePanel);
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !$('skSheet').hidden) closePanel();
            if (e.key === 'Tab' && !$('skSheet').hidden) {      // 焦点留在面板内
                const items = [...$('skSheet').querySelectorAll('button:not(:disabled), input:not([hidden])')].filter(el => el.offsetParent !== null);
                if (!items.length) return;
                const first = items[0], last = items[items.length - 1];
                if (e.shiftKey && (document.activeElement === first || document.activeElement.classList.contains('sk-panel'))) { e.preventDefault(); last.focus(); }
                else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
            }
        });
        $('skTiles').addEventListener('click', (e) => {
            const del = e.target.closest('.sk-del');
            if (del) { deleteUpload(del.dataset.del); return; }
            if (e.target.closest('#skImportTile')) { $('skFile').click(); return; }
            const tile = e.target.closest('.sk-tile');
            if (tile) choose(tile.dataset.skin || null, tile.dataset.kind);
        });
        // error 事件不冒泡，用捕获阶段统一接
        $('skTiles').addEventListener('error', (e) => { if (e.target && e.target.tagName === 'IMG') explainTileFailure(e.target); }, true);
        $('skResetBtn').addEventListener('click', resetDefault);
        $('skImportTop').addEventListener('click', () => $('skFile').click());
        $('skFile').addEventListener('change', (e) => {
            const file = e.target.files && e.target.files[0];
            e.target.value = '';
            if (file) importFile(file);
        });
        $('skMigrate').addEventListener('click', (e) => { if (e.target.id === 'skRetryMigrate') migrate(); });
    }

    async function init() {
        bind();
        initSync();
        try {
            const [heroData, stateData] = await Promise.all([
                api('/api/heroes'), api('/api/skins?profile_id=' + encodeURIComponent(PROFILE))
            ]);
            heroes = (heroData.heroes || []).map(h => ({ id: h.id, name: h.name, faction: h.faction, title: h.title }));
            applyState(stateData);
        } catch (error) {
            $('skHeroGrid').innerHTML = '';
            $('skError').hidden = false;
            $('skError').textContent = error.message;
            return;
        }
        try { catalog = await api('/api/skins/catalog'); }
        catch (error) { catalogError = 'noname 候选目录读取失败：' + error.message; }
        migrate().catch(() => {});
        const params = new URLSearchParams(location.search);
        if (params.get('hero') && heroById(params.get('hero'))) openPanel(params.get('hero'));
    }
    init();
})();
