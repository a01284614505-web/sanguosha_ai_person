#!/usr/bin/env python3
"""Small paired strategy-ablation batch using the production rule-AI entrypoint.

Each seed reuses the same deck, hero, identity, and initial engine setup across
the four modes. Later random draws may diverge when a mode changes a choice.
No model/provider calls are made.
"""

import asyncio
import json
import logging
import random

from game_engine import MainEngine


MODES = {
    "baseline": {"skill_strategy": False, "target_strategy": False},
    "skill_only": {"skill_strategy": True, "target_strategy": False},
    "target_only": {"skill_strategy": False, "target_strategy": True},
    "both": {"skill_strategy": True, "target_strategy": True},
}
SAMPLES = (
    {"seed": 20261020, "identity": "lord", "hero": "liubei"},
    {"seed": 20261123, "identity": "loyalist", "hero": "guanyu"},
    {"seed": 20261226, "identity": "rebel", "hero": "zhangfei"},
    {"seed": 20261329, "identity": "spy", "hero": "zhaoyun"},
)
AI_HEROES = ("caocao", "sunquan", "huatuo", "zhouyu")
DECK_COUNTS = {"standard": 108, "extra": 53, "combined": 161}


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


async def run_game(sample, mode_name, knobs):
    random.seed(sample["seed"])
    config = {
        "mode": "5人身份局",
        "selected_hero": {"id": sample["hero"]},
        "ais": [
            {"name": f"AI{seat}", "api_key": "", "hero": {"id": hero_id}}
            for seat, hero_id in enumerate(AI_HEROES, start=1)
        ],
        "identity_card": {"use": True, "identity": sample["identity"]},
        "deck_id": "standard",
        "max_turns": 60,
        "phase_delay": 0,
        "turn_delay": 0,
        "ai_ablation": dict(knobs),
    }
    engine = MainEngine(config)
    engine.set_trustee(True, source="rules")
    illegal_actions = []
    original_execute = engine.execute_action

    async def checked_execute(player, action, target_ids=None):
        accepted = await original_execute(player, action, target_ids)
        if not accepted:
            illegal_actions.append({
                "player_id": player.id,
                "action": action,
                "targets": list(target_ids or []),
                "phase": str(engine.game_state.current_phase),
            })
        return accepted

    engine.execute_action = checked_execute
    winner = await engine.run()
    cards = all_cards(engine.game_state)
    card_ids = [card.id for card in cards]
    rescue_events = [entry for entry in engine.game_log
                     if entry.get("event_kind") == "dying_rescue"]
    activation_count = sum(
        1 for entry in engine.skill_manager.activation_log
        if entry.get("event") == "activate"
    )
    stat_rows = engine.stats.snapshot()
    identity_wins = {
        identity: int(winner == identity)
        for identity in ("lord", "loyalist", "rebel", "spy")
    }
    return {
        "mode": mode_name,
        "knobs": dict(knobs),
        "seed": sample["seed"],
        "starting_identity": sample["identity"],
        "starting_hero": sample["hero"],
        "ai_heroes": [player.hero.get("id") for player in engine.game_state.players[1:]],
        "winner": winner,
        "winner_by_identity": identity_wins,
        "turns": engine.completed_turns,
        "draw": winner == "draw",
        "aborted": bool(engine._abort_reason),
        "abort_reason": engine._abort_reason,
        "illegal_action_count": len(illegal_actions),
        "illegal_actions": illegal_actions,
        "skill_activation_count": activation_count,
        "rescue_count": len(rescue_events),
        "rescue_events": rescue_events,
        "healing_total": sum(row.get("healing", 0) for row in stat_rows.values()),
        "card_count": len(card_ids),
        "expected_card_count": DECK_COUNTS["standard"],
        "card_conservation_ok": len(card_ids) == DECK_COUNTS["standard"] == len(set(card_ids)),
        "distinct_card_count": len(set(card_ids)),
    }


def summarize(rows):
    output = {}
    for mode in MODES:
        group = [row for row in rows if row["mode"] == mode]
        by_identity = {}
        for identity in ("lord", "loyalist", "rebel", "spy"):
            games = [row for row in group if row["starting_identity"] == identity]
            by_identity[identity] = {
                "games": len(games),
                "wins": sum(row["winner"] == identity for row in games),
                "game_winners": {name: sum(row["winner"] == name for row in games)
                                 for name in ("lord", "rebel", "spy", "draw", "aborted")},
            }
        output[mode] = {
            "games": len(group),
            "wins_by_role": {name: sum(row["winner"] == name for row in group)
                             for name in ("lord", "rebel", "spy", "draw", "aborted")},
            "mean_turns": round(sum(row["turns"] for row in group) / len(group), 2) if group else 0,
            "skill_activations": sum(row["skill_activation_count"] for row in group),
            "rescues": sum(row["rescue_count"] for row in group),
            "healing": sum(row["healing_total"] for row in group),
            "illegal_actions": sum(row["illegal_action_count"] for row in group),
            "aborts": sum(row["aborted"] for row in group),
            "draws": sum(row["draw"] for row in group),
            "card_conservation_failures": sum(not row["card_conservation_ok"] for row in group),
            "by_starting_identity": by_identity,
        }
    return output


async def main():
    logging.disable(logging.CRITICAL)
    rng_state = random.getstate()
    try:
        results = []
        for sample in SAMPLES:
            for mode_name, knobs in MODES.items():
                results.append(await run_game(sample, mode_name, knobs))
    finally:
        # The experiment is an isolated measurement: deterministic seeding in
        # one process must not shift any later production-game randomness.
        random.setstate(rng_state)
    print(json.dumps({
        "experiment": "paired_rule_ai_strategy_ablation_small",
        "schema_version": 1,
        "provider_calls": 0,
        "deck": "standard",
        "paired_seeds": [sample["seed"] for sample in SAMPLES],
        "games_per_mode": len(SAMPLES),
        "total_games": len(results),
        "modes": MODES,
        "summary": summarize(results),
        "results": results,
        "notes": [
            "Each seed shares the same configured heroes, starting identity, deck and initial setup across all four modes.",
            "A changed decision can change later random draws; exact turn-by-turn draw identity is not claimed.",
            "Rescue count uses explicit event_kind=dying_rescue records; no hidden hand contents are inferred.",
            "Small batch exposes regressions; it is not a win-rate significance claim.",
        ],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
