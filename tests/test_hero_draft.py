"""正式选将：候选、顺序、隐私、初始化、超时 / 托管 / 重连、自由选将不受影响。

对应方案 logs/handover/20261018_1015_正式选将施工方案.md 第 4 节逐条。
"""

import asyncio
import json
import logging
import random

import pytest

from game_engine import MainEngine
from game_engine import hero_draft
from game_engine.game_logs import GameLogStore, build_game_log
from game_engine.hero_registry import HeroRegistry
from game_engine.recovery import dump_engine, restore_engine
from game_server import GameServer

POOL = HeroRegistry().all_heroes()
LORD_IDS = {"caocao", "liubei", "sunquan", "yuanshao", "zhangjiao"}


def config(**extra):
    cfg = {
        "mode": "5人身份局", "hero_draft": "standard", "player_name": "我",
        "ais": [{"name": f"AI{i}", "api_key": ""} for i in range(1, 5)],
        "max_turns": 0, "phase_delay": 0, "turn_delay": 0, "profile_id": "draft_p1",
    }
    cfg.update(extra)
    return MainEngine.normalize_config(cfg)


def make_engine(seed=1, **extra):
    random.seed(seed)
    return MainEngine(config(**extra))


class Table:
    """旁路收集引擎事件，并按脚本替真人回答选将请求。"""

    def __init__(self, engine, choose=None):
        self.engine = engine
        self.choose = choose          # callable(payload) -> 候选下标；None 表示不回答
        self.requests = []
        self.states = []
        self.logs = []
        engine.on("require_response", self.on_request)
        engine.on("state_changed", self.on_state)
        engine.on("event_notification", self.on_log)

    async def on_request(self, **data):
        self.requests.append(data)
        if self.choose is not None and data.get("kind") == "choose_hero":
            self.engine.submit_response(data["request_id"], self.choose(data))

    async def on_state(self, **data):
        self.states.append(data["state"])

    async def on_log(self, **data):
        self.logs.append(data)


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- 候选生成

def test_lord_candidates_are_all_lord_heroes_plus_two_non_lord():
    for seed in range(20):
        cards = hero_draft.lord_candidates(POOL, random.Random(seed))
        ids = {c["id"] for c in cards}
        assert LORD_IDS <= ids, "主公候选必须含全部主公技武将"
        extra = [c for c in cards if c["id"] not in LORD_IDS]
        assert len(cards) == 7 and len(extra) == 2
        assert not any(hero_draft.is_lord_hero(c) for c in extra)


def test_other_candidates_are_five_each_disjoint_and_exclude_lord_pick():
    cards = hero_draft.lord_candidates(POOL, random.Random(3))
    chosen = cards[0]["id"]
    hands = hero_draft.deal_candidates(POOL, 4, 5, exclude_ids=[chosen], rng=random.Random(4))
    assert [len(h) for h in hands] == [5, 5, 5, 5]
    flat = [c["id"] for h in hands for c in h]
    assert len(flat) == len(set(flat)) == 20
    assert chosen not in flat


def test_lord_unchosen_cards_return_to_pool():
    """主公没选的牌放回将池：它们有机会出现在其他人的候选里。"""
    seen = set()
    for seed in range(30):
        cards = hero_draft.lord_candidates(POOL, random.Random(seed))
        hands = hero_draft.deal_candidates(POOL, 4, 5, exclude_ids=[cards[0]["id"]], rng=random.Random(seed))
        seen |= {c["id"] for h in hands for c in h} & {c["id"] for c in cards[1:]}
    assert seen, "30 局里主公落选的武将一次都没回到其他人的候选里"


def test_fixed_rng_is_deterministic():
    one = hero_draft.deal_candidates(POOL, 4, 5, rng=random.Random(9))
    two = hero_draft.deal_candidates(POOL, 4, 5, rng=random.Random(9))
    assert [[c["id"] for c in h] for h in one] == [[c["id"] for c in h] for h in two]
    assert ([c["id"] for c in hero_draft.lord_candidates(POOL, random.Random(9))]
            == [c["id"] for c in hero_draft.lord_candidates(POOL, random.Random(9))])


