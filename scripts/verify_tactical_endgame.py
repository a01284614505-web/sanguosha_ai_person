"""重放华佗、吕布和郭嘉的取舍；可选的模型配对实验使用同一份华佗残局。"""
import argparse
import asyncio
import json
import os
import random
import time
from unittest.mock import patch

from game_engine import MainEngine
from game_engine import tactical_evidence as tactics
from game_engine.state_manager import Phase


def table(heroes):
    cfg = MainEngine.normalize_config({
        "mode": "5人身份局", "selected_hero": {"id": heroes[0]}, "deck_id": "standard",
        "ais": [{"name": hero, "hero": {"id": hero}, "api_key": "test_key"} for hero in heroes[1:]],
    })
    engine = MainEngine(cfg)
    state = engine.game_state
    for i, p in enumerate(state.players):
        p.is_ai = True
        p.ai_config["api_key"] = "test_key"
        p.identity = ("lord", "loyalist", "rebel", "rebel", "spy")[i]
        p.identity_revealed = i == 0
        state.deck.extend(p.hand)
        p.hand.clear()
    state.deck.sort(key=lambda c: c.id)
    state._public_seats = {p.id: i+1 for i, p in enumerate(state.players)}
    state.current_phase = Phase.PLAY
    return engine


def take(state, name, suit=None):
    card = next(c for c in state.deck if c.name == name and (suit is None or c.suit == suit))
    state.deck.remove(card)
    return card


async def endgame(hidden_suit="heart", *, lord_pick="杀"):
    engine = table(["sunquan", "huatuo", "zhenji", "simayi", "lvbu"])
    s = engine.game_state
    lord, hua, zhen, sima, dead = s.players
    dead.alive = False
    lord.hp, zhen.hp, sima.hp = 3, 2, 2
    s.current_player, s.current_player_index = sima, 3
    zhen.hand.append(take(s, "杀", hidden_suit))
    hua.hand.append(take(s, "闪"))
    sima.hand.extend([take(s, "杀", "club"), take(s, "杀", "spade")])
    grains, arrows = take(s, "五谷丰登"), take(s, "万箭齐发")
    sima.hand.extend([grains, arrows])
    # 从司马懿起依次公开取牌。主公取桃的对照只改这一个可见条件，甄姬另一个手牌位仍是暗的。
    picks = [take(s, "过河拆桥", "spade"), take(s, lord_pick, "club" if lord_pick == "杀" else "heart"),
             take(s, "杀", "diamond"), take(s, "过河拆桥", "heart")]
    s.deck[:0] = picks

    async def respond(p, request):
        # 两种暗牌世界的公开行为一致：甄姬即使能倾国也选择承受这次万箭。
        if p is hua and request.get("requested_name") == "闪":
            return engine._resolve_option(p, request, 0)
        return {"bool": False}

    async def choose(p, prompt, candidates, **kwargs):
        return candidates[:1]

    with patch.object(engine, "ask_choose_cards", choose), patch.object(engine.card_system, "responder", respond):
        for card in (grains, arrows):
            action = next(a for a in engine.get_available_actions(sima)
                          if a.get("type") == "play_card" and a["card"]["name"] == card.name)
            assert await engine.execute_action(sima, action)
    s.current_player, s.current_player_index = hua, 1
    assert (lord.hp, hua.hp, zhen.hp, sima.hp) == (2, hua.max_hp, 1, 2)
    assert [p.get_hand_count() for p in (hua, zhen, sima)] == [1, 2, 3]
    return engine


async def replay(action, targets, *, lord_pick="杀"):
    outcomes = []
    for label, suit in (("红杀，不能倾国", "heart"), ("黑杀，可倾国", "spade")):
        engine = await endgame(suit, lord_pick=lord_pick)
        state = engine.game_state
        lord, hua, zhen, sima, _ = state.players
        assert action in engine.get_available_actions(hua)
        accepted = await engine.execute_action(hua, action, targets)
        immediate = {"accepted": accepted, "甄姬存活": zhen.alive, "主公体力": lord.hp,
                     "华佗手牌数": len(hua.hand)}
        # 固定一次后续两点伤害，只比较资源能否保命。真实对局中这次伤害是否会来仍待判断。
        state.current_player, state.current_player_index = sima, 3
        await engine.card_system.damage(sima, lord, 2)
        outcomes.append({"甄姬暗牌": label, "即时结算": immediate, "假设随后主公受到两点伤害": {
            "主公存活": lord.alive, "主公体力": lord.hp}})
    return outcomes


async def replay_wushuang(second_card):
    """目标公开拿过一张闪，另有一张暗牌。两个世界给吕布相同的信息。"""
    engine = table(["sunquan", "zhangfei", "lvbu", "zhouyu", "simayi"])
    state = engine.game_state
    target, attacker = state.players[1:3]
    state.current_player, state.current_player_index = attacker, 2
    attacker.hand.append(take(state, "杀"))
    seen = next(c for c in state.deck if c.name == "闪")
    await engine.move_card(seen, "deck", "shown", to_owner=target, reason="五谷丰登亮牌")
    await engine.move_card(seen, "shown", "hand", from_owner=target, to_owner=target, reason="五谷丰登")
    target.hand.append(take(state, second_card))
    target.hp = 2
    actions = engine.get_available_actions(attacker)
    evidence = tactics.answer_query(engine, attacker, actions, {"target_seat": 2})
    attack = next(a for a in actions if a.get("card", {}).get("name") == "杀")
    # 固定响应策略：有闪就出，目标放弃后续可选的利驭，只考察无双本次是否打穿。
    async def decline(*args, **kwargs):
        return False
    with patch.object(engine, "ask_confirm", decline):
        assert await engine.execute_action(attacker, attack, [target.id])
    return {"出杀前验算": evidence, "目标结算后体力": target.hp, "目标剩余手牌数": len(target.hand)}


