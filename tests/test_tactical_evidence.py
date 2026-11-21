"""Reproducible four-survivor endgame and privacy/probability checks. No provider required."""
import asyncio
import json
from itertools import combinations
from unittest.mock import AsyncMock, patch

import pytest

from game_engine import MainEngine
from game_engine import tactical_evidence as tactics
from game_engine.recovery import dump_engine, restore_engine
from game_engine.tactical_context import RISK_GUIDANCE
from scripts.verify_tactical_endgame import endgame, replay_wushuang, replay_yiji, table, take


def test_exact_marginals_and_behavior_conditioning_match_enumeration():
    cards = list(tactics.catalogue("standard").values())
    o = tactics.hand_odds(cards, 2, qingguo=True)
    hands = list(combinations(cards, 2))
    no_dodge = [h for h in hands if all(s not in tactics.BLACK and n != "闪" for n, s, _ in h)]
    neither = [h for h in no_dodge if all(n not in {"桃", "酒"} for n, *_ in h)]
    assert (o.total, o.no_dodge, o.neither) == (len(hands), len(no_dodge), len(neither)) == (5778, 741, 465)
    assert o.with_dodge_after_pass(0) == 0
    assert o.with_dodge_after_pass(100) == pytest.approx(o.has_dodge)
    assert o.with_dodge_after_pass(25) == pytest.approx(5037/(5037+4*741))
    certain = tactics.hand_odds([("闪", "diamond", 2)], 1)
    assert certain.with_dodge_after_pass(0) is None
    assert tactics.hand_odds(cards, 109) is None


@pytest.mark.parametrize("fixed", [[], [("杀", "club", 7)], [("闪", "heart", 2), ("酒", "spade", 3)]])
def test_two_dodges_count_known_and_converted_cards_only_once(fixed):
    pool = [("闪", "diamond", 2), ("闪", "club", 3), ("酒", "club", 4), ("桃", "heart", 5), ("杀", "heart", 6)]
    for count in range(len(fixed), len(pool) + len(fixed) + 1):
        odds = tactics.hand_odds(pool, count, fixed=fixed, qingguo=True, longdan=True)
        hands = (fixed + list(draw) for draw in combinations(pool, count - len(fixed)))
        assert odds.at_least_two_dodges == sum(
            sum(n in ("杀", "闪") or s in tactics.BLACK for n, s, _ in hand) >= 2 for hand in hands)


@pytest.mark.parametrize("hidden_suit,dodges", [("heart", False), ("spade", True)])
def test_same_history_can_end_in_death_or_qingguo(hidden_suit, dodges):
    async def play():
        engine = await endgame(hidden_suit)
        s = engine.game_state
        _, hua, zhen, _, _ = s.players
        action = next(a for a in engine.get_available_actions(hua) if a.get("card", {}).get("name") == "杀")
        assert await engine.execute_action(hua, action, [zhen.id])
        assert zhen.alive is dodges
        assert len(hua.hand) == (0 if dodges else 3)  # Rebel kill reward in this mode.
    asyncio.run(play())


def test_qingnang_and_reserve_alternatives_settle_through_engine():
    async def play():
        engine = await endgame()
        s = engine.game_state
        lord, hua, _, sima, _ = s.players
        actions = engine.get_available_actions(hua)
        heal = next(a for a in actions if a.get("skill_name") == "青囊")
        assert await engine.execute_action(hua, heal, [lord.id])
        assert lord.hp == 3 and len(hua.hand) == 0
        engine = await endgame()
        s = engine.game_state
        lord, hua, _, sima, _ = s.players
        assert await engine.execute_action(hua, {"type": "end_phase"})
        s.current_player, s.current_player_index = sima, 3
        await engine.card_system.damage(sima, lord, 2)
        assert lord.alive and lord.hp == 1 and not hua.hand
    asyncio.run(play())


def test_public_peach_changes_who_can_save_the_lord_when_hua_gambles():
    async def play():
        e = await endgame("spade", lord_pick="桃")
        s = e.game_state
        lord, hua, zhen, sima, _ = s.players
        assert "1号五谷取♥" in tactics.history_block(s) and lord.hand[0].name == "桃"
        attack = next(a for a in e.get_available_actions(hua) if a.get("card", {}).get("name") == "杀")
        assert await e.execute_action(hua, attack, [zhen.id])
        assert zhen.alive and not hua.hand
        s.current_player, s.current_player_index = sima, 3
        await e.card_system.damage(sima, lord, 2)
        rescue = next(r for r in s.tactical_observations if r["kind"] == "rescue" and r["player"] == lord.id)
        assert rescue["source"] == lord.id and lord.hp == 1
    asyncio.run(play())


