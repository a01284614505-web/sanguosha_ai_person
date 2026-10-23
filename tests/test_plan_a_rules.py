"""Rule-derived, real-engine regression scenes for the 2026-10 A batch.

These tests describe standard turn/judgment/dying behavior, rather than treating
current implementation output as the oracle.  A1/A2/A3 changes are integrated by
the core owner in game_engine; this file remains owned by the rules verifier.
"""

import asyncio
from unittest.mock import AsyncMock

from game_engine import MainEngine
from game_engine.state_manager import Card, Phase, PlayerStatus


def game():
    engine = MainEngine({
        "mode": "5人身份局", "player_name": "真人",
        "ais": [{"name": f"AI{i}"} for i in range(1, 5)],
        "deck_id": "standard",
    })
    engine.response_timeout = 1
    for player in engine.game_state.players:
        player.hand.clear()
        player.equipment.clear()
        player.judge_area.clear()
        player.treasure_cards.clear()
        player.shown.clear()
        player.temporary.clear()
    return engine


def card(tag, name, suit="club", rank=5, kind="trick"):
    return Card(tag, name, suit, rank, kind)


def run(coro):
    return asyncio.run(coro)


class ScriptedResponder:
    """Select a real response candidate by as_name, exercising engine recheck."""
    def __init__(self, engine, choices):
        self.engine = engine
        self.choices = dict(choices)
        self.requests = []

    async def __call__(self, player, request):
        self.requests.append((player, request))
        wanted = self.choices.get(player.id, "pass")
        options = request["options"]
        if wanted == "pass":
            index = len(options) - 1
        else:
            index = next(i for i, option in enumerate(options)
                         if option.get("as_name", option.get("card").name) == wanted)
        return self.engine._resolve_option(player, request, index)


def loc(engine, player, card):
    """Count one physical card across every public/owned card zone."""
    state = engine.game_state
    return sum(card is c for c in state.deck + state.discard_pile
               + [c for p in state.players for c in (
                   p.hand + p.judge_area + p.shown + p.temporary + p.treasure_cards
               )] + [c for p in state.players for c in p.equipment.values()])


def test_judgment_zone_uses_lifo_snapshot_and_skips_cards_moved_during_resolution():
    engine = game()
    target = engine.game_state.players[0]
    # Distinct standard delayed tricks in a known placement order. The last placed
    # one must resolve first; a later card removed by an earlier resolution must
    # not be resurrected from the iteration snapshot.
    lebu = card("a1_lebu", "乐不思蜀", "heart")
    bing = card("a1_bing", "兵粮寸断", "club")
    lightning = card("a1_lightning", "闪电", "club", 10)
    target.judge_area.extend([lebu, bing, lightning])
    engine.game_state.deck[:] = [
        card("a1_j1", "杀", "heart", 2, "basic"),
        card("a1_j2", "杀", "club", 3, "basic"),
        card("a1_j3", "杀", "diamond", 4, "basic"),
    ]
    engine.card_system.ask_wuxie = AsyncMock(return_value=False)
    seen = []
    original = engine.skill_manager.before_judge

    async def record_and_move(player, revealed, context=None):
        delayed = context["delayed_card"]
        seen.append(delayed.id)
        if delayed is lightning:
            # Remove the later-in-order lebu while the judge-area snapshot exists.
            await engine.move_card(lebu, "judge", "discard", from_owner=target,
                                   reason="test_removed_during_judgment")
        return await original(player, revealed, context)

    engine.skill_manager.before_judge = record_and_move
    run(engine.phase_controller.judge_phase())

    assert seen == [lightning.id, bing.id]
    assert lebu not in target.judge_area
    assert lebu in engine.game_state.discard_pile
    assert all(loc(engine, target, physical) == 1 for physical in (lebu, bing, lightning))


def test_mixed_delayed_tricks_resolve_last_placed_first_and_keep_lightning_transfer():
    engine = game()
    target, next_player = engine.game_state.players[:2]
    lebu = card("a1_mixed_lebu", "乐不思蜀", "heart")
    bing = card("a1_mixed_bing", "兵粮寸断", "club")
    lightning = card("a1_mixed_lightning", "闪电", "club", 10)
    target.judge_area.extend([lebu, bing, lightning])
    # Lightning misses on heart and transfers; Bingliang's club succeeds;
    # Lebu's spade succeeds and marks only the play phase for skipping.
    engine.game_state.deck[:] = [
        card("a1_mixed_j1", "杀", "heart", 2, "basic"),
        card("a1_mixed_j2", "杀", "club", 3, "basic"),
        card("a1_mixed_j3", "杀", "spade", 4, "basic"),
    ]
    engine.card_system.ask_wuxie = AsyncMock(return_value=False)
    seen = []
    original = engine.skill_manager.before_judge

    async def record(player, revealed, context=None):
        seen.append(context["delayed_card"].id)
        return await original(player, revealed, context)

    engine.skill_manager.before_judge = record
    run(engine.phase_controller.judge_phase())

    assert seen == [lightning.id, bing.id, lebu.id]
    assert lightning in next_player.judge_area
    assert bing in engine.game_state.discard_pile
    assert lebu in engine.game_state.discard_pile
    from game_engine.state_manager import Phase
    assert Phase.PLAY in engine.phase_controller.skip_phases
    assert all(loc(engine, target, physical) == 1 for physical in (lebu, bing, lightning))


