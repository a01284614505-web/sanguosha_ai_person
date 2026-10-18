"""军争牌修复：火杀/雷杀可见、铁索连环重铸、借刀取武器中性（2026-10-18）。"""

import asyncio
import json
import re
from pathlib import Path

from game_engine import MainEngine
from game_engine.ai_decision import AIDecision
from game_engine.card_system import option_label
from game_engine.card_table import CARD_TABLE, card_label, damage_text
from game_engine.card_text import NATURE_CARD_TEXT
from game_engine.state_manager import Card, Phase, card_to_dict

ROOT = Path(__file__).resolve().parents[1]


def run(coro):
    return asyncio.run(coro)


def game(deck_id="extra"):
    engine = MainEngine({
        "mode": "5人身份局", "player_name": "P0",
        "ais": [{"name": f"P{i}"} for i in range(1, 5)],
        "deck_id": deck_id,
    })
    for player in engine.game_state.players:
        player.hand.clear()
        player.equipment.clear()
        player.judge_area.clear()
        player.is_ai = True
        player.hp = player.max_hp = 4
    return engine


def card(tag, name, suit="spade", rank=7, nature=None):
    spec = CARD_TABLE.get(name)
    return Card(tag, name, suit, rank, spec.card_type if spec else "basic", nature=nature)


def into_play_phase(engine, player):
    engine.game_state.current_player = player
    engine.game_state.current_phase = Phase.PLAY
    player.sha_count = 0


def no_response(engine):
    async def responder(player, request):
        return {"bool": False}
    engine.card_system.responder = responder


def messages(engine):
    return [e.get("message", "") for e in engine.game_log if e.get("message")]


# ───────────────────────── 1. 属性可见 ─────────────────────────

def test_card_to_dict_carries_nature_only_when_present():
    assert card_to_dict(card("f", "杀", nature="fire"))["nature"] == "fire"
    assert card_to_dict(card("t", "杀", nature="thunder"), include_id=False)["nature"] == "thunder"
    assert "nature" not in card_to_dict(card("n", "杀"))
    # 技能虚拟牌（改了牌名）不继承原牌属性
    assert "nature" not in card_to_dict(card("f2", "杀", nature="fire"), name="闪")


def test_real_extra_deck_natures_reach_hand_actions_and_state():
    engine = game("extra")
    fire = next(c for c in engine.game_state.deck if c.nature == "fire")
    thunder = next(c for c in engine.game_state.deck if c.nature == "thunder")
    human = engine.game_state.players[0]
    human.is_ai = False
    assert engine.human_player() is human
    human.hand.extend([fire, thunder])
    into_play_phase(engine, human)
    hand = engine.get_player_hand(human)
    assert [c.get("nature") for c in hand] == ["fire", "thunder"]
    assert [c.get("nature") for c in engine.serialize()["self_hand"]] == ["fire", "thunder"]
    plays = [a for a in engine.get_available_actions(human) if a["type"] == "play_card"]
    assert {a["card"].get("nature") for a in plays} == {"fire", "thunder"}
    # 军争牌堆里 14 张属性杀（5 火 9 雷）都带着 nature 进入引擎
    raw = json.loads((ROOT / "data" / "deck_extra_53.json").read_text(encoding="utf-8"))
    raw = raw if isinstance(raw, list) else raw["cards"]
    assert sorted(c["nature"] for c in raw if c.get("nature")) == ["fire"] * 5 + ["thunder"] * 9


def test_labels_come_from_card_table():
    assert card_label(card("f", "杀", nature="fire")) == "火【杀】"
    assert card_label({"name": "杀", "nature": "thunder"}) == "雷【杀】"
    assert card_label(card("n", "杀")) == "【杀】"
    assert card_label(card("s", "闪", nature="fire")) == "【闪】"      # 只有杀带属性前缀
    assert card_label(None, name="杀", nature="fire") == "火【杀】"
    assert damage_text(1, "fire") == "1点火焰伤害"
    assert damage_text(3, "thunder") == "3点雷电伤害"
    assert damage_text(2) == "2点伤害"


def test_battle_report_uses_fire_sha_and_fire_damage_wording():
    engine = game()
    p0, p1 = engine.game_state.players[:2]
    into_play_phase(engine, p0)
    p0.hand.append(card("fire1", "杀", "heart", 4, nature="fire"))
    no_response(engine)
    assert run(engine.execute_action(p0, {"type": "play_card", "card_index": 0}, [p1.id])) is True
    log = messages(engine)
    assert any("使用火【杀】" in m for m in log), log
    assert any("受到1点火焰伤害" in m for m in log), log
    assert p1.hp == 3