def test_visible_jink_against_wushuang_requires_a_second_card():
    one, two = (asyncio.run(replay_wushuang(card)) for card in ("杀", "闪"))
    assert one["出杀前验算"] == two["出杀前验算"]
    assert "持可作闪牌100.0%" in one["出杀前验算"] and "手牌够两张13.2%" in one["出杀前验算"]
    assert (one["目标结算后体力"], two["目标结算后体力"]) == (1, 2)


@pytest.mark.parametrize("hp", [1, 2])
def test_guojia_can_spend_health_to_help_lord_but_can_die_doing_so(hp):
    guarded = asyncio.run(replay_yiji(hp, True))
    accepted = asyncio.run(replay_yiji(hp, False))
    assert guarded == {"郭嘉存活": True, "郭嘉体力": hp, "主公手牌数": 0}
    assert accepted == {"郭嘉存活": hp > 1, "郭嘉体力": hp - 1, "主公手牌数": 2}


@pytest.mark.parametrize("index,reason", [(0, "保住自己的最后一血"), (1, "押遗计能给主公补牌")])
def test_guojia_can_choose_either_response_with_the_same_risk_prompt(index, reason):
    engine = table(["sunquan", "guojia", "zhouyu", "lvbu", "simayi"])
    guo = engine.game_state.players[1]
    guo.ai_config["api_key"] = "offline-stub"
    guo.hp = 1
    guo.hand.append(take(engine.game_state, "闪"))
    reply = AsyncMock(return_value=json.dumps({"reasoning": reason, "option_index": index}))
    with patch.object(engine.ai_decision, "_call_with_session", reply):
        response = asyncio.run(engine.card_system.choose_to_respond(
            guo, "是否打出闪？", lambda card: card.name == "闪", requested_name="闪"))
    assert response["bool"] is (index == 0)
    assert engine.ai_decision.last_reasoning[guo.id] == reason
    assert RISK_GUIDANCE in reply.await_args.args[-1]


def test_observations_queries_recovery_and_two_indistinguishable_worlds():
    async def run():
        e = await endgame("heart")
        s = e.game_state
        _, hua, zhen, sima, _ = s.players
        actions = e.get_available_actions(hua)
        args = {"target_seat": 3, "helper_seat": 4, "keep_pick": True, "decline_pct": 25}
        def evidence():
            return (tactics.decision_block(e, hua, actions), tactics.history_block(s),
                    tactics.answer_query(e, hua, actions, args))
        original = evidence()
        assert "余0张" in original[0] and "1张红牌" in original[0]
        assert "3号未挡住万箭齐发" in original[1] and "4号五谷取♠" in original[1]
        assert "占一个手牌位" in original[2] and "洛神" in original[2] and "25%" in original[2]
        # Change hidden roles, an unrevealed hand and the *entire* deck order without changing the view.
        zhen.identity, sima.identity = "spy", "loyalist"
        idx = next(i for i,c in enumerate(s.deck) if c.name == "杀" and c.suit == "spade")
        s.deck[idx], zhen.hand[0] = zhen.hand[0], s.deck[idx]
        s.deck.reverse()
        assert evidence() == original
        payload = dump_engine(e)
        restored = restore_engine(payload, MainEngine)
        assert tactics.history_block(restored.game_state) == original[1]
        assert tactics.answer_query(restored, restored.game_state.players[1], actions, args) == original[2]
        del payload["state"]["tactical_observations"]
        assert not restore_engine(payload, MainEngine).game_state.tactical_observations
        # A formerly public pick that is now visibly discarded cannot be pinned in a hidden hand.
        picked = next(c for c in sima.hand if c.name == "过河拆桥")
        await e.move_card(picked, "hand", "discard", from_owner=sima, reason="discard")
        assert "另行定位" in evidence()[2]
    asyncio.run(run())


