"""Import/enable real custom heroes and exercise representative DSL templates."""
import asyncio
from pathlib import Path

import pytest

from game_engine import MainEngine
from game_engine.config_validator import normalize_config
from game_engine.hero_package_store import HeroImportError, HeroPackageStore
from game_engine.hero_registry import HeroRegistry
from game_engine.state_manager import Card, Phase


@pytest.fixture
def store(tmp_path):
    (tmp_path / 'data').mkdir()
    native = Path(__file__).resolve().parents[1] / 'data/heroes.json'
    (tmp_path / 'data/heroes.json').write_bytes(native.read_bytes())
    return HeroPackageStore(tmp_path)


PACKAGE = {'id': 'template_pack', 'name': '模板测试包'}


def make_hero(dsl, status='active'):
    return {'id': 'template_hero', 'name': '测试新将', 'faction': '群', 'max_hp': 4,
            'skills': [{'name': '模板技能', 'description': '模板测试',
                        'implementation_status': status, 'dsl': dsl}]}


def build(store, dsl):
    store.import_hero(PACKAGE, make_hero(dsl))
    store.set_enabled(PACKAGE['id'], True)
    registry = HeroRegistry(store.project_root)
    cfg = normalize_config({'selected_hero': {'id': 'template_hero'},
                            'ais': [{'name': str(i)} for i in range(4)]}, hero_registry=registry)
    engine = MainEngine(cfg)
    owner = engine.game_state.players[0]
    engine.game_state.current_player = owner
    engine.game_state.current_phase = Phase.PLAY
    assert owner.hero['id'] == 'template_hero'
    return engine, owner


def use(engine, owner):
    manager = engine.skill_manager
    action = next((a for a in manager.get_actions(owner) if a.get('skill_name') == '模板技能'), None)
    return asyncio.run(manager.execute(owner, action, [])) if action else False


def test_builtin_is_canonical_and_duplicate_name_cannot_be_reimported(store):
    hero = HeroRegistry(store.project_root).canonical_hero({'id': 'caocao', 'skills': [], 'max_hp': 1})
    assert hero['name'] == '界曹操' and hero['max_hp'] == 4 and hero['skills']
    custom = make_hero({'version': 1, 'trigger': 'play_action', 'effects': [{'type': 'announce'}]})
    custom['skills'][0]['name'] = '奸雄'
    with pytest.raises(HeroImportError, match='技能名冲突'):
        store.import_hero(PACKAGE, custom)


def test_limited_hp_loss_executes_once(store):
    engine, owner = build(store, {'version': 1, 'trigger': 'play_action',
        'usage': {'scope': 'game', 'limit': 1},
        'effects': [{'type': 'lose_hp', 'target': 'owner', 'amount': 1}]})
    before = owner.hp
    assert use(engine, owner) and owner.hp == before - 1
    assert not use(engine, owner) and owner.hp == before - 1


def test_conversion_toggles_and_phase_limit(store):
    # Read the old mode into a local, branch on it, then update state exactly once.
    is_yang = {'op': 'eq', 'path': 'locals.old_mode', 'value': 'yang'}
    engine, owner = build(store, {'version': 1, 'trigger': 'play_action',
        'usage': {'scope': 'phase', 'limit': 2},
        'effects': [
            {'type': 'set_local', 'key': 'old_mode', 'value': {'path': 'state.mode'}},
            {'type': 'draw_cards', 'target': 'owner', 'count': 1, 'when': {'op': 'not', 'args': is_yang}},
            {'type': 'lose_hp', 'target': 'owner', 'amount': 1, 'when': is_yang},
            {'type': 'set_state', 'key': 'mode', 'value': 'yin', 'when': is_yang},
            {'type': 'set_state', 'key': 'mode', 'value': 'yang', 'when': {'op': 'not', 'args': is_yang}},
        ]})
    before = len(owner.hand), owner.hp
    assert use(engine, owner)
    assert len(owner.hand) == before[0] + 1 and owner.hp == before[1]
    assert engine.skill_manager.skill_state_value(owner, '模板技能', 'mode') == 'yang'
    assert use(engine, owner) and owner.hp == before[1] - 1
    assert engine.skill_manager.skill_state_value(owner, '模板技能', 'mode') == 'yin'
    assert not use(engine, owner)


@pytest.mark.parametrize('damage_type', ['normal', 'fire', 'thunder'])
def test_typed_damage_template(store, damage_type):
    engine, owner = build(store, {'version': 1, 'trigger': 'play_action',
        'usage': {'scope': 'phase', 'limit': 1},
        'effects': [{'type': 'damage', 'target': 'owner', 'source': 'owner',
                     'amount': 1, 'damage_type': damage_type}]})
    # The real engine must distinguish fire (藤甲 +1) and elemental chain
    # handling from ordinary damage, rather than treating all three as HP loss.
    owner.equipment['armor'] = Card('template_armor', '藤甲', 'club', 2, 'equipment')
    owner.chained = True
    before = owner.hp
    assert use(engine, owner) and owner.hp == before - (2 if damage_type == 'fire' else 1)
    assert owner.chained == (damage_type == 'normal')
    assert not use(engine, owner)