def test_per_player_shrinks_when_pool_is_small():
    assert hero_draft.candidates_per_player(26, 4) == 5      # 5 人局
    assert hero_draft.candidates_per_player(26, 7) == 3      # 8 人局放不下 5 张互不重复
    with pytest.raises(ValueError):
        hero_draft.deal_candidates(POOL, 7, 5)


def test_lord_skill_comes_from_metadata_not_description():
    hero = {"id": "x", "skills": [{"name": "冒牌", "type": "trigger", "description": "主公技。其实不是。"}]}
    assert not hero_draft.is_lord_hero(hero)
    hero["skills"].append({"name": "真", "type": "lord", "description": "随便写"})
    assert hero_draft.is_lord_hero(hero)


def test_every_lord_skill_text_is_tagged_in_metadata():
    """数据守卫：描述以"主公技"开头的技能必须带 type=lord，反之亦然，避免两处说法漂移。"""
    for hero in POOL:
        for skill in hero["skills"]:
            says_lord = skill.get("description", "").startswith("主公技")
            assert says_lord == hero_draft.is_lord_skill(skill), (hero["id"], skill["name"])
    assert {h["id"] for h in POOL if hero_draft.is_lord_hero(h)} == LORD_IDS


def test_runtime_skill_exposes_lord_flag():
    engine = make_engine()
    caocao = next(h for h in POOL if h["id"] == "caocao")
    player = engine.game_state.players[1]
    engine.game_state.players[1].identity = "lord"
    engine.set_hero(player, caocao)
    flags = {s["name"]: s["lord_skill"] for s in engine.skill_manager.public_player_skills(player)}
    assert flags == {"奸雄": False, "护驾": True}


# ---------------------------------------------------------------- 规则 AI 打分

def test_rule_scoring_follows_identity():
    by_id = {h["id"]: h for h in POOL}
    pair = [by_id["xuchu"], by_id["huatuo"]]           # 纯进攻 vs 纯辅助
    assert hero_draft.pick_by_rules(pair, "rebel", None, random.Random(0)) == 0
    assert hero_draft.pick_by_rules(pair, "loyalist", None, random.Random(0)) == 1
    assert hero_draft.pick_by_rules(pair, "lord", None, random.Random(0)) == 1
    # 非主公不要白占主公技武将
    non_lord = [by_id["liubei"], by_id["guanyu"]]
    assert hero_draft.pick_by_rules(non_lord, "rebel", None, random.Random(0)) == 1
    # 主公自己选主公技武将
    assert hero_draft.pick_by_rules([by_id["guanyu"], by_id["liubei"]], "lord", None, random.Random(0)) == 1


def test_rule_tie_break_uses_injected_rng():
    twin = {"id": "unknown_a", "max_hp": 4, "faction": "群", "skills": []}
    twin2 = dict(twin, id="unknown_b")
    picks = {hero_draft.pick_by_rules([twin, twin2], "spy", None, random.Random(seed)) for seed in range(20)}
    assert picks == {0, 1}


# ---------------------------------------------------------------- 流程与顺序

def test_draft_runs_identity_first_then_lord_then_others_and_deals_hands_last():
    engine = make_engine(seed=7)
    engine.set_trustee(True, source="rules")
    table = Table(engine)
    # 开局前：没有武将、没有手牌
    assert all(p.hero is None for p in engine.game_state.players)
    assert all(not p.hand for p in engine.game_state.players)
    run(engine.run())
    players = engine.game_state.players
    assert all(p.identity for p in players)
    assert all(p.hero for p in players)
    assert all(len(p.hand) == 4 for p in players)
    # 第一份状态里身份已分、武将未定
    first = table.states[0]
    assert first["hero_draft"]["active"] is True and first["hero_draft"]["stage"] == "lord"
    assert all(row["hero"]["id"] == "" and row["hero_name"] == "选将中" for row in first["players"])
    assert table.states[-1]["hero_draft"]["active"] is False


