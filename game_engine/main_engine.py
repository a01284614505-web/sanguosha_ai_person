#!/usr/bin/env python3
"""主游戏引擎 v2：引擎生成合法操作，玩家或AI只能从中选择。"""

import asyncio
from collections import deque
import copy
from itertools import combinations, permutations
import logging
import random
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Set, Tuple

from .state_manager import Card, GameState, Player, Phase, card_to_dict
from .phase_controller import PhaseController
from .skill_manager import SkillManager
from .card_system import CardSystem, make_pass_option, option_label
from .card_table import CARD_TABLE, NO_EXTERNAL_TARGET, card_label
from .rules_engine import RulesEngine
from .ai_decision import AIDecision
from .identity_system import IdentitySystem
from .chat_director import ChatDirector, normalize_level
from .token_usage import USAGE_KINDS, apply_usage, empty_bucket
from .config_validator import normalize_ai, normalize_config
from .deck_manager import DeckManager
from .game_stats import GameStats, record_stat
from .effect_context import EffectContext
from .behavior_ledger import BehaviorLedger
from .cognitive_notes import CognitiveNotes
from .seats import seat_of
from .chat_facts import contradiction
from .prompt_trace import redact


logger = logging.getLogger(__name__)
from .hero_registry import HeroRegistry
from .protocol import ENGINE_EVENT, PROVIDERS


class _TrusteePlayerView:
    """Use the human's exact game perspective with a separate model connection."""

    def __init__(self, player, ai_config):
        self._player = player
        self.ai_config = ai_config

    def __getattr__(self, name):
        return getattr(self._player, name)