def test_thunder_sha_report_and_tengjia_rules_still_hold():
    engine = game()
    p0, p1 = engine.game_state.players[:2]
    into_play_phase(engine, p0)
    p1.equipment["armor"] = card("tj", "藤甲")
    p0.hand.append(card("th1", "杀", "spade", 4, nature="thunder"))
    no_response(engine)
    run(engine.execute_action(p0, {"type": "play_card", "card_index": 0}, [p1.id]))
    log = messages(engine)
    assert any("使用雷【杀】" in m for m in log), log
    assert any("受到1点雷电伤害" in m for m in log), log   # 雷杀不被藤甲挡住，也不 +1
    assert p1.hp == 3


def test_fire_sha_on_tengjia_is_plus_one_and_labelled():
    engine = game()
    p0, p1 = engine.game_state.players[:2]
    p1.equipment["armor"] = card("tj", "藤甲")
    run(engine.card_system.damage(p0, p1, 1, card=card("f", "杀", nature="fire")))
    assert p1.hp == 2
    assert any("受到2点火焰伤害" in m for m in messages(engine))


def test_chain_transfer_damage_is_labelled_with_nature():
    engine = game()
    p0, p1, p2 = engine.game_state.players[:3]
    engine.game_state.current_player = p0
    p1.chained = p2.chained = True
    run(engine.card_system.damage(p0, p1, 1, card=card("th", "杀", nature="thunder")))
    log = messages(engine)
    assert any(m.startswith(f"{p1.name}受到1点雷电伤害") and "传导" not in m for m in log), log
    assert any(m.startswith(f"{p2.name}受到1点雷电伤害") and "铁索连环传导" in m for m in log), log


def test_huogong_damage_is_fire_damage():
    engine = game()
    p0, p1 = engine.game_state.players[:2]
    into_play_phase(engine, p0)
    shown = card("shown", "杀", "heart", 9)
    p1.hand.append(shown)
    p0.hand.extend([card("hg", "火攻", "heart", 2), card("same", "闪", "heart", 3)])
    p1.equipment["armor"] = card("tj", "藤甲")
    no_response(engine)
    assert run(engine.execute_action(p0, {"type": "play_card", "card_index": 0}, [p1.id]))
    assert any("火焰伤害" in m for m in messages(engine))


def test_zhuque_converts_plain_sha_and_report_says_so():
    engine = game()
    p0, p1 = engine.game_state.players[:2]
    into_play_phase(engine, p0)
    p0.equipment["weapon"] = card("zq", "朱雀羽扇")
    p0.hand.append(card("n1", "杀", "club", 9))
    no_response(engine)
    run(engine.execute_action(p0, {"type": "play_card", "card_index": 0}, [p1.id]))
    log = messages(engine)
    assert any("朱雀羽扇" in m and "火【杀】" in m for m in log), log
    assert any("受到1点火焰伤害" in m for m in log), log


def test_ai_prompts_name_the_nature():
    engine = game()
    p0 = engine.game_state.players[1]
    into_play_phase(engine, p0)
    p0.hand.extend([card("t1", "杀", "spade", 5, nature="thunder"), card("n1", "杀", "club", 9)])
    actions = engine.get_available_actions(p0)
    ai = engine.ai_decision
    action_lines = [AIDecision.format_action(a) for a in actions if a["type"] == "play_card"]
    assert any("雷【杀】" in line for line in action_lines), action_lines
    assert any("【杀】" in line and "雷" not in line for line in action_lines)
    message = ai.build_decision_turn_message(p0, actions)
    assert "雷【杀】" in message
    assert "0:雷【杀】(spade5)" in message            # 手牌描述
    # 响应 prompt 的候选标签
    request = {"prompt": "请打出一张【杀】", "requested_name": "杀",
               "options": [{"card": p0.hand[0], "owner": p0, "as_name": "杀"}]}
    assert "雷【杀】" in option_label(request["options"][0])
    assert "雷【杀】" in ai.build_response_prompt(p0, request)
    rules = ai.worldbook_manager.build_global_rules()
    assert "火【杀】" in rules and "重铸" in rules and NATURE_CARD_TEXT["fire"][2] in rules


def test_nature_card_text_matches_frontend_exactly():
    js = (ROOT / "frontend" / "js" / "card_info.js").read_text(encoding="utf-8")
    found = dict(
        (key, (name, kind, text)) for key, name, kind, text in re.findall(
            r"(fire|thunder): \{ name: '([^']+)', type: '([^']+)', text: '([^']*)' \}", js))
    assert found == {key: value for key, value in NATURE_CARD_TEXT.items()}
    assert "'火杀'" in js and "'雷杀'" in js          # 图鉴分组里列出


# ───────────────────────── 2. 铁索连环重铸 ─────────────────────────

def _recasts(engine, player):
    return [a for a in engine.get_available_actions(player) if a["type"] == "recast"]