def test_lord_request_precedes_everyone_else_and_is_public_before_others_start():
    engine = make_engine(seed=11)
    engine.set_trustee(True, source="rules")
    calls = []
    original = engine.request_choice

    async def spy(player, request):
        if request.get("kind") == "choose_hero":
            lord = engine.game_state.current_player
            calls.append(("ask", player.id, lord.hero is not None))
        result = await original(player, request)
        if request.get("kind") == "choose_hero":
            calls.append(("done", player.id, None))
        return result

    engine.request_choice = spy
    run(engine.run())
    lord_id = next(p.id for p in engine.game_state.players if p.identity == "lord")
    assert calls[0] == ("ask", lord_id, False)
    assert calls[1] == ("done", lord_id, None)
    # 主公选完（武将已公开）之后才有别人的请求
    others = [c for c in calls[2:] if c[0] == "ask"]
    assert len(others) == 4 and all(c[1] != lord_id and c[2] is True for c in others)


def test_four_non_lord_requests_run_concurrently():
    engine = make_engine(seed=12)
    engine.set_trustee(True, source="rules")
    inflight = {"now": 0, "max": 0}
    original = engine.request_choice

    async def spy(player, request):
        if request.get("kind") != "choose_hero" or player.identity == "lord":
            return await original(player, request)
        inflight["now"] += 1
        inflight["max"] = max(inflight["max"], inflight["now"])
        await asyncio.sleep(0.05)       # 让并发窗口足够大
        try:
            return await original(player, request)
        finally:
            inflight["now"] -= 1

    engine.request_choice = spy
    run(engine.run())
    assert inflight["max"] == 4


def test_candidates_dealt_to_each_seat_are_disjoint_in_a_real_run():
    engine = make_engine(seed=21)
    engine.set_trustee(True, source="rules")
    run(engine.run())
    rows = engine.draft_record
    assert len(rows) == 5
    lord_row = next(r for r in rows if r["identity"] == "lord")
    assert LORD_IDS <= set(lord_row["candidates"]) and len(lord_row["candidates"]) == 7
    other_ids = [cid for r in rows if r is not lord_row for cid in r["candidates"]]
    assert len(other_ids) == len(set(other_ids)) == 20
    assert lord_row["chosen"] not in other_ids
    finals = [p.hero["id"] for p in engine.game_state.players]
    assert len(set(finals)) == 5
    for row in rows:
        assert row["chosen"] in row["candidates"]


# ---------------------------------------------------------------- 隐私

class Socket:
    def __init__(self):
        self.raw = []
        self.remote_address = ("test", 0)

    async def send(self, text):
        self.raw.append(text)

    @property
    def messages(self):
        return [json.loads(t) for t in self.raw]

    def types(self):
        return [m["type"] for m in self.messages]


def attach(server, engine, gid, ws):
    from game_engine.protocol import ENGINE_EVENT, ENGINE_EVENTS
    engine.game_id = gid
    server.engines[gid] = engine
    server.ws_map[ws] = gid
    server.viewers[gid] = ws
    server.viewer_modes[gid] = "player"
    for event in ENGINE_EVENTS:
        engine.on(event, server._forward(gid, event))
    engine.on(ENGINE_EVENT.CARD_ANIMATION, server._animation_handler(gid))


