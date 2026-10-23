(function () {
    'use strict';
    const $ = id => document.getElementById(id);
    const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[c]);
    let scanned = null;
    let previewURL = null;
    let sourcePreviewURL = null;
    let sourceCatalog = null;
    let sourceSelection = null;
    let sourceFile = null;
    let heroes = [];

    function setStatus(message, error) {
        const status = $('skinStatus');
        status.textContent = message;
        status.classList.toggle('bad', !!error);
    }

    async function loadHeroes() {
        const list = $('skinHeroIds');
        try {
            const response = await fetch('/api/heroes', { cache: 'no-store' });
            const data = await response.json();
            if (!response.ok || !Array.isArray(data.heroes)) throw new Error('武将列表不可用');
            heroes = data.heroes;
            list.innerHTML = heroes.map(hero => '<option value="' + esc(hero.id) + '">' + esc(hero.name || hero.id) + '</option>').join('');
            $('skinHeroId').dispatchEvent(new Event('change'));
        } catch (_) {
            list.innerHTML = '';
        }
    }

    function clearSourcePreview() {
        if (sourcePreviewURL) URL.revokeObjectURL(sourcePreviewURL);
        sourcePreviewURL = null;
        sourceFile = null;
        $('sourceSkinPreview').replaceChildren();
        $('sourceSkinPreview').appendChild(document.createTextNode('选择并预览一张候选图'));
        $('importSourceSkinBtn').disabled = true;
    }

    function renderSourceChoices() {
        const select = $('sourceSkinChoice');
        clearSourcePreview();
        const id = $('skinHeroId').value.trim();
        const rows = sourceCatalog ? sourceCatalog.items.filter(item => item.hero_id === id) : [];
        select.replaceChildren(new Option(rows.length ? `选择候选图（${rows.length} 张）` : '没有该武将的候选图', ''));
        rows.forEach((item, index) => {
            const option = new Option(`${String(index + 1).padStart(2, '0')} · ${item.filename} · ${(item.bytes / 1024).toFixed(0)} KiB`, String(index));
            select.add(option);
        });
        select.disabled = rows.length === 0;
        $('previewSourceSkinBtn').disabled = rows.length === 0;
        $('sourceSkinMeta').textContent = rows.length
            ? `武将 ${id} · ${rows.length} 张可选 · 提交 ${sourceCatalog.source_commit.slice(0, 12)} · 选择后才从上游加载图片。`
            : '目录只包含固定提交中与项目 27 名武将对应的图片。';
        sourceSelection = null;
    }

    async function loadSourceCatalog() {
        const select = $('sourceSkinChoice');
        try {
            const response = await fetch('data/noname_skin_candidates.json', { cache: 'no-cache' });
            if (!response.ok) throw new Error('候选目录暂不可用。');
            sourceCatalog = await response.json();
            if (!Array.isArray(sourceCatalog.items) || sourceCatalog.items.length !== 307) throw new Error('候选目录校验失败。');
            select.disabled = false;
            renderSourceChoices();
        } catch (error) {
            select.replaceChildren(new Option(error.message, ''));
            $('sourceSkinMeta').textContent = '读取本地候选目录失败。';
        }
    }

    async function previewSourceSkin() {
        const id = $('skinHeroId').value.trim();
        const rows = sourceCatalog && sourceCatalog.items.filter(item => item.hero_id === id);
        const item = rows && rows[Number($('sourceSkinChoice').value)];
        if (!item) return;
        clearSourcePreview();
        sourceSelection = item;
        $('previewSourceSkinBtn').disabled = true;
        $('sourceSkinMeta').textContent = `正在从固定来源加载 ${item.path}…`;
        try {
            const response = await fetch(item.url, { mode: 'cors', cache: 'force-cache' });
            if (!response.ok) throw new Error(`来源返回 HTTP ${response.status}。`);
            const blob = await response.blob();
            if (blob.size !== item.bytes) throw new Error('下载大小与来源清单不符。');
            const bytes = await blob.arrayBuffer();
            const prefix = new TextEncoder().encode(`blob ${bytes.byteLength}\0`);
            const payload = new Uint8Array(prefix.length + bytes.byteLength);
            payload.set(prefix);
            payload.set(new Uint8Array(bytes), prefix.length);
            const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-1', payload)))
                .map(value => value.toString(16).padStart(2, '0')).join('');
            if (digest !== item.git_blob_sha1) throw new Error('来源内容 SHA-1 校验失败。');
            sourceFile = new File([blob], item.filename, { type: 'image/jpeg' });
            const meta = await LocalHeroSkins.inspectFile(sourceFile);
            sourcePreviewURL = URL.createObjectURL(blob);
            const image = document.createElement('img');
            image.alt = `${id} 候选原画预览`;
            image.src = sourcePreviewURL;
            $('sourceSkinPreview').replaceChildren(image);
            $('sourceSkinMeta').textContent = `${item.path} · ${meta.width}×${meta.height} · ${(meta.size / 1024).toFixed(1)} KiB · Git blob SHA 已校验`;
            $('importSourceSkinBtn').disabled = false;
        } catch (error) {
            $('sourceSkinPreview').textContent = '无法预览该候选图';
            $('sourceSkinMeta').textContent = `${item.path} · ${error.message}`;
            sourceFile = null;
        } finally {
            $('previewSourceSkinBtn').disabled = false;
        }
    }

    async function importSourceSkin() {
        if (!sourceSelection || !sourceFile) return;
        const id = $('skinHeroId').value.trim();
        if (sourceSelection.hero_id !== id) return;
        try {
            await LocalHeroSkins.importAndBind(id, sourceFile, `noname · ${sourceSelection.path}`);
            await refreshLibrary();
            LocalHeroSkins.applyImages(document);
            setStatus(`已导入并应用到 ${id}。图片来自固定历史提交，保存在本浏览器。`, false);
        } catch (error) { setStatus(error.message, true); }
    }

    function chosenFile() { return $('skinFile').files && $('skinFile').files[0]; }

    async function scan() {
        const file = chosenFile();
        $('importSkinBtn').disabled = true;
        scanned = null;
        if (previewURL) URL.revokeObjectURL(previewURL);
        previewURL = null;
        $('skinPreview').replaceChildren();
        try {
            if (!file) throw new Error('请先选择一张图片。');
            const meta = await LocalHeroSkins.inspectFile(file);
            previewURL = URL.createObjectURL(file);
            const image = document.createElement('img');
            image.alt = '本地图片预览';
            image.src = previewURL;
            $('skinPreview').appendChild(image);
            $('skinFileInfo').textContent = file.name + ' · ' + meta.type + ' · ' + meta.width + '×' + meta.height +
                ' · ' + (meta.size / 1024).toFixed(1) + ' KiB';
            scanned = { file, meta };
            $('importSkinBtn').disabled = false;
            setStatus('图片类型、文件内容与解码尺寸检查通过。', false);
        } catch (error) {
            $('skinPreview').innerHTML = '<span class="muted">无法预览</span>';
            $('skinFileInfo').textContent = error.message;
            setStatus(error.message, true);
        }
    }

    async function refreshLibrary() {
        const root = $('skinLibrary');
        try {
            const items = await LocalHeroSkins.listResources();
            if (!items.length) {
                root.innerHTML = '<p class="muted">还没有导入本地皮肤。</p>';
                $('existingSkin').innerHTML = '<option value="">没有已导入资源</option>';
                $('bindSkinBtn').disabled = true;
                return;
            }
            const previews = await Promise.all(items.map(item => LocalHeroSkins.resourceURL(item.skin_id)));
            $('existingSkin').innerHTML = items.map(item => '<option value="' + esc(item.skin_id) + '">' +
                esc(item.label) + ' · ' + esc(item.width + '×' + item.height) + '</option>').join('');
            $('bindSkinBtn').disabled = false;
            root.innerHTML = items.map((item, i) => '<article class="skin-card"><img src="' + esc(previews[i]) + '" alt="本地皮肤预览" loading="lazy">' +
                '<b>' + esc(item.label) + '</b><div class="skin-meta">' + esc(item.type) + ' · ' + esc(item.width + '×' + item.height) +
                ' · ' + esc((item.size / 1024).toFixed(1)) + ' KiB</div><div class="skin-meta">资源 ID：' + esc(item.skin_id) + '</div>' +
                '<div class="skin-actions"><button type="button" class="btn small" data-bind-skin="' + esc(item.skin_id) + '">绑定给当前武将</button>' +
                '<button type="button" class="btn small danger" data-delete-skin="' + esc(item.skin_id) + '">删除资源</button></div></article>').join('');
            root.querySelectorAll('[data-bind-skin]').forEach(button => button.addEventListener('click', () => {
                $('existingSkin').value = button.dataset.bindSkin;
                bindExisting();
            }));
            root.querySelectorAll('[data-delete-skin]').forEach(button => button.addEventListener('click', async () => {
                if (!confirm('删除这张本地皮肤？删除后会清除引用它的本地映射。')) return;
                try {
                    await LocalHeroSkins.deleteResource(button.dataset.deleteSkin);
                    await refreshLibrary();
                    LocalHeroSkins.applyImages(document);
                    setStatus('本地资源已删除。', false);
                } catch (error) { setStatus(error.message, true); }
            }));
        } catch (error) {
            root.textContent = error.message;
            setStatus(error.message, true);
        }
    }

    async function importSkin() {
        if (!scanned) return;
        try {
            const id = $('skinHeroId').value.trim();
            const saved = await LocalHeroSkins.importAndBind(id, scanned.file, scanned.file.name);
            await refreshLibrary();
            LocalHeroSkins.applyImages(document);
            setStatus('已导入并应用到 ' + id + '。资源只保存在本浏览器。', false);
            $('skinFile').value = '';
            $('importSkinBtn').disabled = true;
            scanned = null;
            $('skinPreview').innerHTML = '<span class="muted">' + esc(saved.label) + ' 已加入本地资源库</span>';
        } catch (error) { setStatus(error.message, true); }
    }

    async function bindExisting() {
        try {
            const id = $('skinHeroId').value.trim();
            await LocalHeroSkins.bindExisting(id, $('existingSkin').value);
            LocalHeroSkins.applyImages(document);
            setStatus('已将所选本地资源绑定到 ' + id + '。', false);
        } catch (error) { setStatus(error.message, true); }
    }

    async function resetSkin() {
        try {
            const id = $('skinHeroId').value.trim();
            await LocalHeroSkins.clearMapping(id);
            LocalHeroSkins.applyImages(document);
            setStatus('已恢复 ' + id + ' 的默认立绘。', false);
        } catch (error) { setStatus(error.message, true); }
    }

    $('scanSkinBtn').addEventListener('click', scan);
    $('importSkinBtn').addEventListener('click', importSkin);
    $('bindSkinBtn').addEventListener('click', bindExisting);
    $('resetSkinBtn').addEventListener('click', resetSkin);
    $('refreshSkinsBtn').addEventListener('click', refreshLibrary);
    $('skinFile').addEventListener('change', () => {
        scanned = null;
        $('importSkinBtn').disabled = true;
        if (previewURL) URL.revokeObjectURL(previewURL);
        previewURL = null;
        $('skinPreview').innerHTML = '<span class="muted">扫描并预览后显示图片</span>';
        $('skinFileInfo').textContent = '支持 PNG、JPEG、WebP；最大 2 MiB，宽高各 64–2048 像素。';
    });
    $('skinHeroId').addEventListener('change', async () => {
        const id = $('skinHeroId').value.trim();
        if (sourceCatalog) renderSourceChoices();
        try {
            const mapping = await LocalHeroSkins.getMapping(id);
            setStatus(mapping ? '当前武将已绑定本地资源 ' + mapping.skin_id + '。' : '当前武将使用默认立绘。', false);
        } catch (error) { setStatus(error.message, true); }
    });
    $('sourceSkinChoice').addEventListener('change', () => {
        clearSourcePreview();
        $('previewSourceSkinBtn').disabled = !$('sourceSkinChoice').value;
        if ($('sourceSkinChoice').value && sourceCatalog) {
            const rows = sourceCatalog.items.filter(item => item.hero_id === $('skinHeroId').value.trim());
            const item = rows[Number($('sourceSkinChoice').value)];
            $('sourceSkinMeta').textContent = item ? `${item.path} · ${(item.bytes / 1024).toFixed(1)} KiB · 点击预览后才下载。` : '';
        }
    });
    $('previewSourceSkinBtn').addEventListener('click', previewSourceSkin);
    $('importSourceSkinBtn').addEventListener('click', importSourceSkin);
    window.addEventListener('pagehide', () => {
        if (previewURL) URL.revokeObjectURL(previewURL);
        if (sourcePreviewURL) URL.revokeObjectURL(sourcePreviewURL);
    }, { once: true });
    loadHeroes();
    loadSourceCatalog();
    refreshLibrary();
})();