def test_lightning_lethal_judgment_stops_remaining_judgments():
    engine = game()
    target = engine.game_state.players[0]
    target.hp = 1
    lebu = card("a1_lethal_lebu", "乐不思蜀", "spade")
    bing = card("a1_lethal_bing", "兵粮寸断", "club")
    lightning = card("a1_lethal_lightning", "闪电", "spade", 5)
    target.judge_area.extend([lebu, bing, lightning])
    engine.game_state.deck[:] = [
        card("a1_lethal_judge", "杀", "spade", 5, "basic"),
        card("a1_later_judge1", "杀", "club", 4, "basic"),
        card("a1_later_judge2", "杀", "heart", 8, "basic"),
    ]
    engine.card_system.ask_wuxie = AsyncMock(return_value=False)
    seen = []
    original = engine.skill_manager.before_judge

    async def record(player, revealed, context=None):
        seen.append(context["delayed_card"].id)
        return await original(player, revealed, context)

    engine.skill_manager.before_judge = record
    run(engine.phase_controller.judge_phase())

    assert seen == [lightning.id]
    assert target.alive is False
    assert target.hp <= 0
    # Death cleanup discards the remaining delayed tricks after the lethal
    # judgment, so they do not survive in the dead player's judgment area.
    assert lebu in engine.game_state.discard_pile
    assert bing in engine.game_state.discard_pile
    assert lightning in engine.game_state.discard_pile
    assert all(loc(engine, target, physical) == 1 for physical in (lebu, bing, lightning))


def test_match_abort_during_first_delayed_judgment_stops_the_remaining_snapshot():
    engine = game()
    target = engine.game_state.players[0]
    target.judge_area.extend([
        card("a1_abort_lebu", "乐不思蜀", "heart"),
        card("a1_abort_bing", "兵粮寸断", "club"),
    ])
    engine.game_state.deck[:] = [
        card("a1_abort_top", "杀", "heart", 2, "basic"),
        card("a1_abort_next", "杀", "club", 3, "basic"),
    ]
    engine.card_system.ask_wuxie = AsyncMock(return_value=False)
    seen = []
    original = engine.skill_manager.before_judge

    async def record_then_abort(player, revealed, context=None):
        seen.append(context["delayed_card"].id)
        result = await original(player, revealed, context)
        engine._abort_reason = "test_abort"
        return result

    engine.skill_manager.before_judge = record_then_abort
    run(engine.phase_controller.judge_phase())

    assert len(seen) == 1
    assert len(engine.game_state.deck) == 1


def test_turned_player_flips_up_and_skips_full_turn_without_phase_skills_or_stale_marks():
    engine = game()
    player = engine.game_state.players[0]
    engine.game_state.current_player = player
    player.status = PlayerStatus.TURNED
    player.chained = True
    player.hero = {"id": "zhenji", "name": "甄姬", "faction": "魏", "max_hp": player.max_hp}
    engine.skill_manager.bind_engine(engine)
    engine.game_state.deck[:] = [card("a2_luoshen_black", "杀", "spade", 7, "basic")]
    # The turned-over rule skips the whole next turn; its six phase hooks,
    # including prepare/END hooks and DSL subscribers, receive no dispatch.
    before = AsyncMock(wraps=engine.skill_manager.before_phase)
    after = AsyncMock(wraps=engine.skill_manager.after_phase)
    engine.skill_manager.before_phase = before
    engine.skill_manager.after_phase = after
    phases = []
    engine.on("event_notification", lambda **data: phases.append(data.get("phase"))
              if data.get("event_kind") == "phase" else None)

    # Trustee ends its play prompt immediately if the public path reaches it.
    engine._trustee_active = True
    async def end_play(_player, _actions):
        return {"action": {"type": "end_phase"}, "target_ids": []}
    engine._trustee_make_decision = end_play
    run(engine._human_turn(player))

    assert player.status == PlayerStatus.NORMAL
    assert player.chained is True
    assert engine.game_state.deck[0].id == "a2_luoshen_black"
    assert before.await_count == 0
    assert after.await_count == 0
    assert phases == []
    assert not engine.phase_controller.skip_phases


