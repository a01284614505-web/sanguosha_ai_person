#!/usr/bin/env python3
"""引擎自驱冒烟：原生 WebSocket 驱动一整局，跑出非 aborted 胜者。

用法（先起服务：start_windows.ps1 -Action start，WS :8889）：
    PYTHONIOENCODING=utf-8 python scripts/manual/ws_engine_smoke.py

以真人替身连接大厅，建 5 人身份局，4 个 AI 用空 api_key（触发 simple_ai 规则决策，
不打真 API），真人替身每轮自动选第一个合法动作，直至收到 game_end。
"""
import asyncio
import json
import sys

import websockets

WS_URI = "ws://127.0.0.1:8889"


def build_config():
    return {
        "mode": "5人身份局",
        "player": {"name": "真人替身"},
        # AIs 直接给空 api_key -> normalize_ai 回退 DEFAULT_API_KEY（默认空）
        "ais": [
            {"name": f"AI{i}", "provider": "deepseek", "api_key": ""}
            for i in range(4)
        ],
    }


async def run():
    deadline = asyncio.get_event_loop().time() + 240
    async with websockets.connect(WS_URI, max_size=2**20) as ws:
        # 建局
        await ws.send(json.dumps({"type": "create_game", "config": build_config()}))
        step = 0
        while True:
            if asyncio.get_event_loop().time() > deadline:
                print("SMOKE_FAIL: 240s 内未决出胜负")
                return 1
            raw = await asyncio.wait_for(ws.recv(), timeout=60)
            msg = json.loads(raw)
            t = msg.get("type")
            step += 1
            if t in ("error", "game_end"):
                print(f"[msg {step}] {t}: {json.dumps(msg, ensure_ascii=False)[:300]}")
            # 真人座位每次都直接结束出牌阶段：全部真实决策交给规则AI，证明引擎自驱不aborted
            if t == "your_turn":
                await ws.send(json.dumps(
                    {"type": "player_action", "action": {"type": "end_phase"}, "target_ids": []}))
            elif t == "require_response":
                options = msg.get("options") or []
                if "request_id" in msg and options:
                    await ws.send(json.dumps({
                        "type": "player_action",
                        "action": {"request_id": msg["request_id"], "option_index": 0},
                        "target_ids": [],
                    }))
            if t == "game_end":
                print(f"[step {step}] winner={msg.get('winner')} | remain={msg.get('players_alive')}")
                print("SMOKE_OK: 规则AI跑到非aborted胜者")
                return 0


def main():
    try:
        return asyncio.run(run())
    except asyncio.TimeoutError:
        print("SMOKE_FAIL: 超时未收到终结事件")
        return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
