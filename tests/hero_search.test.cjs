const assert = require('node:assert/strict');
const { matches } = require('../frontend/js/hero_search.js');
const heroes = require('../data/heroes.json');
const hero = id => heroes.find(h => h.id === id);
for (const query of ['曹', '曹操', '界操', 'CAO', 'cao cao', 'ＣＡＯＣＡＯ', 'cc', '太祖']) {
    assert.equal(matches(hero('caocao'), query), true, query);
}
for (const query of ['许', '许褚', 'xu chu', 'XUZHU', 'xz']) {
    assert.equal(matches(hero('xuchu'), query), true, query);
}
assert.equal(matches(hero('caocao'), '诸葛'), false);
assert.equal(matches(hero('caocao'), '   '), true);
assert.equal(matches({id:'custom_aria', name:'艾莉亚', title:'星辰'}, 'ARIA'), true);
assert.equal(matches({id:'custom_aria', name:'艾莉亚', title:'星辰'}, '艾亚'), true);
console.log('hero search passed');
