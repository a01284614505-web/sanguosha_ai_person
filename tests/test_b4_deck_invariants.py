"""三套牌堆固定种子的 B4 实体守恒与合法操作回放。"""

import asyncio
import random
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from game_engine import MainEngine
from game_engine.card_table import CARD_TABLE
from game_engine.state_manager import Phase


def test_every_card_table_image_resolves_to_a_real_png():
    """界面按 image 字段加载牌图，逐条核对，防止名称回退或假占位。"""
    asset_dir = Path(__file__).resolve().parents[1] / "frontend/assets/cards"
    assert len(CARD_TABLE) == 42
    for name, spec in CARD_TABLE.items():
        assert spec.image, f"{name} 没有牌图映射"
        path = asset_dir / f"{spec.image}.png"
        assert path.is_file(), f"{name} 对应文件不存在：{path.name}"
        assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", f"{name} 并非 PNG"


def all_cards(state):
    cards = list(state.deck) + list(state.discard_pile)
    for player in state.players:
        cards.extend(player.hand)
        cards.extend(player.equipment.values())
        cards.extend(player.judge_area)
        cards.extend(player.shown)
        cards.extend(player.temporary)
        cards.extend(player.treasure_cards)
    return cards


@pytest.mark.parametrize("deck_id,expected", [("standard", 108), ("extra", 53), ("combined", 161)])
@pytest.mark.parametrize("seed", [7, 23, 41])
def test_equipment_action_preserves_every_card_in_three_decks(deck_id, expected, seed):
    random_state = random.getstate()
    random.seed(seed)
    try:
        engine = MainEngine({"mode": "5人身份局", "player_name": "P0",
                             "ais": [{"name": f"P{i}"} for i in range(1, 5)],
                             "deck_id": deck_id})
    finally:
        random.setstate(random_state)
    state = engine.game_state
    player = state.players[0]
    state.current_player = player
    state.current_player_index = 0
    state.current_phase = Phase.PLAY
    before = {card.id for card in all_cards(state)}
    assert len(before) == expected

    async def scenario():
        equipment = next(card for card in state.deck
                         if CARD_TABLE[card.name].card_type == "equipment")
        assert await engine.move_card(equipment, "deck", "hand", to_owner=player,
                                      reason="test_deal", actor_id=player.id) is not None
        index = player.hand.index(equipment)
        legal = next(action for action in engine.get_available_actions(player)
                     if action.get("type") == "play_card" and action.get("card_index") == index)
        assert await engine.execute_action(player, legal)
        assert equipment in player.equipment.values()

        if equipment.name == "木牛流马" and state.deck:
            stored = state.deck[0]
            await engine.move_card(stored, "deck", "hand", to_owner=player,
                                   reason="test_deal", actor_id=player.id)
            engine.ask_choose_players = AsyncMock(return_value=[])
            action = next(action for action in engine.get_available_actions(player)
                          if action.get("skill_name") == "木牛流马"
                          and action.get("card_indices") == [player.hand.index(stored)])
            assert await engine.execute_action(player, action)
            assert stored in player.treasure_cards

    asyncio.run(scenario())
    after = all_cards(state)
    assert len(after) == expected
    assert {card.id for card in after} == before
    assert len({card.id for card in after}) == expected
