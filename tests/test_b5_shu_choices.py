"""B5 skill choices must commit effects only after a valid decision."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from game_engine import MainEngine
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
