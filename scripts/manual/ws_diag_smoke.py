#!/usr/bin/env python3
"""诊断版冒烟：在 ws_engine_smoke 基础上补 动画ACK + 全量消息统计。

用途：排查"完整游玩流程是否跑通"，区分"引擎卡死"与"客户端不回ACK导致的2.5s惩罚"。
    PYTHONIOENCODING=utf-8 python scripts/manual/ws_diag_smoke.py

热闹档 + 假网关模式（Stage T · T3a，自带进程内服务器，占用 8889，用完自动关闭）：
    PYTHONPATH=... python3 scripts/manual/ws_diag_smoke.py --fake-gateway
4 个 AI 全部带"假 Key"、热闹档开局；AIGateway.call_ai 换成假实现（决策 0.1 秒后失败 → 降级规则 AI；
聊天 0.3 秒后回一句）；真人客户端每个回合发一句话。检查：整局在限定时间内跑完（无卡死）、
AI 聊天出现且全程聊天并发 <= 2。冷场阈值在本模式缩短为 2 秒，让冷场路径也被走到（其余参数不变）。
"""
import asyncio
import collections
import json
import os
import sys
import tempfile
import time

import websockets

WS_URI = "ws://127.0.0.1:8889"
DEADLINE_SEC = 600
FAKE = "--fake-gateway" in sys.argv
FAKE_DEADLINE_SEC = 180
FAKE_STATS = {"chat_calls": 0, "decision_calls": 0, "active_chat": 0, "max_active_chat": 0}


def build_config():
    if FAKE:
        return {
            "mode": "5人身份局",
            "player": {"name": "真人替身"},
            "chat_level": "lively",
            "ais": [{"name": f"AI{i}", "provider": "deepseek", "api_key": f"sk-fake-smoke-key-{i:04d}-xyz"}
                    for i in range(4)],
        }
    return {
        "mode": "5人身份局",
        "player": {"name": "真人替身"},
        "ais": [{"name": f"AI{i}", "provider": "deepseek", "api_key": ""} for i in range(4)],
    }


async def fake_call_ai(self, **kwargs):
    """假网关：带 max_tokens 的是聊天回合（0.3 秒回一句），其余是决策 / 响应（0.1 秒后失败，降级规则 AI）。"""
    if kwargs.get("max_tokens"):
        FAKE_STATS["chat_calls"] += 1
        FAKE_STATS["active_chat"] += 1
        FAKE_STATS["max_active_chat"] = max(FAKE_STATS["max_active_chat"], FAKE_STATS["active_chat"])
        try:
            await asyncio.sleep(0.3)
            return json.dumps({"say": f"冒烟台词{FAKE_STATS['chat_calls']}"}, ensure_ascii=False), \
                {"prompt_tokens": 100, "cached_tokens": 50, "completion_tokens": 8}
        finally:
            FAKE_STATS["active_chat"] -= 1
    FAKE_STATS["decision_calls"] += 1
    await asyncio.sleep(0.1)
    raise RuntimeError("假网关：决策一律失败，走规则 AI")


async def start_fake_server():
    """进程内服务器：隔离战绩 / 日志路径，AIGateway.call_ai 换成假实现，冷场阈值缩短。"""
    tmp = tempfile.mkdtemp(prefix="smoke_fake_")
    os.environ["SANGUOSHA_HISTORY_PATH"] = os.path.join(tmp, "history.json")
    os.environ["SANGUOSHA_GAME_LOG_DIR"] = os.path.join(tmp, "logs")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from websockets.asyncio.server import serve
    import game_server
    from game_engine import chat_director
    from game_engine.ai_decision import AIGateway

    AIGateway.call_ai = fake_call_ai
    chat_director.CHAT_LEVELS["lively"]["idle_secs"] = 2.0
    server = game_server.GameServer()
    return await serve(server.handle, "127.0.0.1", 8889, max_size=2**20)


async def run():
    if FAKE:
        listener = await start_fake_server()
        try:
            return await run_client()
        finally:
            listener.close()
            await listener.wait_closed()
    return await run_client()


