// Skin-gallery search only: the chosen hero's canonical id remains the upload key.
(function (root) {
    'use strict';
    const aliases = { xuchu: ['xuzhu'] };
    function normalize(value) {
        let text = String(value || '');
        if (typeof text.normalize === 'function') text = text.normalize('NFKC');
        return text.toLowerCase().replace(/[\s_.\-·'’]/g, '');
    }
    function subsequence(query, field) {
        let i = 0;
        for (const ch of field) if (ch === query[i]) i++;
        return i === query.length;
    }
    function matches(hero, query) {
        const q = normalize(query);
        if (!q) return true;
        const extra = Object.prototype.hasOwnProperty.call(aliases, hero.id) ? aliases[hero.id] : [];
        const fields = [hero.name, hero.id, hero.title, ...extra].map(normalize);
        return fields.some(field => field.includes(q) || subsequence(q, field));
    }
    const api = { matches };
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    else root.HeroSearch = api;
})(typeof window !== 'undefined' ? window : globalThis);
