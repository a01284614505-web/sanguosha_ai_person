#!/usr/bin/env python3
'''游戏服务器 v2：HTTP 静态页面 + WebSocket 纯消息泵。'''
import asyncio
import json
import logging
import os
import sys
import traceback
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlsplit
from websockets.exceptions import ConnectionClosedOK
from game_engine import MainEngine
from game_engine.config_validator import sanitize_client_config
from game_engine.game_history import GameHistoryStore, validate_profile_id
from game_engine.model_catalog import ModelListError, list_models
from game_engine.game_logs import GameLogStore, build_game_log, validate_game_id
from game_engine.identity_system import IdentitySystem
from game_engine.seats import seat_of
from game_engine.protocol import INBOUND, OUTBOUND, ENGINE_EVENT, ENGINE_EVENT_MAP, ENGINE_EVENTS
BASE_DIR = Path(__file__).resolve().parent
HTTP_PORT = 8_888
WS_PORT = 8889
HISTORY_PATH = Path(os.environ.get("SANGUOSHA_HISTORY_PATH") or BASE_DIR / "logs/runtime/game_history.json")
GAME_LOG_DIR = Path(os.environ.get("SANGUOSHA_GAME_LOG_DIR") or BASE_DIR / "logs/runtime/game_logs")
# 运行中的 GameServer；HTTP 线程只读取它，用于局内“拉取模型”沿用该 AI 已保存的 Key。
ACTIVE_SERVER = None