async def replay_yiji(hp, dodge):
    """同样持一张闪，比较保血和承伤给主公分牌。固定遗计的摸牌，只检验这个分支。"""
    engine = table(["sunquan", "guojia", "zhouyu", "lvbu", "simayi"])
    state = engine.game_state
    lord, guo, attacker = state.players[:3]
    state.current_player, state.current_player_index = attacker, 2
    guo.hp = hp
    guo.hand.append(take(state, "闪"))
    attacker.hand.append(take(state, "杀"))
    state.deck[:0] = [take(state, "杀", "club"), take(state, "过河拆桥", "spade")]

    respond = engine.card_system.responder
    async def choose_response(player, request):
        if player is guo and request.get("requested_name") == "闪" and not dodge:
            return {"bool": False}
        return await respond(player, request)

    async def invoke(player, prompt, **kwargs):
        return kwargs.get("skill_name") == "遗计"

    async def give_to_lord(*args, **kwargs):
        return [lord]

    attack = next(a for a in engine.get_available_actions(attacker) if a.get("card", {}).get("name") == "杀")
    with (patch.object(engine.card_system, "responder", choose_response),
          patch.object(engine, "ask_confirm", invoke), patch.object(engine, "ask_choose_players", give_to_lord)):
        assert await engine.execute_action(attacker, attack, [guo.id])
    return {"郭嘉存活": guo.alive, "郭嘉体力": guo.hp, "主公手牌数": len(lord.hand)}


async def report(model=None, provider="deepseek", samples=1):
    e = await endgame()
    _, hua, zhen, _, _ = e.game_state.players
    actions = e.get_available_actions(hua)
    query = {"target_seat": 3, "helper_seat": 4, "keep_target_pick": True, "keep_pick": True, "decline_pct": 25}
    results = {"公开经过": tactics.history_block(e.game_state),
               "出牌依据": tactics.decision_block(e, hua, actions),
               "假设验算": tactics.answer_query(e, hua, actions, query), "分支": {}}
    lord = e.game_state.players[0]
    for action in actions:
        if action.get("type") == "end_phase":
            label, targets = "留红", []
        elif action.get("skill_name") == "青囊":
            label, targets = "青囊救主", [lord.id]
        elif action.get("card", {}).get("name") == "杀":
            label, targets = "杀甄姬", [zhen.id]
        else:
            continue
        results["分支"][label] = await replay(action, targets)
        if label == "杀甄姬":
            results["主公五谷取桃后，华佗仍出杀"] = await replay(action, targets, lord_pick="桃")
    results["吕布无双"] = {card: await replay_wushuang(card) for card in ("杀", "闪")}
    results["郭嘉遗计"] = {f"{hp}血，{choice}": await replay_yiji(hp, choice == "出闪")
                         for hp in (2, 1) for choice in ("出闪", "承伤")}
    if model:
        api_key = os.environ.get("SANGUOSHA_TACTICS_API_KEY")
        if not api_key:
            raise ValueError("模型对照需要设置 SANGUOSHA_TACTICS_API_KEY")
        decisions = []
        for seed in range(samples):
            for enabled in ((False, True) if seed % 2 == 0 else (True, False)):
                engine = await endgame()
                actor = engine.game_state.players[1]
                actor.ai_config.update(model=model, provider=provider, api_key=api_key, temperature=0,
                                       api_url=os.environ.get("SANGUOSHA_TACTICS_API_URL", ""))
                engine.ai_decision.rng = random.Random(seed)
                engine.game_config["ai_ablation"] = {"tactical_history": True, "tactical_evidence": enabled}
                start = time.perf_counter()
                choices = engine.get_available_actions(actor)
                decision = await engine.ai_decision.make_decision(actor, choices)
                failure = engine.ai_decision.last_failure.get(actor.id)
                decisions.append({"组": seed, "战术依据": enabled, "回退原因": failure,
                                  "决策耗时毫秒": round(1000*(time.perf_counter()-start)),
                                  "用量": engine.usage_stats.get(actor.id, {}).get("decision"),
                                  "调用验算": bool(engine.ai_decision.last_meta.get(actor.id, {}).get("tactical_result")),
                                  "行动": decision["action"], "目标ID": decision["target_ids"],
                                  "分支结算": await replay(decision["action"], decision["target_ids"]) if not failure else []})
        results["模型对照"] = decisions
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="显式指定后才请求模型；默认仅做离线重放")
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--samples", type=int, default=1, help="模型对照的配对次数")
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples 须为正数")
    print(json.dumps(asyncio.run(report(args.model, args.provider, args.samples)), ensure_ascii=False, indent=2))
