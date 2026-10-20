/* Browser-local portrait overrides. Images and mappings remain in IndexedDB on this device. */
(function (global) {
    'use strict';

    const DB_NAME = 'sgs_local_skins_v1';
    const DB_VERSION = 1;
    const RESOURCE_STORE = 'resources';
    const MAPPING_STORE = 'mappings';
    const MAX_BYTES = 2 * 1024 * 1024;
    const MIN_EDGE = 64;
    const MAX_EDGE = 2048;
    const HERO_ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
    const resources = new Map();
    const heroURLs = new Map();
    const channel = typeof BroadcastChannel === 'function' ? new BroadcastChannel(DB_NAME) : null;
    let dbPromise;

    function openDB() {
        if (!global.indexedDB) return Promise.reject(new Error('此浏览器不支持 IndexedDB。'));
        if (!dbPromise) dbPromise = new Promise((resolve, reject) => {
            const request = indexedDB.open(DB_NAME, DB_VERSION);
            request.onupgradeneeded = () => {
                const db = request.result;
                if (!db.objectStoreNames.contains(RESOURCE_STORE)) db.createObjectStore(RESOURCE_STORE, { keyPath: 'skin_id' });
                if (!db.objectStoreNames.contains(MAPPING_STORE)) db.createObjectStore(MAPPING_STORE, { keyPath: 'hero_id' });
            };
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error || new Error('无法打开本地皮肤库。'));
            request.onblocked = () => reject(new Error('本地皮肤库正在被其他标签页更新，请关闭旧标签页后重试。'));
        });
        return dbPromise;
    }

    function transaction(stores, mode, action) {
        return openDB().then(db => new Promise((resolve, reject) => {
            const tx = db.transaction(stores, mode);
            let result;
            try { result = action(tx); }
            catch (error) { tx.abort(); reject(error); return; }
            tx.oncomplete = () => resolve(result);
            tx.onerror = () => reject(tx.error || new Error('本地皮肤保存失败。'));
            tx.onabort = () => reject(tx.error || new Error('本地皮肤操作已取消。'));
        }));
    }

    function heroId(value) {
        const id = String(value || '').trim();
        if (!HERO_ID.test(id)) throw new Error('武将 ID 格式无效。');
        return id;
    }

    async function inspectFile(file) {
        if (!file || typeof file.arrayBuffer !== 'function') throw new Error('请选择一张本地图片。');
        if (file.size <= 0 || file.size > MAX_BYTES) throw new Error('图片大小必须在 1 字节到 2 MiB 之间。');
        const bytes = new Uint8Array(await file.slice(0, 16).arrayBuffer());
        let type = '';
        if (bytes.length >= 8 && bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47 &&
            bytes[4] === 0x0d && bytes[5] === 0x0a && bytes[6] === 0x1a && bytes[7] === 0x0a) type = 'image/png';
        else if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) type = 'image/jpeg';
        else if (bytes.length >= 12 && String.fromCharCode(...bytes.slice(0, 4)) === 'RIFF' &&
            String.fromCharCode(...bytes.slice(8, 12)) === 'WEBP') type = 'image/webp';
        if (!type) throw new Error('只接受真实 PNG、JPEG 或 WebP 图片。');
        if (typeof createImageBitmap !== 'function') throw new Error('此浏览器无法安全解码图片。');
        let bitmap;
        try { bitmap = await createImageBitmap(file); }
        catch (_) { throw new Error('图片无法解码，文件可能已损坏。'); }
        const width = bitmap.width, height = bitmap.height;
        bitmap.close();
        if (width < MIN_EDGE || height < MIN_EDGE || width > MAX_EDGE || height > MAX_EDGE) {
            throw new Error('图片宽高必须各在 64 到 2048 像素之间。');
        }
        return { type, width, height, size: file.size };
    }

    function makeId() {
        return global.crypto && typeof crypto.randomUUID === 'function'
            ? crypto.randomUUID().replace(/-/g, '')
            : Date.now().toString(36) + Math.random().toString(36).slice(2);
    }

    function releaseURL(skinId) {
        const row = resources.get(skinId);
        if (row) URL.revokeObjectURL(row.url);
        resources.delete(skinId);
    }

    async function resourceURL(skinId) {
        if (!skinId) return null;
        if (resources.has(skinId)) return resources.get(skinId).url;
        const record = await transaction([RESOURCE_STORE], 'readonly', tx => {
            const request = tx.objectStore(RESOURCE_STORE).get(skinId);
            return request;
        }).then(request => request.result);
        if (!record || !(record.blob instanceof Blob)) return null;
        const url = URL.createObjectURL(record.blob);
        resources.set(skinId, { url, blob: record.blob });
        return url;
    }

    async function getHeroImageURL(value) {
        const id = heroId(value);
        if (heroURLs.has(id)) return heroURLs.get(id);
        const request = await transaction([MAPPING_STORE], 'readonly', tx => tx.objectStore(MAPPING_STORE).get(id));
        const mapping = request.result;
        if (!mapping) return null;
        const recordRequest = await transaction([RESOURCE_STORE], 'readonly', tx => tx.objectStore(RESOURCE_STORE).get(mapping.skin_id));
        const record = recordRequest.result;
        if (!record || !(record.blob instanceof Blob)) return null;
        const url = URL.createObjectURL(record.blob);
        heroURLs.set(id, url);
        return url;
    }

    async function listResources() {
        const request = await transaction([RESOURCE_STORE], 'readonly', tx => tx.objectStore(RESOURCE_STORE).getAll());
        return (request.result || []).map(({ blob, ...meta }) => meta).sort((a, b) => b.imported_at.localeCompare(a.imported_at));
    }

    async function getMapping(value) {
        const id = heroId(value);
        const request = await transaction([MAPPING_STORE], 'readonly', tx => tx.objectStore(MAPPING_STORE).get(id));
        return request.result || null;
    }

    async function importAndBind(value, file, label) {
        const id = heroId(value);
        const meta = await inspectFile(file);
        const skinId = makeId();
        const record = { skin_id: skinId, label: String(label || file.name || '本地图片').slice(0, 120),
            type: meta.type, size: meta.size, width: meta.width, height: meta.height,
            imported_at: new Date().toISOString(), blob: new Blob([file], { type: meta.type }) };
        await transaction([RESOURCE_STORE, MAPPING_STORE], 'readwrite', tx => {
            tx.objectStore(RESOURCE_STORE).put(record);
            tx.objectStore(MAPPING_STORE).put({ hero_id: id, skin_id: skinId, updated_at: new Date().toISOString() });
        });
        releaseHeroURL(id);
        announceChange(id);
        return { ...record, blob: undefined };
    }

    async function bindExisting(value, skinId) {
        const id = heroId(value);
        if (!skinId) throw new Error('请选择已导入的皮肤。');
        await transaction([RESOURCE_STORE, MAPPING_STORE], 'readwrite', tx => {
            const resourcesStore = tx.objectStore(RESOURCE_STORE);
            const check = resourcesStore.get(skinId);
            check.onerror = () => tx.abort();
            check.onsuccess = () => {
                if (!check.result) { tx.abort(); return; }
                tx.objectStore(MAPPING_STORE).put({ hero_id: id, skin_id: skinId, updated_at: new Date().toISOString() });
            };
        });
        releaseHeroURL(id);
        announceChange(id);
    }

    async function clearMapping(value) {
        const id = heroId(value);
        const old = await getMapping(id);
        await transaction([MAPPING_STORE], 'readwrite', tx => tx.objectStore(MAPPING_STORE).delete(id));
        releaseHeroURL(id);
        announceChange(id);
        return old;
    }

    async function deleteResource(skinId) {
        const removedMappings = await transaction([RESOURCE_STORE, MAPPING_STORE], 'readwrite', tx => {
            const mappings = tx.objectStore(MAPPING_STORE);
            const removed = [];
            const request = mappings.getAll();
            request.onsuccess = () => (request.result || []).filter(row => row.skin_id === skinId).forEach(row => {
                removed.push(row.hero_id);
                mappings.delete(row.hero_id);
            });
            tx.objectStore(RESOURCE_STORE).delete(skinId);
            return removed;
        });
        releaseURL(skinId);
        removedMappings.forEach(id => { releaseHeroURL(id); announceChange(id); });
    }

    function releaseHeroURL(value) {
        const id = String(value || '');
        const url = heroURLs.get(id);
        if (url) URL.revokeObjectURL(url);
        heroURLs.delete(id);
    }

    async function refreshHeroImages(value) {
        const id = heroId(value);
        releaseHeroURL(id);
        const url = await getHeroImageURL(id).catch(() => null);
        document.querySelectorAll('img[data-hero-id]').forEach(img => {
            if (img.dataset.heroId !== id) return;
            const next = url || img.dataset.defaultSrc;
            if (next) img.src = next;
        });
    }

    function announceChange(id) {
        global.dispatchEvent(new CustomEvent('hero-skin-changed', { detail: { hero_id: id } }));
        if (channel) channel.postMessage({ hero_id: id });
    }

    function receiveChange(message) {
        const id = message && message.hero_id;
        if (typeof id === 'string' && HERO_ID.test(id)) refreshHeroImages(id).catch(() => {});
    }

    const pending = new WeakMap();
    function applyImages(root) {
        const scope = root || document;
        const candidates = [];
        if (scope.nodeType === 1 && scope.matches && scope.matches('img[data-hero-id]')) candidates.push(scope);
        if (scope.querySelectorAll) candidates.push(...scope.querySelectorAll('img[data-hero-id]'));
        candidates.forEach(img => {
            const id = img.dataset.heroId;
            if (!id || pending.has(img)) return;
            const task = getHeroImageURL(id).then(url => {
                if (url && img.isConnected && img.dataset.heroId === id) img.src = url;
            }).catch(() => {}).finally(() => pending.delete(img));
            pending.set(img, task);
        });
    }

    const api = { DB_NAME, DB_VERSION, MAX_BYTES, MIN_EDGE, MAX_EDGE, inspectFile, importAndBind,
        bindExisting, clearMapping, deleteResource, listResources, getMapping, resourceURL, getHeroImageURL, applyImages, refreshHeroImages };
    global.LocalHeroSkins = api;
    global.addEventListener('hero-skin-changed', event => receiveChange(event.detail));
    if (channel) channel.addEventListener('message', event => receiveChange(event.data));

    if (typeof document !== 'undefined') {
        const start = () => {
            applyImages(document);
            const observer = new MutationObserver(records => records.forEach(record =>
                record.addedNodes.forEach(node => { if (node.nodeType === 1) applyImages(node); })));
            observer.observe(document.documentElement, { childList: true, subtree: true });
        };
        if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
        else start();
        global.addEventListener('pagehide', () => {
            for (const row of resources.values()) URL.revokeObjectURL(row.url);
            resources.clear();
            for (const url of heroURLs.values()) URL.revokeObjectURL(url);
            heroURLs.clear();
            if (channel) channel.close();
        }, { once: true });
    }
})(window);
