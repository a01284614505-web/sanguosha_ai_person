"""B5 skill choices must commit effects only after a valid decision."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from game_engine import MainEngine
from game_engine.skill_runtime_core import reset_turn_flags
from game_engine.state_manager import Card, Phase


def engine_for(hero_id):
    config = MainEngine.normalize_config({
        "mode": "5人身份局", "selected_hero": {"id": hero_id},
        "ais": [{"name": f"AI{i}"} for i in range(4)], "deck_id": "standard",
    })
    engine = MainEngine(config)
    for player in engine.game_state.players:
        player.hand.clear()
        player.equipment.clear()
        player.judge_area.clear()
    engine.game_state.current_player = engine.game_state.players[0]
    engine.game_state.current_player_index = 0
    return engine


def test_tishen_decline_preserves_limited_charge_then_accept_consumes_once():
    engine = engine_for("zhangfei")
    player = engine.game_state.players[0]
    handler = engine.skill_manager.handlers[0]
    player.hp = player.max_hp - 2
    engine.game_state.current_phase = Phase.PREPARE
    instance = engine.skill_manager._skill_instance(player, "替身")
    assert instance.charges == 1
    engine.ask_confirm = AsyncMock(side_effect=[False, True])

    asyncio.run(handler.before_phase(player, Phase.PREPARE))
    assert player.hp == player.max_hp - 2
    assert instance.charges == 1
    assert engine.stats.row(player)["skill_activations"] == 0

    asyncio.run(handler.before_phase(player, Phase.PREPARE))
    assert player.hp == player.max_hp
    assert len(player.hand) == 2
    assert instance.charges == 0
    assert engine.stats.row(player)["skill_activations"] == 1
    assert engine.skill_manager.skill_available(player, "替身") is False


def test_guanxing_uses_player_order_and_places_remainder_at_bottom():
    engine = engine_for("zhugeliang")
    player = engine.game_state.players[0]
    player.is_ai = True
    engine.game_state.current_phase = Phase.PREPARE
    original = list(engine.game_state.deck)
    top_five = original[:5]
    requests = []

    class Picker:
        async def make_choice_decision(self, _player, request):
            requests.append(request)
            if request["kind"] == "confirm":
                return [0]
            if "牌堆顶" in request["prompt"]:
                return [1, 0]
            return [2, 1, 0]

    engine.ai_decision = Picker()
    asyncio.run(engine.skill_manager.handlers[0].before_phase(player, Phase.PREPARE))
    assert engine.game_state.deck[:2] == [top_five[1], top_five[0]]
    assert engine.game_state.deck[-3:] == [top_five[4], top_five[3], top_five[2]]
    assert len(engine.game_state.deck) == len(original)
    assert {card.id for card in engine.game_state.deck} == {card.id for card in original}
    assert [request["kind"] for request in requests] == ["confirm", "choose_cards", "choose_cards"]


def test_guanxing_decline_and_short_deck_preserve_cards():
    engine = engine_for("zhugeliang")
    owner = engine.game_state.players[0]
    handler = engine.skill_manager.handlers[0]
    engine.game_state.current_phase = Phase.PREPARE
    cards = list(engine.game_state.deck[:2])
    engine.game_state.deck[:] = cards
    engine.ask_confirm = AsyncMock(return_value=False)
    asyncio.run(handler.before_phase(owner, Phase.PREPARE))
    assert engine.game_state.deck == cards
    assert not owner.flags.get("guanxing_bottomed")

    engine.ask_confirm = AsyncMock(return_value=True)
    engine.ask_choose_cards_result = AsyncMock(return_value={"bool": True, "cards": [cards[1]]})
    asyncio.run(handler.before_phase(owner, Phase.PREPARE))
    assert engine.game_state.deck == [cards[1], cards[0]]
    assert len(engine.game_state.deck) == 2


def test_tieqi_decline_does_not_judge_or_disable_target():
    engine = engine_for("machao")
    source, target = engine.game_state.players[:2]
    handler = engine.skill_manager.handlers[0]
    original_top = engine.game_state.deck[0]
    event = {"shanRequired": 1, "baseDamage": 1}
    engine.ask_confirm = AsyncMock(return_value=False)
    asyncio.run(handler.before_sha(source, target, Card("b5_sha", "杀", "spade", 7, "basic"), event))
    assert engine.game_state.deck[0] is original_top
    assert not target.flags.get("nonlocked_disabled")
    assert event == {"shanRequired": 1, "baseDamage": 1}


def test_jizhi_decline_leaves_draw_pile_and_stats_untouched():
    engine = engine_for("huangyueying")
    player = engine.game_state.players[0]
    handler = engine.skill_manager.handlers[0]
    original_top = engine.game_state.deck[0]
    engine.ask_confirm = AsyncMock(return_value=False)
    asyncio.run(handler.after_card_used(player, Card("b5_trick", "无中生有", "heart", 7, "trick"), [], True))
    assert engine.game_state.deck[0] is original_top
    assert not player.hand
    assert engine.stats.row(player)["skill_activations"] == 0


def test_yijue_target_chooses_shown_card_and_owner_can_decline_red_benefits():
    engine = engine_for("guanyu")
    owner, target = engine.game_state.players[:2]
    cost = Card("yijue_cost", "杀", "spade", 7, "basic")
    red = Card("yijue_red", "闪", "heart", 2, "basic")
    black = Card("yijue_black", "杀", "club", 9, "basic")
    owner.hand.append(cost)
    target.hand.extend([black, red])
    target.hp -= 1
    engine.ask_choose_cards = AsyncMock(side_effect=[[cost], [red]])
    engine.ask_confirm = AsyncMock(side_effect=[False, False])
    action = {"skill_name": "义绝", "variant": "reveal", "card_indices": []}
    result = asyncio.run(engine.skill_manager.handlers[0].execute(owner, action, [target]))
    assert result is True
    assert red in target.hand and red not in owner.hand
    assert target.hp == target.max_hp - 1
    assert cost in engine.game_state.discard_pile
    assert engine.ask_choose_cards.await_args.args[0] is target


def test_yijue_equipment_cost_is_legal_and_cancel_preserves_equipment():
    engine = engine_for("guanyu")
    owner, target = engine.game_state.players[:2]
    weapon = Card("yijue_weapon", "青釭剑", "spade", 6, "equipment")
    owner.equipment["weapon"] = weapon
    target.hand.append(Card("yijue_shown", "杀", "club", 5, "basic"))
    handler = engine.skill_manager.handlers[0]
    actions = handler.get_actions(owner)
    assert any(action["skill_name"] == "义绝" for action in actions)
    engine.ask_choose_cards = AsyncMock(return_value=[])
    action = next(action for action in actions if action["skill_name"] == "义绝")
    assert asyncio.run(handler.execute(owner, action, [target])) is False
    assert owner.equipment["weapon"] is weapon
    assert not owner.flags.get("skill_used", {}).get("义绝")


def test_yijue_black_restricts_hand_and_nonlocked_skills_until_turn_end():
    engine = engine_for("guanyu")
    owner, target = engine.game_state.players[:2]
    cost = Card("yijue_black_cost", "闪", "heart", 3, "basic")
    shown = Card("yijue_black_shown", "杀", "spade", 8, "basic")
    owner.hand.append(cost)
    target.hand.append(shown)
    assert engine.skill_manager.has_skill(target, "反馈")
    engine.ask_choose_cards = AsyncMock(side_effect=[[cost], [shown]])
    handler = engine.skill_manager.handlers[0]
    assert asyncio.run(handler.execute(owner, {"skill_name": "义绝", "variant": "reveal"}, [target])) is True
    assert target.flags["cannot_use_hand"] is True
    assert target.flags["nonlocked_disabled"] is True
    assert not engine.skill_manager.has_skill(target, "反馈")
    assert engine.rules.can_play_card(target, shown, [owner])[0] is False
    asyncio.run(handler.after_phase(owner, Phase.END))
    assert not target.flags.get("cannot_use_hand")
    assert not target.flags.get("nonlocked_disabled")
    assert engine.skill_manager.has_skill(target, "反馈")


def test_yijue_and_tieqi_overlapping_sources_clear_only_their_own_effects():
    engine = engine_for("guanyu")
    yijue_owner, target, tieqi_owner = engine.game_state.players[:3]
    cost = Card("yijue_overlap_cost", "闪", "heart", 3, "basic")
    shown = Card("yijue_overlap_shown", "杀", "spade", 8, "basic")
    yijue_owner.hand.append(cost)
    target.hand.append(shown)
    engine.ask_choose_cards = AsyncMock(side_effect=[[cost], [shown]])
    handler = engine.skill_manager.handlers[0]
    assert asyncio.run(handler.execute(yijue_owner, {"skill_name": "义绝", "variant": "reveal"}, [target]))
    original_has = handler.has
    handler.has = lambda player, skill: (player is tieqi_owner and skill == "铁骑") or original_has(player, skill)
    handler.manager.judge = AsyncMock(return_value=Card("tieqi_overlap_judge", "桃", "heart", 6, "basic"))
    engine.ask_confirm = AsyncMock(return_value=True)
    event = {"shanRequired": 1, "baseDamage": 1}
    asyncio.run(handler.before_sha(tieqi_owner, target, Card("tieqi_overlap_sha", "杀", "club", 7, "basic"), event))
    assert target.flags["yijue_sources"] == [yijue_owner.id]
    assert target.flags["tieqi_sources"] == [tieqi_owner.id]
    reset_turn_flags(target)
    assert target.flags["cannot_use_hand"] and target.flags["nonlocked_disabled"]

    asyncio.run(handler.after_phase(yijue_owner, Phase.END))
    assert not target.flags.get("cannot_use_hand")
    assert target.flags["nonlocked_disabled"]
    assert asyncio.run(handler.modify_damage(yijue_owner, target, 1, Card("overlap_heart_sha", "杀", "heart", 4, "basic"))) == 1

    asyncio.run(handler.after_phase(tieqi_owner, Phase.END))
    assert not target.flags.get("nonlocked_disabled")
    assert not target.flags.get("tieqi_sources")


def test_yajiao_decline_preserves_deck_and_matching_reveal_uses_player_target():
    engine = engine_for("zhaoyun")
    owner, other = engine.game_state.players[:2]
    engine.game_state.current_player = other
    lost = Card("yajiao_lost", "杀", "spade", 7, "basic")
    owner.hand.append(lost)
    reveal = engine.game_state.deck[0]
    reveal.card_type = lost.card_type
    handler = engine.skill_manager.handlers[0]
    event = SimpleNamespace(from_zone="hand")
    engine.ask_confirm = AsyncMock(return_value=False)
    asyncio.run(handler.on_cards_lost(owner, [lost], "respond", event=event))
    assert engine.game_state.deck[0] is reveal

    engine.ask_confirm = AsyncMock(return_value=True)
    engine.ask_choose_players = AsyncMock(return_value=[owner])
    asyncio.run(handler.on_cards_lost(owner, [lost], "respond", event=event))
    assert reveal in owner.hand
    assert reveal not in engine.game_state.deck
    assert reveal not in engine.game_state.discard_pile


def test_yajiao_mismatched_reveal_discards_selected_nearby_card():
    engine = engine_for("zhaoyun")
    owner, nearby, current = engine.game_state.players[:3]
    engine.game_state.current_player = current
    lost = Card("yajiao_mismatch_lost", "杀", "spade", 7, "basic")
    nearby_card = Card("yajiao_nearby", "闪", "heart", 4, "basic")
    owner.hand.append(lost)
    nearby.hand.append(nearby_card)
    reveal = engine.game_state.deck[0]
    reveal.card_type = "trick"
    engine.ask_confirm = AsyncMock(return_value=True)
    engine.ask_choose_players = AsyncMock(return_value=[nearby])
    engine.ask_choose_cards = AsyncMock(return_value=[nearby_card])
    event = SimpleNamespace(from_zone="hand")
    asyncio.run(engine.skill_manager.handlers[0].on_cards_lost(owner, [lost], "respond", event=event))
    assert reveal in engine.game_state.discard_pile
    assert nearby_card in engine.game_state.discard_pile
    assert nearby_card not in nearby.hand


def test_jijiang_response_requires_donor_consent_and_card_selection():
    engine = engine_for("liubei")
    lord, first, second = engine.game_state.players[:3]
    lord.identity = "lord"
    first.hero = {"faction": "shu"}
    second.hero = {"faction": "shu"}
    first_card = Card("jijiang_first", "杀", "spade", 3, "basic")
    second_card = Card("jijiang_second", "杀", "heart", 4, "basic")
    first.hand.append(first_card)
    second.hand.append(second_card)
    engine.ask_confirm = AsyncMock(side_effect=[False, True])
    engine.ask_choose_cards = AsyncMock(return_value=[second_card])
    offered = asyncio.run(engine.skill_manager.request_lord_sha(lord, first))
    assert offered["card"] is second_card
    assert offered["owner"] is second
    assert first_card in first.hand and second_card in second.hand
    assert engine.ask_choose_cards.await_args.args[0] is second


def test_rende_virtual_card_rejects_stale_target_without_spending_once_per_turn_use():
    engine = engine_for("liubei")
    owner = engine.game_state.players[0]
    owner.flags["rende_basic_available"] = True
    action = {"skill_name": "仁德", "variant": "basic_sha", "card_indices": []}
    assert asyncio.run(engine.skill_manager.handlers[0].execute(owner, action, [])) is False
    assert owner.flags["rende_basic_available"] is True
    assert not owner.flags.get("rende_basic_used")

    owner.hp = owner.max_hp
    action["variant"] = "basic_tao"
    assert asyncio.run(engine.skill_manager.handlers[0].execute(owner, action, [])) is False
    assert owner.flags["rende_basic_available"] is True
    assert not owner.flags.get("rende_basic_used")


def test_rende_gifts_two_distinct_players_before_virtual_card_becomes_available():
    engine = engine_for("liubei")
    owner, first, second = engine.game_state.players[:3]
    first_card = Card("rende_first", "杀", "club", 3, "basic")
    second_card = Card("rende_second", "闪", "diamond", 4, "basic")
    owner.hand.extend([first_card, second_card])
    owner.hp -= 1
    handler = engine.skill_manager.handlers[0]
    give = {"skill_name": "仁德", "variant": "give", "card_indices": [0]}
    assert asyncio.run(handler.execute(owner, give, [first])) is True
    assert first_card in first.hand
    assert owner.flags["rende_count"] == 1
    assert first.id not in handler.get_actions(owner)[0]["valid_targets"]
    assert asyncio.run(handler.execute(owner, give, [second])) is True
    assert second_card in second.hand
    assert owner.flags["rende_basic_available"] is True
    choices = handler.get_actions(owner)
    assert {choice["variant"] for choice in choices} >= {"basic_tao", "basic_sha"}
    assert asyncio.run(handler.execute(owner, {"skill_name": "仁德", "variant": "basic_tao"}, [])) is True
    assert owner.hp == owner.max_hp
    assert owner.flags["rende_basic_used"] is True
    assert not owner.flags["rende_basic_available"]


def test_tieqi_target_may_give_matching_card_to_avoid_extra_damage():
    engine = engine_for("machao")
    source, target = engine.game_state.players[:2]
    handler = engine.skill_manager.handlers[0]
    matching = Card("tieqi_match", "闪", "heart", 5, "basic")
    target.hand.append(matching)
    handler.manager.judge = AsyncMock(return_value=Card("tieqi_judge", "杀", "heart", 8, "basic"))
    engine.ask_confirm = AsyncMock(return_value=True)
    engine.ask_choose_cards = AsyncMock(return_value=[matching])
    event = {"shanRequired": 1, "baseDamage": 1}
    asyncio.run(handler.before_sha(source, target, Card("tieqi_sha", "杀", "spade", 7, "basic"), event))
    assert matching in source.hand and matching not in target.hand
    assert event == {"shanRequired": 1, "baseDamage": 1}
    assert target.flags["nonlocked_disabled"] is True


def test_tieqi_without_matching_card_prevents_dodge_and_adds_damage():
    engine = engine_for("machao")
    owner, target = engine.game_state.players[:2]
    target.hand.append(Card("tieqi_shan", "闪", "heart", 6, "basic"))
    handler = engine.skill_manager.handlers[0]
    handler.manager.judge = AsyncMock(return_value=Card("tieqi_judge_black", "杀", "spade", 8, "basic"))
    engine.ask_confirm = AsyncMock(return_value=True)
    before = target.hp
    assert asyncio.run(engine.card_system.use_sha(owner, Card("tieqi_resolve", "杀", "club", 7, "basic"), target)) is True
    assert target.hp == before - 2
    assert target.flags["nonlocked_disabled"] is True
    assert any(card.name == "闪" for card in target.hand)
    asyncio.run(handler.after_phase(owner, Phase.END))
    assert not target.flags.get("nonlocked_disabled")


def test_rende_virtual_sha_resolves_after_last_hand_card_is_given():
    engine = engine_for("liubei")
    owner, first, second = engine.game_state.players[:3]
    victim = engine.game_state.players[4]
    owner.hand.extend([
        Card("rende_sha_gift1", "闪", "heart", 2, "basic"),
        Card("rende_sha_gift2", "桃", "heart", 3, "basic"),
    ])
    handler = engine.skill_manager.handlers[0]
    give = {"skill_name": "仁德", "variant": "give", "card_indices": [0]}
    assert asyncio.run(handler.execute(owner, give, [first])) is True
    assert asyncio.run(handler.execute(owner, give, [second])) is True
    assert not owner.hand
    assert any(action["variant"] == "basic_sha" for action in handler.get_actions(owner))
    before = victim.hp
    assert asyncio.run(handler.execute(owner, {"skill_name": "仁德", "variant": "basic_sha"}, [victim])) is True
    assert victim.hp == before - 1
    assert owner.flags["rende_basic_used"] is True


def test_jizhi_accept_draws_and_optional_basic_discard_increases_hand_limit():
    engine = engine_for("huangyueying")
    owner = engine.game_state.players[0]
    handler = engine.skill_manager.handlers[0]
    top = Card("jizhi_top", "闪", "diamond", 6, "basic")
    engine.game_state.deck.insert(0, top)
    engine.ask_confirm = AsyncMock(side_effect=[True, True])
    asyncio.run(handler.after_card_used(owner, Card("jizhi_trick", "无中生有", "heart", 7, "trick"), [], True))
    assert top in engine.game_state.discard_pile
    assert top not in owner.hand
    assert owner.flags["hand_limit_bonus"] == 1


def test_wusheng_and_longdan_offer_only_valid_conversion_cards():
    wusheng = engine_for("guanyu")
    owner = wusheng.game_state.players[0]
    red = Card("wusheng_red", "桃", "heart", 3, "basic")
    black = Card("wusheng_black", "桃", "spade", 4, "basic")
    owner.hand.extend([red, black])
    options = wusheng.skill_manager.handlers[0].response_options(owner, "杀")
    assert [option["card"] for option in options if option["skill_name"] == "武圣"] == [red]

    longdan = engine_for("zhaoyun")
    owner = longdan.game_state.players[0]
    sha = Card("longdan_sha", "杀", "club", 5, "basic")
    shan = Card("longdan_shan", "闪", "diamond", 6, "basic")
    tao = Card("longdan_tao", "桃", "heart", 7, "basic")
    wine = Card("longdan_wine", "酒", "spade", 8, "basic")
    owner.hand.extend([sha, shan, tao, wine])
    handler = longdan.skill_manager.handlers[0]
    assert [option["card"] for option in handler.response_options(owner, "闪")] == [sha]
    assert [option["card"] for option in handler.response_options(owner, "杀")] == [shan]
    assert [option["card"] for option in handler.response_options(owner, "桃")] == [wine]
    assert [option["card"] for option in handler.response_options(owner, "酒")] == [tao]


def test_paoxiao_dodges_accumulate_damage_then_spend_tokens():
    engine = engine_for("zhangfei")
    owner, target = engine.game_state.players[:2]
    handler = engine.skill_manager.handlers[0]
    sha = Card("paoxiao_sha", "杀", "spade", 9, "basic")
    asyncio.run(handler.on_turn_start(owner))
    assert owner.max_sha == 999
    asyncio.run(handler.on_sha_dodged(owner, target, sha, {}))
    asyncio.run(handler.on_sha_dodged(owner, target, sha, {}))
    assert asyncio.run(handler.modify_damage(owner, target, 1, sha)) == 3
    assert owner.flags.get("pao_tokens", 0) == 0
    assert asyncio.run(handler.modify_damage(owner, target, 1, sha)) == 1

    asyncio.run(handler.on_sha_dodged(owner, target, sha, {}))
    asyncio.run(handler.after_phase(owner, Phase.END))
    assert "pao_tokens" not in owner.flags
    assert asyncio.run(handler.modify_damage(owner, target, 1, sha)) == 1


def test_kongcheng_mashu_and_qicai_passive_boundaries():
    kongcheng = engine_for("zhugeliang")
    owner, attacker = kongcheng.game_state.players[:2]
    handler = kongcheng.skill_manager.handlers[0]
    assert handler.can_target(attacker, owner, "杀")
    assert handler.can_target(attacker, owner, "决斗")
    assert handler.can_target(attacker, owner, "火攻") is None
    owner.flags["nonlocked_disabled"] = True
    assert handler.can_target(attacker, owner, "杀")
    owner.flags.pop("nonlocked_disabled")
    owner.hand.append(Card("kongcheng_card", "桃", "heart", 1, "basic"))
    assert handler.can_target(attacker, owner, "杀") is None

    mashu = engine_for("machao")
    assert mashu.skill_manager.handlers[0].modify_distance(mashu.game_state.players[0],
                                                             mashu.game_state.players[1], 2) == 1

    qicai = engine_for("huangyueying")
    owner = qicai.game_state.players[0]
    armor = Card("qicai_armor", "八卦阵", "club", 2, "equipment")
    handler = qicai.skill_manager.handlers[0]
    assert handler.protect_card(owner, armor, "other_discard_equipment") is True
    assert handler.protect_card(owner, armor, "discard") is False
    grain = Card("qicai_grain", "兵粮寸断", "spade", 10, "trick")
    owner.hand.append(grain)
    qicai.game_state.current_phase = Phase.PLAY
    assert qicai.game_state.get_distance(owner, qicai.game_state.players[2]) > 1
    assert qicai.rules.can_play_card(owner, grain, [qicai.game_state.players[2]])[0] is True
