"""牌面事件使用牌表中的真实图片名；未知牌仍保留可读文字。"""

from game_engine.state_manager import Card, card_to_dict


def test_playable_card_uses_existing_art_and_preserves_face():
    card = Card("display_sha", "杀", "heart", 7, "basic")
    payload = card_to_dict(card)
    assert payload["image"] == "sha"
    assert (payload["name"], payload["suit"], payload["rank"]) == ("杀", "heart", 7)


def test_new_art_and_virtual_name_use_the_resolved_effect_art():
    card = Card("display_conversion", "无中生有", "spade", 3, "trick")
    assert card_to_dict(card)["image"] == "wuzhongshengyou"
    converted = card_to_dict(card, name="杀")
    assert converted["image"] == "sha"
    assert converted["name"] == "杀"
    assert (converted["suit"], converted["rank"]) == ("spade", 3)
    # 牌表之外的自定义牌仍能以文字显示，不应构造不存在的图片 URL。
    assert "image" not in card_to_dict(Card("display_unknown", "自定义牌", "club", 1, "trick"))
