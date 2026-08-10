#!/usr/bin/env python3
'''游戏服务器 v2：HTTP 静态页面 + WebSocket 纯消息泵。'''
import asyncio
import json
import traceback
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit
from websockets.exceptions import ConnectionClosedOK
from game_engine import MainEngine
BASE_DIR = Path(__file__).resolve().parent
HTTP_PORT = 8_888
WS_PORT = 8889
class GameServer:
    def __init__(self):
        self.engines = {}
        self.tasks = {}
        self.ws_map = {}
        self.next_game_id = 1
        self.animation_waiters = {}
        self.animation_seq = 0
    async def handle(self, ws):
        print(f"[连接] {ws.remote_address}")
        try:
            async for raw in ws:
                try:
                    data = json.loads(raw)
                    await self.dispatch(ws, data)
                except json.JSONDecodeError:
                    await self.send_error(ws, "消息不是合法JSON")
                except Exception as exc:
                    print(f"[消息处理错误] {exc}")
                    traceback.print_exc()
                    await self.send_error(ws, str(exc))
        except Exception as exc:
            print(f"[连接关闭] {exc}")
        finally:
            gid = self.ws_map.pop(ws, None)
            task = self.tasks.get(gid)
            if task and not task.done():
                task.cancel()
            prefix = f"{gid}-"
            for animation_id, waiter in list(self.animation_waiters.items()):
                if animation_id.startswith(prefix):
                    if not waiter.done():
                        waiter.cancel()
                    self.animation_waiters.pop(animation_id, None)
    async def dispatch(self, ws, data):
        message_type = data.get("type", "")
        handlers = {
            "create_game": lambda: self.do_create(ws, data.get("config", {})),
            "player_action": lambda: self.do_action(ws, data),
            "chat": lambda: self.do_chat(ws, data),
            "card_animation_done": lambda: self.do_animation_done(data),
            "end_game": lambda: self.do_end_game(ws, data),
            "update_ai_config": lambda: self.do_update_ai_config(ws, data),
            "ping": lambda: self.send(ws, {"type": "pong"}),
            "server_info": lambda: self.send(
                ws, {"type": "server_info", **MainEngine.server_info()}
            ),
        }
        handler = handlers.get(message_type)
        if handler:
            await handler()
        else:
            await self.send_error(ws, f"未知消息类型: {message_type}")
    def engine_for(self, ws):
        return self.engines.get(self.ws_map.get(ws))
    async def do_create(self, ws, raw_config):
        old_gid = self.ws_map.get(ws)
        if old_gid and old_gid in self.tasks and not self.tasks[old_gid].done():
            await self.send_error(ws, "当前连接已有正在运行的游戏")
            return
        cfg = MainEngine.normalize_config(raw_config, BASE_DIR)
        gid = str(self.next_game_id)
        self.next_game_id += 1
        print(f"\n[创建] game_{gid} | 模式: {cfg['mode']} | 玩家: {cfg['player']['name']}")
        engine = MainEngine(cfg)
        self.engines[gid] = engine
        self.ws_map[ws] = gid
        for event in (
            "state_changed", "your_turn", "action_result", "ai_action", "chat",
            "event_notification", "require_response", "game_end",
        ):
            engine.on(event, self._forward(ws, event))
        engine.on("card_animation", self._animation_handler(ws, gid))
        await self.send(ws, {"type": "game_created", "game_id": gid})
        self.tasks[gid] = asyncio.create_task(self._run_engine(gid, engine, ws))
    async def _run_engine(self, gid, engine, ws):
        try:
            await engine.run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[引擎错误] game_{gid}: {exc}")
            traceback.print_exc()
            await self.send_error(ws, f"游戏引擎异常: {exc}", fatal=True)
    async def do_action(self, ws, data):
        engine = self.engine_for(ws)
        if not engine:
            await self.send_error(ws, "当前连接没有游戏")
            return
        engine.submit_action(data.get("action", {}), data.get("target_ids", []))
    async def do_chat(self, ws, data):
        message = str(data.get("message", "")).strip()[:200]
        if message:
            await self.send(ws, {"type": "chat", "from": "玩家", "message": message})
    async def do_animation_done(self, data):
        waiter = self.animation_waiters.get(str(data.get("animation_id", "")))
        if waiter and not waiter.done():
            waiter.set_result(True)
    async def do_end_game(self, ws, data):
        engine = self.engine_for(ws)
        if not engine:
            await self.send_error(ws, "当前连接没有游戏")
            return
        reason = str(data.get("reason", "玩家主动结束游戏"))[:100]
        await engine.request_end_game(reason)
        await self.send(ws, {"type": "end_game_accepted"})
    async def do_update_ai_config(self, ws, data):
        engine = self.engine_for(ws)
        if not engine:
            await self.send_error(ws, "当前连接没有游戏")
            return
        try:
            updated = engine.update_ai_config(
                int(data.get("player_id")), data.get("config") or {}
            )
            await self.send(ws, {"type": "ai_config_updated", "config": updated})
        except Exception as exc:
            await self.send_error(ws, f"AI配置更新失败: {exc}")
    def _forward(self, ws, event):
        message_types = {
            "state_changed": "game_state",
            "event_notification": "event_notification",
        }
        async def handler(**data):
            if event == "chat" and "from_" in data:
                data["from"] = data.pop("from_")
            await self.send(ws, {"type": message_types.get(event, event), **data})
        return handler
    def _animation_handler(self, ws, gid):
        async def handler(**data):
            await_ui = bool(data.pop("await_ui", False))
            self.animation_seq += 1
            animation_id = f"{gid}-{self.animation_seq}"
            waiter = asyncio.get_running_loop().create_future()
            if await_ui:
                self.animation_waiters[animation_id] = waiter
            await self.send(
                ws, {"type": "event_notification", "animation_id": animation_id, **data}
            )
            if not await_ui:
                return
            try:
                await asyncio.wait_for(waiter, timeout=2.5)
            except asyncio.TimeoutError:
                print(f"[动画ACK超时] {animation_id} {data.get('card_name', '')}")
            except asyncio.CancelledError:
                return
            finally:
                self.animation_waiters.pop(animation_id, None)
        return handler
    async def send_error(self, ws, message, fatal=False):
        await self.send(ws, {"type": "error", "message": message, "fatal": fatal})
    async def send(self, ws, data):
        try:
            await ws.send(json.dumps(data, ensure_ascii=False))
        except ConnectionClosedOK:
            return
        except Exception as exc:
            print(f"[发送失败] {exc}")