def test_outbound_messages_never_contain_other_seats_candidates(tmp_path):
    """抓服务器出站的全部消息：非本人看不到别人的候选（只有本人那条请求带候选）。"""
    async def scenario():
        server = GameServer(history_path=tmp_path / "h.json")
        server.game_logs = GameLogStore(tmp_path / "logs")
        engine = make_engine(seed=31, identity_card={"use": True, "identity": "loyalist"})
        ws = Socket()
        attach(server, engine, "g31", ws)

        def respond(message):
            if message.get("type") == "require_response" and message.get("kind") == "choose_hero":
                engine.submit_response(message["request_id"], 0)

        original = ws.send

        async def send(text):
            await original(text)
            respond(json.loads(text))

        ws.send = send
        await engine.run()
        return engine, ws

    engine, ws = run(scenario())
    rows = {r["player_id"]: r for r in engine.draft_record}
    mine = rows[0]
    finals = {p.hero["id"] for p in engine.game_state.players}
    names = {h["id"]: h["name"] for h in POOL}
    secret = set()
    for pid, row in rows.items():
        if pid != 0:
            secret |= set(row["candidates"])
    secret -= set(mine["candidates"]) | finals     # 本人看得到的、最终公开的不算秘密
    assert secret, "测试场景里应当存在别人没选中的候选"

    blob = "\n".join(ws.raw)
    for hero_id in secret:
        assert f'"{hero_id}"' not in blob, f"出站消息泄露了别人的候选 {hero_id}"
        assert names[hero_id] not in blob, f"出站消息泄露了别人的候选 {names[hero_id]}"
    # 本人收到的候选请求恰好是自己那 5 张，且不含身份以外的他人信息
    requests = [m for m in ws.messages if m["type"] == "require_response" and m.get("kind") == "choose_hero"]
    assert len(requests) == 1
    assert [h["id"] for h in requests[0]["heroes"]] == mine["candidates"]
    assert requests[0]["draft"]["identity"] == "loyalist"
    assert requests[0]["draft"]["lord_hero"]["id"] == rows[next(
        pid for pid, r in rows.items() if r["identity"] == "lord")]["chosen"]
    assert requests[0]["timeout"] == engine.human_action_timeout


def test_server_log_prints_each_ai_identity_and_hero_but_not_to_clients(tmp_path, caplog):
    async def scenario():
        server = GameServer(history_path=tmp_path / "h.json")
        server.game_logs = GameLogStore(tmp_path / "logs")
        engine = make_engine(seed=32)
        engine.set_trustee(True, source="rules")
        ws = Socket()
        attach(server, engine, "g32", ws)
        await engine.run()
        return engine, ws

    with caplog.at_level(logging.INFO, logger="game_engine.main_engine"):
        engine, ws = run(scenario())
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("[选将]")]
    assert len(lines) == 5
    for player in engine.game_state.players:
        if player.is_ai:
            assert any(f"身份={player.identity}" in line and player.hero["name"] in line and player.name in line
                       for line in lines), player.name
    assert not any("[选将]" in text for text in ws.raw)
    assert not any("身份=" in text for text in ws.raw)


# ---------------------------------------------------------------- 初始化

def test_set_hero_rebuilds_hp_skills_and_session_for_lord_and_others():
    engine = make_engine(seed=2)
    engine.set_trustee(True, source="rules")
    run(engine.run())
    for player in engine.game_state.players:
        base = int(player.hero["max_hp"])
        bonus = 1 if player.identity == "lord" else 0
        assert player.max_hp == base + bonus and player.hp == player.max_hp
        names = {s["name"] for s in player.hero["skills"]}
        registered = {s.name for s in engine.skill_manager.player_skills(player)}
        assert names <= registered
    lord = next(p for p in engine.game_state.players if p.identity == "lord")
    assert lord.max_hp == lord.hero["max_hp"] + 1


def test_set_hero_twice_replaces_old_skills():
    engine = make_engine()
    player = engine.game_state.players[1]
    player.identity = "rebel"
    by_id = {h["id"]: h for h in POOL}
    engine.set_hero(player, by_id["zhouyu"])
    assert engine.skill_manager.has_skill(player, "英姿")
    engine.set_hero(player, by_id["xuchu"])
    assert not engine.skill_manager.has_skill(player, "英姿")
    assert engine.skill_manager.has_skill(player, "裸衣")
    assert {i.skill_id for i in engine.skill_manager.skill_state.for_owner(player.id)} == {"xuchu_裸衣"}