def test_recast_moves_card_to_discard_and_draws_one_without_wuxie():
    engine = game("standard")
    p0 = engine.game_state.players[0]
    into_play_phase(engine, p0)
    chain = card("ts", "铁索连环", "club", 12)
    p0.hand.append(chain)
    asked = []

    async def responder(player, request):
        asked.append(request)
        return {"bool": False}
    engine.card_system.responder = responder
    moves = []

    async def on_move(**data):
        moves.append(data["move"])
    engine.on("card_move", on_move)
    deck_before, discard_before = len(engine.game_state.deck), len(engine.game_state.discard_pile)

    actions = _recasts(engine, p0)
    assert len(actions) == 1 and actions[0]["card_index"] == 0
    assert run(engine.execute_action(p0, {"type": "recast", "card_index": 0}, [])) is True
    assert chain in engine.game_state.discard_pile and chain not in p0.hand
    assert len(p0.hand) == 1 and p0.hand[0] is not chain                # 摸了 1 张
    assert len(engine.game_state.deck) == deck_before - 1
    assert len(engine.game_state.discard_pile) == discard_before + 1
    assert asked == []                                                  # 不指定目标、不询问无懈可击
    recast_move = next(m for m in moves if m["reason"] == "重铸")
    assert (recast_move["from_zone"], recast_move["to_zone"], recast_move["card_id"]) == ("hand", "discard", "ts")
    assert any("重铸" in m for m in messages(engine))


def test_recast_does_not_touch_behavior_ledger_or_use_counters():
    engine = game("standard")
    p0 = engine.game_state.players[0]
    into_play_phase(engine, p0)
    p0.hand.append(card("ts", "铁索连环", "club", 12))
    run(engine.execute_action(p0, {"type": "recast", "card_index": 0}, []))
    assert engine.ledger.entries == []
    assert not any(p.chained for p in engine.game_state.players)


def test_recast_only_available_in_play_phase_and_validated_by_engine():
    engine = game("standard")
    p0, p1 = engine.game_state.players[:2]
    p0.hand.append(card("ts", "铁索连环", "club", 12))
    engine.game_state.current_player = p0
    engine.game_state.current_phase = Phase.DISCARD
    assert _recasts(engine, p0) == []
    assert run(engine.execute_action(p0, {"type": "recast", "card_index": 0}, [])) is False
    assert len(p0.hand) == 1                                            # 什么也没发生
    into_play_phase(engine, p0)
    p0.hand.append(card("sha", "杀"))
    assert run(engine.execute_action(p0, {"type": "recast", "card_index": 1}, [])) is False   # 不是铁索
    assert run(engine.execute_action(p0, {"type": "recast", "card_index": 9}, [])) is False
    into_play_phase(engine, p1)
    assert run(engine.execute_action(p0, {"type": "recast", "card_index": 0}, [])) is False   # 不是自己的回合
    assert any(c.name == "铁索连环" for c in p0.hand)


def test_recast_is_offered_alongside_play_and_ai_can_choose_it():
    engine = game("standard")
    p0 = engine.game_state.players[1]
    into_play_phase(engine, p0)
    p0.hand.append(card("ts", "铁索连环", "club", 12))
    actions = engine.get_available_actions(p0)
    assert [a["type"] for a in actions].count("recast") == 1
    line = AIDecision.format_action(next(a for a in actions if a["type"] == "recast"))
    assert "重铸" in line and "弃置这张铁索连环，摸一张牌" in line
    prompt = engine.ai_decision.build_decision_turn_message(p0, actions)
    assert "弃置这张铁索连环，摸一张牌" in prompt
    # LLM 路径：返回 recast 的索引能被解析为该操作
    index = next(i for i, a in enumerate(actions) if a["type"] == "recast")
    parsed = engine.ai_decision.parse_ai_response(
        f'{{"action_index": {index}, "target_ids": [], "reasoning": "换牌"}}', p0, actions)
    assert parsed["action"]["type"] == "recast"
    # 规则 AI：手里只有铁索（没有更优出牌）时重铸
    chosen = engine.ai_decision.simple_ai_decision(p0, actions)
    assert chosen["action"]["type"] == "recast"
    assert run(engine.execute_action(p0, chosen["action"], chosen["target_ids"])) is True
    assert len(p0.hand) == 1 and p0.hand[0].name != "铁索连环"      # 标准牌堆里没有铁索，摸到的是新牌


def test_recast_flag_lives_only_in_card_table():
    assert [n for n, s in CARD_TABLE.items() if s.recast] == ["铁索连环"]


# ───────────────────────── 3. 借刀取武器中性 ─────────────────────────

def test_jiedao_records_only_instigator_to_final_target():
    engine = game("standard")
    p0, p1, p2 = engine.game_state.players[:3]
    p1.equipment["weapon"] = card("w", "诸葛连弩", "club")
    engine.card_system.responder = None
    run(engine.card_system.use_card(p0, card("jd", "借刀杀人"), [p1, p2]))
    rows = [(e.source_id, e.target_id, e.kind, e.label) for e in engine.ledger.entries]
    assert rows == [(0, 2, "hostile", "借刀")]
    assert not any(e.label == "借刀夺武器" or e.target_id == 1 for e in engine.ledger.entries)