class CustomHandler(SimpleHTTPRequestHandler):
    ALLOWED_STATIC_SUFFIXES = {".html", ".css", ".js", ".json", ".png", ".jpg", ".mp3"}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR / "frontend"), **kwargs)
    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
    def _read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        data = json.loads(self.rfile.read(length))
        return data if isinstance(data, dict) else {}
    def do_GET(self):
        request_path = urlsplit(self.path).path
        if request_path == "/api/decks":
            try:
                info = MainEngine.deck_list(BASE_DIR)
                self._send_json(200, {"success": True, **info})
            except Exception as exc:
                self._send_json(
                    500,
                    {"success": False, "message": f"{type(exc).__name__}: {exc}"},
                )
            return
        if request_path.startswith("/api/"):
            self.send_error(404)
            return
        if request_path.endswith("/"):
            self.path = request_path + "index.html"
            request_path = self.path
        if Path(request_path).suffix.lower() not in self.ALLOWED_STATIC_SUFFIXES:
            self.send_error(404)
            return
        super().do_GET()
    def do_POST(self):
        if self.path.split("?")[0] != "/api/switch_deck":
            self.send_error(404)
            return
        try:
            requested = self._read_json_body().get("deck_id")
            result = MainEngine.switch_deck(requested, BASE_DIR)
            if not result["success"]:
                self._send_json(400, {
                    "success": False, "message": f"未知牌堆ID: {requested}",
                    "active_deck": result["active_deck"], "decks": result["decks"],
                })
                return
            deck = result["deck"]
            self._send_json(200, {
                **result,
                "message": f"默认牌堆已切换为{deck.get('name')}（{deck.get('cards_count')}张），新开局生效",
            })
        except json.JSONDecodeError:
            self._send_json(400, {"success": False, "message": "请求体不是合法JSON"})
        except Exception as exc:
            self._send_json(500, {"success": False, "message": f"{type(exc).__name__}: {exc}"})
def start_http():
    HTTPServer(("0.0.0.0", HTTP_PORT), CustomHandler).serve_forever()
async def main():
    from websockets.asyncio.server import serve
    server = GameServer()
    info = MainEngine.server_info()
    print(f"\n{'=' * 50}\n  🎮 三国杀AI酒馆 P0")
    print(f"  HTTP: http://localhost:{HTTP_PORT}\n  WS:   ws://localhost:{WS_PORT}")
    print(f"  武将数据: {info['hero_count']}将\n{'=' * 50}\n")
    async with serve(server.handle, "0.0.0.0", WS_PORT, max_size=2**20):
        await asyncio.Future()
if __name__ == "__main__":
    Thread(target=start_http, daemon=True).start()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n已停止")