def test_turned_ai_and_trustee_paths_do_not_dispatch_skipped_phase_hooks():
    for path in ("ai", "trustee"):
        engine = game()
        player = engine.game_state.players[1] if path == "ai" else engine.game_state.players[0]
        engine.game_state.current_player = player
        player.status = PlayerStatus.TURNED
        player.chained = True  # 翻面与横置是独立状态，跳过后不能清掉横置。
        hero_id, hero_name, faction = {
            "ai": ("zhouyu", "周瑜", "吴"),
            "trustee": ("diaochan", "貂蝉", "群"),
        }[path]
        player.hero = {"id": hero_id, "name": hero_name, "faction": faction, "max_hp": player.max_hp}
        engine.skill_manager.bind_engine(engine)
        if path == "trustee":
            engine._trustee_active = True
            async def end_play(_player, _actions):
                return {"action": {"type": "end_phase"}, "target_ids": []}
            engine._trustee_make_decision = end_play
        before = AsyncMock(wraps=engine.skill_manager.before_phase)
        after = AsyncMock(wraps=engine.skill_manager.after_phase)
        engine.skill_manager.before_phase = before
        engine.skill_manager.after_phase = after
        if path == "ai":
            run(engine._ai_turn(player))
        else:
            run(engine._human_turn(player))
        assert player.status == PlayerStatus.NORMAL
        assert player.chained is True, path
        assert before.await_count == 0, path
        assert after.await_count == 0, path
        assert not engine.phase_controller.skip_phases, path


def test_bingliang_skipped_draw_phase_does_not_run_native_or_dsl_phase_hooks():
    engine = game()
    player = engine.game_state.players[0]
    player.hero = {
        "id": "a2_skipped_phase_hooks", "name": "跳过阶段钩子测试", "faction": "魏",
        "max_hp": player.max_hp,
        "skills": [
            {"name": "摸牌开始监听", "implementation_status": "active", "dsl": {
                "version": 1, "trigger": "phase_start",
                "condition": {"op": "eq", "path": "event.phase", "value": "draw"},
                "effects": [{"type": "draw_cards", "target": "owner", "count": 1}],
            }},
            {"name": "摸牌结束监听", "implementation_status": "active", "dsl": {
                "version": 1, "trigger": "phase_end",
                "condition": {"op": "eq", "path": "event.phase", "value": "draw"},
                "effects": [{"type": "draw_cards", "target": "owner", "count": 1}],
            }},
        ],
    }
    engine.skill_manager.bind_engine(engine)
    engine.game_state.current_player = player
    engine.game_state.deck[:] = [card("a2_skipped_draw_top", "桃", "heart", 2, "basic")]
    before = AsyncMock(wraps=engine.skill_manager.before_phase)
    after = AsyncMock(wraps=engine.skill_manager.after_phase)
    engine.skill_manager.before_phase = before
    engine.skill_manager.after_phase = after
    engine.phase_controller.skip_phases.add(Phase.DRAW)

    run(engine._execute_phase_with_ui(Phase.DRAW))

    assert before.await_count == 0
    assert after.await_count == 0
    assert player.hand == []
    assert engine.phase_controller.skip_phases == set()
    assert engine.skill_manager.activation_log == []


def test_lebu_skipped_play_consumes_mark_without_dispatching_phase_hooks():
    engine = game()
    player = engine.game_state.players[0]
    before = AsyncMock(wraps=engine.skill_manager.before_phase)
    after = AsyncMock(wraps=engine.skill_manager.after_phase)
    engine.skill_manager.before_phase = before
    engine.skill_manager.after_phase = after
    engine.phase_controller.skip_phases.add(Phase.PLAY)

    skipped = run(engine._skip_play_phase_if_needed(player))

    assert skipped is True
    assert before.await_count == 0
    assert after.await_count == 0
    assert Phase.PLAY not in engine.phase_controller.skip_phases


def test_turned_over_turn_resets_per_turn_scope_without_turn_start_dispatch():
    engine = game()
    player = engine.game_state.players[1]
    player.status = PlayerStatus.TURNED
    player.max_sha = 4
    player.sha_count = 3
    player.jiu_used_this_turn = True
    player.jiu_buff = True
    player.flags["sha_used_this_turn"] = True
    player.flags["skill_used"] = {"current_turn_skill": True}
    engine.skill_manager.bind_engine(engine)
    turn_start = AsyncMock(wraps=engine.skill_manager.on_turn_start)
    engine.skill_manager.on_turn_start = turn_start

    skipped = run(engine._consume_turned_over_turn(player))

    assert skipped is True
    assert player.status == PlayerStatus.NORMAL
    assert player.max_sha == 1
    assert player.sha_count == 0
    assert player.jiu_used_this_turn is False
    assert player.jiu_buff is False
    assert player.flags.get("sha_used_this_turn") is False
    assert player.flags.get("skill_used", {}).get("current_turn_skill") is not True
    turn_start.assert_not_awaited()


