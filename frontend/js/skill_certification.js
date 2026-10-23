/* Render content-bound Python/DSL parity evidence without treating it as rules certification. */
(function () {
    'use strict';

    const status = document.getElementById('certificationStatus');
    const output = document.getElementById('certificationOutput');
    const button = document.getElementById('refreshCertification');
    if (!status || !output || !button) return;

    const labels = {
        scenario_parity: '具名场景 parity（Python / DSL 结果一致）',
        parity: '补充场景 parity（实现结果一致）',
        passed: '通过',
        pending: '待验证'
    };
    const make = (tag, className, text) => {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text != null) node.textContent = String(text);
        return node;
    };

    function evidenceList(parent, title, entries, emptyText) {
        const section = make('div', 'cert-evidence-group');
        section.appendChild(make('strong', '', title));
        const list = make('ul', 'cert-evidence-list');
        if (entries.length) entries.forEach(entry => list.appendChild(make('li', '', entry)));
        else list.appendChild(make('li', 'muted', emptyText));
        section.appendChild(list);
        parent.appendChild(section);
    }

    function render(data) {
        output.replaceChildren();
        const report = data.report || {};
        const current = data.current === true;
        const skills = Array.isArray(report.skills) ? report.skills : [];
        status.dataset.kind = current ? 'current' : 'stale';
        status.textContent = current
            ? '证据内容指纹与当前技能/引擎文件匹配。'
            : '证据已过期：技能或引擎内容指纹与生成报告时不同，请重新生成后再参考。';

        const warning = make('div', 'certification-warning');
        warning.appendChild(make('strong', '', report.rules_version_verified === true
            ? '规则版本已标注核验。'
            : '规则版本尚未核验。'));
        warning.appendChild(make('p', '', '下面的 parity 仅表示列出的 Python 与 DSL 实现在指定场景中结果一致；不能据此认定规则正确、等同于某个客户端版本，或表示未列分支已经认证。'));
        output.appendChild(warning);

        const list = make('div', 'certification-list');
        skills.forEach(skill => {
            const details = make('details', 'certification-item');
            const summary = make('summary', '');
            summary.appendChild(make('strong', '', skill.skill || '未命名技能'));
            summary.appendChild(make('span', '', labels[skill.status] || skill.status || '未提供状态'));
            summary.appendChild(make('span', current ? 'cert-current-badge' : 'cert-stale-badge',
                current ? '当前证据' : '过期证据'));
            details.appendChild(summary);

            const body = make('div', 'cert-detail');
            body.appendChild(make('p', '', '覆盖范围：' + (skill.scope || '未记录')));
            body.appendChild(make('p', '', '固定场景数：' + (Array.isArray(skill.scenarios) ? skill.scenarios.length : 0) +
                '；记录的测试数：' + (Number.isFinite(skill.test_count) ? skill.test_count : 0)));
            evidenceList(body, '已列场景 / 证据', Array.isArray(skill.scenarios) ? skill.scenarios : [], '没有关联场景');
            evidenceList(body, '尚未覆盖的分支', Array.isArray(skill.branch_gaps) ? skill.branch_gaps : [], '报告没有列出分支缺口（不代表规则版本已核实）');
            details.appendChild(body);
            list.appendChild(details);
        });
        output.appendChild(list);

        const supplemental = Array.isArray(report.supplemental_scenarios) ? report.supplemental_scenarios : [];
        if (supplemental.length) {
            const heading = make('h3', '', '补充 parity 场景');
            output.appendChild(heading);
            evidenceList(output, '补充场景（不替代逐技能分支覆盖）', supplemental.map(item => {
                const covers = Array.isArray(item.covers) ? item.covers.join('、') : '未记录覆盖范围';
                const skillsCovered = Array.isArray(item.skills_covered) ? item.skills_covered.join('、') : '';
                return (item.id || '未命名') + '：' + covers + (skillsCovered ? '；涉及技能：' + skillsCovered : '');
            }), '没有补充场景');
        }
    }

    async function load() {
        button.disabled = true;
        status.dataset.kind = '';
        status.textContent = '正在读取认证证据…';
        try {
            const response = await fetch('/api/heroes/certification', {cache: 'no-store'});
            const data = await response.json();
            if (!response.ok || !data.success || !data.report) throw new Error(data.message || ('HTTP ' + response.status));
            render(data);
        } catch (error) {
            output.replaceChildren();
            status.dataset.kind = 'error';
            status.textContent = '认证证据暂不可用：' + (error && error.message ? error.message : '读取失败');
        } finally {
            button.disabled = false;
        }
    }

    button.addEventListener('click', load);
    load();
})();