@pytest.mark.parametrize("query,expected_calls", [(False, 1), (True, 2)])
@pytest.mark.parametrize("attack", [True, False])
def test_model_can_take_or_decline_the_risk_even_after_tool_result(query, expected_calls, attack):
    async def run():
        e = await endgame()
        hua = e.game_state.players[1]
        hua.ai_config["api_key"] = "offline-stub"
        actions = e.get_available_actions(hua)
        if attack:
            index = next(i for i, a in enumerate(actions) if a.get("card", {}).get("name") == "杀")
        else:
            index = next(i for i, a in enumerate(actions) if a["type"] == "end_phase")
        reply = json.dumps({"action_index": index, "reasoning": "争取击杀" if attack else "留红救主",
                            "target_ids": [3] if attack else []})
        calls = AsyncMock(side_effect=([json.dumps({"tactical_query": {"target_seat": 3}})] if query else []) + [reply])
        with patch("game_engine.ai_decision.select_examples", return_value=[]), patch.object(e.ai_decision, "_call_with_session", calls):
            decision = await e.ai_decision.make_decision(hua, actions)
        assert decision["action"] == actions[index]
        assert decision["target_ids"] == ([e.game_state.players[2].id] if attack else [])
        assert e.ai_decision.last_failure[hua.id] is None
        assert calls.await_count == expected_calls
        assert all(RISK_GUIDANCE in call.args[-1] for call in calls.await_args_list)
        if query:
            assert "【假设验算】" in calls.await_args.args[-1]
        e.game_config["ai_ablation"] = {"tactical_evidence": False}
        prompt = e.ai_decision.build_decision_turn_message(hua, actions)
        assert "【战术依据】" not in prompt and "【可复查的公开经过】" not in prompt
        assert RISK_GUIDANCE in prompt
    asyncio.run(run())


@pytest.mark.parametrize("skill,hero,donor_hero,name", [
    ("激将", "liubei", "guanyu", "杀"), ("护驾", "caocao", "zhenji", "闪"),
])
def test_lord_invitations_do_not_disclose_donor_cards(skill, hero, donor_hero, name):
    async def run():
        e = table([hero, donor_hero, "huatuo", "lvbu", "sunquan"])
        s = e.game_state
        lord, donor, target = s.players[:3]
        s.current_player, s.current_player_index = lord, 0
        def menu():
            options = e.card_system.build_response_options(lord, lambda c: c.name == name, name)
            request = {"options": options, "requested_name": name}
            return (e.get_available_actions(lord), e._response_decision_view(request),
                    [e._serialize_option(opt, i) for i,opt in enumerate(options)])
        donor.hand.append(take(s, "过河拆桥", "spade" if skill == "激将" else "heart"))
        menu_without = menu()
        invite, cancel = menu_without[2]
        assert not invite["is_pass"] and invite["owner_id"] is None and invite["card"] is None
        assert cancel["is_pass"]
        e.ask_confirm = AsyncMock(return_value=True)
        if skill == "激将":
            active = next(a for a in menu_without[0] if a.get("skill_name") == skill)
            assert await e.execute_action(lord, active, [target.id if target.id in active["valid_targets"] else active["valid_targets"][0]])
            assert lord.sha_count == 0 and lord.flags["jijiang_unanswered"]
            assert active not in e._after_unanswered_invitation(lord, e.get_available_actions(lord))
        result = await e.card_system.choose_to_respond(lord, "响应", lambda c: c.name == name, requested_name=name)
        assert result == {"bool": False}
        # Same hand size, now a usable conversion (Wusheng or Qingguo).
        face = take(s, "过河拆桥", "heart" if skill == "激将" else "spade")
        s.deck.append(donor.hand.pop())
        donor.hand.append(face)
        assert menu() == menu_without
        e.ask_choose_cards = AsyncMock(return_value=[face])
        result = await e.card_system.choose_to_respond(lord, "响应", lambda c: c.name == name, requested_name=name)
        assert result["owner"] is donor and result["card"] is face
        assert await e.card_system._consume_response(lord, result, "test", {})
        assert face not in donor.hand and face in s.discard_pile
    asyncio.run(run())


def test_declined_invitation_preserves_own_response_and_public_outflow_rules_out_same_hand_update():
    async def run():
        e = table(["liubei", "guanyu", "huatuo", "lvbu", "sunquan"])
        s = e.game_state
        lord = s.players[0]
        own = take(s, "杀")
        lord.hand.append(own)
        e.ask_confirm = AsyncMock(return_value=False)
        e._ai_choose_option = AsyncMock(side_effect=[1, 0])
        result = await e.card_system.choose_to_respond(lord, "响应", lambda c: c.name == "杀", requested_name="杀")
        assert result["card"] is own and result["owner"] is lord
        e = await endgame()
        s = e.game_state
        _, hua, zhen, _, _ = s.players
        actions = e.get_available_actions(hua)
        assert await e.move_card(zhen.hand[0], "hand", "discard", from_owner=zhen, reason="discard")
        await e.draw_cards(zhen, 1)
        assert zhen.get_hand_count() == 2
        assert "本次不更新" in tactics.answer_query(e, hua, actions, {"target_seat": 3, "decline_pct": 0})
    asyncio.run(run())


