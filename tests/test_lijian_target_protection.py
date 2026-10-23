"""A skill-created duel must respect the target's real protection before cost."""

from game_engine import MainEngine
from game_engine.state_manager import Card


def test_lijian_does_not_offer_duel_against_empty_hand_kongcheng():
    game = MainEngine({
        "mode": "5人身份局", "player_name": "P0",
        "ais": [{"name": f"AI{i}"} for i in range(1, 5)],
    })
    actor, first, protected = game.game_state.players[:3]
    actor.hero = {"id": "diaochan"}
    first.hero = {"id": "guanyu"}
    protected.hero = {"id": "zhugeliang"}
    actor.hand[:] = [Card("lijian-cost", "闪", "club", 4, "basic")]
    protected.hand.clear()
    game.skill_manager.bind_engine(game)

    actions = game.skill_manager.get_actions(actor)
    assert not any(action.get("skill_name") == "离间"
                   and action.get("fixed_target_ids") == [first.id, protected.id]
                   for action in actions)

    protected.hand.append(Card("kongcheng-off", "杀", "spade", 7, "basic"))
    actions = game.skill_manager.get_actions(actor)
    assert any(action.get("skill_name") == "离间"
               and action.get("fixed_target_ids") == [first.id, protected.id]
               for action in actions)