def configure_logging():
    """进程入口统一配置：引擎/服务器日志输出到控制台，保留原始消息文本。

    尊重既有的 stderr 过滤习惯，并保留被启动器重定向 stdout 的兼容路径。
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
        force=True,
    )


class GameServer:
    """对局与浏览器连接脱钩：断线只是观众离开，对局继续，由 5 分钟离席 watchdog 与托管兜底。"""

    FINISHED_KEEP = 20          # 无人观看时结束的对局，保留多少条结果供重连领取
    DISCONNECT_GRACE = 300.0    # 断线后保留对局的秒数，与 5 分钟离席铁规则一致

    def __init__(self, history_path=None):
        self.engines = {}
        self.tasks = {}
        self.ws_map = {}            # ws -> game_id
        self.viewers = {}           # game_id -> 当前观看的 ws（可在重连时替换）
        self.finished = {}          # game_id -> {"profile_id", "game_end"}：无人观看时结束的结果
        self.history = GameHistoryStore(history_path or HISTORY_PATH)
        self.game_logs = GameLogStore(GAME_LOG_DIR)
        self.animation_waiters = {}
        self.animation_seq = 0
        self.grace_tasks = {}       # game_id -> 断线宽限计时任务

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
            await self._detach(ws)

    async def _detach(self, ws):
        """连接断开：只解除观看关系。进行中的对局保留，等重连或由离席规则收尾。"""
        gid = self.ws_map.pop(ws, None)
        if gid is None or self.viewers.get(gid) is not ws:
            return
        self.viewers.pop(gid, None)
        self._release_animation_waiters(gid)
        engine = self.engines.get(gid)
        task = self.tasks.get(gid)
        if engine is None or task is None or task.done():
            self._drop_game(gid)
            return
        print(f"[观众离开] game_{gid} 对局继续，{int(self.DISCONNECT_GRACE)} 秒内可重连")
        self._cancel_grace(gid)
        self.grace_tasks[gid] = asyncio.create_task(self._disconnect_grace(gid))

    def _cancel_grace(self, gid):
        task = self.grace_tasks.pop(gid, None)
        if task is not None and not task.done():
            task.cancel()

    async def _disconnect_grace(self, gid):
        """断线超过宽限期仍未重连：按离席规则中止对局（记为中断），不让无人对局一直消耗模型调用。"""
        try:
            await asyncio.sleep(self.DISCONNECT_GRACE)
        except asyncio.CancelledError:
            return
        self.grace_tasks.pop(gid, None)
        engine = self.engines.get(gid)
        if engine is None or self.viewers.get(gid) is not None or engine.game_aborted:
            return
        try:
            await engine.request_end_game("离线超过 5 分钟，对局中止")
        except Exception as exc:
            logging.getLogger(__name__).error("断线收摊失败: %s", exc)

    def _release_animation_waiters(self, gid):
        prefix = f"{gid}-"
        for animation_id, waiter in list(self.animation_waiters.items()):
            if animation_id.startswith(prefix):
                if not waiter.done():
                    waiter.set_result(False)
                self.animation_waiters.pop(animation_id, None)

    def _drop_game(self, gid):
        self._cancel_grace(gid)
        self.tasks.pop(gid, None)
        self.engines.pop(gid, None)
        self.viewers.pop(gid, None)
        self._release_animation_waiters(gid)

    async def dispatch(self, ws, data):
        message_type = data.get("type", "")
        handlers = {
            INBOUND.CREATE_GAME: lambda: self.do_create(ws, data.get("config", {})),
            INBOUND.RESUME_GAME: lambda: self.do_resume(ws, data),
            INBOUND.PLAYER_ACTION: lambda: self.do_action(ws, data),
            INBOUND.CHAT: lambda: self.do_chat(ws, data),
            INBOUND.CARD_ANIMATION_DONE: lambda: self.do_animation_done(data),
            INBOUND.END_GAME: lambda: self.do_end_game(ws, data),
            INBOUND.UPDATE_AI_CONFIG: lambda: self.do_update_ai_config(ws, data),
            INBOUND.SET_TRUSTEE: lambda: self.do_set_trustee(ws, data),
            INBOUND.UPDATE_SETTINGS: lambda: self.do_update_settings(ws, data),
            INBOUND.PING: lambda: self.send(ws, {"type": OUTBOUND.PONG}),
            INBOUND.SERVER_INFO: lambda: self.send(
                ws, {"type": OUTBOUND.SERVER_INFO, **MainEngine.server_info()}
            ),
        }
        handler = handlers.get(message_type)
        if handler:
            await handler()
        else:
            await self.send_error(ws, f"未知消息类型: {message_type}")

    def engine_for(self, ws):
        gid = self.ws_map.get(ws)
        # 只有当前观看者能操作对局；被新页面接管的旧连接不再能下指令。
        if gid is None or self.viewers.get(gid) is not ws:
            return None
        return self.engines.get(gid)

    async def _end_orphaned_games(self, profile_id):
        """同一档案开新局时，结束它在后台无人观看、仍在进行的旧局（记为中断）。"""
        for gid, engine in list(self.engines.items()):
            if self.viewers.get(gid) is not None:
                continue
            if engine.game_config.get("profile_id") != profile_id or engine.game_aborted:
                continue
            try:
                await engine.request_end_game("开始了新对局，旧对局中止")
            except Exception as exc:
                logging.getLogger(__name__).error("结束旧对局失败: %s", exc)

    async def do_create(self, ws, raw_config):
        old_gid = self.ws_map.get(ws)
        if old_gid and old_gid in self.tasks and not self.tasks[old_gid].done():
            await self.send_error(ws, "当前连接已有正在运行的游戏")
            return
        if old_gid:
            self.ws_map.pop(ws, None)
            if self.viewers.get(old_gid) is ws:
                self._drop_game(old_gid)
        cfg = MainEngine.normalize_config(sanitize_client_config(raw_config), BASE_DIR)
        gid = uuid.uuid4().hex
        cfg["profile_id"] = validate_profile_id(cfg.get("profile_id") or f"guest_{gid}")
        await self._end_orphaned_games(cfg["profile_id"])
        print(f"\n[创建] game_{gid} | 模式: {cfg['mode']} | 玩家: {cfg['player']['name']}")
        engine = MainEngine(cfg)
        engine.game_id = gid
        identity_card = cfg.get("identity_card") or {}
        if identity_card.get("use"):
            if IdentitySystem.IDENTITY_ALIASES.get(identity_card.get("identity")) not in IdentitySystem.IDENTITY_5:
                await self.send_error(ws, "身份卡指定了无效身份")
                return
            try:
                self.history.reserve_identity_card(cfg["profile_id"], gid)
            except (ValueError, OSError, RuntimeError) as exc:
                await self.send_error(ws, f"身份卡使用失败: {exc}")
                return
        self.engines[gid] = engine
        self.ws_map[ws] = gid
        self.viewers[gid] = ws
        for event in ENGINE_EVENTS:
            engine.on(event, self._forward(gid, event))
        engine.on(ENGINE_EVENT.CARD_ANIMATION, self._animation_handler(gid))
        await self.send(ws, {"type": OUTBOUND.GAME_CREATED, "game_id": gid,
                             "profile_id": cfg["profile_id"]})
        self.tasks[gid] = asyncio.create_task(self._run_engine(gid, engine))

    async def do_resume(self, ws, data):
        """重连：校验档案后把新连接设为观看者，补发状态快照和仍在等待的提示。"""
        gid = str(data.get("game_id") or "")
        try:
            profile_id = validate_profile_id(data.get("profile_id"))
        except ValueError:
            await self.send(ws, {"type": OUTBOUND.RESUME_FAILED, "game_id": gid,
                                 "reason": "bad_profile", "message": "档案 ID 无效"})
            return
        engine = self.engines.get(gid)
        if engine is None or gid in self.finished:
            # 对局已结束（包括引擎还在收尾的瞬间）：直接把结算结果交给重连的页面。
            finished = self.finished.get(gid)
            if finished and finished["profile_id"] == profile_id:
                await self.send(ws, {"type": OUTBOUND.GAME_RESUMED, "game_id": gid,
                                     "profile_id": profile_id, "finished": True})
                await self.send(ws, finished["game_end"])
                return
            await self.send(ws, {"type": OUTBOUND.RESUME_FAILED, "game_id": gid, "reason": "not_found",
                                 "message": "这局已经不在服务器上了（可能服务器重启过）"})
            return
        if engine.game_config.get("profile_id") != profile_id:
            await self.send(ws, {"type": OUTBOUND.RESUME_FAILED, "game_id": gid,
                                 "reason": "forbidden", "message": "这局不属于当前浏览器档案"})
            return
        previous = self.viewers.get(gid)
        if previous is not None and previous is not ws:
            self.ws_map.pop(previous, None)
            await self.send_error(previous, "本局已在另一个页面继续")
        old_gid = self.ws_map.get(ws)
        if old_gid and old_gid != gid and self.viewers.get(old_gid) is ws:
            self.viewers.pop(old_gid, None)
        self.ws_map[ws] = gid
        self.viewers[gid] = ws
        self._cancel_grace(gid)
        print(f"[重连] game_{gid}")
        await self.send(ws, {"type": OUTBOUND.GAME_RESUMED, "game_id": gid, "profile_id": profile_id,
                             "finished": False, "idle_seconds": int(engine.idle_seconds())})
        await self.send(ws, {"type": OUTBOUND.GAME_STATE, "state": engine.serialize()})
        status = engine.trustee_status() if hasattr(engine, "trustee_status") else None
        if status:
            await self.send(ws, {"type": OUTBOUND.TRUSTEE_STATUS, **status})
        for prompt in engine.pending_prompts():
            await self.send(ws, {"type": ENGINE_EVENT_MAP.get(prompt["event"], prompt["event"]),
                                 **prompt["payload"]})
        # 作弊局重连：补发一次最新笔记（非作弊局 cheat_notes_payload() 为 None，什么都不发）。
        notes_payload = engine.cheat_notes_payload()
        if notes_payload is not None:
            await self.send(ws, {"type": OUTBOUND.COGNITIVE_NOTES, **notes_payload})

    async def _run_engine(self, gid, engine):
        try:
            await engine.run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[引擎错误] game_{gid}: {exc}")
            traceback.print_exc()
            if (engine.game_config.get("identity_card") or {}).get("use"):
                try:
                    self.history.refund_identity_card(engine.game_config["profile_id"], gid)
                except (OSError, ValueError, RuntimeError) as refund_exc:
                    logging.getLogger(__name__).error("身份卡退款失败: %s", type(refund_exc).__name__)
            ws = self.viewers.get(gid)
            if ws is not None:
                await self.send_error(ws, f"游戏引擎异常: {exc}", fatal=True)
        finally:
            if self.viewers.get(gid) is None:
                # 无人观看时结束：结果已写入战绩并留在 finished 里供重连领取，释放引擎。
                self._drop_game(gid)

    async def do_action(self, ws, data):
        engine = self.engine_for(ws)
        if not engine:
            await self.send_error(ws, "当前连接没有游戏")
            return
        receipt = engine.submit_action(data.get("action", {}), data.get("target_ids", []))
        if receipt is not None:
            await self.send(ws, {"type": OUTBOUND.ACTION_RESULT, **receipt})
    async def do_chat(self, ws, data):
        message = str(data.get("message", "")).strip()[:200]
        if not message:
            return
        engine = self.engine_for(ws)
        human = engine.human_player() if engine else None
        if engine is not None and human is not None:
            # 真人发言交给引擎入库（AI 下次出牌决策能看到）；回显由引擎事件统一转发，这里不再自己发。
            await engine.submit_chat(human.id, message)
            return
        # 没有对局时（例如大厅里误发）只给发送者一条系统回显。
        await self.send(ws, {"type": OUTBOUND.CHAT, "from": "玩家", "message": message,
                             "is_self": True, "kind": "system"})
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
        accepted = await engine.request_end_game(reason)
        if accepted:
            await self.send(ws, {"type": OUTBOUND.END_GAME_ACCEPTED})
        else:
            await self.send_error(ws, "对局已结束")
    async def do_update_ai_config(self, ws, data):
        engine = self.engine_for(ws)
        if not engine:
            await self.send_error(ws, "当前连接没有游戏")
            return
        try:
            updated = engine.update_ai_config(
                int(data.get("player_id")), data.get("config") or {}
            )
            await self.send(ws, {"type": OUTBOUND.AI_CONFIG_UPDATED, "config": updated})
        except Exception as exc:
            await self.send_error(ws, f"AI配置更新失败: {exc}")
    async def do_update_settings(self, ws, data):
        engine = self.engine_for(ws)
        if engine is None:
            await self.send_error(ws, "当前连接没有游戏")
            return
        try:
            engine.update_settings(data.get("settings"))
        except ValueError as exc:
            await self.send_error(ws, str(exc))
            return
        # 新档位随状态快照回到界面（界面显示的是服务器确认后的值）。
        await engine.emit(ENGINE_EVENT.STATE_CHANGED, state=engine.serialize())

    async def do_set_trustee(self, ws, data):
        engine = self.engine_for(ws)
        if engine is None:
            await self.send_error(ws, "当前连接没有游戏")
            return
        try:
            status = engine.set_trustee(
                data.get("enabled") is True,
                source=data.get("source", "rules"),
                player_id=data.get("player_id"),
                config=data.get("config"),
            )
            await engine.emit(ENGINE_EVENT.TRUSTEE_STATUS, **status)
            await engine.emit(ENGINE_EVENT.STATE_CHANGED, state=engine.serialize())
        except ValueError as exc:
            await self.send_error(ws, str(exc))
    def _forward(self, gid, event):
        async def handler(**data):
            engine = self.engines.get(gid)
            if event == ENGINE_EVENT.GAME_END and engine is not None:
                # 战绩写入不依赖是否有人在看：断线期间结束的对局同样入账。
                try:
                    data.update(self.history.record_result(
                        engine.game_config["profile_id"], engine.game_id, data
                    ))
                except (OSError, ValueError, RuntimeError) as exc:
                    logging.getLogger(__name__).error("战绩持久化失败: %s", exc)
                    data["history_error"] = "战绩保存失败，请检查服务器日志"
            if event in (ENGINE_EVENT.COGNITIVE_NOTES, ENGINE_EVENT.CHAT_REJECTED) and (engine is None or not engine.cheat_mode):
                # 认知笔记只在作弊局下发：第二道闸门，即使引擎误发也不转给前端。
                return
            if event == OUTBOUND.CHAT and "from_" in data:
                data["from"] = data.pop("from_")
            if event == OUTBOUND.CHAT and isinstance(data.get("from_id"), int):
                data["seat"] = seat_of(engine.game_state, data["from_id"]) if engine else None
            if event == OUTBOUND.CHAT and data.get("kind") == "human":
                # 旧前端靠 is_self 认出“这是我自己说的话”，保持兼容。
                data["is_self"] = True
            if event == ENGINE_EVENT.CARD_MOVE and isinstance(data.get("move"), dict):
                move = dict(data["move"])
                owner_id = move.get("to_owner") if move.get("to_owner") is not None else move.get("from_owner")
                # 本版本真人座位为 0；owner 可见的私密移动不能暴露 AI 手牌的实体 ID。
                if move.get("visibility") != "public" and owner_id != 0:
                    move["card_id"] = None
                data["move"] = move
            if event == ENGINE_EVENT.GAME_END and engine is not None:
                data["log_saved"] = self._save_game_log(engine, data)
            message = {"type": ENGINE_EVENT_MAP.get(event, event), **data}
            if event == ENGINE_EVENT.GAME_END and engine is not None:
                self.finished[gid] = {"profile_id": engine.game_config.get("profile_id"),
                                      "game_end": message}
                while len(self.finished) > self.FINISHED_KEEP:
                    self.finished.pop(next(iter(self.finished)))
            ws = self.viewers.get(gid)
            if ws is not None:
                await self.send(ws, message)
        return handler

    def _save_game_log(self, engine, game_end):
        """对局结束自动保存日志；开局时设了无痕模式则跳过。失败只记服务器日志，不影响结算。"""
        settings = engine.game_config.get("global_settings") or {}
        if settings.get("log_incognito") is True:
            return False
        try:
            record = build_game_log(engine, game_end,
                                    include_thinking=settings.get("log_include_thinking") is not False)
            self.game_logs.save(record)
            return True
        except (OSError, ValueError, TypeError) as exc:
            logging.getLogger(__name__).error("对局日志保存失败: %s", type(exc).__name__)
            return False

    def _animation_handler(self, gid):
        async def handler(**data):
            await_ui = bool(data.pop("await_ui", False))
            ws = self.viewers.get(gid)
            if ws is None:
                # 没人在看就不等动画 ACK，后台对局全速推进。
                return
            self.animation_seq += 1
            animation_id = f"{gid}-{self.animation_seq}"
            waiter = asyncio.get_running_loop().create_future()
            if await_ui:
                self.animation_waiters[animation_id] = waiter
            await self.send(
                ws, {"type": OUTBOUND.EVENT_NOTIFICATION, "animation_id": animation_id, **data}
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
        await self.send(ws, {"type": OUTBOUND.ERROR, "message": message, "fatal": fatal})
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
        parsed = urlsplit(self.path)
        request_path = parsed.path
        if request_path == "/api/history":
            try:
                profile_id = validate_profile_id(parse_qs(parsed.query).get("profile_id", [None])[0])
                # 与 WebSocket 线程共用同一个存储对象（同一把锁），补发见面礼时不会和战绩写入互相覆盖。
                store = ACTIVE_SERVER.history if ACTIVE_SERVER is not None else GameHistoryStore(HISTORY_PATH)
                profile = store.profile(profile_id)
                self._send_json(200, {"success": True, "profile": profile})
            except ValueError as exc:
                self._send_json(400, {"success": False, "message": str(exc)})
            except (OSError, RuntimeError) as exc:
                logging.getLogger(__name__).error("读取战绩失败: %s", exc)
                self._send_json(500, {"success": False, "message": "战绩读取失败，请检查服务器日志"})
            return
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
        if request_path == "/api/logs" or request_path.startswith("/api/logs/"):
            self._handle_logs_get(request_path, parse_qs(parsed.query))
            return
        if request_path == "/api/providers":
            self._send_json(200, {"success": True, "providers": MainEngine.providers()})
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
    def _log_store(self):
        server = ACTIVE_SERVER
        return server.game_logs if server is not None else GameLogStore(GAME_LOG_DIR)

    def _handle_logs_get(self, request_path, query):
        try:
            profile_id = validate_profile_id((query.get("profile_id") or [None])[0])
            store = self._log_store()
            if request_path == "/api/logs":
                self._send_json(200, {"success": True, "logs": store.list(profile_id)})
                return
            game_id = validate_game_id(request_path[len("/api/logs/"):])
            record = store.get(profile_id, game_id)
            if record is None:
                self._send_json(404, {"success": False, "message": "日志不存在或已删除"})
                return
            if (query.get("download") or [""])[0] == "1":
                body = json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="sanguosha_{game_id}.json"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._send_json(200, {"success": True, "log": record})
        except ValueError as exc:
            self._send_json(400, {"success": False, "message": str(exc)})
        except OSError as exc:
            logging.getLogger(__name__).error("读取对局日志失败: %s", type(exc).__name__)
            self._send_json(500, {"success": False, "message": "日志读取失败"})

    def _handle_logs_delete(self):
        try:
            body = self._read_json_body()
            profile_id = validate_profile_id(body.get("profile_id"))
            ids = body.get("game_ids") or []
            if not isinstance(ids, list):
                raise ValueError("game_ids 必须是数组")
            removed = self._log_store().delete(profile_id, ids, delete_all=body.get("all") is True)
            self._send_json(200, {"success": True, "removed": removed})
        except json.JSONDecodeError:
            self._send_json(400, {"success": False, "message": "请求体不是合法JSON"})
        except ValueError as exc:
            self._send_json(400, {"success": False, "message": str(exc)})
        except OSError as exc:
            logging.getLogger(__name__).error("删除对局日志失败: %s", type(exc).__name__)
            self._send_json(500, {"success": False, "message": "删除失败"})

    def _saved_ai_key(self, body):
        """局内调整 AI 时 Key 可留空：按 game_id + 座位取服务器上已保存的 Key（不回传）。"""
        server = ACTIVE_SERVER
        game_id = str(body.get("game_id") or "")
        if server is None or not game_id:
            return ""
        engine = server.engines.get(game_id)
        if engine is None or engine.game_config.get("profile_id") != body.get("profile_id"):
            return ""
        try:
            player_id = int(body.get("player_id"))
        except (TypeError, ValueError):
            return ""
        player = next((p for p in engine.game_state.players if p.id == player_id and p.is_ai), None)
        return str((player.ai_config or {}).get("api_key") or "") if player is not None else ""

    def _handle_list_models(self):
        try:
            body = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"success": False, "message": "请求体不是合法JSON"})
            return
        api_key = str(body.get("api_key") or "").strip() or self._saved_ai_key(body)
        try:
            result = list_models(str(body.get("provider") or ""), body.get("api_url"), api_key)
        except ModelListError as exc:
            self._send_json(200, {"success": False, "message": str(exc)})
            return
        except Exception as exc:  # 不把 Key 或请求细节写进日志
            logging.getLogger(__name__).error("拉取模型列表失败: %s", type(exc).__name__)
            self._send_json(200, {"success": False, "message": "拉取失败，请手动填写模型名"})
            return
        self._send_json(200, {"success": True, **result})

    def do_POST(self):
        if self.path.split("?")[0] == "/api/models":
            self._handle_list_models()
            return
        if self.path.split("?")[0] == "/api/logs/delete":
            self._handle_logs_delete()
            return
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
    # 多线程：拉取模型列表要等外部 API，不能卡住静态页面与其他请求。
    httpd = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), CustomHandler)
    httpd.daemon_threads = True
    httpd.serve_forever()
async def main():
    from websockets.asyncio.server import serve
    global ACTIVE_SERVER
    server = GameServer()
    ACTIVE_SERVER = server
    info = MainEngine.server_info()
    print(f"\n{'=' * 50}\n  🎮 三国杀AI酒馆 P0")
    print(f"  HTTP: http://localhost:{HTTP_PORT}\n  WS:   ws://localhost:{WS_PORT}")
    print(f"  武将数据: {info['hero_count']}将\n{'=' * 50}\n")
    async with serve(server.handle, "0.0.0.0", WS_PORT, max_size=2**20):
        await asyncio.Future()
if __name__ == "__main__":
    configure_logging()
    Thread(target=start_http, daemon=True).start()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n已停止")
