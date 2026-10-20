"""Contracts for a versioned, privacy-safe model situation snapshot."""
import json

import pytest

from game_engine import MainEngine
from game_engine.public_situation import (
    build_private_situation,
    build_public_situation,
    compact_public_situation,
)
from game_engine.state_manager import Card, Phase
from game_engine.seats import seat_of


def make_engine():
    engine = MainEngine({"player_name": "真人", "ais": [{"name": f"AI{i}"} for i in range(1, 5)]})
    for player, identity in zip(engine.game_state.players,
                               ["lord", "rebel", "spy", "loyalist", "rebel"]):
        player.identity = identity
        player.identity_revealed = identity == "lord"
    return engine


def test_same_public_state_has_stable_version_and_compact_json():
    engine = make_engine()
    first = build_public_situation(engine)
    second = build_public_situation(engine)
    third = build_public_situation(engine)
    assert first == second == third
    assert first["schema_version"] == 1
    assert len(first["state_version"]) == 16
    assert first["event_seq"] == engine._log_seq
    assert first["card_move_seq"] == engine.game_state._card_move_sequence
    compact = compact_public_situation(first)
    assert compact == compact_public_situation(second)
    assert json.loads(compact) == first


@pytest.mark.parametrize("change", [
    "hp", "phase", "discard", "equipment", "sha_count", "event_seq", "card_move_seq",
])
def test_relevant_public_state_changes_update_version(change):
    engine = make_engine()
    before = build_public_situation(engine)["state_version"]
    player = engine.game_state.players[1]
    if change == "hp":
        player.hp -= 1
    elif change == "phase":
        engine.game_state.current_phase = Phase.DRAW
    elif change == "discard":
        engine.game_state.discard_pile.append(Card("pub-discard", "桃", "heart", 3, "basic"))
    elif change == "equipment":
        player.equipment["weapon"] = Card("pub-weapon", "丈八蛇矛", "spade", 12, "equipment",
                                           sub_type="weapon")
    elif change == "sha_count":
        player.sha_count += 1
    elif change == "event_seq":
        engine.next_log_seq()
    elif change == "card_move_seq":
        engine.game_state._card_move_sequence += 1
    assert build_public_situation(engine)["state_version"] != before


def test_private_hand_and_unrevealed_identity_changes_do_not_change_public_snapshot():
    engine = make_engine()
    hidden = engine.game_state.players[1]
    hidden.identity_revealed = False
    hidden.identity = "rebel"
    hidden.hand[:] = [Card("secret-a", "杀", "spade", 7, "basic"),
                      Card("secret-b", "桃", "heart", 3, "basic")]
    before = build_public_situation(engine)
    hidden.hand.reverse()
    hidden.identity = "spy"
    after = build_public_situation(engine)
    assert before == after
    assert after["players"][1]["identity"] is None
    encoded = compact_public_situation(after)
    assert "secret-a" not in encoded and "secret-b" not in encoded
    assert '"identity":"spy"' not in encoded


def test_distances_and_attack_range_delegate_to_authoritative_engine_apis(monkeypatch):
    engine = make_engine()
    source, target = engine.game_state.players[:2]
    source.equipment["weapon"] = Card("range-weapon", "丈八蛇矛", "spade", 12, "equipment",
                                       sub_type="weapon")
    distance_calls = []
    modifier_calls = []

    def base_distance(a, b):
        distance_calls.append((a.id, b.id))
        return 6

    def modify_distance(a, b, value):
        modifier_calls.append((a.id, b.id, value))
        return value - 2

    monkeypatch.setattr(engine.rules, "get_distance", base_distance)
    monkeypatch.setattr(engine.skill_manager, "modify_distance", modify_distance)
    view = build_public_situation(engine)
    assert view["distances"][str(source.id)][str(target.id)] == 4
    assert (source.id, target.id) in distance_calls
    assert (source.id, target.id, 6) in modifier_calls
    assert view["players"][0]["attack_range"] == source.get_equipment_range() == 3


def test_dead_players_are_omitted_from_distance_map():
    engine = make_engine()
    dead = engine.game_state.players[-1]
    dead.alive = False
    view = build_public_situation(engine)
    assert str(dead.id) not in view["distances"]
    assert all(str(dead.id) not in targets for targets in view["distances"].values())


def test_discard_summary_is_current_zone_and_clears_after_refill():
    engine = make_engine()
    state = engine.game_state
    state.deck.clear()
    state.discard_pile[:] = [Card("d1", "杀", "spade", 1, "basic"),
                             Card("d2", "桃", "heart", 2, "basic")]
    current = build_public_situation(engine)
    assert current["discard"] == {
        "count": 2,
        "by_name": {"杀": 1, "桃": 1},
        "latest": ["杀", "桃"],
    }
    assert state.refill_deck_if_empty()
    after_shuffle = build_public_situation(engine)
    assert after_shuffle["discard"] == {"count": 0, "by_name": {}, "latest": []}
    assert after_shuffle["state_version"] != current["state_version"]


def test_private_view_contains_only_viewers_cards_and_uses_existing_notes_api():
    engine = make_engine()
    viewer, other = engine.game_state.players[1:3]
    viewer.hand[:] = [Card("viewer-secret", "闪", "heart", 2, "basic")]
    viewer.treasure_cards[:] = [Card("viewer-treasure", "酒", "club", 9, "basic")]
    other.hand[:] = [Card("other-secret", "杀", "spade", 7, "basic")]
    engine.notes.ensure(viewer.id)
    engine.notes.update(viewer.id, {str(seat_of(engine.game_state, other.id)): {
        "guess": "rebel", "conf": "中", "why": "公开行为", "locked": False,
    }})
    view = build_private_situation(engine, viewer)
    assert view["public_state_version"] == build_public_situation(engine)["state_version"]
    assert [card["id"] for card in view["hand"]] == ["viewer-secret"]
    assert [card["id"] for card in view["treasure"]] == ["viewer-treasure"]
    assert next(item for item in view["cognitive_notes"]
                if item["target_id"] == other.id)["guess"] == "rebel"
    assert "other-secret" not in json.dumps(view, ensure_ascii=False)
    assert "other-secret" not in compact_public_situation(build_public_situation(engine))
    with pytest.raises(ValueError):
        build_private_situation(engine, 999)