def test_skills_work_after_draft_yingzi_draw_and_xueyi_hand_limit():
    """挑两个开局相关的技能验证：英姿（摸牌阶段多摸 1）、血裔（主公手牌上限 +2/名其他群雄）。"""
    engine = make_engine()
    state = engine.game_state
    by_id = {h["id"]: h for h in POOL}
    lord, rebel, other_qun = state.players[0], state.players[1], state.players[2]
    lord.identity, rebel.identity, other_qun.identity = "lord", "rebel", "loyalist"
    engine.set_hero(lord, by_id["yuanshao"])
    engine.set_hero(rebel, by_id["zhouyu"])
    engine.set_hero(other_qun, by_id["lvbu"])
    # 英姿：摸牌阶段摸 3 张（原本 2 张）；袁绍没有这个技能，照常摸 2 张
    from game_engine.state_manager import Phase
    for player, expected in ((rebel, 3), (lord, 2)):
        state.current_player = player
        before = len(player.hand)
        run(engine._execute_phase_with_ui(Phase.DRAW))
        assert len(player.hand) - before == expected, player.hero["name"]
    # 袁绍（主公）血裔：场上每有一名其他群雄存活，手牌上限 +2；吕布是群雄
    assert engine.skill_manager.hand_limit(lord, lord.hp) == lord.hp + 2
    assert engine.skill_manager.hand_limit(rebel, rebel.hp) == rebel.hp
    # 蜀汉的主公技没登记在非主公身上也没关系，但血裔给非主公袁绍不生效
    rebel2 = state.players[3]
    rebel2.identity = "rebel"
    engine.set_hero(rebel2, by_id["yuanshao"])
    assert engine.skill_manager.hand_limit(rebel2, rebel2.hp) == rebel2.hp


def test_ai_session_prefix_is_built_after_draft_with_final_heroes():
    """选将请求不碰会话；选将结束后 L1 才按最终武将构建（不含默认 / 空武将）。"""
    engine = make_engine(seed=41)
    seen = []

    class Gateway:
        async def call_ai(self, **kwargs):
            seen.append(kwargs["messages"])
            return '{"reasoning":"随便","option_indices":[0]}', {"prompt_tokens": 10, "completion_tokens": 5}

    engine.ai_decision.gateway = Gateway()
    for p in engine.game_state.players:
        if p.is_ai:
            p.ai_config["api_key"] = "sk-test"
    engine.set_trustee(True, source="rules")
    sessions_during = []
    original = engine.set_hero

    def watch(player, hero):
        sessions_during.append(dict(engine.ai_decision._sessions))
        return original(player, hero)

    engine.set_hero = watch
    run(engine.run())
    assert seen, "带 Key 的 AI 应当发过选将请求"
    assert all(not s for s in sessions_during), "选将过程中不应已建立任何 AI 会话"
    for player in engine.game_state.players:
        if not player.is_ai:
            continue
        engine.ai_decision.reset_session(player.id)
        l1 = engine.ai_decision.get_session(player)["messages"][1]["content"]
        for other in engine.game_state.players:
            assert other.hero["name"] in l1


