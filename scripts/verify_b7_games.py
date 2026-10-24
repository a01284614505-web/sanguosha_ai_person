#!/usr/bin/env python3
"""Run the B7 five-player rules-AI acceptance batch with fixed seeds.

Usage: python -m scripts.verify_b7_games [--hero-draft free|standard] [--picker coverage|rules]

--hero-draft free      自由选将（默认）：真人与 AI 的武将由脚本固定，保持原有的武将覆盖统计。
--hero-draft standard  正式选将：武将由引擎的选将流程产生，脚本不再固定武将。
--picker coverage      仅正式选将有效（默认）：AI 座位从候选里挑"目前被覆盖次数最少"的武将，
                       让 30 局仍能覆盖全部 27 名武将，ai_heroes_covered 保持原有意义。
--picker rules         AI 座位用引擎自带的规则打分选将（看真实选将会选出什么武将分布）。
"""

import argparse
import asyncio
import json
import logging
import random

from game_engine import MainEngine


DECKS = {"standard": 108, "extra": 53, "combined": 161}
HEROES = ("liubei", "guanyu", "zhangfei", "zhugeliang", "zhaoyun",
          "machao", "huangyueying")
AI_HEROES = {
    "wei": ("caocao", "simayi", "xiahoudun", "zhangliao", "xuchu", "guojia", "zhenji"),
    "shu": HEROES,
    "wu": ("sunquan", "ganning", "lvmeng", "huanggai", "zhouyu", "daqiao", "luxun"),
    "qun": ("huatuo", "lvbu", "diaochan", "huaxiong", "yuanshao", "zhangjiao"),
}
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


def install_coverage_picker(engine, counts):
    """正式选将下替 AI 座位挑覆盖最少的候选（真人托管座位仍走规则打分）。"""
    original = engine.ai_decision.simple_choice_decision

    def picker(player, request):
        if request.get("kind") != "choose_hero" or not player.is_ai:
            return original(player, request)
        choices = request["choices"]
        best = min(range(len(choices)), key=lambda i: (counts.get(choices[i]["id"], 0), i))
        counts[choices[best]["id"]] = counts.get(choices[best]["id"], 0) + 1
        return [best]

    engine.ai_decision.simple_choice_decision = picker


async def one_game(deck_id, index, hero_draft="free", picker="coverage", counts=None):
    seed = 20261017 + index * 103 + list(DECKS).index(deck_id) * 1009
    random.seed(seed)
    identity = IDENTITIES[index % len(IDENTITIES)]
    game_index = list(DECKS).index(deck_id) * 10 + index
    selected_hero = HEROES[index % len(HEROES)]
    ai_heroes = []
    for faction, pool in AI_HEROES.items():
        position = (game_index + (1 if faction == "shu" else 0)) % len(pool)
        if pool[position] == selected_hero:
            position = (position + 1) % len(pool)
        ai_heroes.append(pool[position])
    raw_config = {
        "mode": "5人身份局",
        "selected_hero": {"id": selected_hero},
        "ais": [{"name": f"AI{seat}", "api_key": "", "hero": {"id": hero_id}}
                for seat, hero_id in enumerate(ai_heroes, start=1)],
        "identity_card": {"use": True, "identity": identity},
        "deck_id": deck_id,
        "max_turns": 120,
        "phase_delay": 0,
        "turn_delay": 0,
    }
    if hero_draft == "standard":
        # 正式选将：武将交给引擎的选将流程，不再固定（固定的武将配置会被引擎丢弃）。
        raw_config["hero_draft"] = "standard"
    config = MainEngine.normalize_config(raw_config)
    engine = MainEngine(config)
    if hero_draft == "standard":
        if picker == "coverage":
            install_coverage_picker(engine, counts if counts is not None else {})
    else:
        actual_ai_heroes = [p.hero.get("id") for p in engine.game_state.players[1:]]
        if actual_ai_heroes != ai_heroes:
            raise AssertionError(f"{deck_id}/{index}: AI hero configuration changed: {actual_ai_heroes!r}")
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
    if hero_draft == "standard":
        if any(not p.hero for p in engine.game_state.players):
            raise AssertionError(f"{deck_id}/{index}: hero draft left a seat without a hero")
        selected_hero = engine.game_state.players[0].hero["id"]
        actual_ai_heroes = [p.hero["id"] for p in engine.game_state.players[1:]]
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
            "hero": selected_hero, "ai_heroes": actual_ai_heroes, "winner": winner,
            "turns": engine.completed_turns, "card_count": len(ids),
            "declined_skills": len(declined_skills)}


async def main(hero_draft="free", picker="coverage"):
    logging.disable(logging.CRITICAL)
    results = []
    counts = {}
    for deck_id in DECKS:
        for index in range(10):
            results.append(await one_game(deck_id, index, hero_draft, picker, counts))
    covered_heroes = {hero for result in results for hero in result["ai_heroes"]}
    expected_heroes = {hero for pool in AI_HEROES.values() for hero in pool}
    # 自由选将与"覆盖优先"的正式选将保证 AI 座位覆盖全部 27 将；规则打分选将只报告分布，不要求全覆盖。
    if (hero_draft == "free" or picker == "coverage") and covered_heroes != expected_heroes:
        raise AssertionError(f"AI hero coverage incomplete: {sorted(expected_heroes - covered_heroes)}")
    print(json.dumps({"hero_draft": hero_draft, "picker": picker if hero_draft == "standard" else None,
                      "games": len(results), "normal": sum(r["winner"] != "draw" for r in results),
                      "draw": sum(r["winner"] == "draw" for r in results),
                      "declined_skills": sum(r["declined_skills"] for r in results),
                      "ai_heroes_covered": len(covered_heroes),
                      "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hero-draft", choices=("free", "standard"), default="free")
    parser.add_argument("--picker", choices=("coverage", "rules"), default="coverage")
    args = parser.parse_args()
    asyncio.run(main(args.hero_draft, args.picker))
