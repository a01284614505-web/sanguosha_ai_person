"""牌面事件使用牌表中的真实图片名，缺图时保留可读文字。"""

from game_engine.state_manager import Card, card_to_dict


def test_playable_card_uses_existing_art_and_preserves_face():
    card = Card("display_sha", "杀", "heart", 7, "basic")
    payload = card_to_dict(card)
    assert payload["image"] == "sha"
    assert (payload["name"], payload["suit"], payload["rank"]) == ("杀", "heart", 7)


def test_missing_art_uses_text_and_virtual_name_uses_effect_art():
    card = Card("display_conversion", "无中生有", "spade", 3, "trick")
    assert "image" not in card_to_dict(card)
    converted = card_to_dict(card, name="杀")
    assert converted["image"] == "sha"
    assert converted["name"] == "杀"
    assert (converted["suit"], converted["rank"]) == ("spade", 3)
