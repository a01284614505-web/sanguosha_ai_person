"""One physical Slash, from a seat's view, resolved by the real engine.

Never clone the live engine/recovery payload: it contains true hidden cards,
roles, RNG state, sessions and callbacks. Capture only observation facts; build
fresh rule-only engines from those facts and identical sampled worlds per arm.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from random import Random
from time import monotonic
import asyncio

from . import card_knowledge, peixiu
from .ai_decision import AIDecision
from .behavior_ledger import BehaviorLedger
from .card_knowledge import DECK, DISCARD, OPEN, PRIVATE, _zones
from .card_system import CardSystem
from .card_table import CARD_TABLE
from .game_stats import GameStats
from .main_engine import MainEngine
from .mode_registry import get_mode
from .rollout_logging import silent
from .rules_engine import RulesEngine
from .seats import seat_of
from .skill_manager import SkillManager
from .skill_runtime_state import SkillStateStore
from .state_manager import Card, GameState, Phase, Player

SAMPLES = 16
SECONDS = .10
MAX_STEPS = 256
HINT = ('如需比较一至两种单目标实体【杀】，仅返回 '
        '{"simulation_query":[{"action_index":0,"target_ids":[3]}]}（填实际索引和座位号）。'
        '每步最多一次额外复核；可直接行动。')
# Publicly observable native counters that can affect a Slash and its immediate hooks.
PUBLIC_FLAGS = ('cannot_use_hand', 'nonlocked_disabled', 'yijue_sources', 'tieqi_sources',
                'luoyi_active', 'zaxiang_active', 'pao_tokens', 'skill_used', 'limited_skills')
ZONE_ATTR = {'hand': 'hand', 'treasure': 'treasure_cards', 'temporary': 'temporary',
             'shown': 'shown', 'judge': 'judge_area'}


class Unsupported(ValueError):
    pass


class BudgetExceeded(Exception):
    pass


def enabled(engine):
    return engine.game_config.get('local_tactical_simulation') is True


def can_query(actions):
    return any(a.get('type') == 'play_card' and (a.get('card') or {}).get('name') == '杀'
               and a.get('valid_targets') for a in actions)


def _branches(actions, query, seats):
    if not isinstance(query, list) or not 1 <= len(query) <= 2:
        raise Unsupported
    by_seat = {seat: pid for pid, seat in seats.items()}
    rows = []
    for item in query:
        if not isinstance(item, dict) or set(item) != {'action_index', 'target_ids'}:
            raise Unsupported
        index, targets = item['action_index'], item['target_ids']
        if (type(index) is not int or not 0 <= index < len(actions)
                or not isinstance(targets, list) or len(targets) != 1 or type(targets[0]) is not int):
            raise Unsupported
        action, pid = actions[index], by_seat.get(targets[0])
        if not can_query([action]) or pid not in action['valid_targets']:
            raise Unsupported
        row = (index, action['card_index'], pid)
        if row in rows:
            raise Unsupported
        rows.append(row)
    return rows


def _capture(engine, viewer):
    state = engine.game_state
    if (state.current_player is None or state.current_player.id != viewer.id
            or state.current_phase is not Phase.PLAY or engine.game_aborted
            or engine.skill_manager.dsl_programs or engine.skill_manager._loss_batches
            or any(peixiu.active(p) for p in state.players)):
        raise Unsupported
    view = card_knowledge.current_view(state, viewer.id)
    # Unknown skill-arranged order and rank-selected pools are not a uniform deck.
    if view is None or view.ordered_by_skill or view.degraded or len(state.players) > 8:
        raise Unsupported
    flags = PUBLIC_FLAGS
    players = [Player(p.id, p.name, hero={key: (p.hero or {}).get(key) for key in ('id', 'name', 'faction')},
                      identity=p.identity if p.id == viewer.id or p.identity_revealed else None,
                      identity_revealed=p.identity_revealed, hp=p.hp, max_hp=p.max_hp,
                      chained=p.chained, status=p.status, alive=p.alive, is_ai=True,
                      flags=deepcopy({k: p.flags[k] for k in flags if k in p.flags}),
                      sha_count=p.sha_count if p.id == viewer.id else 0,
                      max_sha=p.max_sha if p.id == viewer.id else 1) for p in state.players]
    next(p for p in players if p.id == viewer.id).jiu_buff = bool(getattr(state.current_player, 'jiu_buff', False))
    # As with the public snapshot, only native skill instance state is copied.
    # Do not traverse private zones of another seat, even to obtain card IDs.
    visible = {DISCARD: tuple(map(card_knowledge.face_of, state.discard_pile))}
    equipment_slots = {}
    for p in state.players:
        for z, cards in _zones(p).items():
            if z in OPEN or p.id == viewer.id and z in PRIVATE:
                visible[p.id, z] = tuple(map(card_knowledge.face_of, cards))
        equipment_slots[p.id] = tuple(p.equipment)
    roles = list(get_mode(state.mode).identities)
    if 'lord' in roles and not any(p.identity == 'lord' and p.identity_revealed for p in players):
        raise Unsupported
    for p in players:
        if p.identity is not None:
            if p.identity not in roles:
                raise Unsupported
            roles.remove(p.identity)
    if len(roles) != sum(p.identity is None for p in players):
        raise Unsupported
    return (deepcopy(view), players, visible, equipment_slots, roles, state.mode, state.round_number,
            engine.completed_turns, engine.skill_manager.skill_state.to_dict())


def _deal(view, visible, rng):
    """Shuffle each exchangeability pool once; distribute its slots without replacement."""
    pools = {g: sorted(cards.elements(), key=repr) for g, cards in view.pools.items()}
    for cards in pools.values():
        rng.shuffle(cards)
    zones = dict(visible)
    for z in sorted(view.fixed.keys() | view.slots.keys(), key=repr):
        if z in visible:
            continue
        fixed = view.fixed.get(z, Counter())
        if z == DECK:
            fixed = fixed - Counter(view.positions.values())
        faces = sorted(fixed.elements(), key=repr)
        for g, count in sorted(view.slots.get(z, {}).items()):
            faces.extend(pools[g].pop() for _ in range(count))
        rng.shuffle(faces)
        if z == DECK and view.positions:
            it = iter(faces)
            faces = [view.positions[i] if i in view.positions else next(it)
                     for i in range(view.capacity(DECK))]
        zones[z] = tuple(faces)
    if any(pools.values()):
        raise Unsupported
    return zones


class _RulePolicy(AIDecision):
    def __init__(self, engine, rng):
        # Deliberately no gateway, worldbook/cache IO, or live AI session.
        self.engine, self.rng = engine, rng

    def record_outcome(self, *_):
        pass


class _SlashSystem(CardSystem):
    def _slash_outcome(self, target, outcome):
        self.engine.slash_outcomes[target.id].add(outcome)


class _Simulation(MainEngine):
    def __init__(self, capture, viewer_id, zones, sampled_roles, seed, deadline):
        _, players, _, slots, _, mode, round_nr, turns, skills = capture
        self.game_config = {'mode': mode}
        self.game_state = state = GameState()
        state.game_config = self.game_config
        state.mode, state.round_number, state.current_phase = mode, round_nr, Phase.PLAY
        state._rng = Random(seed)
        state.players = deepcopy(players)
        self._abort_reason = None
        self._effect_seq = 0
        self.game_id = 'simulation'
        self.completed_turns = turns
        self.hide_dead_identity = False
        self.stats = GameStats(state.players)
        self.ledger = BehaviorLedger()
        self.ai_decision = _RulePolicy(self, Random(seed))
        self.dying = set()
        self.slash_outcomes = defaultdict(set)
        self.steps, self.deadline = 0, deadline
        ids = iter(range(sum(map(len, zones.values()))))

        def cards(zone):
            return [Card(str(next(ids)), f.name, f.suit, f.rank, f.kind,
                         target_rule=deepcopy(CARD_TABLE[f.name].target_rule), nature=f.nature)
                    for f in zones.get(zone, ())]

        state.deck, state.discard_pile = cards(DECK), cards(DISCARD)
        roles = iter(sampled_roles)
        for p in state.players:
            if p.identity is None:
                p.identity = next(roles)
            if p.id == viewer_id:
                state.current_player = p
                state.current_player_index = state.players.index(p)
            p.equipment = dict(zip(slots[p.id], cards((p.id, 'equipment')), strict=True))
            for z, attr in ZONE_ATTR.items():
                setattr(p, attr, cards((p.id, z)))
        self.skill_manager = SkillManager(self)
        self.skill_manager.skill_state = SkillStateStore.from_dict(deepcopy(skills))
        self.card_system = _SlashSystem(state, None, self.skill_manager, self._notify_card_ui,
                                         self.request_response, self)
        self.rules = RulesEngine(state, self.skill_manager)

    def _tick(self):
        self.steps += 1
        if self.steps > MAX_STEPS or monotonic() >= self.deadline:
            raise BudgetExceeded

    async def emit(self, *args, **kwargs):
        self._tick()

    _notify_card_ui = emit
    log_event = emit

    def on_player_dying(self, player):
        self.dying.add(player.id)

    def on_player_death(self, *_):
        pass

    record_death = on_player_death

    async def push_notes_after_death(self):
        pass

    async def request_response(self, player, request):
        self._tick()
        index = self.ai_decision.simple_response_decision(player, self._response_decision_view(request))
        return self._resolve_option(player, request, index)

    async def request_choice(self, player, request):
        self._tick()
        raw = self.ai_decision.simple_choice_decision(player, self._mask_hidden_candidates(request))
        result = self._resolve_choice(player, request, raw)
        return {**result, 'status': 'resolved' if result.get('bool') else 'cancelled'}


def _resources(p):
    return len(p.hand) + len(p.equipment) + len(p.treasure_cards) + len(p.temporary)


async def _resolve(capture, viewer_id, zones, roles, seed, deadline, branch):
    sim = _Simulation(capture, viewer_id, zones, roles, seed, deadline)
    players = sim.game_state.players
    before = {p.id: _resources(p) for p in players}
    _, card_index, target = branch
    if not await sim.execute_action(sim.game_state.current_player, {'type': 'play_card', 'card_index': card_index}, [target]):
        raise Unsupported
    return {p.id: Counter(immune=int('immune' in sim.slash_outcomes[p.id]),
                          dodged=int('dodged' in sim.slash_outcomes[p.id]),
                          damage=sim.stats.row(p)['damage_taken'], dying=int(p.id in sim.dying),
                          rescued=int(p.id in sim.dying and p.alive), dead=int(not p.alive),
                          resources=_resources(p) - before[p.id])
            for p in players if p.alive or next(row.alive for row in capture[1] if row.id == p.id)}


async def compare(engine, viewer, actions, query, *, seed=0, samples=SAMPLES, seconds=SECONDS):
    """Return sample totals only (no hidden faces/identity assignments or raw traces)."""
    if not enabled(engine):
        return {'status': 'disabled'}
    deadline = monotonic() + min(seconds, SECONDS)
    token = silent.set(True)
    try:
        capture = _capture(engine, viewer)
        # Read the already-public anchor from the projection, not hidden roles;
        # use a fresh GameState so the real seat-map cache is not modified.
        public = GameState()
        public.players = capture[1]
        seats = {p.id: seat_of(public, p.id) for p in public.players}
        branches = _branches(actions, query, seats)
        rng = Random(seed)
        totals = [defaultdict(Counter) for _ in branches]
        count = 0
        for _ in range(max(0, min(samples, SAMPLES))):
            if monotonic() >= deadline:
                break
            zones = _deal(capture[0], capture[2], rng)
            roles = capture[4].copy()
            rng.shuffle(roles)
            common_seed = rng.getrandbits(64)
            try:
                paired = [await _resolve(capture, viewer.id, zones, roles, common_seed, deadline, branch)
                          for branch in branches]
            except BudgetExceeded:
                break
            for accum, result in zip(totals, paired):
                for pid, stats in result.items():
                    accum[seats[pid]].update(stats)
            count += 1
            # Yield between complete pairs; the remaining branches still use the frozen observation.
            await asyncio.sleep(0)
        return {'status': 'ok' if count else 'budget', 'samples': count,
                'partial': count < min(samples, SAMPLES),
                'branches': [{'action_index': i, 'target': seats[pid], 'totals': dict(total)}
                             for (i, _, pid), total in zip(branches, totals)]}
    except Unsupported:
        return {'status': 'unsupported'}
    except Exception:
        return {'status': 'unavailable'}
    finally:
        silent.reset(token)


def format_result(result):
    if result['status'] != 'ok':
        return '一步结算不可用（不支持该牌局/候选，或超出预算）；请按合法菜单决策。'
    n = result['samples']
    lines = [f'同批{n}个样本' + ('（预算截断）' if result['partial'] else '')
             + '；暗牌按牌账抽样，暗身份按剩余身份随机分配。规则代打：能闪则闪，'
               '自救或按公开主公身份救援。不是实战概率，闪避后可能追击。']
    for branch in result['branches']:
        target = branch['target']
        parts = []
        for seat, stats in sorted(branch['totals'].items()):
            if seat == target or any(stats.values()):
                parts.append(f'{seat}号 免疫{stats["immune"]}次/闪避{stats["dodged"]}次，'
                             f'均受伤{stats["damage"]/n:.1f}，濒死/救回/阵亡'
                             f'{stats["dying"]}/{stats["rescued"]}/{stats["dead"]}次，'
                             f'资源均变化{stats["resources"]/n:+.1f}')
        lines.append(f'操作{branch["action_index"]}→{target}号：' + '；'.join(parts))
    return '\n'.join(lines)
