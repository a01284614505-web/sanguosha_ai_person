(function () {
    'use strict';
    const $ = id => document.getElementById(id);
    const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[c]);
    let scanned = null;
    let previewURL = null;
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
        } catch (_) {
            list.innerHTML = '';
        }
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
        try {
            const mapping = await LocalHeroSkins.getMapping(id);
            setStatus(mapping ? '当前武将已绑定本地资源 ' + mapping.skin_id + '。' : '当前武将使用默认立绘。', false);
        } catch (error) { setStatus(error.message, true); }
    });
    window.addEventListener('pagehide', () => { if (previewURL) URL.revokeObjectURL(previewURL); }, { once: true });
    loadHeroes();
    refreshLibrary();
})();