class MainEngine:
    """自驱动游戏引擎。服务器仅负责消息转发。"""

    TABLE_CHAT_KEEP = 50          # 引擎内存里保留的最近桌面发言条数
    CHAT_TEXT_MAX = 200           # 单条发言入库上限
    AI_CHAT_PER_ROUND = 5         # 单 AI 每回合最多发言数（含免费台词）
    # 发言文本里伪造的系统标记：入库时把【】换成〔〕，防止有人在聊天里冒充引擎事实（方案 5.2）。
    _CHAT_MARK_RE = re.compile(r"【(\s*(?:引擎确认|仅你可见|发言·未验证)[^】]*)(】?)")

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

        # 行为账本（Stage T · T1）：只记公开行为，牌 / 技能结算确定目标处写入，AI 决策与局后日志读取。
        self.ledger = BehaviorLedger()
        # 认知笔记（Stage T · T2）：每个模型 AI 一份，独立于会话窗口；cheat_mode 局才会下发给前端。
        self.notes = CognitiveNotes(self)
        self._notes_round = None
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
        # 聊天调度器（Stage T · T3a）：订阅引擎事件与账本，后台生成 AI 聊天；主循环从不 await 它。
        self.chat_director = ChatDirector(
            self, normalize_level(game_config.get("chat_level") or "normal"))

        self.handlers: Dict[str, Callable] = {}
        self._player_event = asyncio.Event()
        self._player_input = None
        # 场外响应专用通道：与出牌用的 _player_event 单槽位完全隔离，按 request_id 寻址。
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._pending_request_specs: Dict[str, Dict] = {}
        self._request_outcomes: Dict[str, str] = {}
        self.game_id = uuid.uuid4().hex
        self._request_seq = 0
        self._effect_seq = 0
        self.game_log: List[Dict] = []
        # 按座位与调用类型累计的 token 消耗，结构见 token_usage.py。
        self.usage_stats: Dict[Any, Dict[str, Dict[str, int]]] = {}
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
        self._trustee_source = "rules"
        self._trustee_config: Dict = {}
        self._trustee_failures = 0
        self._trustee_degraded = False
        self._trustee_degrade_reason = None
        self._trustee_generation = 0
        self._waiting_for_action = False
        # 正在等待真人的提示（出牌回合 / 选择请求），断线重连时据此重发；键为 "your_turn" 或 request_id。
        self._open_prompts: Dict[str, Dict] = {}
        self._abort_reason: Any = None
        self._watchdog_task: Any = None
        # 临时展示池（五谷丰登亮出的牌）：公开信息，随状态快照下发；结算结束置 None。
        self.shown_pool: Any = None
        self._game_end_emitted = False
        self.spy_duel_lord = False
        self._spy_duel_lord_ready = False
        self._started_at: Any = None
        # 大厅「席间聊天」开关：关闭时 AI 不发聊天消息（真人发言仍会回显）。
        chat_cfg = game_config.get("chat")
        self.ai_spectate = game_config.get("ai_spectate", True) is True
        self.chat_enabled = not (isinstance(chat_cfg, dict) and chat_cfg.get("enabled") is False)
        # 开局锁定的两个选项：对局中途不可改（服务器不提供修改入口）。
        # 作弊模式：真人可看到 AI 的公开理由（不含手牌与隐藏身份）；本局不计连胜与身份卡。
        self.cheat_mode = game_config.get("cheat_mode") is True
        # 阵亡暗置：阵亡角色的身份不对任何人公开（奖惩仍按真实身份结算）。默认官方规则亮明。
        self.hide_dead_identity = game_config.get("hide_dead_identity") is True
        # 局后日志用：每次 AI 决策的完整理由（不实时下发，只在对局结束后按设置写入日志）。
        self.decision_log: List[Dict] = []
        # 桌面发言（Stage T0）：table_chat 只留最近 50 条，进入出牌决策的 L2；
        # chat_log 是同一批发言的完整记录（局后日志用），两者由 _record_table_chat 同时写入。
        self.chat_log: List[Dict] = []
        self.blocked_chat: List[Dict] = []
        self.chat_corrections: Dict[int, str] = {}
        self.table_chat: deque = deque(maxlen=self.TABLE_CHAT_KEEP)
        # 单个 AI 每回合最多发言数（含免费台词）：(player_id, round) → 已发句数。
        self._chat_counts: Dict[Tuple[int, int], int] = {}
        self._log_seq = 0

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

    def next_log_seq(self) -> int:
        """局后日志里时间线、聊天、思考共用的先后序号，用来按发生顺序穿插展示。"""
        self._log_seq += 1
        return self._log_seq

    async def log_event(self, message: str, **data):
        entry = {"message": message, **data}
        self.game_log.append({**entry, "round": self.game_state.round_number, "seq": self.next_log_seq()})
        await self.emit(ENGINE_EVENT.EVENT_NOTIFICATION, **entry)

    async def move_card(
        self, card, from_zone, to_zone, *, from_owner=None, to_owner=None,
        reason, actor_id=None, effect_id=None, visibility="public",
        from_slot=None, to_slot=None, to_index=None, project=True,
    ):
        """Commit a validated physical card move, then publish the same fact."""
        if self.game_aborted:
            return None
        event = self.game_state.move_card(
            card, from_zone, to_zone, from_owner=from_owner, to_owner=to_owner,
            reason=reason, actor_id=actor_id, effect_id=effect_id,
            visibility=visibility, from_slot=from_slot, to_slot=to_slot,
            to_index=to_index,
        )
        if event is None:
            return None
        event_data = event.to_dict()
        if project:
            self.skill_manager.record_card_move_stats(event)
        await self.emit(ENGINE_EVENT.CARD_MOVE, move=event_data)
        if project:
            await self.skill_manager.on_card_move(card, event, stats_recorded=True)
        if from_zone == "equipment" and from_owner is not None:
            # 防具/宝物失去装备区的效果观察同一条已提交移动事实。
            await self.card_system.on_equipment_left(from_owner, card, event)
        return event

    async def draw_cards(self, player: Player, count: int, reason: str = "draw") -> List:
        """从摸牌堆顶摸 count 张：逐张走 move_card（统计/事件一致），牌堆空时先洗弃牌堆。

        摸完发一次 draw 动画通知：真人看到自己摸到的牌面，别人的只显示张数（牌背）。
        """
        drawn = []
        for _ in range(max(0, int(count))):
            if self.game_aborted or not self.game_state.refill_deck_if_empty():
                break
            card = self.game_state.deck[0]
            moved = await self.move_card(
                card, "deck", "hand", to_owner=player, reason=reason,
                actor_id=player.id, visibility="owner",
            )
            if moved is None:
                break
            drawn.append(card)
        if drawn and not self.game_aborted:
            own = player is self.human_player()
            await self._notify_card_ui(
                event_kind="draw", actor_id=player.id, actor_name=player.name,
                count=len(drawn), reason=reason,
                cards=[card_to_dict(c) for c in drawn] if own else None,
                deck_count=len(self.game_state.deck),
                message=f"{player.name}摸了{len(drawn)}张牌" + (
                    "" if reason in ("draw", "摸牌阶段") else
                    "（击杀奖励）" if reason == "kill_rebel_reward" else f"（{reason}）"),
            )
        return drawn

    async def announce_judge(self, player: Player, card, judge_for: str, effective=None, result_text: str = ""):
        """判定结果通知：前端在牌桌中央展示判定牌与“生效/失效”，并等待动画 ACK 后再继续结算。

        effective 为 None 表示该判定没有统一的生效/失效语义（如技能判定），前端只展示判定牌。
        """
        suit_text = {"spade": "♠", "heart": "♥", "club": "♣", "diamond": "♦"}.get(card.suit, "")
        verdict = "" if effective is None else ("生效" if effective else "失效")
        message = f"{player.name}的【{judge_for}】判定：{suit_text}{card.rank}{card.name}"
        if verdict:
            message += f"，{verdict}"
        if result_text:
            message += f"（{result_text}）"
        await self._notify_card_ui(
            event_kind="judge",
            actor_id=player.id,
            actor_name=player.name,
            card=card_to_dict(card),
            card_name=card.name,
            judge_for=judge_for,
            effective=effective,
            result_text=result_text,
            message=message,
            reason="judge",
        )

    async def _notify_card_ui(self, **data):
        """卡牌UI统一通知（弃牌/出牌/技能转化共用）：等待浏览器确认动画完成后才继续结算。"""
        if self.game_aborted:
            return
        entry = {"event_kind": "card_to_discard", "await_ui": True, **data}
        self.game_log.append({**entry, "round": self.game_state.round_number, "seq": self.next_log_seq()})
        await self.emit(ENGINE_EVENT.CARD_ANIMATION, **entry)

    async def _execute_phase_with_ui(self, phase: Phase):
        """执行阶段，并为阶段产生的弃牌补发可解释的卡牌UI事件。"""
        if self.game_aborted:
            return
        player = self.game_state.current_player
        before_discard = len(self.game_state.discard_pile)
        before_hand = list(player.hand)
        skill_result = await self.skill_manager.before_phase(player, phase)
        if self.game_aborted:
            return
        if not skill_result.get("skip_default"):
            await self.phase_controller.execute_phase(phase)
        if self.game_aborted:
            return
        await self.skill_manager.after_phase(player, phase)
        if self.game_aborted:
            return
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
                    message=f"{player.name}因手牌上限弃置{card_label(card)}",
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
                    "seat": seat_of(gs, p.id),
                    "name": p.name,
                    "hp": p.hp,
                    "max_hp": p.max_hp,
                    "hand_count": len(p.hand),
                    # 手牌上限由引擎按技能（英姿、血裔、清俭等）算好下发，前端不自行推算。
                    "hand_limit": self.skill_manager.hand_limit(p, max(0, p.hp)),
                    "chained": bool(getattr(p, "chained", False)),
                    "treasure_count": len(p.treasure_cards),
                    "alive": p.alive,
                    "death_round": p.flags.get("death_round"),
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
                    "ai_id": p.ai_config.get("ai_id") if p.is_ai else None,
                    "title": (p.ai_config.get("title") if p.is_ai else p.title),
                    "ai_config": {
                        # 没填 Key 的座位实际由规则 AI 代打，界面据此显示“规则 AI”而不是模型名。
                        "rule_ai": not self._has_model_key(p),
                        "provider": p.ai_config.get("provider", "deepseek"),
                        "model": p.ai_config.get("model", "deepseek-chat"),
                        "api_url": p.ai_config.get("api_url", ""),
                        "temperature": p.ai_config.get("temperature", 0.8),
                        "thinking": bool(p.ai_config.get("thinking", False)),
                        "ai_id": p.ai_config.get("ai_id"),
                        "title": p.ai_config.get("title"),
                    } if p.is_ai else None,
                    "identity": p.identity if identity_visible else None,
                    "identity_revealed": identity_visible,
                    "equipment": {slot: card.name for slot, card in p.equipment.items()},
                    # 判定区是公开信息（乐不思蜀/兵粮寸断/闪电），前端按牌名显示标记。
                    "judge_area": [card.name for card in getattr(p, "judge_area", [])],
                    "stats": self.stats.row(p),
                    "skill_state": [
                        instance.to_dict()
                        for instance in self.skill_manager.skill_state.for_owner(p.id)
                    ],
                    "marks": {
                        key: p.flags[key]
                        for key in ("pao_tokens", "hand_limit_bonus", "rende_count",
                                    "cannot_use_hand", "nonlocked_disabled")
                        if isinstance(p.flags.get(key), (bool, int)) and p.flags[key]
                    },
                }
            )
        # serialize() 只发给真人自己的连接（AI 决策不读它），因此可以附带真人自己的手牌，
        # 让前端在非出牌阶段也能看到手牌。他人手牌仍只有 hand_count。
        human = self.human_player()
        return {
            "self_hand": self.get_player_hand(human) if human else [],
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
            "cheat_mode": self.cheat_mode,
            "chat_level": self.chat_director.level,
            "ai_spectate": self.ai_spectate,
            "hide_dead_identity": self.hide_dead_identity,
            "winner": gs.winner,
            "trustee": self.trustee_status(),
            "shown_pool": copy.deepcopy(self.shown_pool) if self.shown_pool else None,
        }

    async def set_shown_pool(self, pool):
        """更新临时展示池并推送状态：亮牌、轮到谁、谁取走了哪张，全桌可见。"""
        self.shown_pool = copy.deepcopy(pool) if pool else None
        await self.emit(ENGINE_EVENT.STATE_CHANGED, state=self.serialize())

    @staticmethod
    def _has_model_key(player: Player) -> bool:
        key = (player.ai_config or {}).get("api_key", "")
        return bool(key) and key != "test_key"

    def human_player(self):
        """本局的真人玩家（无则返回 None）。"""
        return next((p for p in self.game_state.players if not p.is_ai), None)

    def get_player_hand(self, player: Player) -> List[Dict]:
        # 扣置牌仅向当前宝物拥有者开放，按独立牌区标记，不增加手牌数。
        cards = [(card, "hand") for card in player.hand]
        if getattr(player.equipment.get("treasure"), "name", None) == "木牛流马":
            cards.extend((card, "treasure") for card in player.treasure_cards)
        return [{**card_to_dict(card), "index": index, "zone": zone,
                 "target_rule": card.target_rule or {}}
                for index, (card, zone) in enumerate(cards)]

    # ---------- 主流程 ----------

    async def run(self):
        if self.game_aborted:
            await self._emit_game_end_once()
            return self.game_state.winner
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

        for p in self.game_state.players:
            if p.is_ai and self._has_model_key(p):
                self.notes.ensure(p.id)
        self._notes_round = self.game_state.round_number
        await self.emit(ENGINE_EVENT.STATE_CHANGED, state=self.serialize())

        self._watchdog_task = asyncio.create_task(self._idle_watchdog())
        self.chat_director.start()
        try:
            while not self.is_game_over():
                self._observe_spy_duel_lord_state()
                self._roll_notes_round()
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
                    # 额外回合未调用 next_turn，也必须开启新的酒/出杀次数作用域。
                    player.sha_count = 0
                    player.jiu_used_this_turn = False
                    player.jiu_buff = False
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
            self._cancel_chat_tasks()

        self._roll_notes_round(final=True)
        await self._emit_game_end_once()
        logger.info(f"\n🎊 游戏结束！胜者: {self.game_state.winner}")
        return self.game_state.winner

    # ---------- 玩家回合 ----------

    async def _ai_turn(self, player: Player):
        logger.info(f"\n{'=' * 60}\n  [AI回合] {player.name}\n{'=' * 60}")
        await self.emit(ENGINE_EVENT.AI_ACTION, player_name=player.name, action="turn_start")
        await self._run_phases(player)
        await self.emit(ENGINE_EVENT.STATE_CHANGED, state=self.serialize())

    def record_usage(self, player_id, kind: str, usage: Any = None, failed: bool = False):
        """累计一次模型调用的 token。usage 缺字段计入 unknown_usage_calls，不当 0。"""
        if kind not in USAGE_KINDS:
            raise ValueError(f"unknown usage kind: {kind}")
        seat = self.usage_stats.setdefault(player_id, {})
        apply_usage(seat.setdefault(kind, empty_bucket()), usage, failed)

    # ---------- 桌面发言（Stage T0） ----------

    @classmethod
    def clean_chat_text(cls, text: Any) -> str:
        """去首尾空白、截断，并把伪造的系统标记【引擎确认】等转义成〔〕。"""
        value = str(text or "").strip()[:cls.CHAT_TEXT_MAX]
        return cls._CHAT_MARK_RE.sub(lambda m: "〔" + m.group(1) + ("〕" if m.group(2) else ""), value)

    async def _record_table_chat(self, player_id: int, name: str, kind: str, text: Any):
        """一条桌面发言的唯一入库点：写 table_chat 与 chat_log，再广播给界面。"""
        clean = self.clean_chat_text(text)
        if not clean:
            return None
        seq = self.next_log_seq()
        round_number = self.game_state.round_number
        ts = self.time_source()
        entry = {"seq": seq, "round": round_number, "from_id": player_id, "name": name,
                 "seat": seat_of(self.game_state, player_id), "kind": kind, "text": clean, "ts": ts}
        self.table_chat.append(entry)
        self.chat_log.append({"seq": seq, "round": round_number, "from": name, "kind": kind,
                              "message": clean, "from_id": player_id, "seat": seat_of(self.game_state, player_id), "ts": ts})
        await self.emit(ENGINE_EVENT.CHAT, from_=name, message=clean, from_id=player_id,
                        kind=kind, ts=ts)
        return entry

    async def submit_chat(self, player_id: int, text: Any):
        """真人发言：进入桌面发言记录（下一次 AI 出牌决策能看到），并广播。"""
        player = next((p for p in self.game_state.players if p.id == player_id), None)
        if player is None:
            return None
        entry = await self._record_table_chat(player.id, player.name, "human", text)
        if entry is not None:
            self.chat_director.on_human_chat(entry)       # 同步登记，回应在后台生成
        return entry

    async def _record_ai_chat(self, player: Player, text: Any):
        """AI 发言入口：保留事实复核；阵亡观战每轮至多一句。"""
        if not self.chat_enabled or (not player.alive and not self.ai_spectate):
            return None
        clean = self.clean_chat_text(text)
        conflict = contradiction(clean, self.game_state, getattr(self, "ledger", None))
        if conflict:
            record = redact({"seq": self.next_log_seq(), "round": self.game_state.round_number,
                             "player_id": player.id, "seat": seat_of(self.game_state, player.id),
                             "name": player.name, "text": clean, **conflict}, self)
            self.blocked_chat.append(record)
            self.chat_corrections[player.id] = "你上一句因与引擎记录矛盾未发出：" + record["text"] + "；" + record["detail"]
            logger.warning("发言被拦截：%s：%s；%s", record["name"], record["text"], record["detail"])
            if self.cheat_mode:
                await self.emit(ENGINE_EVENT.CHAT_REJECTED, **record)
            return None
        cap = self.AI_CHAT_PER_ROUND if player.alive else 1
        key = (player.id, self.game_state.round_number)
        if self._chat_counts.get(key, 0) >= cap:
            logger.info("  💬 %s 本回合发言已达 %d 句上限，丢弃：%s", player.name,
                        self.AI_CHAT_PER_ROUND, str(text)[:20])
            return None
        entry = await self._record_table_chat(player.id, player.name,
                                              "ai" if player.alive else "spectator", clean)
        if entry is not None:
            self._chat_counts[key] = self._chat_counts.get(key, 0) + 1
        return entry

    def _cancel_chat_tasks(self):
        self.chat_director.shutdown()

    @property
    def chat_level(self) -> str:
        return self.chat_director.level

    def update_settings(self, settings: Any) -> Dict[str, Any]:
        """对局中修改设置（update_settings 入站）：本批只放行 chat_level，其余一律拒绝。"""
        if not isinstance(settings, dict) or not settings:
            raise ValueError("缺少要修改的设置项")
        blocked = sorted(str(key) for key in settings if key != "chat_level")
        if blocked:
            raise ValueError("对局中不可修改的设置: " + ", ".join(blocked))
        return {"chat_level": self.chat_director.set_level(settings["chat_level"])}

    def on_player_dying(self, player: Player):
        """CardSystem 在有人进入濒死时同步通知（不 await）：聊天调度器据此处理「主公濒死」。"""
        self.chat_director.on_dying(player)

    async def _human_turn(self, player: Player):
        logger.info(f"\n{'=' * 60}\n  [人类回合] {player.name}\n{'=' * 60}")
        await self.emit(ENGINE_EVENT.STATE_CHANGED, state=self.serialize())

        for phase in [Phase.PREPARE, Phase.JUDGE, Phase.DRAW]:
            if self.game_aborted:
                return
            await self._enter_phase(player, phase)
            if self.game_aborted:
                return
            await self._execute_phase_with_ui(phase)
            await self.emit(ENGINE_EVENT.STATE_CHANGED, state=self.serialize())

        await self._enter_phase(player, Phase.PLAY)
        player.sha_count = 0
        await self.emit(ENGINE_EVENT.STATE_CHANGED, state=self.serialize())

        # 乐不思蜀等效果会把出牌阶段加入跳过集合：此时不向真人下发 your_turn。
        play_skipped = await self._skip_play_phase_if_needed(player)

        while not play_skipped and player.alive and not self.game_state.game_over:
            actions = self.get_available_actions(player)
            if self._trustee_active:
                generation = self._trustee_generation
                decision = await self._trustee_make_decision(player, actions)
                if decision is None or generation != self._trustee_generation:
                    continue
                action = decision.get("action") or {"type": "end_phase"}
                if action.get("type") == "end_phase":
                    await self._emit_decision_trace(player, "play", len(actions), action, "accepted")
                    break
                target_ids = decision.get("target_ids") or []
                ok = await self.execute_action(player, action, target_ids)
                await self._emit_decision_trace(player, "play", len(actions), action,
                                                "accepted" if ok else "invalid")
                if not self.game_aborted:
                    await self.emit(ENGINE_EVENT.ACTION_RESULT, success=ok, trustee=True)
                    await self.emit(ENGINE_EVENT.STATE_CHANGED, state=self.serialize())
                if not ok:
                    break
                continue
            # 必须先创建等待器再广播，避免WebSocket客户端立即响应造成丢操作。
            self._player_event = asyncio.Event()
            self._player_input = None
            self._waiting_for_action = True
            # 出牌阶段引擎同样在等真人，纳入离席计时。
            self._mark_waiting_for_human()
            payload = {
                "player_name": player.name,
                "hand": self.get_player_hand(player),
                "actions": [dict(action) for action in actions],
                "timeout": self.human_action_timeout,
            }
            self._remember_prompt("your_turn", ENGINE_EVENT.YOUR_TURN, payload)
            try:
                await self.emit(ENGINE_EVENT.YOUR_TURN, **payload)
                data = await self._wait_player_input()
            finally:
                self._open_prompts.pop("your_turn", None)
            self._waiting_for_action = False
            if self.game_state.game_over:
                break
            action = data["action"]
            target_ids = data["target_ids"]
            if action.get("type") == "trustee":
                continue
            if action.get("type") == "end_phase":
                break

            ok = await self.execute_action(player, action, target_ids)
            await self.emit(ENGINE_EVENT.ACTION_RESULT, success=ok)
            await self.emit(ENGINE_EVENT.STATE_CHANGED, state=self.serialize())

        if self.game_state.game_over:
            return

        for phase in [Phase.DISCARD, Phase.END]:
            if self.game_aborted:
                return
            await self._enter_phase(player, phase)
            if self.game_aborted:
                return
            await self._execute_phase_with_ui(phase)
            await self.emit(ENGINE_EVENT.STATE_CHANGED, state=self.serialize())

    async def _enter_phase(self, player: Player, phase: Phase):
        """切换到新阶段，并给前端阶段栏发一条轻量通知（不附整份状态）。

        skipped=True 表示该阶段已被判定/技能标记为跳过（如兵粮寸断跳过摸牌、乐不思蜀跳过出牌），
        前端据此把阶段栏对应格子显示为“跳过”。
        """
        self.game_state.current_phase = phase
        skipped = phase in self.phase_controller.skip_phases
        await self.emit(
            ENGINE_EVENT.EVENT_NOTIFICATION,
            event_kind="phase",
            player_id=player.id,
            player_name=player.name,
            phase=phase.value,
            skipped=skipped,
        )

    async def _skip_play_phase_if_needed(self, player: Player) -> bool:
        """出牌阶段不经 PhaseController.execute_phase，因此在这里单独消费“跳过出牌阶段”标记。

        修复：此前人类与 AI 的出牌阶段都不检查跳过集合，导致乐不思蜀判定生效后仍可出牌，
        且标记残留到之后的回合。
        """
        if Phase.PLAY not in self.phase_controller.skip_phases:
            return False
        self.phase_controller.skip_phases.discard(Phase.PLAY)
        await self.log_event(f"{player.name}跳过出牌阶段", player_id=player.id)
        return True

    async def _run_phases(self, player: Player):
        for phase in Phase:
            if self.game_state.game_over:
                break
            await self._enter_phase(player, phase)
            logger.info(f"\n[{phase.value}阶段]")
            if phase == Phase.PLAY:
                player.sha_count = 0
                if not await self._skip_play_phase_if_needed(player):
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
                reasoning=""
            )
            await self._emit_cognitive_notes_if_changed()
            action = decision.get("action") or {"type": "end_phase"}
            target_ids = decision.get("target_ids", [])

            if action.get("type") == "end_phase":
                await self._emit_decision_trace(player, "play", len(actions), action,
                                                "accepted")
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
            await self._emit_decision_trace(player, "play", len(actions), action,
                                            "accepted" if ok else "invalid")
            if not ok:
                logger.info("  ⚠️ AI操作被引擎拒绝，结束本次出牌阶段")
                break
            await self.emit(ENGINE_EVENT.STATE_CHANGED, state=self.serialize())

    # ---------- 认知笔记（Stage T · T2） ----------

    def _roll_notes_round(self, final: bool = False):
        """轮次推进时给上一轮存一份笔记快照；final=True 表示对局结束，补存最后一轮。"""
        current = self.game_state.round_number
        if self._notes_round is None:
            self._notes_round = current
        if final:
            self.notes.snapshot(self._notes_round)
            self._notes_round = None
        elif current != self._notes_round:
            self.notes.snapshot(self._notes_round)
            self._notes_round = current

    def on_player_death(self, player: Player):
        """CardSystem 在玩家阵亡（alive=False）后调用：冻结其笔记，并让其他 AI 下次出牌时复核。"""
        player.flags.setdefault("death_round", int(getattr(self.game_state, "round_number", 0) or 0))
        if player.identity == "lord":
            survivors = [p for p in self.game_state.players if p.alive]
            self.spy_duel_lord = (self._spy_duel_lord_ready and len(survivors) == 1
                                  and survivors[0].identity == "spy")
        self.notes.on_death(player)
        self.chat_director.on_death(player)

    def _observe_spy_duel_lord_state(self):
        """Remember a real action-boundary state with only the lord and spy alive."""
        alive = [p for p in self.game_state.players if p.alive]
        self._spy_duel_lord_ready = (len(alive) == 2
                                     and {p.identity for p in alive} == {"lord", "spy"})

    async def push_notes_after_death(self):
        """阵亡后（作弊局）立刻推送一次笔记，让"冻结"标记即时可见；非作弊局什么都不发。"""
        payload = self.cheat_notes_payload()
        if payload is not None:
            await self.emit(ENGINE_EVENT.COGNITIVE_NOTES, **payload)

    def cheat_notes_payload(self):
        """作弊局的笔记下发内容；非作弊局恒为 None —— 服务器根本不构造 cognitive_notes 消息（D14）。"""
        if not self.cheat_mode:
            return None
        reasons = getattr(self.ai_decision, "last_reasoning", {}) or {}
        payload = self.notes.client_payload(reasons)
        for row in payload["players"]:
            plan = getattr(self.ai_decision, "plans", {}).get(row["player_id"])
            if plan:
                row["plan"] = dict(plan)
        return payload

    async def _emit_cognitive_notes_if_changed(self):
        changed = self.notes.pop_changed()
        if changed and self.cheat_mode:
            await self.emit(ENGINE_EVENT.COGNITIVE_NOTES, **self.cheat_notes_payload())

    def _record_ai_outcome(self, player: Player, action: Dict, target_ids: List, ok: bool):
        """把引擎的实际执行结果回灌进该AI的会话窗口，让它记得自己刚干了什么。"""
        recorder = getattr(self.ai_decision, "record_outcome", None)
        if recorder is None:
            return
        names = [p.name for p in self.game_state.players if p.id in (target_ids or [])]
        target_text = f"，目标：{'、'.join(names)}" if names else ""
        verdict = "已生效" if ok else "被引擎判定为非法，未生效"
        recorder(player, f"【引擎执行结果】你的操作 {action.get('type')}{target_text} {verdict}。")

    async def _emit_decision_trace(self, player, kind, candidate_count, choice, validation):
        """Publish only information already visible to the human client."""
        own_decision = player is self.human_player()
        meta = getattr(self.ai_decision, "last_meta", {}).get(player.id) or {}
        if own_decision and (self._trustee_source == "rules" or self._trustee_degraded):
            meta = {}
        failure = getattr(self.ai_decision, "last_failure", {}).get(player.id)
        private_reason = getattr(self.ai_decision, "last_reasoning", {}).get(player.id, "") if meta else ""
        # 作弊模式（开局锁定）下，AI 的公开理由也推给真人；否则只公开真人自己托管的理由。
        reveal = own_decision or (self.cheat_mode and player.is_ai)
        reason = private_reason if reveal else ""
        if isinstance(choice, dict) and hasattr(self.ai_decision, "format_action"):
            full_choice = self.ai_decision.format_action(choice, self.game_state)
        else:
            full_choice = choice.get("type", "") if isinstance(choice, dict) else ("放弃" if choice is None else str(choice)[:100])
        # 局后日志：不论是否作弊都记录完整理由，对局结束后才按设置写入。
        self.decision_log.append({
            "seq": self.next_log_seq(), "round": self.game_state.round_number, "player_id": player.id, "player_name": player.name,
            "kind": kind, "model": meta.get("model"), "reason": private_reason[:1000],
            "choice": str(full_choice)[:200], "validation": validation,
            "elapsed_ms": meta.get("elapsed_ms"),
        })
        if not reason:
            reason = "模型结果已由引擎复核" if meta.get("model") and not failure else "按规则选择合法候选"
        if reveal:
            final_choice = full_choice
        else:
            final_choice = choice.get("type", "已选择") if isinstance(choice, dict) else "已选择" if choice is not None else "放弃"
        await self.emit(
            ENGINE_EVENT.DECISION_TRACE,
            player_id=player.id, player_name=player.name, kind=kind,
            source="trustee" if own_decision else "rules" if failure or not meta.get("model") else "model",
            model=meta.get("model"), elapsed_ms=meta.get("elapsed_ms"),
            prompt_tokens=meta.get("prompt_tokens"), completion_tokens=meta.get("completion_tokens"),
            candidate_count=int(candidate_count),
            candidate_summary=f"{kind}：{int(candidate_count)} 个引擎候选",
            worldbook_hits=meta.get("worldbook_hits") or [], reason=reason[:200],
            final_choice=final_choice, validation=validation,
            cheat=bool(self.cheat_mode and player.is_ai and private_reason),
        )

    # ---------- 玩家输入 ----------

    async def _wait_player_input(self) -> Dict:
        try:
            await asyncio.wait_for(self._player_event.wait(), timeout=self.human_action_timeout)
        except asyncio.TimeoutError:
            self.set_trustee(True, source="rules")
            return {"action": {"type": "trustee"}, "target_ids": []}
        return self._player_input or {"action": {"type": "end_phase"}, "target_ids": []}

    def submit_action(self, action: Dict, target_ids: List[int]):
        if not isinstance(action, dict):
            return {"status": "invalid", "success": False, "message": "操作格式错误"}
        if action.get("type") == "response":
            option_indices = action.get("option_indices")
            if action.get("cancel") is True:
                selection = {"cancel": True}
            else:
                selection = option_indices if option_indices is not None else action.get("option_index")
            return self.submit_response_status(action.get("request_id"), selection)
        if self.game_aborted:
            return {"status": "game_ended", "success": False, "message": "对局已结束"}
        if self._trustee_active:
            self._note_human_input()
            return {"status": "stale", "success": False,
                    "message": "已解除托管，请等待新的出牌提示后重试"}
        if (not self._waiting_for_action or self._player_event.is_set()
                or self.game_state.current_player is not self.human_player()):
            return {"status": "stale", "success": False,
                    "message": "当前没有等待中的出牌操作，请等待新的出牌提示"}
        self._note_human_input()
        self._player_input = {"action": action, "target_ids": target_ids or action.get("target_ids", []) or []}
        if self._player_event and not self._player_event.is_set():
            self._player_event.set()
        return {"status": "accepted", "success": True, "message": "已接收操作"}

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
        hidden = bool(option.get("hidden"))
        return {
            "index": index,
            "label": self._option_label(option),
            "card": None if card is None or hidden else card_to_dict(card),
            "card_index": None if hidden else option.get("card_index"),
            "owner_id": getattr(owner, "id", None),
            "owner_name": getattr(owner, "name", None),
            "as_name": option.get("as_name"),
            "skill_name": option.get("skill_name"),
            "is_pass": card is None,
            "hidden": hidden,
        }

    @staticmethod
    def _response_decision_view(request: Dict) -> Dict:
        masked = dict(request)
        masked["context"] = MainEngine._public_decision_value(request.get("context") or {})
        masked["options"] = [
            {key: value for key, value in option.items() if key not in ("owner", "card", "card_index")}
            | {"card": None if option.get("hidden") else option.get("card"),
               "available": option.get("card") is not None,
               "label": option_label(option)}
            for option in request.get("options") or []
        ]
        return masked

    @staticmethod
    def _serialize_response_context(context: Dict) -> Dict:
        """只传公开的 Player 标识与标量；Card 对象不经上下文泄露。"""
        out: Dict[str, Any] = {}
        for key, value in (context or {}).items():
            if hasattr(value, "id") and hasattr(value, "name") and hasattr(value, "hp"):
                out[key] = {"id": value.id, "name": value.name}
            # Card may come from an unrevealed hand. Context is advisory UI data,
            # so omit card objects instead of exposing suit/rank by accident.
            elif isinstance(value, (str, int, float, bool)) or value is None:
                out[key] = value
            elif isinstance(value, (list, tuple)) and all(
                    isinstance(item, (str, int, float, bool)) for item in value):
                # 只放行纯标量列表（如五谷丰登的 pool_slots），对象列表一律不传。
                out[key] = list(value)
        return out

    def _next_request_id(self) -> str:
        self._request_seq += 1
        return f"{self.game_id}:resp{self._request_seq}"

    def _prepare_request(self, player: Player, request: Dict, request_id: str) -> Dict:
        """Freeze the server-side request envelope and candidate version."""
        prepared = dict(request)
        candidate_version = f"{request_id}:candidate"
        prepared.update({
            "game_id": self.game_id,
            "request_id": request_id,
            "candidate_version": candidate_version,
            "player_id": player.id,
            "timeout": self.response_timeout,
        })
        if prepared.get("kind") in ("choose_cards", "choose_players"):
            prepared["selection"] = {
                "mode": "multi" if prepared.get("max_n", 1) > 1 else "single",
                "min": prepared.get("min_n", 1),
                "max": prepared.get("max_n", 1),
                "cancelable": prepared.get("cancelable", True),
                "zone": prepared.get("zone"),
            }
        return prepared

    async def _emit_selection_result(self, player: Player, request: Dict, status: str):
        """Emit final resolution separately from the immediate accepted receipt."""
        if status not in {"resolved", "cancelled", "timeout", "stale", "invalid", "game_ended"}:
            status = "invalid"
        await self.emit(
            ENGINE_EVENT.SELECTION_RESULT,
            game_id=request.get("game_id", self.game_id),
            request_id=request.get("request_id"),
            candidate_version=request.get("candidate_version"),
            player_id=player.id,
            kind=request.get("kind", "respond"),
            status=status,
        )

    def _new_effect_context(self, player: Player, card, *, skill_source=None, card_cost_ids=None, target=None):
        self._effect_seq += 1
        effect_id = f"{self.game_id}:effect{self._effect_seq}"
        if skill_source:
            return EffectContext.from_skill_virtual_card(
                effect_id, card, card_cost_ids or [], skill_source, player.id,
                current_target_id=getattr(target, "id", None),
            )
        return EffectContext.from_entity_card(
            effect_id, card, player.id, current_target_id=getattr(target, "id", None),
        )

    def _remember_prompt(self, key: str, event: str, payload: Dict):
        self._open_prompts[key] = {"event": event, "payload": payload,
                                   "since": asyncio.get_running_loop().time()}

    def pending_prompts(self) -> List[Dict]:
        """断线重连时需要重发给真人的提示，timeout 换算成剩余秒数。"""
        if self.game_aborted:
            return []
        now = asyncio.get_running_loop().time()
        prompts = []
        for entry in self._open_prompts.values():
            payload = dict(entry["payload"])
            if "hand" in payload:
                # 出牌提示里的手牌以当前为准（等待期间可能被拆、被顺）。
                payload["hand"] = self.get_player_hand(self.human_player())
            try:
                remaining = float(payload.get("timeout") or 0) - (now - entry["since"])
            except (TypeError, ValueError):
                remaining = 0
            payload["timeout"] = max(1, int(remaining))
            prompts.append({"event": entry["event"], "payload": payload})
        return prompts

    def _close_request(self, request_id: str):
        self._open_prompts.pop(request_id, None)
        self._pending_requests.pop(request_id, None)
        self._pending_request_specs.pop(request_id, None)
        self._request_outcomes.setdefault(request_id, "expired")
        while len(self._request_outcomes) > 128:
            self._request_outcomes.pop(next(iter(self._request_outcomes)))

    def _resolve_option(self, player: Player, request: Dict, index) -> Dict:
        """引擎复核：索引合法 → 有牌 → 牌仍在 owner 手上 → owner 存活 → 名称匹配。任一不满足即视为不响应。"""
        if self.game_aborted:
            return {"bool": False}
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
        source_zone = option.get("source_zone", "hand")
        source_cards = owner.treasure_cards if source_zone == "treasure" else owner.hand
        if card not in source_cards or (source_zone == "treasure" and getattr(
                owner.equipment.get("treasure"), "name", None) != "木牛流马"):
            logger.info(f"  ❌ 响应复核失败：【{card.name}】已不在 {owner.name} 的合法牌区")
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
            "source_zone": source_zone,
        }

    @staticmethod
    def _response_resolution_status(player: Player, request: Dict, index, result: Dict) -> str:
        if index is None or result.get("bool"):
            return "resolved"
        options = request.get("options") or []
        chosen = options[index] if isinstance(index, int) and 0 <= index < len(options) else None
        card = (chosen or {}).get("card")
        owner = (chosen or {}).get("owner") or player
        source_cards = owner.treasure_cards if (chosen or {}).get("source_zone") == "treasure" else owner.hand
        return "stale" if card is not None and card not in source_cards else "resolved"

    async def _ask_index(self, player: Player, request: Dict, resolver) -> Any:
        """共用询问机制：人/AI分派 + 超时托管 + 回灌。resolver 决定如何验证原始索引。"""
        if self.game_aborted:
            return {"bool": False}
        request_id = self._next_request_id()
        request = self._prepare_request(player, request, request_id)
        trustee_request = self._trustee_active and player is self.human_player()
        generation = self._trustee_generation
        if player.is_ai or trustee_request:
            index = await self._ai_choose_option(player, request)
            if self.game_aborted:
                await self._emit_selection_result(player, request, "game_ended")
                return {"bool": False}
            if trustee_request and generation != self._trustee_generation:
                if self._trustee_active:
                    index = await self._ai_choose_option(player, request)
                else:
                    index, input_status = await self._human_choose_option(player, request, request_id)
                    if input_status in {"timeout", "trustee"} and not self.game_aborted:
                        index = await self._trustee_choose(player, request)
                    elif input_status != "accepted":
                        await self._emit_selection_result(player, request, input_status)
                        return {"bool": False}
            if self.game_aborted:
                await self._emit_selection_result(player, request, "game_ended")
                return {"bool": False}
            result = resolver(player, request, index)
            self._record_response_outcome(player, request, result)
            await self._emit_selection_result(
                player, request, self._response_resolution_status(player, request, index, result)
            )
            if player.is_ai or self._trustee_active:
                await self._emit_decision_trace(
                    player, request.get("kind", "respond"), len(request.get("options") or []),
                    index, "accepted" if result.get("bool") else "pass",
                )
            return result
        index, input_status = await self._human_choose_option(player, request, request_id)
        if input_status == "accepted":
            result = resolver(player, request, index)
            status = self._response_resolution_status(player, request, index, result)
        elif input_status in {"timeout", "trustee"} and not self.game_aborted:
            index = await self._trustee_choose(player, request)
            if self.game_aborted:
                result, status = {"bool": False}, "game_ended"
            else:
                result = resolver(player, request, index)
                status = "timeout" if input_status == "timeout" else "resolved"
        elif input_status == "cancelled":
            result, status = {"bool": False}, "cancelled"
        else:
            result, status = {"bool": False}, "game_ended"
        await self._emit_selection_result(player, request, status)
        if input_status in {"timeout", "trustee"} and not self.game_aborted:
            await self._emit_decision_trace(
                player, request.get("kind", "respond"), len(request.get("options") or []),
                index, status,
            )
        return result

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
        if card is None:
            return False
        if zone == "deck":
            return card in self.game_state.deck
        if owner is None:
            return False
        if zone == "hand":
            return card in owner.hand
        if zone == "treasure":
            return card in owner.treasure_cards and getattr(
                owner.equipment.get("treasure"), "name", None) == "木牛流马"
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
                fallback_raw = self.ai_decision.simple_choice_decision(
                    player, self._mask_hidden_candidates(request)
                )
            except Exception as exc:
                logger.info("  ⚠️ 兜底决策失败: %s", type(exc).__name__)
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
    def _public_decision_value(value):
        """Remove live player and card objects from advisory decision context."""
        if isinstance(value, Player):
            public = {"id": value.id, "name": value.name, "hp": value.hp,
                      "alive": value.alive, "is_ai": value.is_ai}
            if value.identity_revealed:
                public["identity"] = value.identity
            return public
        if isinstance(value, Card):
            return None
        if isinstance(value, dict):
            return {key: MainEngine._public_decision_value(item)
                    for key, item in value.items() if not isinstance(item, Card)}
        if isinstance(value, (list, tuple)):
            return [MainEngine._public_decision_value(item) for item in value
                    if not isinstance(item, Card)]
        return value if isinstance(value, (str, int, float, bool, type(None))) else None

    @staticmethod
    def _mask_hidden_candidates(request: Dict) -> Dict:
        """Give AI only public candidate data; keep live objects in the validator snapshot."""
        hidden = set(request.get("hidden_indices") or [])
        masked = dict(request)
        if request.get("candidate_cards") is not None:
            masked["candidate_cards"] = [
                None if index in hidden else card
                for index, card in enumerate(request.get("candidate_cards") or [])
            ]
        masked["options"] = [
            {key: value for key, value in option.items() if key not in ("owner", "card")}
            | {"card": None if index in hidden else option.get("card")}
            for index, option in enumerate(request.get("options") or [])
        ]
        masked.pop("candidate_places", None)
        masked.pop("card_owner", None)
        masked["context"] = MainEngine._public_decision_value(request.get("context") or {})
        if "choices" in masked:
            masked["choices"] = MainEngine._public_decision_value(masked["choices"])
        return masked

    async def _ai_choose_choice(self, player: Player, request: Dict):
        """AI dispatch for four new primitives. Returns List[int]."""
        request = self._mask_hidden_candidates(request)
        trustee = self._trustee_active and player is self.human_player()
        if trustee and (self._trustee_source == "rules" or self._trustee_degraded):
            return self.ai_decision.simple_choice_decision(player, request)
        decision_player = self._trustee_view(player) if trustee else player
        handler = getattr(self.ai_decision, "make_choice_decision", None)
        if handler is not None:
            try:
                result = await handler(decision_player, request)
                if trustee:
                    self._update_trustee_failure(player)
                return result
            except Exception as exc:
                logger.info("  ⚠️ 选择AI失败，切换规则AI: %s", type(exc).__name__)
                if trustee:
                    self._trustee_failures += 1
                    self._trustee_degraded = self._trustee_failures >= 3
        return self.ai_decision.simple_choice_decision(player, request)

    async def _trustee_choose_choice(self, player: Player, request: Dict):
        if self._abort_reason:
            return []
        if not self._trustee_active:
            self.set_trustee(True, source="rules")
        indices = await self._ai_choose_choice(player, request)
        await self.log_event("[托管] 已代为选择", trustee=True, player_id=player.id)
        return indices

    async def _human_choose_choice(self, player: Player, request: Dict, request_id: str):
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending_requests[request_id] = future
        self._pending_request_specs[request_id] = request
        self._mark_waiting_for_human()
        selection_block = {
            "mode": "multi" if request.get("max_n", 1) > 1 else "single",
            "min": request.get("min_n", 1),
            "max": request.get("max_n", 1),
            "zone": request.get("zone"),
            "skill_name": request.get("skill_name"),
            "cancelable": request.get("cancelable", True),
        }
        request["selection"] = selection_block
        try:
            payload = {
                "request_id": request_id,
                "game_id": request.get("game_id", self.game_id),
                "candidate_version": request.get("candidate_version"),
                "player_id": player.id,
                "kind": request.get("kind", "confirm"),
                "prompt": request.get("prompt", ""),
                "timeout": self.response_timeout,
                "options": [self._serialize_choice_option(o, i) for i, o in enumerate(request.get("options") or [])],
                "context": self._serialize_response_context(request.get("context") or {}),
                "selection": selection_block,
            }
            self._remember_prompt(request_id, ENGINE_EVENT.REQUIRE_RESPONSE, payload)
            await self.emit(ENGINE_EVENT.REQUIRE_RESPONSE, **payload)
            raw = await asyncio.wait_for(future, timeout=self.response_timeout)
            if isinstance(raw, dict) and raw.get("trustee"):
                return None, "trustee"
            if isinstance(raw, dict) and raw.get("cancel"):
                return None, "cancelled"
            if self.game_aborted:
                return None, "game_ended"
            return raw, "accepted"
        except asyncio.TimeoutError:
            logger.info(f"  ⏱️ 选择请求 {request_id} 超时，交规则托管")
            if self.game_aborted:
                return None, "game_ended"
            return None, "timeout"
        finally:
            self._close_request(request_id)

    def _choice_has_stale_candidates(self, request: Dict, raw) -> bool:
        """Detect a candidate that left its server-snapshotted zone while awaiting input."""
        indices = self._normalize_indices(raw)
        if request.get("kind") == "choose_cards":
            cards = request.get("candidate_cards") or []
            places = request.get("candidate_places") or []
            for index in indices:
                if not 0 <= index < len(cards):
                    continue
                owner, zone = places[index] if index < len(places) else (
                    request.get("card_owner"), request.get("zone", "hand")
                )
                if not self._card_in_zone(cards[index], owner, zone):
                    return True
        elif request.get("kind") == "choose_players":
            ids = request.get("candidate_ids") or []
            players = {p.id: p for p in self.game_state.players}
            for index in indices:
                if 0 <= index < len(ids):
                    target = players.get(ids[index])
                    if target is None or not target.alive:
                        return True
        return False

    async def request_choice(self, player: Player, request: Dict) -> Dict:
        """四交互原语的统一入口。"""
        if self.game_aborted:
            return {**self._empty_choice_result(request.get("kind", "confirm")), "status": "game_ended"}
        request_id = self._next_request_id()
        request = self._prepare_request(player, request, request_id)
        trustee_request = self._trustee_active and player is self.human_player()
        generation = self._trustee_generation
        if player.is_ai or trustee_request:
            raw = await self._ai_choose_choice(player, request)
            if trustee_request and generation != self._trustee_generation:
                if self._trustee_active:
                    raw = await self._ai_choose_choice(player, request)
                    input_status = "accepted"
                else:
                    raw, input_status = await self._human_choose_choice(player, request, request_id)
            else:
                input_status = "accepted"
        else:
            raw, input_status = await self._human_choose_choice(player, request, request_id)

        if input_status == "game_ended" or self.game_aborted:
            result, status = self._empty_choice_result(request.get("kind", "confirm")), "game_ended"
        elif input_status == "cancelled":
            result, status = self._empty_choice_result(request.get("kind", "confirm")), "cancelled"
        elif input_status in {"timeout", "trustee"}:
            if self.game_aborted:
                result, status = self._empty_choice_result(request.get("kind", "confirm")), "game_ended"
            else:
                raw = await self._trustee_choose_choice(player, request)
                if self.game_aborted:
                    result, status = self._empty_choice_result(request.get("kind", "confirm")), "game_ended"
                else:
                    result = self._resolve_choice(player, request, raw)
                    status = "timeout" if input_status == "timeout" else "resolved"
        elif self._choice_has_stale_candidates(request, raw):
            result, status = self._empty_choice_result(request.get("kind", "confirm")), "stale"
        else:
            result = self._resolve_choice(player, request, raw)
            if result.get("bool") or request.get("kind") == "confirm":
                status = "resolved"
            elif request.get("cancelable", True):
                status = "cancelled"
            else:
                status = "invalid"
        result.update({
            "status": status,
            "request_id": request_id,
            "candidate_version": request.get("candidate_version"),
        })
        await self._emit_selection_result(player, request, status)
        if (player.is_ai or trustee_request or input_status in {"timeout", "trustee"}) and not self.game_aborted:
            await self._emit_decision_trace(
                player, request.get("kind", "confirm"), len(request.get("options") or []),
                raw, status,
            )
        return result

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
        result = await self.ask_choose_cards_result(
            player, prompt, candidates, min_n=min_n, max_n=max_n, zone=zone,
            skill_name=skill_name, context=context, cancelable=cancelable,
            hidden_indices=hidden_indices, places=places,
        )
        return result.get("cards", [])

    async def ask_choose_cards_result(self, player: Player, prompt: str, candidates, *,
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
            return {"bool": False, "cards": [], "status": "invalid"}
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
        return await self.request_choice(player, request)

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
        decision_request = self._response_decision_view(request)
        trustee = self._trustee_active and player is self.human_player()
        if trustee and (self._trustee_source == "rules" or self._trustee_degraded):
            return self.ai_decision.simple_response_decision(player, decision_request)
        decision_player = self._trustee_view(player) if trustee else player
        handler = getattr(self.ai_decision, "make_response_decision", None)
        if handler is not None:
            try:
                result = await handler(decision_player, decision_request)
                if trustee:
                    self._update_trustee_failure(player)
                return result
            except Exception as exc:
                logger.info("  ⚠️ 响应AI失败，切换规则AI: %s", type(exc).__name__)
                if trustee:
                    self._trustee_failures += 1
                    self._trustee_degraded = self._trustee_failures >= 3
        return self.ai_decision.simple_response_decision(player, decision_request)

    async def _human_choose_option(self, player: Player, request: Dict, request_id: str):
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending_requests[request_id] = future
        self._pending_request_specs[request_id] = request
        self._mark_waiting_for_human()
        try:
            payload = {
                "request_id": request_id,
                "game_id": request.get("game_id", self.game_id),
                "candidate_version": request.get("candidate_version"),
                "player_id": player.id,
                "kind": request.get("kind", "respond"),
                "prompt": request.get("prompt", ""),
                "requested_name": request.get("requested_name"),
                "timeout": self.response_timeout,
                "selection": request.get("selection", {
                    "mode": "single", "min": 0, "max": 1, "cancelable": True,
                }),
                "options": [self._serialize_option(o, i) for i, o in enumerate(request.get("options") or [])],
                "context": self._serialize_response_context(request.get("context") or {}),
            }
            self._remember_prompt(request_id, ENGINE_EVENT.REQUIRE_RESPONSE, payload)
            await self.emit(ENGINE_EVENT.REQUIRE_RESPONSE, **payload)
            raw = await asyncio.wait_for(future, timeout=self.response_timeout)
            if isinstance(raw, dict) and raw.get("trustee"):
                return None, "trustee"
            if isinstance(raw, dict) and raw.get("cancel"):
                return None, "cancelled"
            if self.game_aborted:
                return None, "game_ended"
            return raw, "accepted"
        except asyncio.TimeoutError:
            logger.info(f"  ⏱️ 响应请求 {request_id} 超时，交规则托管")
            if self.game_aborted:
                return None, "game_ended"
            return None, "timeout"
        finally:
            self._close_request(request_id)

    def submit_response(self, request_id, selection) -> bool:
        """兼容旧调用方：详细回执由 submit_response_status 返回。"""
        return self.submit_response_status(request_id, selection)["success"]

    def submit_response_status(self, request_id, selection, *, player_id=0) -> Dict:
        """在唤醒等待者前验证请求、类型、数量和索引；非法输入可重试。"""
        def receipt(status, message):
            return {"request_id": request_id, "kind": "response", "status": status,
                    "success": status == "accepted", "message": message}

        if not isinstance(request_id, str):
            return receipt("invalid", "缺少有效的请求 ID")
        if self.game_aborted:
            return receipt("game_ended", "对局已结束，该选择未生效")
        future = self._pending_requests.get(request_id)
        if future is None:
            outcome = self._request_outcomes.get(request_id)
            if outcome == "accepted":
                return receipt("duplicate", "该请求已经应答")
            return receipt("stale", "请求已过期，请等待当前选择")
        if future.done():
            if self._request_outcomes.get(request_id) == "accepted":
                return receipt("duplicate", "该请求已经应答")
            return receipt("stale", "请求已过期，请等待当前选择")
        request = self._pending_request_specs[request_id]
        if player_id != request.get("player_id", 0):
            return receipt("invalid", "此请求不属于该玩家")
        kind = request.get("kind", "respond")
        is_multi = kind in ("choose_cards", "choose_players") and request.get("max_n", 1) > 1
        # 显式取消；另外兼容旧前端：可取消的单选请求收到空数组也视为取消
        # （此前会被当成"需要单个整数索引"，界面上表现为取消时报参数错误）。
        wants_cancel = (isinstance(selection, dict) and selection.get("cancel") is True) or (
            not is_multi and isinstance(selection, list) and not selection
            and request.get("cancelable", True))
        if wants_cancel:
            if not request.get("cancelable", True):
                return receipt("invalid", "此请求不可取消")
            self._note_human_input()
            future.set_result({"cancel": True})
            self._request_outcomes[request_id] = "accepted"
            return receipt("accepted", "已接收取消")
        if is_multi:
            if not isinstance(selection, list):
                return receipt("invalid", "此请求需要索引数组")
            value = selection
        elif isinstance(selection, int) and not isinstance(selection, bool):
            value = selection
        else:
            return receipt("invalid", "此请求需要单个整数索引")
        indices = value if is_multi else [value]
        if (not all(isinstance(i, int) and not isinstance(i, bool) for i in indices)
                or len(indices) != len(set(indices))
                or any(i < 0 or i >= len(request.get("options") or []) for i in indices)):
            return receipt("invalid", "选项索引无效或重复")
        if is_multi:
            min_n, max_n = self._choice_limits(request)
            if not min_n <= len(indices) <= max_n:
                return receipt("invalid", f"请选择 {min_n} 至 {max_n} 项")
        self._note_human_input()
        future.set_result(value)
        self._request_outcomes[request_id] = "accepted"
        return receipt("accepted", "已接收选择")

    # ---------- 托管兜底与离席看门狗 ----------

    def trustee_status(self) -> Dict:
        return {
            "enabled": self._trustee_active,
            "source": self._trustee_source if self._trustee_active else None,
            "model": self._trustee_config.get("model") if self._trustee_active and not self._trustee_degraded else None,
            "failures": self._trustee_failures if self._trustee_active else 0,
            "degraded": bool(self._trustee_active and self._trustee_degraded),
            "degrade_reason": self._trustee_degrade_reason if self._trustee_active else None,
        }

    def set_trustee(self, enabled: bool, *, source="rules", player_id=None, config=None) -> Dict:
        """Set one human's takeover source without changing their cards or identity."""
        if self.game_aborted:
            raise ValueError("对局已结束")
        if not enabled:
            self._trustee_active = False
            self._trustee_generation += 1
            self._human_idle_since = None
            return self.trustee_status()
        if source not in {"default", "copy_ai", "custom", "rules"}:
            raise ValueError("未知托管来源")
        connection = {}
        if source == "default":
            connection = normalize_ai(self.game_config.get("trustee_default") or {}, use_default=True)
        elif source == "copy_ai":
            candidate = next((p for p in self.game_state.players
                              if p.id == player_id and p.is_ai), None)
            if candidate is None:
                raise ValueError("复制来源不是场上 AI")
            connection = dict(candidate.ai_config or {})
        elif source == "custom":
            if not isinstance(config, dict):
                raise ValueError("托管配置必须是对象")
            connection = normalize_ai(config, use_default=False)
        allowed = {"provider", "model", "api_url", "base_url", "temperature", "thinking", "api_key"}
        self._trustee_config = {key: value for key, value in connection.items() if key in allowed}
        self._trustee_source = source
        self._trustee_active = True
        self._trustee_failures = 0
        self._trustee_degraded = source != "rules" and not bool(self._trustee_config.get("api_key"))
        self._trustee_degrade_reason = "missing_api_key" if self._trustee_degraded else None
        self._trustee_generation += 1
        self._human_idle_since = None
        # Wake a pending turn/selection so the takeover starts immediately.
        for future in self._pending_requests.values():
            if not future.done():
                future.set_result({"trustee": True})
        self._player_input = {"action": {"type": "trustee"}, "target_ids": []}
        if self._player_event is not None and not self._player_event.is_set():
            self._player_event.set()
        return self.trustee_status()

    def _trustee_view(self, player):
        return _TrusteePlayerView(player, self._trustee_config)

    async def _trustee_make_decision(self, player, actions):
        generation = self._trustee_generation
        if self._trustee_source == "rules" or self._trustee_degraded:
            decision = self.ai_decision.simple_ai_decision(player, actions)
        else:
            decision = await self.ai_decision.make_decision(self._trustee_view(player), actions)
            self._update_trustee_failure(player)
        return decision if self._trustee_active and generation == self._trustee_generation else None

    def _update_trustee_failure(self, player):
        failure = getattr(self.ai_decision, "last_failure", {}).get(player.id)
        if failure:
            self._trustee_failures += 1
            if self._trustee_failures >= 3:
                self._trustee_degraded = True
                self._trustee_degrade_reason = "three_failures"
        else:
            self._trustee_failures = 0

    def _mark_waiting_for_human(self):
        """引擎开始等真人。已经在计时就不重新打点，保证是累计而不是每次重置。"""
        if not self._trustee_active and self._human_idle_since is None:
            self._human_idle_since = self.time_source()

    def _note_human_input(self):
        """收到任何真人输入即清零，并解除托管状态。"""
        self._human_idle_since = None
        self._trustee_active = False
        self._trustee_generation += 1

    def idle_seconds(self) -> float:
        if self._human_idle_since is None:
            return 0.0
        return float(self.time_source() - self._human_idle_since)

    async def _trustee_choose(self, player: Player, request: Dict):
        """Resolve a timed out response through the configured takeover source."""
        if self._abort_reason:
            return None
        if not self._trustee_active:
            self.set_trustee(True, source="rules")
        index = await self._ai_choose_option(player, request)
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
        if self.game_aborted:
            return
        minutes = self.idle_abort_seconds / 60
        self._abort_reason = "idle_timeout"
        self._trustee_active = False
        self.game_state.game_over = True
        self.game_state.winner = "aborted"
        self.game_state.end_message = (
            f"真人玩家离席超过{minutes:.0f}分钟，本局自动结束。服务器仍在运行，刷新页面即可重开。"
        )
        # 立刻取消在途聊天（幂等，与 run() 的 finally 不冲突）。
        self.chat_director.shutdown()
        await self.log_event(self.game_state.end_message, important=True, abort_reason="idle_timeout")

        # 唤醒所有挂起的响应请求，否则等待中的协程会永久挂住。
        for request_id, future in list(self._pending_requests.items()):
            self._request_outcomes[request_id] = "game_ended"
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
        if self.game_aborted:
            return []
        if self.game_state.current_phase != Phase.PLAY or player != self.game_state.current_player or not player.alive:
            return [{"type": "end_phase"}]

        playable_cards = list(player.hand)
        if getattr(player.equipment.get("treasure"), "name", None) == "木牛流马":
            playable_cards.extend(player.treasure_cards)
        for i, card in enumerate(playable_cards):
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
                    if (card.name == "杀" and i < len(player.hand)
                            and len(player.hand) == 1
                            and getattr(player.equipment.get("weapon"), "name", None) == "方天画戟"):
                        groups = [list(group) for count in range(1, min(3, len(valid)) + 1)
                                  for group in permutations(valid, count)]
                        actions.append({"type": "play_card", "card_index": i,
                                        "card": card_to_dict(card, include_id=False),
                                        "requires_target": True, "target_count": 3,
                                        "min_target_count": 1,
                                        "valid_target_groups": groups,
                                        "valid_targets": valid})
                        continue
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

        # 军争重铸：出牌阶段可把可重铸的牌（铁索连环）置入弃牌堆并摸一张牌；不是使用，无目标、不可被无懈。
        for i, card in enumerate(player.hand):
            spec = CARD_TABLE.get(card.name)
            if spec is not None and spec.recast:
                actions.append({"type": "recast", "card_index": i,
                                "card": card_to_dict(card, include_id=False),
                                "requires_target": False, "valid_targets": [],
                                "text": f"重铸{card_label(card)}"})

        # 木牛流马存牌是装备主动操作，输入索引始终指向真正手牌。
        if (getattr(player.equipment.get("treasure"), "name", None) == "木牛流马"
                and not player.flags.get("muniu_stored_this_turn")):
            for i in range(len(player.hand)):
                actions.append({"type": "use_skill", "skill_name": "木牛流马",
                                "variant": "store", "card_indices": [i],
                                "requires_target": False, "valid_targets": [],
                                "text": "将一张手牌扣置于木牛流马"})
        if (getattr(player.equipment.get("weapon"), "name", None) == "丈八蛇矛"
                and player.sha_count < player.max_sha):
            # 每组双牌代价都用同一合法杀目标校验，避免技能按钮绕过射程。
            for first, second in combinations(range(len(player.hand)), 2):
                virtual = Card(f"zhangba:{player.hand[first].id}:{player.hand[second].id}",
                               "杀", "none", 1, "basic")
                valid = [target.id for target in self.game_state.players
                         if target.alive and target is not player
                         and self.rules.can_play_sha(player, virtual, [target])[0]]
                if valid:
                    actions.append({"type": "use_skill", "skill_name": "丈八蛇矛",
                                    "variant": "as_sha", "card_indices": [first, second],
                                    "requires_target": True, "valid_targets": valid,
                                    "text": "将两张手牌当【杀】使用"})
        # 只有运行状态为active且满足当前条件的技能才作为合法操作暴露。
        actions.extend(self.skill_manager.get_actions(player))
        actions.append({"type": "end_phase"})
        return actions

    # ---------- 执行操作 ----------

    async def execute_action(self, player: Player, action: Dict, target_ids: List = None) -> bool:
        if self.game_aborted or player != self.game_state.current_player or not player.alive:
            return False
        action_type = action.get("type")
        try:
            if action_type == "play_card":
                card_index = action.get("card_index")
                playable_cards = list(player.hand)
                if getattr(player.equipment.get("treasure"), "name", None) == "木牛流马":
                    playable_cards.extend(player.treasure_cards)
                if not isinstance(card_index, int) or not 0 <= card_index < len(playable_cards):
                    return False
                card = playable_cards[card_index]
                source_zone = "hand" if card_index < len(player.hand) else "treasure"
                source_index = card_index if source_zone == "hand" else card_index - len(player.hand)
                target_ids = target_ids or []
                players_by_id = {p.id: p for p in self.game_state.players}
                targets = [players_by_id[pid] for pid in target_ids if pid in players_by_id]
                can_play, reason = self.rules.can_play_card(player, card, targets)
                if not can_play:
                    logger.info(f"  ❌ 不能出牌: {reason}")
                    return False

                # 先广播“使用牌”，使客户端按正确顺序展示：使用牌 → 响应牌 → 弃牌堆。
                effect_context = self._new_effect_context(
                    player, card, target=targets[0] if targets else None,
                )
                effect_context.last_hand_card = source_zone == "hand" and len(player.hand) == 1
                await self._notify_card_ui(
                    message=f"{player.name}使用{card_label(card)}"
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
                    effect_id=effect_context.effect_id,
                    discard_count=len(self.game_state.discard_pile) + 1,
                )
                if self.game_aborted:
                    return False
                move = await self.move_card(
                    card, source_zone, "discard", from_owner=player,
                    reason="use_card", actor_id=player.id,
                    effect_id=effect_context.effect_id, project=False,
                )
                if move is None:
                    return False
                success = await self.card_system.use_card(
                    player, card, targets, effect_context=effect_context,
                )
                # 正常击杀可在此处结束对局；已提交的用牌仍应计入统计并回报成功。
                if self._abort_reason:
                    return False
                if not success:
                    await self.move_card(
                        card, "discard", source_zone, to_owner=player,
                        reason="use_card_failed", actor_id=player.id,
                        effect_id=effect_context.effect_id, project=False,
                        to_index=source_index,
                    )
                if success:
                    await self.skill_manager.on_card_move(card, move)
                    # 延时锦囊与装备已离开弃牌区，不触发“被弃置”技能。
                    if not self.game_state.game_over and card in self.game_state.discard_pile:
                        await self.skill_manager.on_card_discarded(player, card, "use_card")
                if not self.game_state.game_over:
                    await self.skill_manager.after_card_used(player, card, targets, success)
                return success

            if action_type == "recast":
                return await self._execute_recast(player, action)

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
                if legal.get("skill_name") == "木牛流马" and legal.get("variant") == "store":
                    return await self.card_system.store_muniu(player, legal["card_indices"][0])
                if legal.get("skill_name") == "丈八蛇矛" and legal.get("variant") == "as_sha":
                    return await self.card_system.use_zhangba(player, legal["card_indices"],
                                                              targets[0] if targets else None)
                return await self.skill_manager.execute(player, legal, targets)

            if action_type == "end_phase":
                return True
            return False
        except Exception as exc:
            logger.info(f"  ❌ 执行出错: {exc}")
            import traceback

            traceback.print_exc()
            return False

    async def _execute_recast(self, player: Player, action: Dict) -> bool:
        """重铸：引擎按合法操作列表复核 → 手牌移入弃牌堆（reason 重铸）→ 摸一张牌。

        重铸不是“使用”：不走 use_card、不询问无懈可击、不记行为账本、不计入出牌统计。"""
        index = action.get("card_index")
        if not isinstance(index, int) or isinstance(index, bool):
            return False
        legal = next((a for a in self.get_available_actions(player)
                      if a.get("type") == "recast" and a.get("card_index") == index), None)
        if legal is None or not 0 <= index < len(player.hand):
            logger.info("  ❌ 重铸不在当前合法操作列表")
            return False
        card = player.hand[index]
        await self._notify_card_ui(
            message=f"{player.name}重铸{card_label(card)}（置入弃牌堆，摸一张牌）",
            actor_id=player.id, actor_name=player.name, source_name=player.name,
            card_name=card.name, card_index=index, card=card_to_dict(card),
            reason="recast", discard_count=len(self.game_state.discard_pile) + 1,
        )
        if self.game_aborted:
            return False
        move = await self.move_card(card, "hand", "discard", from_owner=player,
                                    reason="重铸", actor_id=player.id)
        if move is None:
            return False
        await self.draw_cards(player, 1, reason="重铸")
        return True

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
            cheat=self.cheat_mode,
            total_rounds=self.game_state.round_number,
            spy_duel_lord=self.spy_duel_lord,
        )
        return True
    async def request_end_game(self, reason: str = "玩家主动结束游戏"):
        if self.game_aborted:
            return False
        self.game_state.game_over = True
        self.game_state.winner = "aborted"
        self.game_state.end_message = reason
        # 立刻取消在途聊天（shutdown 幂等，run() 的 finally 里再调一次无副作用）。
        self.chat_director.shutdown()
        # 与离席看门狗一致：挂起的交互请求不得在收摊后继续落地效果。
        self._abort_reason = self._abort_reason or "player_end_game"
        for request_id, future in list(self._pending_requests.items()):
            self._request_outcomes[request_id] = "game_ended"
            if not future.done():
                future.set_result(None)
        self._player_input = {"action": {"type": "end_phase"}, "target_ids": []}
        if self._player_event and not self._player_event.is_set():
            self._player_event.set()
        await self._emit_game_end_once()
        return True

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
