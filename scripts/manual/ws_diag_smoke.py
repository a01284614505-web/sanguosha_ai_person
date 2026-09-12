#!/usr/bin/env python3
"""诊断版冒烟：在 ws_engine_smoke 基础上补 动画ACK + 全量消息统计。

用途：排查"完整游玩流程是否跑通"，区分"引擎卡死"与"客户端不回ACK导致的2.5s惩罚"。
    PYTHONIOENCODING=utf-8 python scripts/manual/ws_diag_smoke.py
"""
import asyncio
import collections
import json
import sys
import time

import websockets

WS_URI = "ws://127.0.0.1:8889"
DEADLINE_SEC = 600


def build_config():
    return {
        "mode": "5人身份局",
        "player": {"name": "真人替身"},
        "ais": [{"name": f"AI{i}", "provider": "deepseek", "api_key": ""} for i in range(4)],
    }


async def run():
    t0 = time.time()
    counts = collections.Counter()
    resp_seen = []
    async with websockets.connect(WS_URI, max_size=2**20) as ws:
        await ws.send(json.dumps({"type": "create_game", "config": build_config()}))
        step = 0
        while True:
            if time.time() - t0 > DEADLINE_SEC:
                print(f"SMOKE_FAIL: {DEADLINE_SEC}s 内未决出胜负")
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=90)
            except asyncio.TimeoutError:
                print(f"SMOKE_FAIL: 90s 无任何消息（疑似引擎卡死），step={step}")
                break
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

            if t == "your_turn":
                await ws.send(json.dumps(
                    {"type": "player_action", "action": {"type": "end_phase"}, "target_ids": []}))

            elif t == "require_response":
                opts = msg.get("options")
                rid = msg.get("request_id")
                resp_seen.append({"rid": rid, "n_opts": len(opts) if opts is not None else None,
                                  "keys": sorted(msg.keys())})
                if rid is not None and opts:
                    # 必须带 type=response，否则 submit_action 走不到 submit_response，
                    # 整个请求会静默等满 response_timeout 再落到规则托管。
                    await ws.send(json.dumps({
                        "type": "player_action",
                        "action": {"type": "response", "request_id": rid, "option_index": 0},
                        "target_ids": [],
                    }))
                else:
                    print(f"[NO-REPLY] require_response 无法应答: {json.dumps(msg, ensure_ascii=False)[:300]}")

            if t == "game_end":
                print(f"[step {step}] winner={msg.get('winner')} 用时={time.time()-t0:.1f}s")
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