def test_parent_decision_trace_survives_nested_choice_and_only_own_reason_is_recalled():
    async def run():
        e = await endgame()
        s = e.game_state
        _, hua, zhen, _, _ = s.players
        actions = e.get_available_actions(hua)
        action = next(a for a in actions if a.get("skill_name") == "青囊")
        e.ai_decision.last_meta[hua.id] = {"model": "parent", "prompt_tokens": 123}
        e.ai_decision.last_reasoning[hua.id] = "先提高主公血线"
        before = e._play_trace_input(hua, [s.players[0].id])
        assert await e.execute_action(hua, action, before["targets"])
        e.ai_decision.last_meta[hua.id] = {"model": "child", "prompt_tokens": 9}
        e.ai_decision.last_reasoning[hua.id] = "子选择"
        await e._emit_decision_trace(hua, "play", len(actions), action, "accepted", before=before)
        row = e.decision_log[-1]
        assert row["model"] == "parent" and row["prompt_tokens"] == 123 and row["reason"] == "先提高主公血线"
        assert row["situation_version"] != row["result_version"]
        assert {c["seat"] for c in row["public_changes"]} == {1,2}
        assert "先提高主公血线" in tactics.previous_decision(e, hua)
        assert "先提高主公血线" not in tactics.previous_decision(e, zhen)
    asyncio.run(run())


def test_pinned_hand_and_rescuer_odds_against_enumerated_endgame():
    e = asyncio.run(endgame())
    s = e.game_state
    _, hua, zhen, sima, _ = s.players
    actions = e.get_available_actions(hua)
    args = {"target_seat": 3, "helper_seat": 4, "keep_target_pick": True, "keep_pick": True, "decline_pct": 25}
    result = tactics.answer_query(e, hua, actions, args)
    pool = tactics.unknown_cards(s, hua)
    for row in s.tactical_observations:
        if row["kind"] == "public_pick" and row.get("holding") == "known" and row["player"] != hua.id:
            face = (row["card_name"], row["suit"], row["rank"])
            del pool[next(key for key, value in pool.items() if value == face)]
    faces = list(pool.values())
    # 目标有一个未知位，救援者有两个。独立枚举可能的分配，不读取两人的真实底牌。
    hands_with_response = both_absent = helper_peach = helper_deals = 0
    for i, (name, suit, _rank) in enumerate(faces):
        if name == "闪" or suit in tactics.BLACK:
            hands_with_response += 1
        elif name not in ("桃", "酒"):
            both_absent += 1
            for c1, c2 in combinations(faces[:i] + faces[i+1:], 2):
                helper_deals += 1
                helper_peach += (c1[0] == "桃" or c2[0] == "桃")
    assert f"持可作闪牌{hands_with_response/len(faces):.1%}" in result
    assert f"和印刷桃酒{both_absent/len(faces):.1%}" in result
    assert f"手里至少一张印刷桃{helper_peach/helper_deals:.1%}" in result
    remaining = hands_with_response + 4 * (len(faces) - hands_with_response)
    assert (f"观察未出后持可作闪牌{hands_with_response/remaining:.1%}，"
            f"同时无可作闪牌和印刷桃酒{4*both_absent/remaining:.1%}") in result
    assert f"若当时总会承伤，仍为{hands_with_response/len(faces):.1%}" in result
    assert "缺少" not in result and "洛神" in result
    assert "仍能公开定位的五谷牌" in tactics.decision_block(e, hua, actions)
    assert "0至100" in tactics.answer_query(e, hua, actions, {**args, "decline_pct": True})
    assert "合法目标" in tactics.answer_query(e, hua, actions, {**args, "target_seat": 99})


def test_reflection_keeps_first_estimate_independent_and_caps_model_calls():
    async def run():
        e = await endgame()
        hua = e.game_state.players[1]
        hua.ai_config["api_key"] = "offline-stub"
        actions = e.get_available_actions(hua)
        double_query = json.dumps({"tactical_query": {"target_seat": 3}})
        calls = AsyncMock(side_effect=[double_query, double_query])
        with patch("game_engine.ai_decision.select_examples", return_value=["example"]), \
                patch("game_engine.ai_decision.examples_prompt", return_value="示例"), \
                patch.object(e.ai_decision, "_call_with_session", calls):
            result = await e.ai_decision.make_decision(hua, actions)
        first, last = [c.args[-1] for c in calls.await_args_list]
        assert "【可复查的公开经过】" in first and "【战术依据】" not in first
        assert "【假设验算】" in last and "【战术依据】" in last
        assert RISK_GUIDANCE in first and RISK_GUIDANCE in last
        assert result["action"] in actions and e.ai_decision.last_failure[hua.id]
    asyncio.run(run())


