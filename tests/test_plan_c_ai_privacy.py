"""Information-isolation checks for deterministic rule-AI choice inputs."""

from game_engine import MainEngine
from game_engine.state_manager import Card


def engine():
    return MainEngine({
        "mode": "5人身份局", "player_name": "P0",
        "ais": [{"name": f"AI{i}"} for i in range(1, 5)],
    })


def test_same_public_target_choice_ignores_hidden_identity_and_private_hands():
    game = engine()
    chooser, left, right = game.game_state.players[:3]
    chooser.identity = "rebel"
    left.identity = "lord"
    right.identity = "loyalist"
    left.identity_revealed = right.identity_revealed = False
    left.hp = right.hp = 2
    left.hand[:] = [Card("secret_l1", "桃", "heart", 3, "basic")]
    right.hand[:] = [Card("secret_r1", "杀", "spade", 8, "basic")]

    request = {
        "kind": "choose_players", "candidate_ids": [left.id, right.id],
        "options": [{"player_id": left.id}, {"player_id": right.id}],
        "min_n": 1, "max_n": 1,
        "context": {"intent": "harm", "all_players": list(game.game_state.players)},
    }
    visible_request = game._mask_hidden_candidates(request)
    first = game.ai_decision.simple_choice_decision(chooser, visible_request)

    # Change secret identities and hand cards without changing public facts.
    left.identity = "spy"
    right.identity = "rebel"
    left.hand[:] = [Card("secret_l2", "无懈可击", "club", 11, "trick")]
    right.hand[:] = [Card("secret_r2", "酒", "diamond", 12, "basic")]
    changed_request = game._mask_hidden_candidates(request)
    second = game.ai_decision.simple_choice_decision(chooser, changed_request)

    assert visible_request["context"] == changed_request["context"]
    assert "identity" not in visible_request["context"]["all_players"][left.id]
    assert "identity" not in visible_request["context"]["all_players"][right.id]
    assert visible_request["context"]["all_players"] == changed_request["context"]["all_players"]
    assert first == second == [0]


def test_hidden_card_candidates_are_masked_before_rules_choose_them():
    game = engine()
    chooser, owner = game.game_state.players[:2]
    first_secret = Card("private_card_1", "桃", "heart", 2, "basic")
    second_secret = Card("private_card_2", "闪", "club", 12, "basic")
    request = {
        "kind": "choose_cards", "candidate_cards": [first_secret, second_secret],
        "options": [{"card": first_secret, "owner": owner},
                    {"card": second_secret, "owner": owner}],
        "hidden_indices": [0, 1], "min_n": 1, "max_n": 1,
        "context": {"intent": "discard"},
    }
    masked = game._mask_hidden_candidates(request)
    first = game.ai_decision.simple_choice_decision(chooser, masked)
    assert masked["candidate_cards"] == [None, None]
    assert [option["card"] for option in masked["options"]] == [None, None]

    request["candidate_cards"] = [
        Card("private_card_3", "杀", "spade", 7, "basic"),
        Card("private_card_4", "无懈可击", "heart", 1, "trick"),
    ]
    request["options"] = [
        {"card": request["candidate_cards"][0], "owner": owner},
        {"card": request["candidate_cards"][1], "owner": owner},
    ]
    changed_masked = game._mask_hidden_candidates(request)
    second = game.ai_decision.simple_choice_decision(chooser, changed_masked)

    assert changed_masked["candidate_cards"] == [None, None]
    assert first == second == [0]
