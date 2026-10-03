#!/usr/bin/env python3
"""主游戏引擎 v2：引擎生成合法操作，玩家或AI只能从中选择。"""

import asyncio
import logging
import random
import time
from pathlib import Path
from typing import Any, Callable, Dict, List

from .state_manager import GameState, Player, Phase, card_to_dict
from .phase_controller import PhaseController
from .skill_manager import SkillManager
from .card_system import CardSystem, make_pass_option, option_label
from .card_table import CARD_TABLE, NO_EXTERNAL_TARGET
from .rules_engine import RulesEngine
from .ai_decision import AIDecision
from .identity_system import IdentitySystem
from .chat_engine import ChatEngine
from .config_validator import normalize_config
from .deck_manager import DeckManager
from .game_stats import GameStats, record_stat


logger = logging.getLogger(__name__)
from .hero_registry import HeroRegistry
from .protocol import ENGINE_EVENT, PROVIDERS


class MainEngine:
    """自驱动游戏引擎。服务器仅负责消息转发。"""

    normalize_config = staticmethod(normalize_config)
    @staticmethod
    def providers():
        """Provider 清单（唯一来源为 protocol.PROVIDERS，返回深拷贝）。"""
        return [dict(p) for p in PROVIDERS]
    @staticmethod
    def server_info():
        registry = HeroRegistry()
        stats = SkillManager().registration_stats()
        return {
            "engine": "MainEngine-v2",
            "supported_modes": ["5人身份局"],
            "hero_count": registry.count(),
            "worldbook_hero_count": registry.count(),
            "generated_skill_count": stats["total_classes"],
            "runtime_skill_count": stats["active_classes"],
            "providers": [dict(p) for p in PROVIDERS],
        }
    @staticmethod
    def deck_list(project_root=None):
        manager = DeckManager(project_root or Path(__file__).resolve().parents[1])
        return {
            "active_deck": manager.get_active_deck_id(),
            "decks": manager.get_deck_list(),
        }
    @staticmethod
    def switch_deck(deck_id, project_root=None):
        manager = DeckManager(project_root or Path(__file__).resolve().parents[1])
        normalized = manager.normalize_deck_id(deck_id)
        switched = manager.switch_deck(normalized)
        return {
            "success": switched,
            "active_deck": manager.get_active_deck_id(),
            "deck": manager.get_deck_info(normalized) if switched else {},
            "decks": manager.get_deck_list(),
        }
    def __init__(self, game_config: Dict):
        if not isinstance(game_config, dict):
            raise TypeError("game_config必须是字典")

        self.game_config = game_config
        self.game_state = GameState()
        self.game_state.init_game(game_config)
        self.stats = GameStats(self.game_state.players)

        self.skill_manager = SkillManager(self)
        self.trigger_manager = self.skill_manager  # 兼容卡牌系统旧参数名
        self.phase_controller = PhaseController(self.game_state, self.skill_manager, engine=self)
        self.card_system = CardSystem(
            self.game_state, None, self.trigger_manager,
            ui_notifier=self._notify_card_ui,
            responder=self.request_response,
            engine=self,
        )
        self.rules = RulesEngine(self.game_state, self.skill_manager)
        self.ai_decision = AIDecision(self)
        self.identity_system = IdentitySystem()
        self.chat_engine = ChatEngine(self.ai_decision.gateway)

        self.handlers: Dict[str, Callable] = {}
        self._player_event = asyncio.Event()
        self._player_input = None
        # 场外响应专用通道：与出牌用的 _player_event 单槽位完全隔离，按 request_id 寻址。
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._request_seq = 0
        self.game_log: List[Dict] = []
        self.completed_turns = 0
        self.max_turns = int(game_config.get("max_turns", 300))
        self.human_action_timeout = int(game_config.get("human_action_timeout", 120))
        self.response_timeout = int(game_config.get("response_timeout", 30))
        # 离席看门狗：只累计「引擎在等真人、而真人没应答」的时间；AI回合期间恒不计时。
        self.idle_abort_seconds = float(game_config.get("idle_abort_seconds", 300))
        self.idle_check_interval = float(game_config.get("idle_check_interval", 15))
        self.time_source: Callable[[], float] = time.monotonic  # 测试可注入假时钟
        self._human_idle_since: Any = None
        self._trustee_active = False
        self._abort_reason: Any = None
        self._watchdog_task: Any = None
        self._game_end_emitted = False
        self._started_at: Any = None

        logger.info(f"\n{'=' * 60}")
        logger.info("  🎮 引擎v2初始化")
        logger.info(f"  模式: {game_config.get('mode', '5人身份局')}")
        logger.info(f"  玩家: {game_config.get('player_name', '玩家')}")
        logger.info(f"  AI数: {sum(1 for p in self.game_state.players if p.is_ai)}")
        logger.info(f"  牌堆: {self.game_state.deck_id} / {self.game_state.initial_deck_count}张")
        logger.info(f"{'=' * 60}\n")

    # ---------- 外部事件 ----------

    def on(self, event_type: str, handler: Callable):
        self.handlers[event_type] = handler

    async def emit(self, event_type: str, **data):
        handler = self.handlers.get(event_type)
        if handler:
            try:
                await handler(**data)
            except Exception as exc:
                logger.info(f"[事件异常] {event_type}: {exc}")

    async def log_event(self, message: str, **data):
        entry = {"message": message, **data}
        self.game_log.append(entry)
        await self.emit(ENGINE_EVENT.EVENT_NOTIFICATION, **entry)

    async def _notify_card_ui(self, **data):
        """卡牌UI统一通知（弃牌/出牌/技能转化共用）：等待浏览器确认动画完成后才继续结算。"""
        entry = {"event_kind": "card_to_discard", "await_ui": True, **data}
        self.game_log.append(entry)
        await self.emit(ENGINE_EVENT.CARD_ANIMATION, **entry)

    async def _execute_phase_with_ui(self, phase: Phase):
        """执行阶段，并为阶段产生的弃牌补发可解释的卡牌UI事件。"""
        player = self.game_state.current_player
        before_discard = len(self.game_state.discard_pile)
        before_hand = list(player.hand)
        skill_result = await self.skill_manager.before_phase(player, phase)
        if not skill_result.get("skip_default"):
            await self.phase_controller.execute_phase(phase)
        await self.skill_manager.after_phase(player, phase)
        if phase == Phase.DISCARD:
            new_cards = self.game_state.discard_pile[before_discard:]
            for offset, card in enumerate(new_cards, start=1):
                original_index = before_hand.index(card) if card in before_hand else None
                await self._notify_card_ui(
                    actor_id=player.id,
                    actor_name=player.name,
                    source_name=player.name,
                    card_name=card.name,
                    card_index=original_index,
                    system_text=f"[‘{player.name}’因手牌上限弃置‘{card.name}’]",
                    card=card_to_dict(card),
                    reason="hand_limit",
                    discard_count=before_discard + offset,
                    message=f"{player.name}因手牌上限弃置【{card.name}】",
                )

    # ---------- 状态序列化 ----------

    @staticmethod
    def _hero_name(player: Player) -> str:
        return (player.hero or {}).get("name", "")

    def serialize(self) -> Dict:
        gs = self.game_state
        players = []
        for p in gs.players:
            identity_visible = p.id == 0 or p.identity_revealed or gs.game_over
            players.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "hp": p.hp,
                    "max_hp": p.max_hp,
                    "hand_count": len(p.hand),
                    "alive": p.alive,
                    "hero_name": self._hero_name(p),
                    "hero": {
                        "id": (p.hero or {}).get("id", ""),
                        "name": self._hero_name(p),
                        "faction": (p.hero or {}).get("faction", ""),
                        "max_hp": (p.hero or {}).get("max_hp", p.max_hp),
                        "skills": self.skill_manager.public_player_skills(p),
                        "worldbook": (p.hero or {}).get("worldbook", {}),
                    },
                    "is_ai": p.is_ai,
                    "ai_config": {
                        "provider": p.ai_config.get("provider", "deepseek"),
                        "model": p.ai_config.get("model", "deepseek-chat"),
                        "api_url": p.ai_config.get("api_url", ""),
                        "temperature": p.ai_config.get("temperature", 0.8),
                        "thinking": bool(p.ai_config.get("thinking", False)),
                    } if p.is_ai else None,
                    "identity": p.identity if identity_visible else None,
                    "identity_revealed": identity_visible,
                    "equipment": {slot: card.name for slot, card in p.equipment.items()},
                    "stats": self.stats.row(p),
                }
            )
        return {
            "mode": gs.mode,
            "round": gs.round_number,
            "completed_turns": self.completed_turns,
            "phase": gs.current_phase.value if gs.current_phase else "none",
            "current_player_id": gs.current_player.id if gs.current_player else None,
            "current_name": gs.current_player.name if gs.current_player else "",
            "players": players,
            "deck_count": len(gs.deck),
            "discard_count": len(gs.discard_pile),
            "game_over": gs.game_over,
            "winner": gs.winner,
        }

    def get_player_hand(self, player: Player) -> List[Dict]:
        return [
            {**card_to_dict(c), "index": i, "target_rule": c.target_rule or {}}
            for i, c in enumerate(player.hand)
        ]

    # ---------- 主流程 ----------

    async def run(self):
        logger.info("\n🎮 游戏开始！\n")
        self._started_at = self.time_source()
        assigned = self.identity_system.assign_identities(
            self.game_state.players,
            self.game_state.mode,
            self.game_config.get("identity_card") or {},
        )
        if not assigned:
            raise ValueError(f"当前引擎暂不支持该模式或人数不匹配: {self.game_state.mode}/{len(self.game_state.players)}人")

        lord = assigned["lord"]
        lord.max_hp += 1
        lord.hp += 1
        self.game_state.current_player_index = self.game_state.players.index(lord)
        self.game_state.current_player = lord
        self.game_state.round_anchor_index = self.game_state.current_player_index

        for p in self.game_state.players:
            logger.info(f"  {p.name}: {p.identity} {'(公开)' if p.identity_revealed else '(隐藏)'}")

        await self.emit(ENGINE_EVENT.STATE_CHANGED, state=self.serialize())

        self._watchdog_task = asyncio.create_task(self._idle_watchdog())
        try:
            while not self.is_game_over():
                if self.completed_turns >= self.max_turns:
                    self.game_state.game_over = True
                    self.game_state.winner = "draw"
                    await self.log_event(f"达到最大回合数{self.max_turns}，对局判和")
                    break

                player = self.game_state.current_player
                if not player.alive:
                    self.game_state.next_turn()
                    continue

                await self.skill_manager.on_turn_start(player)
                if player.is_ai:
                    await self._ai_turn(player)
                else:
                    await self._human_turn(player)

                if self.game_state.game_over:
                    break

                self.completed_turns += 1
                victory = self.identity_system.check_victory(self.game_state.players)
                if victory.get("game_over"):
                    self.game_state.game_over = True
                    self.game_state.winner = victory.get("winner")
                    await self.log_event(victory.get("message", "游戏结束"), important=True)
                    break

                if getattr(player, "flags", {}).pop("extra_turn", False):
                    self.game_state.current_player = player
                    self.game_state.current_player_index = self.game_state.players.index(player)
                    self.game_state.current_phase = Phase.PREPARE
                else:
                    self.game_state.next_turn()
                await asyncio.sleep(float(self.game_config.get("turn_delay", 0.05)))
        finally:
            if self._watchdog_task is not None:
                self._watchdog_task.cancel()
                self._watchdog_task = None

        await self._emit_game_end_once()
        logger.info(f"\n🎊 游戏结束！胜者: {self.game_state.winner}")
        return self.game_state.winner

    # ---------- 玩家回合 ----------

    async def _ai_turn(self, player: Player):
        logger.info(f"\n{'=' * 60}\n  [AI回合] {player.name}\n{'=' * 60}")
        await self.emit(ENGINE_EVENT.AI_ACTION, player_name=player.name, action="turn_start")
        await self._run_phases(player)

        if random.random() < 0.3:
            msg = await self.chat_engine.trigger_event_chat(
                "turn_start", player, {"round": self.game_state.round_number}
            )
            if msg:
                await self.emit(ENGINE_EVENT.CHAT, from_=player.name, message=msg)
        await self.emit(ENGINE_EVENT.STATE_CHANGED, state=self.serialize())

    async def _human_turn(self, player: Player):
        logger.info(f"\n{'=' * 60}\n  [人类回合] {player.name}\n{'=' * 60}")
        await self.emit(ENGINE_EVENT.STATE_CHANGED, state=self.serialize())

        for phase in [Phase.PREPARE, Phase.JUDGE, Phase.DRAW]:
            self.game_state.current_phase = phase
            await self._execute_phase_with_ui(phase)
            await self.emit(ENGINE_EVENT.STATE_CHANGED, state=self.serialize())

        self.game_state.current_phase = Phase.PLAY
        player.sha_count = 0
        await self.emit(ENGINE_EVENT.STATE_CHANGED, state=self.serialize())

        while player.alive and not self.game_state.game_over:
            actions = self.get_available_actions(player)
            # 必须先创建等待器再广播，避免WebSocket客户端立即响应造成丢操作。
            self._player_event = asyncio.Event()
            self._player_input = None
            # 出牌阶段引擎同样在等真人，纳入离席计时。
            self._mark_waiting_for_human()
            await self.emit(
                ENGINE_EVENT.YOUR_TURN,
                player_name=player.name,
                hand=self.get_player_hand(player),
                actions=[dict(action) for action in actions],
            )
            data = await self._wait_player_input()
            if self.game_state.game_over:
                break
            action = data["action"]
            target_ids = data["target_ids"]
            if action.get("type") == "end_phase":
                break

            ok = await self.execute_action(player, action, target_ids)
            await self.emit(ENGINE_EVENT.ACTION_RESULT, success=ok)
            await self.emit(ENGINE_EVENT.STATE_CHANGED, state=self.serialize())

        if self.game_state.game_over:
            return

        for phase in [Phase.DISCARD, Phase.END]:
            self.game_state.current_phase = phase
            await self._execute_phase_with_ui(phase)
            await self.emit(ENGINE_EVENT.STATE_CHANGED, state=self.serialize())

    async def _run_phases(self, player: Player):
        for phase in Phase:
            if self.game_state.game_over:
                break
            self.game_state.current_phase = phase
            logger.info(f"\n[{phase.value}阶段]")
            if phase == Phase.PLAY:
                player.sha_count = 0
                await self._auto_play_phase(player)
            else:
                await self._execute_phase_with_ui(phase)
            if not player.alive:
                break
            await asyncio.sleep(float(self.game_config.get("phase_delay", 0.01)))

    async def _auto_play_phase(self, player: Player):
        logger.info(f"  {player.name}的出牌阶段")
        for _ in range(20):
            if self.game_state.game_over:
                break
            actions = self.get_available_actions(player)
            if len(actions) <= 1:
                break

            await self.emit(ENGINE_EVENT.AI_ACTION, player_name=player.name, action="thinking_start")
            decision = await self.ai_decision.make_decision(player, actions)
            await self.emit(
                ENGINE_EVENT.AI_ACTION, player_name=player.name, action="thinking_end",
                reasoning=decision.get("reasoning", "")
            )
            action = decision.get("action") or {"type": "end_phase"}
            target_ids = decision.get("target_ids", [])

            if decision.get("chat"):
                await self.emit(ENGINE_EVENT.CHAT, from_=player.name, message=decision["chat"])
            if action.get("type") == "end_phase":
                break

            if action.get("type") == "play_card":
                index = action.get("card_index")
                if isinstance(index, int) and 0 <= index < len(player.hand):
                    await self.emit(
                        ENGINE_EVENT.AI_ACTION,
                        player_name=player.name,
                        action="use_card",
                        card_name=player.hand[index].name,
                    )

            ok = await self.execute_action(player, action, target_ids)
            self._record_ai_outcome(player, action, target_ids, ok)
            if not ok:
                logger.info("  ⚠️ AI操作被引擎拒绝，结束本次出牌阶段")
                break
            await self.emit(ENGINE_EVENT.STATE_CHANGED, state=self.serialize())

    def _record_ai_outcome(self, player: Player, action: Dict, target_ids: List, ok: bool):
        """把引擎的实际执行结果回灌进该AI的会话窗口，让它记得自己刚干了什么。"""
        recorder = getattr(self.ai_decision, "record_outcome", None)
        if recorder is None:
            return
        names = [p.name for p in self.game_state.players if p.id in (target_ids or [])]
        target_text = f"，目标：{'、'.join(names)}" if names else ""
        verdict = "已生效" if ok else "被引擎判定为非法，未生效"
        recorder(player, f"【引擎执行结果】你的操作 {action.get('type')}{target_text} {verdict}。")

    # ---------- 玩家输入 ----------

    async def _wait_player_input(self) -> Dict:
        try:
            await asyncio.wait_for(self._player_event.wait(), timeout=self.human_action_timeout)
        except asyncio.TimeoutError:
            return {"action": {"type": "end_phase"}, "target_ids": []}
        return self._player_input or {"action": {"type": "end_phase"}, "target_ids": []}

    def submit_action(self, action: Dict, target_ids: List[int]):
        if not isinstance(action, dict):
            return
        if action.get("type") == "response":
            option_indices = action.get("option_indices")
            selection = option_indices if option_indices is not None else action.get("option_index")
            self.submit_response(action.get("request_id"), selection)
            return
        self._note_human_input()
        self._player_input = {"action": action, "target_ids": target_ids or action.get("target_ids", []) or []}
        if self._player_event and not self._player_event.is_set():
            self._player_event.set()

    # ---------- 场外响应通道 ----------

    @staticmethod
    def make_pass_option() -> Dict:
        """「不响应」候选。实现在 card_system，这里只做转发，避免两处定义。"""
        return make_pass_option()

    @staticmethod
    def _option_label(option: Dict) -> str:
        return option_label(option)

    def _serialize_option(self, option: Dict, index: int) -> Dict:
        card = option.get("card")
        owner = option.get("owner")
        return {
            "index": index,
            "label": self._option_label(option),
            "card": None if card is None else card_to_dict(card),
            "card_index": option.get("card_index"),
            "owner_id": getattr(owner, "id", None),
            "owner_name": getattr(owner, "name", None),
            "as_name": option.get("as_name"),
            "skill_name": option.get("skill_name"),
            "is_pass": card is None,
        }

    @staticmethod
    def _serialize_response_context(context: Dict) -> Dict:
        """把 context 里的 Player/Card 对象换成可 JSON 化的标识，绝不把对象丢给前端。"""
        out: Dict[str, Any] = {}
        for key, value in (context or {}).items():
            if hasattr(value, "id") and hasattr(value, "name") and hasattr(value, "hp"):
                out[key] = {"id": value.id, "name": value.name}
            elif hasattr(value, "id") and hasattr(value, "name") and hasattr(value, "suit"):
                out[key] = {"id": value.id, "name": value.name, "suit": value.suit, "rank": value.rank}
            elif isinstance(value, (str, int, float, bool)) or value is None:
                out[key] = value
        return out

    def _next_request_id(self) -> str:
        self._request_seq += 1
        return f"resp{self._request_seq}"

    def _resolve_option(self, player: Player, request: Dict, index) -> Dict:
        """引擎复核：索引合法 → 有牌 → 牌仍在 owner 手上 → owner 存活 → 名称匹配。任一不满足即视为不响应。"""
        options = request.get("options") or []
        if not isinstance(index, int) or not 0 <= index < len(options):
            return {"bool": False}
        option = options[index]
        card = option.get("card")
        if card is None:
            return {"bool": False}
        owner = option.get("owner") or player
        if not getattr(owner, "alive", True):
            logger.info(f"  ❌ 响应复核失败：{getattr(owner, 'name', '?')} 已阵亡")
            return {"bool": False}
        if card not in owner.hand:
            logger.info(f"  ❌ 响应复核失败：【{card.name}】已不在 {owner.name} 手上")
            return {"bool": False}
        as_name = option.get("as_name") or card.name
        requested = request.get("requested_name")
        if requested and as_name != requested:
            logger.info(f"  ❌ 响应复核失败：需要【{requested}】，候选给的是【{as_name}】")
            return {"bool": False}
        return {
            "bool": True,
            "card": card,
            "owner": owner,
            "as_name": as_name,
            "skill_name": option.get("skill_name"),
        }

    async def _ask_index(self, player: Player, request: Dict, resolver) -> Any:
        """共用询问机制：人/AI分派 + 超时托管 + 回灌。resolver 决定如何验证原始索引。"""
        request_id = self._next_request_id()
        if player.is_ai:
            index = await self._ai_choose_option(player, request)
            result = resolver(player, request, index)
            self._record_response_outcome(player, request, result)
            return result
        index = await self._human_choose_option(player, request, request_id)
        return resolver(player, request, index)

    async def request_response(self, player: Player, request: Dict) -> Dict:
        """场外响应统一入口。返回值契约与旧 choose_to_respond 一致。"""
        options = list(request.get("options") or [])
        if not any(option.get("card") is not None for option in options):
            return {"bool": False}
        return await self._ask_index(player, request, self._resolve_option)

    def _record_response_outcome(self, player: Player, request: Dict, resolved: Dict):
        """AI 的响应结果同样回灌会话窗口，包括被引擎复核驳回的情况。"""
        recorder = getattr(self.ai_decision, "record_outcome", None)
        if recorder is None:
            return
        if resolved.get("bool"):
            text = f"你打出了【{resolved.get('as_name')}】响应「{request.get('prompt', '')}」。"
        else:
            text = f"你没有响应「{request.get('prompt', '')}」（未选择或被引擎复核驳回）。"
        recorder(player, f"【引擎执行结果】{text}")

    # ---------- 四交互原语 ----------

    @staticmethod
    def _normalize_indices(raw) -> List[int]:
        """int/列表统一成去重后的索引列表；布尔与非整数一律丢弃。"""
        if isinstance(raw, bool):
            return []
        if isinstance(raw, int):
            values = [raw]
        elif isinstance(raw, (list, tuple)):
            values = list(raw)
        else:
            return []
        result: List[int] = []
        seen = set()
        for value in values:
            if isinstance(value, bool) or not isinstance(value, int) or value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def _card_in_zone(self, card, owner, zone: str) -> bool:
        """复核单张牌是否仍在声明的牌区内（兼容装备字典与判定区）。"""
        if owner is None or card is None:
            return False
        if zone == "hand":
            return card in owner.hand
        if zone == "equipment":
            return card in owner.equipment.values()
        if zone == "judge":
            return card in owner.judge_area
        if zone == "discard":
            return card in self.game_state.discard_pile
        if zone == "shown":
            # 临时展示池（如五谷丰登）没有持久牌区：调用方在结算前再核对一次。
            return True
        return False

    def _validate_choice_cards(self, request: Dict, indices: List[int]) -> List:
        cand_cards = list(request.get("candidate_cards") or [])
        places = request.get("candidate_places") or []
        default_owner = request.get("card_owner")
        default_zone = request.get("zone", "hand")
        selected = []
        for index in indices:
            if not 0 <= index < len(cand_cards):
                continue
            card = cand_cards[index]
            if places and index < len(places):
                owner, zone = places[index]
            else:
                owner, zone = default_owner, default_zone
            if not self._card_in_zone(card, owner, zone):
                continue
            if card in selected:
                continue
            selected.append(card)
        return selected

    def _validate_choice_players(self, request: Dict, indices: List[int]) -> List:
        all_players = request.get("context", {}).get("all_players") or []
        players_map = {p.id: p for p in all_players}
        cand_ids = list(request.get("candidate_ids") or [])
        selected = []
        for index in indices:
            if not 0 <= index < len(cand_ids):
                continue
            target = players_map.get(cand_ids[index])
            if target is None or not target.alive or target in selected:
                continue
            selected.append(target)
        return selected

    @staticmethod
    def _choice_limits(request: Dict):
        min_n = max(0, int(request.get("min_n", 1)))
        max_n = max(min_n, int(request.get("max_n", 1)))
        return min_n, max_n

    @staticmethod
    def _empty_choice_result(kind: str) -> Dict:
        if kind == "choose_players":
            return {"bool": False, "players": []}
        if kind == "choose_cards":
            return {"bool": False, "cards": []}
        if kind == "choose_option":
            return {"bool": False, "choice": None}
        return {"bool": False, "confirmed": False}

    @property
    def game_aborted(self) -> bool:
        """对局已收摊（离席看门狗或玩家主动结束）：新效果不得再结算。"""
        return bool(self._abort_reason) or bool(self.game_state.game_over)

    def _resolve_choice(self, player: Player, request: Dict, raw, *, _allow_rule_fallback=True) -> Dict:
        """引擎复核：四原语共用的验证器。raw 是 int 或 List[int]，任何非法选择都不落地。"""
        kind = request.get("kind", "confirm")
        indices = self._normalize_indices(raw)
        if self.game_aborted:
            return self._empty_choice_result(kind)

        if kind == "confirm":
            if not indices or indices[0] not in (0, 1):
                val = bool(request.get("default", False))
                return {"bool": val, "confirmed": val}
            confirmed = indices[0] == 0
            return {"bool": confirmed, "confirmed": confirmed}

        if kind == "choose_option":
            choices = request.get("choices") or []
            if not choices:
                logger.warning("  ⚠️ choose_option 无候选，返回空选择")
                return {"bool": False, "choice": None}
            if not indices or not (0 <= indices[0] < len(choices)):
                if request.get("cancelable", True):
                    return {"bool": False, "choice": None}
                logger.warning("  ⚠️ choose_option复核失败，使用兜底")
                return {"bool": bool(choices), "choice": choices[0] if choices else None}
            return {"bool": True, "choice": choices[indices[0]]}

        if kind not in ("choose_players", "choose_cards"):
            return {"bool": False}

        min_n, max_n = self._choice_limits(request)
        if kind == "choose_players":
            selected = self._validate_choice_players(request, indices)
        else:
            selected = self._validate_choice_cards(request, indices)
        if min_n <= len(selected) <= max_n:
            key = "players" if kind == "choose_players" else "cards"
            return {"bool": True, key: selected}
        return self._choice_rejected(player, request, kind, selected, _allow_rule_fallback)

    def _choice_rejected(self, player: Player, request: Dict, kind: str, selected: List, allow_rule_fallback: bool) -> Dict:
        """数量或内容不合法：可取消则空手而归，不可取消则规则兜底 + 确定性兜底。"""
        key = "players" if kind == "choose_players" else "cards"
        if request.get("cancelable", True):
            return {"bool": False, key: []}
        logger.warning(f"  ⚠️ {kind}复核失败（有效候选 {len(selected)}），使用兜底")
        if allow_rule_fallback:
            try:
                fallback_raw = self.ai_decision.simple_choice_decision(player, request)
            except Exception as exc:
                logger.info(f"  ⚠️ 兜底决策失败: {type(exc).__name__}: {exc}")
                fallback_raw = []
            result = self._resolve_choice(player, request, fallback_raw, _allow_rule_fallback=False)
            if result.get("bool"):
                return result
        deterministic = self._deterministic_choice(request, kind)
        min_n, _ = self._choice_limits(request)
        if len(deterministic) < min_n:
            # 兜底也无法凑足最小选择量：视为无法完成，不产出部分选择。
            return {"bool": False, key: []}
        return {"bool": True, key: deterministic}

    def _deterministic_choice(self, request: Dict, kind: str) -> List:
        """最终兜底：按候选顺序取仍然有效的项，绝不放行非法内容。"""
        _, max_n = self._choice_limits(request)
        if kind == "choose_players":
            indices = list(range(len(request.get("candidate_ids") or [])))
            return self._validate_choice_players(request, indices)[:max_n]
        indices = list(range(len(request.get("candidate_cards") or [])))
        return self._validate_choice_cards(request, indices)[:max_n]

    def _serialize_choice_option(self, option: Dict, index: int) -> Dict:
        card = option.get("card")
        hidden = bool(option.get("hidden"))
        return {
            "index": index,
            "label": option.get("label", str(index)),
            "card": None if (card is None or hidden) else card_to_dict(card),
            "hidden": hidden,
            "player_id": option.get("player_id"),
            "player_name": option.get("player_name"),
            "key": option.get("key"),
            "detail": option.get("detail"),
            "is_pass": False,
        }

    @staticmethod
    def _mask_hidden_candidates(request: Dict) -> Dict:
        """决策脱敏视图：隐藏候选（他人手牌）不把真实牌面交给 AI/托管。

        引擎复核仍使用原 request；只有决策函数拿到脱敏副本。
        """
        hidden = set(request.get("hidden_indices") or [])
        if not hidden or not request.get("candidate_cards"):
            return request
        masked = dict(request)
        cards = list(request.get("candidate_cards") or [])
        masked["candidate_cards"] = [
            None if index in hidden else card for index, card in enumerate(cards)
        ]
        return masked

    async def _ai_choose_choice(self, player: Player, request: Dict):
        """AI dispatch for four new primitives. Returns List[int]."""
        request = self._mask_hidden_candidates(request)
        handler = getattr(self.ai_decision, "make_choice_decision", None)
        if handler is not None:
            try:
                return await handler(player, request)
            except Exception as exc:
                logger.info(f"  ⚠️ 选择AI失败，切换规则AI: {type(exc).__name__}: {exc}")
        return self.ai_decision.simple_choice_decision(player, request)

    async def _trustee_choose_choice(self, player: Player, request: Dict):
        if self._abort_reason:
            return []
        self._trustee_active = True
        try:
            indices = self.ai_decision.simple_choice_decision(
                player, self._mask_hidden_candidates(request)
            )
        except Exception as exc:
            logger.info(f"  ⚠️ 托管选择决策失败: {type(exc).__name__}: {exc}")
            indices = []
        await self.log_event("[托管] 已代为选择", trustee=True, player_id=player.id)
        return indices

    async def _human_choose_choice(self, player: Player, request: Dict, request_id: str):
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending_requests[request_id] = future
        self._mark_waiting_for_human()
        selection_block = {
            "mode": "multi" if request.get("max_n", 1) > 1 else "single",
            "min": request.get("min_n", 1),
            "max": request.get("max_n", 1),
            "zone": request.get("zone"),
            "skill_name": request.get("skill_name"),
            "cancelable": request.get("cancelable", True),
        }
        try:
            await self.emit(
                ENGINE_EVENT.REQUIRE_RESPONSE,
                request_id=request_id,
                player_id=player.id,
                kind=request.get("kind", "confirm"),
                prompt=request.get("prompt", ""),
                timeout=self.response_timeout,
                options=[self._serialize_choice_option(o, i) for i, o in enumerate(request.get("options") or [])],
                context=self._serialize_response_context(request.get("context") or {}),
                selection=selection_block,
            )
            return await asyncio.wait_for(future, timeout=self.response_timeout)
        except asyncio.TimeoutError:
            logger.info(f"  ⏱️ 选择请求 {request_id} 超时，交规则托管")
            return await self._trustee_choose_choice(player, request)
        finally:
            self._pending_requests.pop(request_id, None)

    async def request_choice(self, player: Player, request: Dict) -> Dict:
        """四交互原语的统一入口。"""
        request_id = self._next_request_id()
        if player.is_ai:
            raw = await self._ai_choose_choice(player, request)
            return self._resolve_choice(player, request, raw)
        raw = await self._human_choose_choice(player, request, request_id)
        return self._resolve_choice(player, request, raw)

    async def ask_confirm(self, player: Player, prompt: str, *,
                          skill_name=None, context=None, default=False) -> bool:
        request = {
            "kind": "confirm",
            "prompt": prompt,
            "skill_name": skill_name,
            "context": context or {},
            "default": default,
            "options": [{"label": "是", "key": "yes"}, {"label": "否", "key": "no"}],
            "min_n": 1, "max_n": 1, "cancelable": False,
        }
        result = await self.request_choice(player, request)
        return result.get("confirmed", default)

    async def ask_choose_players(self, player: Player, prompt: str, candidates, *,
                                  min_n=1, max_n=1, skill_name=None,
                                  context=None, cancelable=True):
        cand_list = list(candidates)
        if not cand_list or len(cand_list) < max(0, int(min_n)):
            # 候选不足以完成最小选择量：不发无效询问，也不产生任何选择。
            return []
        ctx = dict(context or {})
        ctx["all_players"] = list(self.game_state.players)
        request = {
            "kind": "choose_players",
            "prompt": prompt,
            "skill_name": skill_name,
            "context": ctx,
            "min_n": min_n,
            "max_n": max_n,
            "cancelable": cancelable,
            "candidate_ids": [p.id for p in cand_list],
            "options": [{"label": p.name, "player_id": p.id, "player_name": p.name} for p in cand_list],
        }
        result = await self.request_choice(player, request)
        return result.get("players", [])

    async def ask_choose_cards(self, player: Player, prompt: str, candidates, *,
                                min_n=1, max_n=1, zone="hand",
                                skill_name=None, context=None, cancelable=True,
                                hidden_indices=None, places=None):
        """从候选牌里选 min_n~max_n 张。

        hidden_indices：对选择者隐藏身份的候选下标（如他人手牌），只影响序列化文案。
        places：与候选一一对应的 (owner, zone) 位置表，用于跨牌区选择时的引擎复核；
                缺省时全部按 card_owner + zone 复核。
        """
        cand_list = list(candidates)
        if not cand_list or len(cand_list) < max(0, int(min_n)):
            # 候选不足以完成最小选择量：不发无效询问，也不产生任何选择。
            return []
        hidden = set(hidden_indices or [])
        options = []
        for i, c in enumerate(cand_list):
            if i in hidden:
                options.append({"label": "手牌", "card": c, "hidden": True, "key": str(i)})
            else:
                options.append({"label": option_label({"card": c}), "card": c, "key": str(i)})
        request = {
            "kind": "choose_cards",
            "prompt": prompt,
            "skill_name": skill_name,
            "context": dict(context or {}),
            "min_n": min_n,
            "max_n": max_n,
            "zone": zone,
            "cancelable": cancelable,
            "candidate_cards": cand_list,
            "candidate_places": list(places) if places is not None else None,
            "hidden_indices": sorted(hidden),
            "card_owner": player,
            "options": options,
        }
        result = await self.request_choice(player, request)
        return result.get("cards", [])

    async def ask_choose_option(self, player: Player, prompt: str, choices, *,
                                 skill_name=None, context=None) -> Any:
        choice_list = list(choices)
        if not choice_list:
            # 无候选不发询问：否则会空等一个无法回答的超时。
            return None
        request = {
            "kind": "choose_option",
            "prompt": prompt,
            "skill_name": skill_name,
            "context": dict(context or {}),
            "choices": choice_list,
            "min_n": 1, "max_n": 1, "cancelable": False,
            "options": [{"label": c.get("label", c.get("key", str(i))), "key": c.get("key")}
                        for i, c in enumerate(choice_list)],
        }
        result = await self.request_choice(player, request)
        return result.get("choice")

    # ---------- 旧响应通道（原有，下面保持不变） ----------

    async def _ai_choose_option(self, player: Player, request: Dict):
        handler = getattr(self.ai_decision, "make_response_decision", None)
        if handler is not None:
            try:
                return await handler(player, request)
            except Exception as exc:
                logger.info(f"  ⚠️ 响应AI失败，切换规则AI: {type(exc).__name__}: {exc}")
        return self.ai_decision.simple_response_decision(player, request)

    async def _human_choose_option(self, player: Player, request: Dict, request_id: str):
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending_requests[request_id] = future
        self._mark_waiting_for_human()
        try:
            await self.emit(
                ENGINE_EVENT.REQUIRE_RESPONSE,
                request_id=request_id,
                player_id=player.id,
                kind=request.get("kind", "respond"),
                prompt=request.get("prompt", ""),
                requested_name=request.get("requested_name"),
                timeout=self.response_timeout,
                options=[self._serialize_option(o, i) for i, o in enumerate(request.get("options") or [])],
                context=self._serialize_response_context(request.get("context") or {}),
            )
            return await asyncio.wait_for(future, timeout=self.response_timeout)
        except asyncio.TimeoutError:
            logger.info(f"  ⏱️ 响应请求 {request_id} 超时，交规则托管")
            return await self._trustee_choose(player, request)
        finally:
            self._pending_requests.pop(request_id, None)

    def submit_response(self, request_id, selection) -> bool:
        """前端应答入口。接受 int（单选）或 List[int]（多选）。"""
        future = self._pending_requests.get(request_id)
        if future is None or future.done():
            return False
        if isinstance(selection, list):
            try:
                value = [int(x) for x in selection]
            except (TypeError, ValueError):
                return False
        else:
            try:
                value = int(selection)
            except (TypeError, ValueError):
                return False
        self._note_human_input()
        future.set_result(value)
        return True

    # ---------- 托管兜底与离席看门狗 ----------

    def _mark_waiting_for_human(self):
        """引擎开始等真人。已经在计时就不重新打点，保证是累计而不是每次重置。"""
        if self._human_idle_since is None:
            self._human_idle_since = self.time_source()

    def _note_human_input(self):
        """收到任何真人输入即清零，并解除托管状态。"""
        self._human_idle_since = None
        self._trustee_active = False

    def idle_seconds(self) -> float:
        if self._human_idle_since is None:
            return 0.0
        return float(self.time_source() - self._human_idle_since)

    async def _trustee_choose(self, player: Player, request: Dict):
        """单次请求超时后的规则脚本托管。不调用任何 API。"""
        if self._abort_reason:
            return None
        self._trustee_active = True
        try:
            index = self.ai_decision.simple_response_decision(player, request)
        except Exception as exc:
            logger.info(f"  ⚠️ 托管决策失败: {type(exc).__name__}: {exc}")
            index = None
        options = request.get("options") or []
        label = "不响应"
        if isinstance(index, int) and 0 <= index < len(options):
            label = self._option_label(options[index])
        await self.log_event(f"[托管] 已代为决策：{label}", trustee=True, player_id=player.id)
        return index

    async def _check_idle_timeout(self) -> bool:
        """看门狗单次检查。返回 True 表示已因离席收摊。"""
        if self._abort_reason or self.game_state.game_over:
            return False
        if self._human_idle_since is None:
            return False
        if self.idle_seconds() < self.idle_abort_seconds:
            return False
        await self._abort_for_idle()
        return True

    async def _abort_for_idle(self):
        """离席超时：停托管代打 + 结束当前对局。服务器进程不受影响。"""
        minutes = self.idle_abort_seconds / 60
        self._abort_reason = "idle_timeout"
        self._trustee_active = False
        self.game_state.game_over = True
        self.game_state.winner = "aborted"
        self.game_state.end_message = (
            f"真人玩家离席超过{minutes:.0f}分钟，本局自动结束。服务器仍在运行，刷新页面即可重开。"
        )
        await self.log_event(self.game_state.end_message, important=True, abort_reason="idle_timeout")

        # 唤醒所有挂起的响应请求，否则等待中的协程会永久挂住。
        for future in list(self._pending_requests.values()):
            if not future.done():
                future.set_result(None)
        # 解除出牌阶段的等待（不走 submit_action，避免被当成真人输入而清零计时）。
        self._player_input = {"action": {"type": "end_phase"}, "target_ids": []}
        if self._player_event and not self._player_event.is_set():
            self._player_event.set()

    async def _idle_watchdog(self):
        try:
            while not self.game_state.game_over:
                await asyncio.sleep(self.idle_check_interval)
                if await self._check_idle_timeout():
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.info(f"  ⚠️ 看门狗异常: {type(exc).__name__}: {exc}")

    # ---------- 合法操作 ----------

    def get_available_actions(self, player: Player) -> List[Dict]:
        actions: List[Dict] = []
        if self.game_state.current_phase != Phase.PLAY or player != self.game_state.current_player or not player.alive:
            return [{"type": "end_phase"}]

        for i, card in enumerate(player.hand):
            spec = CARD_TABLE.get(card.name)
            # 只能响应/未实现的牌不作为合法操作暴露（闪、无懈、未实现锦囊、装备）。
            if spec and spec.usage in ("response", "unimplemented"):
                continue

            # 需显式选目标：target_rule.type 为 other/any（桃 self_or_dying 与酒/无中生有 self 无外部目标）。
            needs_target = bool(spec) and spec.target_rule.get("type") not in NO_EXTERNAL_TARGET
            if needs_target:
                allow_self = spec.target_rule.get("type") == "any"
                if spec.target_rule.get("min", 1) == 2:
                    valid_pairs = []
                    for first in self.game_state.players:
                        for second in self.game_state.players:
                            if first is second:
                                continue
                            if not first.alive or not second.alive:
                                continue
                            can_play, _ = self.rules.can_play_card(player, card, [first, second])
                            if can_play:
                                valid_pairs.append([first.id, second.id])
                    if valid_pairs:
                        actions.append(
                            {
                                "type": "play_card",
                                "card_index": i,
                                "card": card_to_dict(card, include_id=False),
                                "requires_target": True,
                                "target_count": 2,
                                "valid_target_pairs": valid_pairs,
                                "valid_targets": sorted({pid for pair in valid_pairs for pid in pair}),
                            }
                        )
                    continue
                valid = []
                for target in self.game_state.players:
                    if not target.alive or (target == player and not allow_self):
                        continue
                    can_play, _ = self.rules.can_play_card(player, card, [target])
                    if can_play:
                        valid.append(target.id)
                if valid:
                    actions.append(
                        {
                            "type": "play_card",
                            "card_index": i,
                            "card": card_to_dict(card, include_id=False),
                            "requires_target": True,
                            "valid_targets": valid,
                        }
                    )
                continue

            can_play, _ = self.rules.can_play_card(player, card, [])
            if can_play:
                actions.append(
                    {
                        "type": "play_card",
                        "card_index": i,
                        "card": card_to_dict(card, include_id=False),
                        "requires_target": False,
                        "valid_targets": [],
                    }
                )

        # 只有运行状态为active且满足当前条件的技能才作为合法操作暴露。
        actions.extend(self.skill_manager.get_actions(player))
        actions.append({"type": "end_phase"})
        return actions

    # ---------- 执行操作 ----------

    async def execute_action(self, player: Player, action: Dict, target_ids: List = None) -> bool:
        if player != self.game_state.current_player or not player.alive:
            return False
        action_type = action.get("type")
        try:
            if action_type == "play_card":
                card_index = action.get("card_index")
                if not isinstance(card_index, int) or not 0 <= card_index < len(player.hand):
                    return False
                card = player.hand[card_index]
                target_ids = target_ids or []
                players_by_id = {p.id: p for p in self.game_state.players}
                targets = [players_by_id[pid] for pid in target_ids if pid in players_by_id]
                can_play, reason = self.rules.can_play_card(player, card, targets)
                if not can_play:
                    logger.info(f"  ❌ 不能出牌: {reason}")
                    return False

                # 先广播“使用牌”，使客户端按正确顺序展示：使用牌 → 响应牌 → 弃牌堆。
                await self._notify_card_ui(
                    message=f"{player.name}使用【{card.name}】"
                    + (f"，目标：{'、'.join(t.name for t in targets)}" if targets else ""),
                    system_text=f"[‘{player.name}’{card.name}！]",
                    actor_id=player.id,
                    actor_name=player.name,
                    source_name=player.name,
                    target_name="、".join(t.name for t in targets),
                    card_name=card.name,
                    card_index=card_index,
                    card=card_to_dict(card),
                    reason="use",
                    discard_count=len(self.game_state.discard_pile) + 1,
                )
                player.hand.remove(card)
                self.game_state.discard_pile.append(card)
                success = await self.card_system.use_card(player, card, targets)
                if not success:
                    if card in self.game_state.discard_pile:
                        self.game_state.discard_pile.remove(card)
                    player.hand.insert(min(card_index, len(player.hand)), card)
                if success:
                    record_stat(self, player, "cards_played")
                    await self.skill_manager.on_cards_lost(player, [card], "use_card")
                    await self.skill_manager.on_card_discarded(player, card, "use_card")
                await self.skill_manager.after_card_used(player, card, targets, success)
                return success

            if action_type == "use_skill":
                target_ids = target_ids or []
                legal = next((candidate for candidate in self.get_available_actions(player)
                              if candidate.get("type") == "use_skill"
                              and candidate.get("skill_name") == action.get("skill_name")
                              and candidate.get("variant") == action.get("variant")
                              and candidate.get("card_indices", []) == action.get("card_indices", [])
                              and candidate.get("fixed_target_ids", []) == action.get("fixed_target_ids", [])), None)
                if not legal:
                    logger.info("  ❌ 技能不在当前合法操作列表")
                    return False
                valid_targets = legal.get("valid_targets", [])
                if legal.get("requires_target"):
                    if len(target_ids) != 1 or target_ids[0] not in valid_targets:
                        logger.info("  ❌ 技能目标非法")
                        return False
                else:
                    target_ids = []
                targets = [p for p in self.game_state.players if p.id in target_ids]
                return await self.skill_manager.execute(player, legal, targets)

            if action_type == "end_phase":
                return True
            return False
        except Exception as exc:
            logger.info(f"  ❌ 执行出错: {exc}")
            import traceback

            traceback.print_exc()
            return False

    async def _emit_game_end_once(self):
        if self._game_end_emitted:
            return False
        self._game_end_emitted = True
        state = self.serialize()
        message = getattr(self.game_state, "end_message", None) or (
            "平局" if self.game_state.winner == "draw"
            else f"{self.game_state.winner}方获胜！"
        )
        duration = 0
        if self._started_at is not None:
            duration = int(max(0.0, self.time_source() - self._started_at))
        await self.emit(ENGINE_EVENT.STATE_CHANGED, state=state)
        await self.emit(
            ENGINE_EVENT.GAME_END,
            winner=self.game_state.winner,
            message=message,
            state=state,
            stats=self.stats.snapshot(),
            mvp=self.stats.mvp(self.game_state.players),
            duration=duration,
        )
        return True
    async def request_end_game(self, reason: str = "玩家主动结束游戏"):
        self.game_state.game_over = True
        self.game_state.winner = "aborted"
        self.game_state.end_message = reason
        # 与离席看门狗一致：挂起的交互请求不得在收摊后继续落地效果。
        self._abort_reason = self._abort_reason or "player_end_game"
        for future in list(self._pending_requests.values()):
            if not future.done():
                future.set_result(None)
        self._player_input = {"action": {"type": "end_phase"}, "target_ids": []}
        if self._player_event and not self._player_event.is_set():
            self._player_event.set()
        await self._emit_game_end_once()

    def update_ai_config(self, player_id: int, config: Dict) -> Dict:
        player = next((p for p in self.game_state.players if p.id == player_id), None)
        if not player or not player.is_ai:
            raise ValueError("目标不是可配置的AI角色")
        allowed = {"provider", "model", "api_url", "temperature", "thinking"}
        for key in allowed:
            if key in config:
                player.ai_config[key] = config[key]
        if config.get("api_key"):
            player.ai_config["api_key"] = config["api_key"]
        try:
            player.ai_config["temperature"] = max(0.0, min(2.0, float(player.ai_config.get("temperature", 0.8))))
        except (TypeError, ValueError):
            player.ai_config["temperature"] = 0.8
        # 换厂商/模型后旧会话窗口的前缀已经不再命中，必须整体重建（R13）。
        reset = getattr(self.ai_decision, "reset_session", None)
        if reset is not None:
            reset(player.id)
        return {
            "player_id": player.id,
            "provider": player.ai_config.get("provider", "deepseek"),
            "model": player.ai_config.get("model", "deepseek-chat"),
            "api_url": player.ai_config.get("api_url", ""),
            "temperature": player.ai_config.get("temperature", 0.8),
            "thinking": bool(player.ai_config.get("thinking", False)),
        }

    def is_game_over(self) -> bool:
        return self.game_state.game_over or len([p for p in self.game_state.players if p.alive]) <= 1


__all__ = ["MainEngine"]
