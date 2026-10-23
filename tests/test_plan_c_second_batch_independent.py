"""Independent C second-batch audit through real engine/rule-AI entrypoints."""

import asyncio

from game_engine import MainEngine
from game_engine.state_manager import Card, Phase


def make_engine(player_hero="caocao", ai_heroes=None):
    ai_heroes = ai_heroes or ["sunquan", "huatuo", "zhouyu", "zhangfei"]
    config = MainEngine.normalize_config({
        "mode": "5人身份局",
        "player": {"name": "审查玩家", "hero": {"id": player_hero}, "is_ai": True},
        "ais": [{"name": f"审查AI{i}", "hero": {"id": hero}}
                 for i, hero in enumerate(ai_heroes, start=1)],
    })
    return MainEngine(config)


def replace_hand_with(engine, player, *cards):
    engine.game_state.deck.extend(player.hand)
    player.hand[:] = list(cards)


def all_physical_ids(engine):
    state = engine.game_state
    cards = list(state.deck) + list(state.discard_pile)
    for player in state.players:
        cards.extend(player.hand + player.judge_area + player.shown + player.temporary + player.treasure_cards)
        cards.extend(player.equipment.values())
    return [card.id for card in cards]


def test_real_engine_balances_zhiheng_and_kurou_costs_and_dying_safety():
    async def scenario():
        engine = make_engine("sunquan", ["caocao", "huatuo", "zhouyu", "zhangfei"])
        player = engine.game_state.players[0]
        player.identity = "lord"
        player.hp = 4
        engine.game_state.current_player = player
        engine.game_state.current_phase = Phase.PLAY
        cheap = Card("c_audit_zhiheng_cheap", "铁索连环", "club", 4, "trick")
        keep = Card("c_audit_zhiheng_keep", "闪", "heart", 10, "basic")
        replace_hand_with(engine, player, cheap, keep)

        actions = engine.get_available_actions(player)
        decision = await engine.ai_decision.make_decision(player, actions)
        assert decision["action"]["skill_name"] == "制衡"
        before_deck = len(engine.game_state.deck)
        accepted = await engine.execute_action(player, decision["action"], decision["target_ids"])
        assert accepted is True
        assert [card.id for card in engine.game_state.discard_pile][-1] == cheap.id
        assert keep in player.hand
        assert len(player.hand) == 2
        assert len(engine.game_state.deck) == before_deck - 1
        ids = all_physical_ids(engine)
        assert len(ids) == len(set(ids))

        # Huang Gai's active skills include a resource-for-benefit combo. At 1 HP
        # the real rule AI declines 苦肉; at 3 HP its 诈降 companion makes it useful.
        safe = make_engine("huanggai", ["caocao", "sunquan", "zhouyu", "zhangfei"])
        vulnerable = safe.game_state.players[0]
        vulnerable.hp = 1
        vulnerable.is_ai = True
        safe.game_state.current_player = vulnerable
        safe.game_state.current_phase = Phase.PLAY
        safe_card = Card("c_audit_kurou_safe", "铁索连环", "club", 4, "trick")
        replace_hand_with(safe, vulnerable, safe_card)
        safe_decision = await safe.ai_decision.make_decision(vulnerable, safe.get_available_actions(vulnerable))
        assert safe_decision["action"].get("skill_name") != "苦肉"
        assert vulnerable.hp == 1 and not safe.game_aborted

        beneficial = make_engine("huanggai", ["caocao", "sunquan", "zhouyu", "zhangfei"])
        huanggai = beneficial.game_state.players[0]
        huanggai.is_ai = True
        huanggai.hp = 3
        beneficial.game_state.current_player = huanggai
        beneficial.game_state.current_phase = Phase.PLAY
        weak = Card("c_audit_kurou_benefit", "铁索连环", "club", 4, "trick")
        replace_hand_with(beneficial, huanggai, weak)
        choice = await beneficial.ai_decision.make_decision(huanggai, beneficial.get_available_actions(huanggai))
        assert choice["action"].get("skill_name") == "苦肉"
        deck_before = len(beneficial.game_state.deck)
        assert await beneficial.execute_action(huanggai, choice["action"], choice["target_ids"])
        assert huanggai.hp == 2
        assert weak in beneficial.game_state.discard_pile
        assert len(huanggai.hand) == 3  # 诈降: the real companion effect supplies its benefit.
        assert len(beneficial.game_state.deck) == deck_before - 3
        ids = all_physical_ids(beneficial)
        assert len(ids) == len(set(ids))

    asyncio.run(scenario())