def test_dying_owner_can_use_alcohol_once_per_needed_hp_without_spending_turn_wine_state():
    engine = game()
    owner = engine.game_state.players[0]
    owner.hp = -1
    wine = card("a3_self_wine", "酒", "heart", 9, "basic")
    wine2 = card("a3_self_wine2", "酒", "diamond", 3, "basic")
    owner.hand.extend([wine, wine2])
    owner.jiu_used_this_turn = True
    owner.jiu_buff = True
    responder = ScriptedResponder(engine, {owner.id: "酒"})
    engine.card_system.responder = responder

    run(engine.card_system.enter_dying(owner))

    assert owner.alive is True and owner.hp == 1
    assert wine not in owner.hand and wine2 not in owner.hand
    assert wine in engine.game_state.discard_pile and wine2 in engine.game_state.discard_pile
    assert loc(engine, owner, wine) == loc(engine, owner, wine2) == 1
    assert owner.jiu_used_this_turn is True
    assert owner.jiu_buff is True
    assert len([r for p, r in responder.requests if p is owner]) == 2


def test_dying_owner_can_rescue_with_alcohol_stored_in_wooden_ox():
    engine = game()
    dying = engine.game_state.players[0]
    dying.hp = 0
    treasure_wine = card("a3_treasure_wine", "酒", "club", 8, "basic")
    wooden_ox = card("a3_treasure", "木牛流马", "diamond", 5, "equipment")
    dying.equipment["treasure"] = wooden_ox
    dying.treasure_cards.append(treasure_wine)
    responder = ScriptedResponder(engine, {dying.id: "酒"})
    engine.card_system.responder = responder

    run(engine.card_system.enter_dying(dying))

    assert dying.alive is True and dying.hp == 1
    assert treasure_wine not in dying.treasure_cards
    assert treasure_wine in engine.game_state.discard_pile
    assert loc(engine, dying, treasure_wine) == 1
    assert wooden_ox in dying.equipment.values()


def test_other_player_alcohol_is_not_a_legal_dying_rescue():
    engine = game()
    dying, other = engine.game_state.players[:2]
    dying.hp = 0
    other_wine = card("a3_other_wine", "酒", "heart", 4, "basic")
    other.hand.append(other_wine)
    responder = ScriptedResponder(engine, {other.id: "酒"})
    engine.card_system.responder = responder

    run(engine.card_system.enter_dying(dying))

    assert dying.alive is False
    assert other_wine in other.hand
    assert other.id not in [p.id for p, _ in responder.requests]


def test_dying_response_keeps_requesting_after_decline_and_uses_view_as_peach_legally():
    engine = game()
    dying, first, second = engine.game_state.players[:3]
    dying.hp = 0
    own_peach = card("a3_declined_self_peach", "桃", "heart", 6, "basic")
    dying.hand.append(own_peach)
    peach = card("a3_view_as_source", "闪", "heart", 7, "basic")
    first.hand.append(peach)
    # A native response skill can offer this card as 桃; use the real trigger
    # response-options contract and the normal response consumer.
    engine.skill_manager.response_options = lambda player, name: ([
        {"card": peach, "owner": first, "as_name": "桃", "skill_name": "测试视为桃"}
    ] if player is first and name == "桃" else [])
    responder = ScriptedResponder(engine, {dying.id: "pass", first.id: "桃"})
    engine.card_system.responder = responder

    run(engine.card_system.enter_dying(dying))

    assert dying.alive is True and dying.hp == 1
    assert own_peach in dying.hand  # 濒死者明确拒绝，不误消费。
    assert peach not in first.hand and peach in engine.game_state.discard_pile
    assert [p.id for p, _ in responder.requests] == [dying.id, first.id]


def test_dying_rescue_does_not_change_attack_wine_bonus_or_regular_use_count():
    engine = game()
    dying = engine.game_state.players[0]
    dying.hp = 0
    peach = card("a3_count_peach", "桃", "heart", 2, "basic")
    dying.hand.append(peach)
    dying.jiu_used_this_turn = False
    dying.jiu_buff = False
    engine.card_system.responder = ScriptedResponder(engine, {dying.id: "桃"})

    run(engine.card_system.enter_dying(dying))

    assert dying.alive and dying.hp == 1
    assert dying.jiu_used_this_turn is False
    assert dying.jiu_buff is False
    assert peach in engine.game_state.discard_pile
