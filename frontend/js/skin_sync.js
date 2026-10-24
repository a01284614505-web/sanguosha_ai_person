// =============================================================================
// 皮肤同步：把旧版“浏览器本地皮肤”（IndexedDB）自动迁移到服务器档案。
// -----------------------------------------------------------------------------
// - 只读旧库，成功上传并拿到服务器确认后才标记“已迁移”；失败不标记，下次打开自动重试。
// - 永远不会自动删除旧数据；确认迁移后，皮肤页提供“清理旧副本”按钮由用户自己点。
// - 上传带 client_ref（旧皮肤 ID），服务器据此去重，重试不会产生重复图片。
// - select=if_empty：不覆盖用户在别的设备上已经选好的皮肤。
// =============================================================================
(function (global) {
    'use strict';
    const DB_NAME = 'sgs_local_skins_v1';
    const FLAG_KEY = 'skinMigrated';
    const HERO_ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
    let running = null;

    function flag() { return SGS.store.get(FLAG_KEY, null); }

    /** 打开旧库；库不存在时返回 null（并撤销 open 顺手建出来的空库）。 */
    function openLegacy() {
        return new Promise(resolve => {
            if (!global.indexedDB) { resolve(null); return; }
            let request;
            try { request = indexedDB.open(DB_NAME); } catch (_) { resolve(null); return; }
            request.onupgradeneeded = () => { try { request.transaction.abort(); } catch (_) {} };
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => resolve(null);
            request.onblocked = () => resolve(null);
        });
    }
    function readAll(db, name) {
        return new Promise((resolve, reject) => {
            if (!db.objectStoreNames.contains(name)) { resolve([]); return; }
            const request = db.transaction([name], 'readonly').objectStore(name).getAll();
            request.onsuccess = () => resolve(request.result || []);
            request.onerror = () => reject(request.error);
        });
    }

    async function upload(profile, heroId, record) {
        const blob = record.blob;
        const ref = 'm_' + String(record.skin_id).replace(/[^A-Za-z0-9_-]/g, '').slice(0, 60);
        const query = '?profile_id=' + encodeURIComponent(profile) + '&hero_id=' + encodeURIComponent(heroId) +
            '&client_ref=' + encodeURIComponent(ref) + '&select=if_empty&label=' + encodeURIComponent(String(record.label || '本机迁移').slice(0, 40));
        const response = await fetch('/api/skins/upload' + query, {
            method: 'POST', headers: { 'Content-Type': blob.type, 'X-SGS-Skin': '1' }, body: blob, cache: 'no-store'
        });
        return response.status;
    }

    async function run(progress) {
        const profile = SGS.skinProfileId();
        if (!profile) return { state: 'no-profile' };
        if (flag()) return { state: 'done', already: true, ...flag() };
        const db = await openLegacy();
        if (!db) { SGS.store.set(FLAG_KEY, { at: new Date().toISOString(), uploaded: 0, rejected: 0, unbound: 0, local: 0 }); return { state: 'none' }; }
        try {
            const [resources, mappings] = await Promise.all([readAll(db, 'resources'), readAll(db, 'mappings')]);
            const byId = new Map(resources.map(r => [r.skin_id, r]));
            const jobs = mappings.filter(m => HERO_ID.test(String(m.hero_id)) && byId.has(m.skin_id) && byId.get(m.skin_id).blob instanceof Blob);
            const bound = new Set(mappings.map(m => m.skin_id));
            const unbound = resources.filter(r => !bound.has(r.skin_id)).length;
            if (!jobs.length && !resources.length) {
                SGS.store.set(FLAG_KEY, { at: new Date().toISOString(), uploaded: 0, rejected: 0, unbound: 0, local: 0 });
                return { state: 'none' };
            }
            let uploaded = 0, rejected = 0, retry = 0;
            for (const [index, job] of jobs.entries()) {
                if (progress) progress({ index: index + 1, total: jobs.length });
                try {
                    const status = await upload(profile, job.hero_id, byId.get(job.skin_id));
                    if (status === 200) uploaded++;
                    else if (status >= 500 || status === 429 || status === 408) retry++;
                    else rejected++;           // 4xx：这张图服务器永久不收（太大/格式不符等），重试没有意义
                } catch (_) { retry++; }
            }
            if (retry) return { state: 'partial', uploaded, rejected, retry, unbound };
            const result = { at: new Date().toISOString(), uploaded, rejected, unbound, local: resources.length };
            SGS.store.set(FLAG_KEY, result);
            await SGS.refreshSkins();
            return { state: 'done', ...result };
        } finally { db.close(); }
    }

    /** 同一页面内只跑一次；失败后可再次调用重试。 */
    function ensureMigrated(progress) {
        if (!running) running = run(progress).catch(error => ({ state: 'error', message: String(error && error.message || error) })).finally(() => { running = null; });
        return running;
    }

    function clearLocal() {
        return new Promise(resolve => {
            if (!global.indexedDB) { resolve(false); return; }
            const request = indexedDB.deleteDatabase(DB_NAME);
            request.onsuccess = () => resolve(true);
            request.onerror = () => resolve(false);
            request.onblocked = () => resolve(false);
        });
    }
    async function hasLocalCopy() {
        if (!global.indexedDB) return false;
        if (typeof indexedDB.databases === 'function') {
            try { return (await indexedDB.databases()).some(d => d.name === DB_NAME); } catch (_) {}
        }
        const db = await openLegacy();
        if (!db) return false;
        db.close();
        return true;
    }

    global.SkinSync = { ensureMigrated, clearLocal, hasLocalCopy, flag };

    // 大厅和皮肤页都会加载本脚本：页面空闲时静默迁移一次（皮肤页会自己再调用并显示进度）
    if (typeof document !== 'undefined' && !/skins\.html/.test(location.pathname)) {
        const start = () => setTimeout(() => { if (!flag()) ensureMigrated(); }, 800);
        if (document.readyState === 'complete') start(); else global.addEventListener('load', start, { once: true });
    }
})(window);
