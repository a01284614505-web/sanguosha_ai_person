#!/usr/bin/env python3
"""Run the B7 five-player rules-AI acceptance batch with fixed seeds.

Usage: python -m scripts.verify_b7_games
"""

import asyncio
import json
import logging
import random

from game_engine import MainEngine


DECKS = {"standard": 108, "extra": 53, "combined": 161}
HEROES = ("liubei", "guanyu", "zhangfei", "zhugeliang", "zhaoyun",
          "machao", "huangyueying")
IDENTITIES = ("lord", "loyalist", "rebel", "spy")


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


async def one_game(deck_id, index):
    seed = 20261017 + index * 103 + list(DECKS).index(deck_id) * 1009
    random.seed(seed)
    identity = IDENTITIES[index % len(IDENTITIES)]
    config = MainEngine.normalize_config({
        "mode": "5人身份局",
        "selected_hero": {"id": HEROES[index % len(HEROES)]},
        "ais": [{"name": f"AI{seat}", "api_key": ""} for seat in range(1, 5)],
        "identity_card": {"use": True, "identity": identity},
        "deck_id": deck_id,
        "max_turns": 120,
        "phase_delay": 0,
        "turn_delay": 0,
    })
    engine = MainEngine(config)
    engine.set_trustee(True, source="rules")
    game_ends = []
    invalid_actions = []
    declined_skills = []
    engine.on("game_end", lambda **data: game_ends.append(data))
    original_execute = engine.execute_action

    async def checked_execute(player, action, target_ids=None):
        accepted = await original_execute(player, action, target_ids)
        if not accepted:
            detail = {"actor": player.name, "action": action,
                      "targets": target_ids, "phase": str(engine.game_state.current_phase)}
            if action.get("skill_name") == "激将" and action.get("variant") == "borrow_sha":
                declined_skills.append(detail)
            else:
                invalid_actions.append(detail)
        return accepted

    engine.execute_action = checked_execute
    winner = await engine.run()
    cards = all_cards(engine.game_state)
    ids = [card.id for card in cards]
    if len(ids) != DECKS[deck_id] or len(set(ids)) != len(ids):
        raise AssertionError(f"{deck_id}/{index}: entity conservation failed ({len(ids)}/{len(set(ids))})")
    if winner not in {"lord", "rebel", "spy", "draw"}:
        raise AssertionError(f"{deck_id}/{index}: abnormal winner {winner!r}")
    if len(game_ends) != 1:
        raise AssertionError(f"{deck_id}/{index}: game_end emitted {len(game_ends)} times")
    if invalid_actions:
        raise AssertionError(f"{deck_id}/{index}: illegal actions {invalid_actions!r}")
    return {"deck": deck_id, "seed": seed, "identity": identity,
            "hero": HEROES[index % len(HEROES)], "winner": winner,
            "turns": engine.completed_turns, "card_count": len(ids),
            "declined_skills": len(declined_skills)}


async def main():
    logging.disable(logging.CRITICAL)
    results = []
    for deck_id in DECKS:
        for index in range(10):
            results.append(await one_game(deck_id, index))
    print(json.dumps({"games": len(results), "normal": sum(r["winner"] != "draw" for r in results),
                      "draw": sum(r["winner"] == "draw" for r in results),
                      "declined_skills": sum(r["declined_skills"] for r in results),
                      "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