def test_qingjian_uses_public_friend_and_ignores_hidden_identity_and_hand_swaps():
    async def scenario():
        engine = make_engine("xiahoudun", ["caocao", "sunquan", "zhouyu", "zhangfei"])
        chooser, known_friend, unknown = engine.game_state.players[:3]
        chooser.identity = "loyalist"
        known_friend.identity = "lord"; known_friend.identity_revealed = True
        unknown.identity = "rebel"; unknown.identity_revealed = False
        request = {
            "kind": "choose_players", "skill_name": "清俭",
            "candidate_ids": [unknown.id, known_friend.id], "min_n": 1, "max_n": 1,
            "context": {"all_players": [unknown, known_friend]},
        }
        first_masked = engine._mask_hidden_candidates(request)
        first = await engine._ai_choose_choice(chooser, request)
        assert first == [1]
        unknown.identity = "loyalist"
        unknown.hand[:] = [Card("secret_hand_swap", "桃", "heart", 3, "basic")]
        second_masked = engine._mask_hidden_candidates(request)
        second = await engine._ai_choose_choice(chooser, request)
        assert first_masked["context"] == second_masked["context"]
        masked_unknown = next(row for row in second_masked["context"]["all_players"]
                              if row["id"] == unknown.id)
        assert "identity" not in masked_unknown
        assert first == second == [1]

        # Exercise the actual 清俭 gain trigger, card selection and receiver choice.
        engine.game_state.current_phase = Phase.PLAY
        engine.game_state.current_player = engine.game_state.players[3]
        cheap = Card("c_audit_qingjian_cheap", "铁索连环", "club", 4, "trick")
        keep = Card("c_audit_qingjian_keep", "闪", "heart", 10, "basic")
        replace_hand_with(engine, chooser, cheap, keep)
        await engine.skill_manager.on_card_gained(chooser, [cheap], "审查获得")
        assert cheap in known_friend.hand
        assert keep in chooser.hand
        assert chooser.flags.get("skill_used", {}).get("清俭") is True
        ids = all_physical_ids(engine)
        assert len(ids) == len(set(ids))

    asyncio.run(scenario())


def _judge_engine(skill_hero):
    engine = make_engine("caocao", [skill_hero, "sunquan", "huatuo", "zhouyu"])
    target, owner = engine.game_state.players[:2]
    target.identity = "lord"; target.identity_revealed = True
    owner.identity = "loyalist"; owner.identity_revealed = True
    return engine, target, owner


def test_ghost_judgment_skills_accept_reject_and_choose_through_real_engine():
    async def one_case(skill_hero, expected_accept, hidden_target=False,
                       hidden_identity="rebel", secret_hand_name="桃"):
        engine, target, owner = _judge_engine(skill_hero)
        skill_name = "鬼才" if skill_hero == "simayi" else "鬼道"
        target.identity_revealed = not hidden_target
        target.identity = hidden_identity if hidden_target else "lord"
        secret_owner = engine.game_state.players[2]
        secret_owner.hand[:] = [Card(f"secret_{hidden_identity}_{secret_hand_name}",
                                     secret_hand_name, "heart", 3, "basic")]
        old = Card(f"c_audit_judge_old_{skill_name}_{hidden_target}", "杀", "heart", 6, "basic")
        delayed = Card(f"c_audit_delay_{skill_name}_{hidden_target}", "兵粮寸断", "diamond", 7, "trick")
        replacement = Card(f"c_audit_judge_repl_{skill_name}_{hidden_target}", "铁索连环", "club", 4, "trick")
        target.shown.append(old)
        replace_hand_with(engine, owner, replacement)

        result = await engine.skill_manager.before_judge(target, old, {"delayed_card": delayed})
        if expected_accept:
            assert result is replacement
            assert replacement in target.shown
            assert replacement not in owner.hand
            if skill_name == "鬼道":
                assert old in owner.hand
            else:
                assert old in engine.game_state.discard_pile
        else:
            assert result is old
            assert replacement in owner.hand
            assert old in target.shown
        ids = all_physical_ids(engine)
        assert len(ids) == len(set(ids))
        return result.id, tuple(sorted(card.id for card in owner.hand))

    async def scenario():
        for hero in ("simayi", "zhangjiao"):
            accepted = await one_case(hero, True)
            hidden_identity_a = await one_case(hero, False, hidden_target=True,
                                               hidden_identity="rebel", secret_hand_name="桃")
            hidden_identity_b = await one_case(hero, False, hidden_target=True,
                                               hidden_identity="spy", secret_hand_name="杀")
            assert accepted[0] != hidden_identity_a[0]
            assert hidden_identity_a == hidden_identity_b

    asyncio.run(scenario())


def test_all_four_ablation_modes_remain_callable_via_engine_choice_dispatch():
    async def scenario():
        cases = [
            ({"skill_strategy": False, "target_strategy": False}, [1], [0]),
            ({"skill_strategy": True, "target_strategy": False}, [0], [0]),
            ({"skill_strategy": False, "target_strategy": True}, [1], [1]),
            ({"skill_strategy": True, "target_strategy": True}, [0], [1]),
        ]
        for knobs, expected_confirm, expected_target in cases:
            engine = make_engine()
            player = engine.game_state.players[0]
            player.identity = "lord"
            engine.game_config["ai_ablation"] = dict(knobs)
            confirm = {"kind": "confirm", "skill_name": "天妒", "default": False}
            target = {
                "kind": "choose_players", "candidate_ids": [1, 2],
                "min_n": 1, "max_n": 1, "context": {"intent": "harm", "all_players": [
                    {"id": 1, "name": "忠臣", "identity": "loyalist", "identity_revealed": True, "alive": True, "hp": 3},
                    {"id": 2, "name": "反贼", "identity": "rebel", "identity_revealed": True, "alive": True, "hp": 3},
                ]},
            }
            assert await engine._ai_choose_choice(player, confirm) == expected_confirm
            assert await engine._ai_choose_choice(player, target) == expected_target

    asyncio.run(scenario())