def test_hidden_transfer_downgrades_a_public_pick_identically_whichever_card_moved():
    async def transfer(public_pick_left):
        e = await endgame()
        s = e.game_state
        lord, hua, zhen, sima, _ = s.players
        pick = next(r for r in s.tactical_observations if r["kind"] == "public_pick" and r["player"] == sima.id)
        assert pick["holding"] == "known"
        outgoing = next(c for c in sima.hand if (c.name == pick["card_name"]) == public_pick_left)
        assert await e.move_card(outgoing, "hand", "hand", from_owner=sima, to_owner=lord,
                                 reason="give", visibility="owner")
        assert pick["holding"] == "uncertain"
        query = {"target_seat": 3, "helper_seat": 4, "keep_pick": True}
        answer = tactics.answer_query(e, hua, e.get_available_actions(hua), query)
        assert "假设4号仍持" in answer
        return tactics.history_block(s), answer, tactics.decision_block(e, hua, e.get_available_actions(hua))
    assert asyncio.run(transfer(True)) == asyncio.run(transfer(False))


def test_damage_benefit_is_recorded_only_after_the_skill_really_pays_out():
    async def scenario(accept):
        e = table(["sunquan", "guojia", "huatuo", "lvbu", "simayi"])
        lord, guo, *_ = e.game_state.players
        e.ask_confirm = AsyncMock(return_value=accept)
        e.ask_choose_players = AsyncMock(return_value=[guo])
        await e.card_system.damage(lord, guo, 1)
        return tactics.history_block(e.game_state), guo.get_hand_count()
    declined, n0 = asyncio.run(scenario(False))
    accepted, n1 = asyncio.run(scenario(True))
    assert "遗计" not in declined and n0 == 0
    assert "受1号伤害后发动遗计获2张，分出0张" in accepted and n1 == 2


def test_discarding_either_of_two_identical_faces_yields_same_public_evidence():
    async def scenario(play_seen_copy):
        e = table(["sunquan", "huatuo", "zhenji", "simayi", "lvbu"])
        s = e.game_state
        _, hua, zhen, *_ = s.players
        s.current_player, s.current_player_index = hua, 1
        copies = [c for c in s.deck if (c.name, c.suit, c.rank) == ("杀", "club", 8)]
        assert len(copies) == 2
        hua.hand.append(take(s, "杀", "diamond"))
        await e.move_card(copies[0], "deck", "shown", to_owner=zhen, reason="五谷丰登亮牌")
        await e.move_card(copies[0], "shown", "hand", from_owner=zhen, to_owner=zhen, reason="五谷丰登")
        await e.move_card(copies[1], "deck", "hand", to_owner=zhen, reason="draw", visibility="owner")
        await e.move_card(copies[0 if play_seen_copy else 1], "hand", "discard", from_owner=zhen, reason="use_card")
        assert s.tactical_observations[-1]["holding"] == "uncertain"
        actions = e.get_available_actions(hua)
        return (tactics.decision_block(e, hua, actions),
                tactics.answer_query(e, hua, actions, {"target_seat": 3, "keep_target_pick": True}))
    left, right = asyncio.run(scenario(True)), asyncio.run(scenario(False))
    assert left == right and "持可作闪牌100.0%" in left[1]


def test_live_pair_driver_uses_same_evidence_and_replays_each_answer(monkeypatch):
    from scripts.verify_tactical_endgame import report

    monkeypatch.setenv("SANGUOSHA_TACTICS_API_KEY", "offline-stub")
    requests = []

    async def gateway(_gateway, **params):
        requests.append(params["messages"][-1]["content"])
        return '{"action_index":2,"target_ids":[],"reasoning":"留红"}', {"prompt_tokens": 10, "completion_tokens": 4}

    with patch("game_engine.ai_decision.AIGateway.call_ai", gateway):
        rows = asyncio.run(report("offline-model"))["模型对照"]
    assert [row["战术依据"] for row in rows] == [False, True]
    assert all(row["回退原因"] is None and len(row["分支结算"]) == 2 for row in rows)
    assert all(row["用量"]["calls"] == 2 for row in rows)
    assert all("仍可定位在手" in prompt for prompt in requests)
    assert "【战术依据】" not in requests[1] and "【战术依据】" in requests[3]