async def run_client():
    t0 = time.time()
    deadline = FAKE_DEADLINE_SEC if FAKE else DEADLINE_SEC
    counts = collections.Counter()
    resp_seen = []
    async with websockets.connect(WS_URI, max_size=2**20) as ws:
        await ws.send(json.dumps({"type": "create_game", "config": build_config()}))
        step = 0
        while True:
            if time.time() - t0 > deadline:
                print(f"SMOKE_FAIL: {deadline}s 内未决出胜负")
                return 1
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=90)
            except asyncio.TimeoutError:
                print(f"SMOKE_FAIL: 90s 无任何消息（疑似引擎卡死），step={step}")
                return 1
            msg = json.loads(raw)
            t = msg.get("type")
            counts[t] += 1
            step += 1

            # 1) 动画 ACK：引擎在 event_notification 里带 animation_id
            anim_id = msg.get("animation_id") or (msg.get("data") or {}).get("animation_id")
            if anim_id:
                counts["_ack_sent"] += 1
                await ws.send(json.dumps({"type": "card_animation_done", "animation_id": anim_id}))

            if t == "error":
                print(f"[ERROR] {json.dumps(msg, ensure_ascii=False)[:400]}")
                if msg.get("fatal"):
                    return 1

            if t == "chat":
                counts[f"_chat_{msg.get('kind')}_{'free' if msg.get('free') else 'extra'}"] += 1

            if t == "your_turn":
                if FAKE:
                    await ws.send(json.dumps({"type": "chat", "message": f"第{counts['your_turn']}手，谁是反贼？"},
                                             ensure_ascii=False))
                await ws.send(json.dumps(
                    {"type": "player_action", "action": {"type": "end_phase"}, "target_ids": []}))

            elif t == "require_response":
                opts = msg.get("options")
                rid = msg.get("request_id")
                sel = msg.get("selection") or {}
                resp_seen.append({"rid": rid, "n_opts": len(opts) if opts is not None else None,
                                  "mode": sel.get("mode"), "keys": sorted(msg.keys())})
                if rid is not None and opts:
                    # 必须带 type=response，否则 submit_action 走不到 submit_response，
                    # 整个请求会静默等满 response_timeout 再落到规则托管。
                    if sel.get("mode") == "multi":
                        want = max(1, int(sel.get("min") or 1))
                        indices = list(range(min(want, len(opts))))
                        await ws.send(json.dumps({
                            "type": "player_action",
                            "action": {"type": "response", "request_id": rid, "option_indices": indices},
                            "target_ids": [],
                        }))
                    else:
                        await ws.send(json.dumps({
                            "type": "player_action",
                            "action": {"type": "response", "request_id": rid, "option_index": 0},
                            "target_ids": [],
                        }))
                else:
                    print(f"[NO-REPLY] require_response 无法应答: {json.dumps(msg, ensure_ascii=False)[:300]}")

            if t == "game_end":
                if msg.get("winner") in (None, "aborted", "draw"):
                    print(f"SMOKE_FAIL: 非正常胜负 {msg.get('winner')}")
                    return 1
                print(f"[step {step}] winner={msg.get('winner')} 用时={time.time()-t0:.1f}s")
                mvp = msg.get("mvp") or {}
                stats = msg.get("stats") or {}
                print(f"duration={msg.get('duration')} mvp={mvp.get('player_name')} "
                      f"kills={mvp.get('kills')} damage_dealt={mvp.get('damage_dealt')} "
                      f"healing={mvp.get('healing')} cards_played={mvp.get('cards_played')}")
                for pid, row in sorted(stats.items(), key=lambda kv: str(kv[0])):
                    print(f"  player {pid}: {row}")
                if FAKE:
                    ai_chat = counts["_chat_ai_extra"] + counts["_chat_ai_free"]
                    print(f"[fake] 聊天回合调用 {FAKE_STATS['chat_calls']} 次，最大并发 {FAKE_STATS['max_active_chat']}，"
                          f"决策/响应调用 {FAKE_STATS['decision_calls']} 次；AI 聊天消息 {ai_chat} 条"
                          f"（调度器 {counts['_chat_ai_extra']}），真人 {counts['_chat_human_extra']} 条")
                    if FAKE_STATS["max_active_chat"] > 2:
                        print("SMOKE_FAIL: 聊天并发超过 2")
                        return 1
                    if counts["_chat_ai_extra"] == 0:
                        print("SMOKE_FAIL: 热闹档下没有任何调度器聊天")
                        return 1
                print("SMOKE_OK")
                break

    print("\n--- 消息类型统计 ---")
    for k, v in counts.most_common():
        print(f"{k:24s} {v}")
    print(f"\n--- require_response 共 {len(resp_seen)} 次 ---")
    for r in resp_seen[:40]:
        print(r)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()) or 0)
