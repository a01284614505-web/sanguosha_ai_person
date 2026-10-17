"""五谷丰登展示池：亮出的牌全桌可见，每一步都能看到谁取走了哪张、轮到谁挑。"""

import asyncio

from game_engine import MainEngine
from game_engine.state_manager import Card

CONFIG = {"mode": "5人身份局", "player_name": "P0",
          "ais": [{"name": f"P{i}"} for i in range(1, 5)], "deck_id": "standard"}


def make_engine():
    engine = MainEngine(dict(CONFIG))
    engine.response_timeout = 3
    for p in engine.game_state.players:
        p.hand.clear()
        p.equipment.clear()
        p.judge_area.clear()
    return engine


def card(tag, name, suit="spade", rank=5, card_type="basic"):
    return Card(f"wp_{tag}", name, suit, rank, card_type)


def stack_deck(engine):
    cards = [card("1", "桃", "heart", 3), card("2", "杀", "spade", 8),
             card("3", "闪", "diamond", 5), card("4", "酒", "spade", 9),
             card("5", "无中生有", "heart", 7, "trick")]
    engine.game_state.deck = list(cards)
    return cards


def capture(engine):
    states, requests = [], []

    async def on_state(**data):
        states.append(data["state"])

    async def on_request(**data):
        requests.append(data)

    engine.on("state_changed", on_state)
    engine.on("require_response", on_request)
    return states, requests


def pools(states):
    return [s.get("shown_pool") for s in states]


def test_pool_is_public_and_records_every_pick_in_order():
    engine = make_engine()
    stack_deck(engine)
    states, _ = capture(engine)
    source = engine.game_state.players[1]  # AI 使用，真人不在第一位

    async def scenario():
        task = asyncio.create_task(engine.card_system.use_wugu(source, card("wg", "五谷丰登", "heart", 4, "trick")))
        while not task.done():
            await asyncio.sleep(0)
            pending = engine._pending_requests
            for request_id in list(pending):
                engine.submit_response(request_id, 0)
        return await task

    assert asyncio.run(scenario()) is True

    snapshots = [p for p in pools(states) if p]
    first = snapshots[0]
    assert first["title"] == "五谷丰登"
    assert first["source_id"] == source.id
    assert [c["card"]["name"] for c in first["cards"]] == ["桃", "杀", "闪", "酒", "无中生有"]
    assert all(c["picked_by"] is None for c in first["cards"])
    assert "id" not in first["cards"][0]["card"], "展示池用公开牌面，不带内部牌 id"
    # 使用者起按座次轮流挑
    assert first["order"][0] == source.id

    final = snapshots[-1]
    picked = [c["picked_by"] for c in final["cards"]]
    assert sorted(picked) == sorted(first["order"])
    # 牌池里的记录与实际到手的牌一致
    for entry in final["cards"]:
        owner = engine.game_state.players[entry["picked_by"]]
        assert entry["picked_name"] == owner.name
        assert any(c.name == entry["card"]["name"] for c in owner.hand)

    # 每取走一张都有一份快照，且已取走的记录不会回退
    taken_counts = [sum(c["picked_by"] is not None for c in p["cards"]) for p in snapshots]
    assert taken_counts == sorted(taken_counts)
    assert max(taken_counts) == 5
    # 结算结束后展示池收起
    assert pools(states)[-1] is None
    assert engine.serialize()["shown_pool"] is None


def test_human_request_carries_pool_slots_and_snapshot_shows_current_picker():
    engine = make_engine()
    cards = stack_deck(engine)
    states, requests = capture(engine)
    human = engine.game_state.players[0]

    async def scenario():
        task = asyncio.create_task(engine.card_system.use_wugu(human, card("wg", "五谷丰登", "heart", 4, "trick")))
        while not requests:
            await asyncio.sleep(0)
        request = requests[-1]
        # 断线重连时靠状态快照恢复面板：此刻快照里就有展示池，轮到真人
        snapshot = engine.serialize()["shown_pool"]
        engine.submit_response(request["request_id"], 2)
        while not task.done():
            await asyncio.sleep(0)
            for request_id in list(engine._pending_requests):
                engine.submit_response(request_id, 0)
        await task
        return request, snapshot

    request, snapshot = asyncio.run(scenario())

    assert request["context"]["shown_pool"] == "五谷丰登"
    assert request["context"]["pool_slots"] == [0, 1, 2, 3, 4]
    assert snapshot["current_id"] == human.id
    assert all(c["picked_by"] is None for c in snapshot["cards"])
    assert cards[2] in human.hand, "真人在面板选第 3 张（闪）应真正到手"

    # 后面的人挑选时，候选与 pool_slots 跳过已被取走的那张
    later = [p for p in pools(states) if p and p["cards"][2]["picked_by"] == human.id]
    assert later and later[0]["cards"][2]["picked_name"] == human.name


def test_context_only_passes_scalar_lists():
    out = MainEngine._serialize_response_context({
        "pool_slots": [0, 2, 3],
        "cards": [card("x", "杀")],
        "label": "五谷丰登",
    })
    assert out == {"pool_slots": [0, 2, 3], "label": "五谷丰登"}