def test_model_ai_prompt_has_identity_lord_hero_and_candidate_skill_text():
    engine = make_engine(seed=42)
    prompts = {}

    class Gateway:
        async def call_ai(self, **kwargs):
            user = kwargs["messages"][-1]["content"]
            prompts[len(prompts)] = user
            return '{"reasoning":"选第一个","option_indices":[0]}', {"prompt_tokens": 20, "completion_tokens": 8}

    engine.ai_decision.gateway = Gateway()
    for p in engine.game_state.players:
        if p.is_ai:
            p.ai_config["api_key"] = "sk-test"
    engine.set_trustee(True, source="rules")
    run(engine.run())
    rows = {r["player_id"]: r for r in engine.draft_record}
    ai_rows = [r for pid, r in rows.items() if engine.game_state.players[pid].is_ai]
    assert len(prompts) == len(ai_rows)          # 每名 AI 恰好一次选将请求
    lord_row = next(r for r in rows.values() if r["identity"] == "lord")
    lord_hero = next(h for h in POOL if h["id"] == lord_row["chosen"])
    text = "\n".join(prompts.values())
    assert "身份：反贼" in text or "身份：忠臣" in text or "身份：内奸" in text
    for skill in lord_hero["skills"]:
        assert skill["description"] in text            # 主公已公开武将的技能全文
    for row in ai_rows:
        if row["identity"] == "lord":
            continue
        for hero_id in row["candidates"]:
            hero = next(h for h in POOL if h["id"] == hero_id)
            assert hero["skills"][0]["description"] in text   # 候选技能全文
    # 提示里只能有自己的身份，不应出现别的座位的身份词组合
    for prompt in prompts.values():
        assert prompt.count("身份：") == 1
    usage = engine.usage_stats
    assert all(usage[p.id]["choice"]["calls"] == 1 for p in engine.game_state.players if p.is_ai)


def test_model_failure_falls_back_to_rules():
    engine = make_engine(seed=43)

    class Gateway:
        async def call_ai(self, **kwargs):
            raise RuntimeError("boom")

    engine.ai_decision.gateway = Gateway()
    for p in engine.game_state.players:
        if p.is_ai:
            p.ai_config["api_key"] = "sk-test"
    engine.set_trustee(True, source="rules")
    run(engine.run())
    assert all(p.hero for p in engine.game_state.players)
    assert {r["source"] for r in engine.draft_record if r["player_id"] != 0} == {"rules"}
    assert all(engine.usage_stats[p.id]["choice"]["failures"] == 1
               for p in engine.game_state.players if p.is_ai)


# ---------------------------------------------------------------- 真人：选择 / 超时 / 托管

def test_human_choice_is_honoured_and_listed_in_log():
    engine = make_engine(seed=51)
    table = Table(engine, choose=lambda payload: len(payload["heroes"]) - 1)
    run(engine.run())
    row = next(r for r in engine.draft_record if r["player_id"] == 0)
    assert row["chosen"] == row["candidates"][-1] and row["source"] == "human"
    assert engine.game_state.players[0].hero["id"] == row["chosen"]
    assert any("选择了武将" in (log.get("message") or "") for log in table.logs)
    human_requests = [r for r in table.requests if r.get("kind") == "choose_hero"]
    assert len(human_requests) == 1
    # 轮到本人时的提示带 2 分钟时限
    assert human_requests[0]["timeout"] == engine.human_action_timeout == 120


def test_human_timeout_picks_randomly_and_writes_log_without_enabling_trustee():
    engine = make_engine(seed=52)
    engine.human_action_timeout = 0.05
    table = Table(engine, choose=None)
    run(engine.run())
    row = next(r for r in engine.draft_record if r["player_id"] == 0)
    assert row["source"] == "timeout" and row["chosen"] in row["candidates"]
    assert any("选将超时" in (log.get("message") or "") for log in table.logs)
    assert engine._trustee_active is False, "选将超时只随机选一名，不借此开启整局托管"


def test_trustee_seat_is_picked_by_ai_without_prompting_human():
    engine = make_engine(seed=53)
    engine.set_trustee(True, source="rules")
    table = Table(engine, choose=None)
    run(engine.run())
    assert not [r for r in table.requests if r.get("kind") == "choose_hero"]
    row = next(r for r in engine.draft_record if r["player_id"] == 0)
    assert row["source"] == "trustee"


