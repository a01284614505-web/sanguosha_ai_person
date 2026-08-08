#!/usr/bin/env python3
"""游戏服务器 v2：HTTP静态页面 + WebSocket消息泵，规则全部交给MainEngine。"""

import asyncio
import copy
import json
import os
import sys
import traceback
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit
from websockets.exceptions import ConnectionClosedOK

BASE_DIR = Path(__file__).resolve().parent
ENGINE_DIR = BASE_DIR / "game_engine"
sys.path.insert(0, str(ENGINE_DIR))

from main_engine import MainEngine

HTTP_PORT = 8888
WS_PORT = 8889

# 默认不内置密钥；用户可由前端提交或通过环境变量设置。
DEFAULT_API_KEY = os.getenv("SANGUOSHA_DEFAULT_API_KEY", "")


def load_heroes():
    path = BASE_DIR / "data" / "heroes.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else data.get("heroes", [])
    except Exception as exc:
        print(f"[数据错误] 无法加载武将: {exc}")
        return []


class GameServer:
    def __init__(self):
        self.engines = {}
        self.tasks = {}
        self.ws_map = {}
        self.heroes = load_heroes()
        self.next_game_id = 1
        self.animation_waiters = {}
        self.animation_seq = 0

    async def handle(self, ws):
        print(f"[连接] {ws.remote_address}")
        try:
            async for raw in ws:
                try:
                    data = json.loads(raw)
                    message_type = data.get("type", "")
                    if message_type == "create_game":
                        await self.do_create(ws, data.get("config", {}))
                    elif message_type == "player_action":
                        await self.do_action(ws, data)
                    elif message_type == "chat":
                        await self.do_chat(ws, data)
                    elif message_type == "card_animation_done":
                        await self.do_animation_done(ws, data)
                    elif message_type == "end_game":
                        await self.do_end_game(ws, data)
                    elif message_type == "update_ai_config":
                        await self.do_update_ai_config(ws, data)
                    elif message_type == "ping":
                        await self.send(ws, {"type": "pong"})
                    elif message_type == "server_info":
                        await self.send(
                            ws,
                            {
                                "type": "server_info",
                                "engine": "MainEngine-v2",
                                "supported_modes": ["5人身份局"],
                                "hero_count": len(self.heroes),
                                "worldbook_hero_count": 27,
                                "generated_skill_count": 54,
                                "runtime_skill_count": 54,
                            },
                        )
                    else:
                        await self.send_error(ws, f"未知消息类型: {message_type}")
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
            if gid:
                # 当前版本每局只有一个真人连接；连接关闭时取消幽灵对局和动画等待器。
                task = self.tasks.get(gid)
                if task and not task.done():
                    task.cancel()
                prefix = f"{gid}-"
                for animation_id, waiter in list(self.animation_waiters.items()):
                    if animation_id.startswith(prefix) and not waiter.done():
                        waiter.cancel()
                    if animation_id.startswith(prefix):
                        self.animation_waiters.pop(animation_id, None)

    def normalize_config(self, raw_config):
        if not isinstance(raw_config, dict):
            raise ValueError("config必须是JSON对象")

        cfg = copy.deepcopy(raw_config)
        cfg.setdefault("mode", "5人身份局")
        if cfg["mode"] != "5人身份局":
            raise ValueError("P0当前只开放5人身份局；其他模式将在后续阶段实现")

        ais = cfg.get("ais") or []
        if len(ais) != 4:
            raise ValueError(f"5人身份局需要4个AI，当前收到{len(ais)}个")

        selected_hero = cfg.get("selected_hero") or {}
        player_cfg = cfg.get("player") or {}
        player_cfg.setdefault("name", cfg.get("player_name", "玩家"))
        player_cfg.setdefault("is_ai", False)
        player_cfg["hero"] = self._canonical_hero(player_cfg.get("hero") or selected_hero, 0)
        if player_cfg.get("is_ai") and not player_cfg.get("ai_config"):
            player_cfg["ai_config"] = self._normalize_ai(player_cfg, use_default=False)
        cfg["player"] = player_cfg

        normalized_ais = []
        used_hero_ids = {player_cfg.get("hero", {}).get("id")}
        for index, raw_ai in enumerate(ais, start=1):
            ai = self._normalize_ai(raw_ai, use_default=True)
            ai["hero"] = self._canonical_hero(ai.get("hero"), index, used_hero_ids)
            used_hero_ids.add(ai.get("hero", {}).get("id"))
            normalized_ais.append(ai)
        cfg["ais"] = normalized_ais

        requested_deck = cfg.get("deck_id")
        if requested_deck:
            from deck_manager import DECKS, DeckManager

            deck_id = DeckManager.normalize_deck_id(requested_deck)
            if deck_id not in DECKS:
                raise ValueError(f"未知牌堆ID: {requested_deck}")
            cfg["deck_id"] = deck_id

        cfg.setdefault("max_turns", 300)
        cfg.setdefault("human_action_timeout", 120)
        cfg.setdefault("phase_delay", 0.05)
        cfg.setdefault("turn_delay", 0.1)
        return cfg

    def _normalize_ai(self, raw_ai, use_default=True):
        ai = copy.deepcopy(raw_ai or {})
        ai["name"] = ai.get("name") or "AI玩家"
        ai["provider"] = (ai.get("provider") or "deepseek").lower()
        ai["model"] = ai.get("model") or "deepseek-chat"
        ai["api_url"] = ai.get("api_url") or ai.get("apiUrl") or ""
        supplied_key = ai.get("api_key") or ai.get("apiKey")
        ai["api_key"] = supplied_key if supplied_key is not None else (DEFAULT_API_KEY if use_default else "")
        try:
            ai["temperature"] = float(ai.get("temperature", 0.8))
        except (TypeError, ValueError):
            ai["temperature"] = 0.8
        return ai

    def _hero_for_seat(self, seat, excluded=None):
        excluded = excluded or set()
        available = [h for h in self.heroes if h.get("id") not in excluded]
        source = available or self.heroes
        if source:
            return copy.deepcopy(source[seat % len(source)])
        return {
            "id": f"default_{seat}",
            "name": "默认武将",
            "faction": "群",
            "max_hp": 4,
            "skills": [],
        }

    def _canonical_hero(self, candidate, seat=0, excluded=None):
        """只信任hero_id；体力、势力和技能从服务器运行时数据重建。"""
        candidate = candidate or {}
        hero_id = candidate.get("id") if isinstance(candidate, dict) else str(candidate)
        canonical = next((h for h in self.heroes if h.get("id") == hero_id), None)
        if canonical:
            return copy.deepcopy(canonical)
        return self._hero_for_seat(seat, excluded)

    async def do_create(self, ws, raw_config):
        old_gid = self.ws_map.get(ws)
        if old_gid and old_gid in self.tasks and not self.tasks[old_gid].done():
            await self.send_error(ws, "当前连接已有正在运行的游戏")
            return

        cfg = self.normalize_config(raw_config)
        gid = str(self.next_game_id)
        self.next_game_id += 1
        print(f"\n[创建] game_{gid} | 模式: {cfg['mode']} | 玩家: {cfg['player']['name']}")

        engine = MainEngine(cfg)
        self.engines[gid] = engine
        self.ws_map[ws] = gid

        engine.on("state_changed", self._make_state_handler(ws))
        engine.on("your_turn", self._make_your_turn_handler(ws))
        engine.on("action_result", self._make_action_result_handler(ws))
        engine.on("ai_action", self._make_ai_action_handler(ws))
        engine.on("chat", self._make_chat_handler(ws))
        engine.on("event_notification", self._make_event_handler(ws))
        engine.on("require_response", self._make_require_response_handler(ws))
        engine.on("card_animation", self._make_card_animation_handler(ws, gid))
        engine.on("game_end", self._make_game_end_handler(ws))

        await self.send(ws, {"type": "game_created", "game_id": gid})
        task = asyncio.create_task(self._run_engine(gid, engine, ws))
        self.tasks[gid] = task

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
        gid = self.ws_map.get(ws)
        engine = self.engines.get(gid)
        if not engine:
            await self.send_error(ws, "当前连接没有游戏")
            return
        engine.submit_action(data.get("action", {}), data.get("target_ids", []))

    async def do_chat(self, ws, data):
        message = str(data.get("message", "")).strip()[:200]
        if message:
            await self.send(ws, {"type": "chat", "from": "玩家", "message": message})

    async def do_animation_done(self, ws, data):
        animation_id = str(data.get("animation_id", ""))
        waiter = self.animation_waiters.get(animation_id)
        if waiter and not waiter.done():
            waiter.set_result(True)

    async def do_end_game(self, ws, data):
        gid = self.ws_map.get(ws)
        engine = self.engines.get(gid)
        if not engine:
            await self.send_error(ws, "当前连接没有游戏")
            return
        reason = str(data.get("reason", "玩家主动结束游戏"))[:100]
        engine.request_end_game(reason)
        await self.send(ws, {"type": "end_game_accepted"})
        await engine.emit("state_changed", state=engine.serialize())
        await engine.emit(
            "game_end", winner="aborted", message=reason, state=engine.serialize()
        )
        task = self.tasks.get(gid)
        if task and not task.done():
            task.cancel()

    async def do_update_ai_config(self, ws, data):
        gid = self.ws_map.get(ws)
        engine = self.engines.get(gid)
        if not engine:
            await self.send_error(ws, "当前连接没有游戏")
            return
        try:
            updated = engine.update_ai_config(int(data.get("player_id")), data.get("config") or {})
            await self.send(ws, {"type": "ai_config_updated", "config": updated})
        except Exception as exc:
            await self.send_error(ws, f"AI配置更新失败: {exc}")

    def _make_state_handler(self, ws):
        async def handler(state=None, **_):
            await self.send(ws, {"type": "game_state", "state": state})
        return handler

    def _make_your_turn_handler(self, ws):
        async def handler(player_name=None, hand=None, actions=None, **_):
            await self.send(
                ws,
                {"type": "your_turn", "player_name": player_name, "hand": hand, "actions": actions},
            )
        return handler

    def _make_action_result_handler(self, ws):
        async def handler(success=False, **_):
            await self.send(ws, {"type": "action_result", "success": success})
        return handler

    def _make_ai_action_handler(self, ws):
        async def handler(player_name=None, action=None, card_name=None, reasoning=None, **_):
            await self.send(
                ws,
                {
                    "type": "ai_action", "player_name": player_name,
                    "action": action, "card_name": card_name,
                    "reasoning": reasoning,
                },
            )
        return handler

    def _make_chat_handler(self, ws):
        async def handler(from_=None, message=None, **_):
            await self.send(ws, {"type": "chat", "from": from_, "message": message})
        return handler

    def _make_event_handler(self, ws):
        async def handler(**data):
            await self.send(ws, {"type": "event_notification", **data})
        return handler

    def _make_require_response_handler(self, ws):
        """纯转发：候选和时机全部由引擎算好，服务器不加任何分派逻辑。"""
        async def handler(**data):
            await self.send(ws, {"type": "require_response", **data})
        return handler

    def _make_card_animation_handler(self, ws, gid):
        async def handler(**data):
            self.animation_seq += 1
            animation_id = f"{gid}-{self.animation_seq}"
            loop = asyncio.get_running_loop()
            waiter = loop.create_future()
            self.animation_waiters[animation_id] = waiter
            await self.send(
                ws,
                {"type": "event_notification", "animation_id": animation_id, **data},
            )
            try:
                # 浏览器正常动画约1.1秒；断线或后台页面最多等待2.5秒后继续。
                await asyncio.wait_for(waiter, timeout=2.5)
            except asyncio.TimeoutError:
                print(f"[动画ACK超时] {animation_id} {data.get('card_name', '')}")
            except asyncio.CancelledError:
                return
            finally:
                self.animation_waiters.pop(animation_id, None)
        return handler

    def _make_game_end_handler(self, ws):
        async def handler(winner=None, message=None, state=None, **_):
            await self.send(
                ws,
                {"type": "game_end", "winner": winner, "message": message, "state": state},
            )
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
            self.api_deck_list()
            return
        if request_path.startswith("/api/"):
            self.send_error(404)
            return
        suffix = Path(request_path).suffix.lower()
        if suffix not in self.ALLOWED_STATIC_SUFFIXES:
            self.send_error(404)
            return
        super().do_GET()

    def do_POST(self):
        """处理POST请求（API）"""
        if self.path.split("?")[0] == "/api/switch_deck":
            self.api_switch_deck()
            return
        self.send_error(404)

    def api_deck_list(self):
        """返回全部可用牌堆和当前默认牌堆。"""
        from deck_manager import DeckManager

        try:
            manager = DeckManager(BASE_DIR)
            self._send_json(
                200,
                {
                    "success": True,
                    "active_deck": manager.get_active_deck_id(),
                    "decks": manager.get_deck_list(),
                },
            )
        except Exception as exc:
            self._send_json(500, {"success": False, "message": f"{type(exc).__name__}: {exc}"})

    def api_switch_deck(self):
        """切换默认牌堆。只影响之后新开的对局，不热替换进行中的牌堆。"""
        from deck_manager import DeckManager

        try:
            requested = self._read_json_body().get("deck_id")
            manager = DeckManager(BASE_DIR)
            deck_id = manager.normalize_deck_id(requested)
            if not manager.switch_deck(deck_id):
                self._send_json(
                    400,
                    {
                        "success": False,
                        "message": f"未知牌堆ID: {requested}",
                        "active_deck": manager.get_active_deck_id(),
                        "decks": manager.get_deck_list(),
                    },
                )
                return
            info = manager.get_deck_info(deck_id)
            self._send_json(
                200,
                {
                    "success": True,
                    "message": f"默认牌堆已切换为{info.get('name', deck_id)}（{info.get('cards_count')}张），新开局生效",
                    "active_deck": deck_id,
                    "deck": info,
                    "decks": manager.get_deck_list(),
                },
            )
        except json.JSONDecodeError:
            self._send_json(400, {"success": False, "message": "请求体不是合法JSON"})
        except Exception as exc:
            self._send_json(500, {"success": False, "message": f"{type(exc).__name__}: {exc}"})



def start_http():
    handler = CustomHandler
    HTTPServer(("0.0.0.0", HTTP_PORT), handler).serve_forever()


async def main():
    from websockets.asyncio.server import serve

    server = GameServer()
    print(f"\n{'=' * 50}")
    print("  🎮 三国杀AI酒馆 P0")
    print(f"  HTTP: http://localhost:{HTTP_PORT}")
    print(f"  WS:   ws://localhost:{WS_PORT}")
    print(f"  武将数据: {len(server.heroes)}将")
    print(f"{'=' * 50}\n")
    async with serve(server.handle, "0.0.0.0", WS_PORT, max_size=2**20):
        await asyncio.Future()


if __name__ == "__main__":
    Thread(target=start_http, daemon=True).start()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n已停止")
