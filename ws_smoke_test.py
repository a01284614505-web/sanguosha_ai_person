#!/usr/bin/env python3
"""WebSocket连通性冒烟测试：验证server_info握手。"""

import asyncio
import json

import websockets


async def main():
    async with websockets.connect('ws://localhost:8889') as ws:
        await ws.send(json.dumps({'type': 'server_info'}))
        reply = await asyncio.wait_for(ws.recv(), timeout=10)
        info = json.loads(reply)
        print('WS OK')
        for key, value in info.items():
            print(f'  {key}: {value}')


if __name__ == '__main__':
    asyncio.run(main())