def test_toggling_trustee_during_draft_hands_over_to_ai():
    engine = make_engine(seed=54)
    table = Table(engine, choose=None)

    async def scenario():
        task = asyncio.create_task(engine.run())
        for _ in range(200):
            await asyncio.sleep(0.01)
            if any(r.get("kind") == "choose_hero" for r in table.requests):
                break
        engine.set_trustee(True, source="rules")
        await asyncio.wait_for(task, 10)

    run(scenario())
    row = next(r for r in engine.draft_record if r["player_id"] == 0)
    assert row["chosen"] in row["candidates"]


def test_invalid_index_is_rejected_and_can_retry():
    engine = make_engine(seed=55)
    results = []

    async def scenario():
        table = Table(engine, choose=None)
        task = asyncio.create_task(engine.run())
        for _ in range(300):
            await asyncio.sleep(0.01)
            hero_requests = [r for r in table.requests if r.get("kind") == "choose_hero"]
            if hero_requests:
                break
        rid = hero_requests[0]["request_id"]
        results.append(engine.submit_response_status(rid, 99)["status"])
        results.append(engine.submit_response_status(rid, 0)["status"])
        await asyncio.wait_for(task, 10)

    run(scenario())
    assert results == ["invalid", "accepted"]


# ---------------------------------------------------------------- 断线重连

def test_reconnect_restores_panel_and_candidates(tmp_path):
    async def scenario():
        server = GameServer(history_path=tmp_path / "h.json")
        server.game_logs = GameLogStore(tmp_path / "logs")
        engine = make_engine(seed=61)
        engine.human_action_timeout = 30
        first = Socket()
        attach(server, engine, "g61", first)
        server.tasks["g61"] = asyncio.create_task(engine.run())
        for _ in range(300):
            await asyncio.sleep(0.01)
            if any(m.get("kind") == "choose_hero" for m in first.messages if m["type"] == "require_response"):
                break
        original = next(m for m in first.messages if m["type"] == "require_response")
        await server._detach(first)
        assert not engine.game_aborted

        second = Socket()
        await server.do_resume(second, {"game_id": "g61", "profile_id": "draft_p1"})
        types = second.types()
        assert types[0] == "game_resumed" and "game_state" in types
        state = next(m for m in second.messages if m["type"] == "game_state")["state"]
        assert state["hero_draft"]["active"] is True
        resent = [m for m in second.messages if m["type"] == "require_response"]
        assert len(resent) == 1 and resent[0]["kind"] == "choose_hero"
        assert resent[0]["request_id"] == original["request_id"]
        assert [h["id"] for h in resent[0]["heroes"]] == [h["id"] for h in original["heroes"]]
        assert resent[0]["draft"] == original["draft"]
        assert 1 <= resent[0]["timeout"] <= 30
        # 重连后照常能选
        assert engine.submit_response_status(resent[0]["request_id"], 1)["status"] == "accepted"
        await asyncio.wait_for(server.tasks["g61"], 10)

    run(scenario())


def test_checkpoint_is_saved_only_after_draft_and_restores_with_skills(tmp_path):
    saved = []
    engine = make_engine(seed=62)
    engine.set_trustee(True, source="rules")

    async def checkpoint():
        saved.append({"has_heroes": all(p.hero for p in engine.game_state.players),
                      "draft_done": engine._draft is None,
                      "payload": dump_engine(engine)})

    engine.recovery_checkpoint = checkpoint
    run(engine.run())
    assert saved and all(row["has_heroes"] and row["draft_done"] for row in saved)
    restored = restore_engine(json.loads(json.dumps(saved[0]["payload"])), MainEngine)
    for player in restored.game_state.players:
        assert player.hero and restored.skill_manager.player_skills(player)
        assert all(restored.skill_manager.has_skill(player, s["name"])
                   for s in player.hero["skills"] if s.get("implementation_status") == "active")
    assert restored.game_state.hero_draft_pending is False


# ---------------------------------------------------------------- 其他模式与自由选将

