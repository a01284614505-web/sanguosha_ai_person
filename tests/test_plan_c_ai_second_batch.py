"""Rule AI must account for costs in the production action and choice entrypoints."""

from game_engine import MainEngine
from game_engine.state_manager import Card


def make_game():
    return MainEngine({
        "mode": "5人身份局", "player_name": "P0",
        "ais": [{"name": f"AI{i}"} for i in range(1, 5)],
    })


def card(card_id, name):
    return Card(card_id, name, "spade", 2, "basic")


def test_active_skill_strategy_avoids_unsafe_kurou_and_recycles_only_cheap_cards():
    game = make_game()
    player = game.game_state.players[1]
    player.hp = 1
    player.hand[:] = [card("tao", "桃"), card("junk", "铁索连环")]
    actions = [
        {"type": "use_skill", "skill_name": "苦肉", "variant": "lose_hp", "card_indices": [1]},
        {"type": "use_skill", "skill_name": "制衡", "variant": "choose_discard"},
        {"type": "end_phase"},
    ]

    chosen = game.ai_decision.simple_ai_decision(player, actions)
    assert chosen["action"]["skill_name"] == "制衡"
    request = {
        "kind": "choose_cards", "skill_name": "制衡", "candidate_cards": list(player.hand),
        "min_n": 1, "max_n": 2, "cancelable": True,
    }
    assert game.ai_decision.simple_choice_decision(player, request) == [1]

    player.hand[:] = [card("tao2", "桃"), card("shan", "闪")]
    assert game.ai_decision.simple_choice_decision(player, request | {"candidate_cards": list(player.hand)}) == []
    assert game.ai_decision.simple_ai_decision(player, actions)["action"]["type"] == "end_phase"


def test_qingjian_uses_public_friend_and_beneficial_receiver_order():
    game = make_game()
    player, lord, unknown = game.game_state.players[:3]
    player.identity = "loyalist"
    lord.identity = "lord"
    lord.identity_revealed = True
    unknown.identity = "rebel"
    unknown.identity_revealed = False
    confirm = {"kind": "confirm", "skill_name": "清俭", "default": False}
    assert game.ai_decision.simple_choice_decision(player, confirm) == [0]

    request = {
        "kind": "choose_players", "skill_name": "清俭",
        "candidate_ids": [unknown.id, lord.id], "min_n": 1, "max_n": 1,
        "context": {"all_players": [unknown, lord]},
    }
    masked = game._mask_hidden_candidates(request)
    assert game.ai_decision.simple_choice_decision(player, masked) == [1]

    lord.identity_revealed = False
    assert game.ai_decision.simple_choice_decision(player, confirm) == [1]


def test_judgement_replacement_requires_public_relation_and_improves_result():
    game = make_game()
    owner, lord, unknown = game.game_state.players[:3]
    owner.identity = "loyalist"
    lord.identity = "lord"
    lord.identity_revealed = True
    unknown.identity = "rebel"
    unknown.identity_revealed = False
    owner.hand[:] = [card("bad", "桃"), Card("good", "杀", "heart", 7, "basic")]
    context = {"judged_player": lord, "judge_type": "乐不思蜀",
               "judge_suit": "spade", "judge_rank": 4}
    confirm = game._mask_hidden_candidates({
        "kind": "confirm", "skill_name": "鬼才", "context": context, "default": False,
    })
    choose = game._mask_hidden_candidates({
        "kind": "choose_cards", "skill_name": "鬼才", "context": context,
        "candidate_cards": list(owner.hand), "min_n": 1, "max_n": 1,
    })
    assert game.ai_decision.simple_choice_decision(owner, confirm) == [0]
    assert game.ai_decision.simple_choice_decision(owner, choose) == [1]

    context["judged_player"] = unknown
    hidden_confirm = game._mask_hidden_candidates({
        "kind": "confirm", "skill_name": "鬼才", "context": context, "default": False,
    })
    assert game.ai_decision.simple_choice_decision(owner, hidden_confirm) == [1]

    owner.hand[:] = [Card("club", "杀", "club", 7, "basic")]
    context = {"judged_player": lord, "judge_type": "兵粮寸断",
               "judge_suit": "heart", "judge_rank": 7}
    masked = game._mask_hidden_candidates({
        "kind": "confirm", "skill_name": "鬼道", "context": context, "default": False,
    })
    assert game.ai_decision.simple_choice_decision(owner, masked) == [0]
