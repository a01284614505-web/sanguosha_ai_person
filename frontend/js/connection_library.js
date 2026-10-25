// 本机连接资料库。Key 只有点击“保存到本机”才持久化，不发送给游戏服务器。
(function () {
    'use strict';
    const STORAGE_KEY = 'sgsConnectionLibraryV1';
    const META = {
        keys: { title: 'API Key', label: 'Key', inputType: 'password' },
        urls: { title: 'Base URL', label: 'Base URL', inputType: 'url' }
    };
    let dialog;
    let active;
    let editingId = null;

    function read() {
        try {
            const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
            return {
                keys: Array.isArray(raw.keys) ? raw.keys.filter(validRecord) : [],
                urls: Array.isArray(raw.urls) ? raw.urls.filter(validRecord) : []
            };
        } catch (_) { return { keys: [], urls: [] }; }
    }
    function validRecord(item) {
        return item && typeof item.id === 'string' && typeof item.provider === 'string' &&
            typeof item.value === 'string' && typeof item.note === 'string';
    }
    function write(data) {
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(data)); return true; }
        catch (_) { SGS.toast('本机存储不可用，未保存', { bad: true }); return false; }
    }
    function providerName(value) {
        const list = typeof Protocol !== 'undefined' ? Protocol.PROVIDERS : [];
        return (list.find(p => p.value === value) || {}).name || value || '当前提供方';
    }
    function mask(value) { return '••••••' + value.slice(-4); }
    function button(label, action, id) {
        const el = document.createElement('button');
        el.type = 'button';
        el.className = 'btn small';
        el.textContent = label;
        el.dataset.action = action;
        el.dataset.id = id;
        return el;
    }
    function ensureDialog() {
        if (dialog) return dialog;
        dialog = document.createElement('dialog');
        dialog.className = 'sgs-dialog conn-dialog';
        dialog.setAttribute('aria-label', '管理已保存的连接');
        dialog.innerHTML = '<div class="frame dialog-body">' +
            '<div class="dialog-head"><h2 class="conn-title"></h2><button class="icon-btn conn-close" type="button" aria-label="关闭">×</button></div>' +
            '<p class="conn-hint">只保存在此浏览器。Key 需要明确点击下方按钮才会保存。</p>' +
            '<div class="conn-list"></div>' +
            '<form class="conn-form"><label class="field"><span>备注</span><input class="conn-note" maxlength="80" placeholder="例如：个人账号、备用线路"></label>' +
            '<label class="field"><span class="conn-value-label"></span><input class="conn-value" autocomplete="off"></label>' +
            '<div class="dialog-actions"><button class="btn cancel conn-clear" type="button">清空编辑</button>' +
            '<button class="btn confirm conn-save" type="submit">保存到本机</button></div></form></div>';
        document.body.appendChild(dialog);
        dialog.querySelector('.conn-close').addEventListener('click', () => dialog.close());
        dialog.addEventListener('click', e => { if (e.target === dialog) dialog.close(); });
        dialog.querySelector('.conn-clear').addEventListener('click', clearEditor);
        dialog.querySelector('.conn-form').addEventListener('submit', save);
        dialog.querySelector('.conn-list').addEventListener('click', onListClick);
        return dialog;
    }
    function clearEditor() {
        editingId = null;
        dialog.querySelector('.conn-note').value = '';
        dialog.querySelector('.conn-value').value = '';
        dialog.querySelector('.conn-save').textContent = '保存到本机';
    }
    function render() {
        const list = dialog.querySelector('.conn-list');
        list.replaceChildren();
        const entries = read()[active.kind].filter(item => item.provider === active.provider);
        if (!entries.length) {
            const empty = document.createElement('p');
            empty.className = 'conn-empty';
            empty.textContent = '此提供方还没有保存的' + META[active.kind].title;
            list.appendChild(empty);
            return;
        }
        for (const item of entries) {
            const row = document.createElement('div');
            row.className = 'conn-entry';
            const info = document.createElement('div');
            info.className = 'conn-entry-info';
            const title = document.createElement('strong');
            title.textContent = item.note || '未命名';
            const value = document.createElement('small');
            value.textContent = active.kind === 'keys' ? mask(item.value) : item.value;
            info.append(title, value);
            const actions = document.createElement('div');
            actions.className = 'conn-entry-actions';
            actions.append(button('使用', 'use', item.id), button('编辑', 'edit', item.id), button('删除', 'delete', item.id));
            row.append(info, actions);
            list.appendChild(row);
        }
    }
    function onListClick(event) {
        const target = event.target.closest('button[data-action]');
        if (!target || !active) return;
        const data = read();
        const item = data[active.kind].find(entry => entry.id === target.dataset.id && entry.provider === active.provider);
        if (!item) return;
        if (target.dataset.action === 'use') {
            active.input.value = item.value;
            active.input.dispatchEvent(new Event('input', { bubbles: true }));
            active.input.dispatchEvent(new Event('change', { bubbles: true }));
            dialog.close();
        } else if (target.dataset.action === 'edit') {
            editingId = item.id;
            dialog.querySelector('.conn-note').value = item.note;
            dialog.querySelector('.conn-value').value = item.value;
            dialog.querySelector('.conn-save').textContent = '保存修改';
            dialog.querySelector('.conn-note').focus();
        } else if (target.dataset.action === 'delete') {
            if (target.dataset.confirm !== 'yes') {
                target.dataset.confirm = 'yes';
                target.textContent = '确认删除';
                return;
            }
            data[active.kind] = data[active.kind].filter(entry => entry.id !== item.id);
            if (write(data)) { if (editingId === item.id) clearEditor(); render(); }
        }
    }
    function save(event) {
        event.preventDefault();
        if (!active) return;
        const value = dialog.querySelector('.conn-value').value.trim();
        const note = dialog.querySelector('.conn-note').value.trim();
        if (!value) { SGS.toast('请填写' + META[active.kind].title, { bad: true }); return; }
        if (active.kind === 'urls') {
            try {
                const url = new URL(value);
                if (!['http:', 'https:'].includes(url.protocol)) throw Error('scheme');
            } catch (_) { SGS.toast('Base URL 必须以 http:// 或 https:// 开头', { bad: true }); return; }
        }
        const data = read();
        const old = editingId && data[active.kind].find(item => item.id === editingId && item.provider === active.provider);
        if (old) Object.assign(old, { note, value });
        else data[active.kind].push({ id: typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random(),
            provider: active.provider, note, value });
        if (write(data)) { clearEditor(); render(); SGS.toast('已保存到本机浏览器'); }
    }
    function open(input, kind, getProvider) {
        ensureDialog();
        active = { input, kind, provider: getProvider() || 'openai' };
        dialog.querySelector('.conn-title').textContent = providerName(active.provider) + ' · 已保存的' + META[kind].title;
        dialog.querySelector('.conn-hint').textContent = kind === 'keys'
            ? '只保存在此浏览器。Key 需要明确点击下方按钮才会保存。'
            : '只保存在此浏览器。地址需要明确点击下方按钮才会保存。';
        dialog.querySelector('.conn-value-label').textContent = META[kind].label;
        const valueInput = dialog.querySelector('.conn-value');
        valueInput.type = META[kind].inputType;
        clearEditor();
        valueInput.value = input.value.trim();
        render();
        dialog.showModal();
    }
    function attach(input, kind, getProvider) {
        if (!input || !META[kind] || input.dataset.connectionLibrary) return;
        input.dataset.connectionLibrary = '1';
        const wrap = document.createElement('span');
        wrap.className = 'conn-pick';
        input.parentNode.insertBefore(wrap, input);
        wrap.appendChild(input);
        const trigger = document.createElement('button');
        trigger.type = 'button';
        trigger.className = 'btn small conn-pick-btn';
        trigger.textContent = '管理已存';
        trigger.setAttribute('aria-label', '管理已保存的' + META[kind].title);
        trigger.addEventListener('click', () => open(input, kind, getProvider));
        wrap.appendChild(trigger);
        return { open: () => open(input, kind, getProvider) };
    }
    window.ConnectionLibrary = { attach };
})();