def test_eight_player_draft_uses_three_disjoint_candidates():
    random.seed(70)
    cfg = MainEngine.normalize_config({
        "mode": "8人身份局", "hero_draft": "standard",
        "ais": [{"name": f"AI{i}", "api_key": ""} for i in range(1, 8)],
        "max_turns": 0, "phase_delay": 0, "turn_delay": 0})
    engine = MainEngine(cfg)
    engine.set_trustee(True, source="rules")
    run(engine.run())
    others = [r for r in engine.draft_record if r["identity"] != "lord"]
    assert len(others) == 7 and all(len(r["candidates"]) == 3 for r in others)
    flat = [c for r in others for c in r["candidates"]]
    assert len(flat) == len(set(flat))
    assert all(len(p.hand) == 4 and p.hero for p in engine.game_state.players)


@pytest.mark.parametrize("mode,count", [("2v2", 3), ("斗地主", 2)])
def test_standard_draft_is_rejected_for_unsupported_modes(mode, count):
    with pytest.raises(ValueError, match="正式选将"):
        MainEngine.normalize_config({"mode": mode, "hero_draft": "standard",
                                     "ais": [{"name": f"AI{i}"} for i in range(count)]})
    cfg = MainEngine.normalize_config({"mode": mode, "ais": [{"name": f"AI{i}"} for i in range(count)]})
    assert cfg["hero_draft"] == "free"


def test_unknown_draft_value_is_rejected():
    with pytest.raises(ValueError, match="选将方式"):
        MainEngine.normalize_config({"hero_draft": "banana", "ais": [{"name": "a"}] * 4})


def test_free_mode_is_unchanged_default_heroes_and_early_hands():
    random.seed(80)
    cfg = MainEngine.normalize_config({
        "mode": "5人身份局", "selected_hero": {"id": "zhaoyun"},
        "ais": [{"name": f"AI{i}", "api_key": ""} for i in range(1, 5)],
        "max_turns": 0, "phase_delay": 0, "turn_delay": 0})
    assert cfg["hero_draft"] == "free"
    engine = MainEngine(cfg)
    players = engine.game_state.players
    assert players[0].hero["id"] == "zhaoyun"
    assert all(p.hero for p in players) and all(len(p.hand) == 4 for p in players)   # 初始化时就发好牌
    table = Table(engine)
    run(engine.run())
    assert not [r for r in table.requests if r.get("kind") == "choose_hero"]
    assert engine.draft_record == [] and engine.hero_draft_mode == "free"
    assert all("hero_draft" not in s for s in table.states)
    lord = next(p for p in players if p.identity == "lord")
    assert lord.max_hp == lord.hero["max_hp"] + 1


def test_standard_config_drops_any_preset_heroes():
    cfg = MainEngine.normalize_config({
        "hero_draft": "standard", "selected_hero": {"id": "zhaoyun"},
        "player": {"hero": {"id": "caocao"}},
        "ais": [{"name": f"AI{i}", "hero": {"id": "lvbu"}} for i in range(1, 5)]})
    assert "hero" not in cfg["player"] and "selected_hero" not in cfg
    assert all("hero" not in ai for ai in cfg["ais"])
    engine = MainEngine(cfg)
    assert all(p.hero is None for p in engine.game_state.players)


# ---------------------------------------------------------------- 日志与历史

def test_game_log_and_history_record_the_draft_mode(tmp_path):
    engine = make_engine(seed=90)
    engine.set_trustee(True, source="rules")
    ends = []

    async def on_end(**data):
        ends.append(data)

    engine.on("game_end", on_end)
    run(engine.run())
    record = build_game_log(engine, ends[0] if ends else {"state": engine.serialize()}, include_thinking=True)
    assert record["hero_draft"] == "standard"
    assert len(record["hero_draft_picks"]) == 5

    from game_engine.game_history import GameHistoryStore
    store = GameHistoryStore(tmp_path / "h.json")
    store.record_result("p1", "g1", {"winner": "draw", "state": engine.serialize(), "hero_draft": "standard"})
    assert store.profile("p1")["history"][0]["hero_draft"] == "standard"
