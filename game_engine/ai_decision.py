#!/usr/bin/env python3
"""AI决策系统：合法操作约束、多Provider调用与世界书注入。"""

import json
import os
import random
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from card_system import option_label


class WorldbookManager:
    """按需加载武将、卡牌和阶段世界书。"""

    def __init__(self, worldbook_dir: str = "worldbook_generated"):
        self.worldbook_dir = worldbook_dir
        self.cache: Dict[str, List[Dict]] = {}
        self._global_rules_cache: Optional[str] = None
        self._load_all_data()

    def _load_all_data(self):
        base_path = os.path.join(os.path.dirname(__file__), "..", self.worldbook_dir)

        heroes_path = os.path.join(base_path, "heroes", "heroes_27_complete.json")
        if os.path.exists(heroes_path):
            with open(heroes_path, "r", encoding="utf-8") as f:
                self.cache["heroes"] = json.load(f).get("heroes", [])

        self.cache["cards"] = []
        for card_type in ["basic_cards", "trick_cards", "equipment_cards"]:
            card_path = os.path.join(base_path, "cards", f"{card_type}.json")
            if os.path.exists(card_path):
                with open(card_path, "r", encoding="utf-8") as f:
                    self.cache["cards"].extend(json.load(f).get("cards", []))

        rules_path = os.path.join(base_path, "rules", "game_flow.json")
        if os.path.exists(rules_path):
            with open(rules_path, "r", encoding="utf-8") as f:
                self.cache["phases"] = json.load(f).get("phases", [])

    @staticmethod
    def _hero_id(player) -> str:
        hero = getattr(player, "hero", None)
        if isinstance(hero, dict):
            return hero.get("id", "")
        return getattr(hero, "id", "") if hero else ""

    def get_hero_worldbook(self, hero_id: str) -> str:
        hero = next((h for h in self.cache.get("heroes", []) if h.get("id") == hero_id), None)
        if not hero:
            return ""
        lines = [f"【{hero['name']}】{hero['faction']}势力，{hero['max_hp']}点体力", "你的技能："]
        for skill in hero.get("skills", []):
            lines.append(f"- 【{skill['name']}】{skill.get('worldbook', skill.get('description', ''))}")
        return "\n".join(lines)

    def get_phase_worldbook(self, phase: str) -> str:
        info = next((p for p in self.cache.get("phases", []) if p.get("id") == phase), None)
        if not info:
            return ""
        lines = [f"【{info['name']}】{info.get('description', '')}"]
        if info.get("actions"):
            lines.append("可执行操作：" + "；".join(info["actions"]))
        if info.get("ai_considerations"):
            lines.append("AI提示：" + info["ai_considerations"])
        return "\n".join(lines)

    # ---------- 三层前缀分层：L0 全局 / L1 角色 / L2 局势 ----------

    def build_global_rules(self) -> str:
        """L0 全局层：整局不变，且**与玩家无关**。

        构造函数刻意不接收 player 参数 —— 从物理上杜绝把玩家名/身份/手牌混进来（R14），
        这是「多个AI玩家用同一模型时也能跨玩家命中缓存」成立的唯一前提。
        """
        if self._global_rules_cache is not None:
            return self._global_rules_cache

        lines = [
            "【三国杀通用规则】",
            "- 回合流程：准备 → 判定 → 摸牌 → 出牌 → 弃牌 → 结束。",
            "- 出牌阶段每回合限用1张【杀】（技能可突破）；手牌上限等于当前体力值。",
            "- 体力降到0进入濒死，按座次逐个询问是否使用【桃】；无人施救即阵亡。",
            "- 身份局胜负：主公与忠臣需杀光反贼与内奸；反贼杀死主公即胜；内奸需最后与主公单挑取胜。",
            "",
            "【卡牌效果表】",
        ]
        seen = set()
        for card in self.cache.get("cards", []):
            name = card.get("name")
            if not name or name in seen:
                continue
            seen.add(name)
            effect = card.get("effect") or card.get("worldbook") or ""
            lines.append(f"- 【{name}】{effect}")

        lines += [
            "",
            "【硬约束】",
            "- 游戏引擎是唯一真理来源。合法性由引擎判定，你只能从引擎给出的候选里挑一个索引。",
            "- 不得自造卡牌、技能、目标，不得越界索引，不得推测其他角色的隐藏身份为已知事实。",
            "- 回复必须是可解析的JSON，不要加解释性前后缀。",
        ]
        self._global_rules_cache = "\n".join(lines)
        return self._global_rules_cache

    def build_static_worldbook(self, player, game_state=None) -> str:
        """L1 角色层：整局不变，单个玩家专属。"""
        sections = [f"你是{player.name}，身份：{player.identity or '未知'}"]
        hero_text = self.get_hero_worldbook(self._hero_id(player))
        if hero_text:
            sections.append(hero_text)
        if game_state is not None:
            seats = "、".join(
                f"{i}号位 {p.name}({(p.hero or {}).get('name', '未知武将') if isinstance(p.hero, dict) else '未知武将'})"
                for i, p in enumerate(game_state.players)
            )
            sections.append(f"开局座次：{seats}")
        return "\n\n".join(sections)

    def build_situation(self, player, game_state, available_actions: List[Dict] = None) -> str:
        """L2 局势层：每次都变，只追加在消息列表末尾。"""
        sections = []
        phase = getattr(game_state.current_phase, "value", game_state.current_phase)
        phase_text = self.get_phase_worldbook(phase)
        if phase_text:
            sections.append(phase_text)

        others = []
        for p in game_state.players:
            if p.alive and p.id != player.id:
                hero = p.hero if isinstance(p.hero, dict) else {}
                identity = p.identity if getattr(p, "identity_revealed", False) else "身份未公开"
                skills = "、".join(
                    f"{s.get('name')}[{s.get('implementation_status', 'data_only')}]"
                    for s in hero.get('skills', []) if isinstance(s, dict)
                ) or "无"
                others.append(
                    f"{p.name}/{hero.get('name', '未知武将')}：{p.hp}/{p.max_hp}体力，{len(p.hand)}手牌，{identity}，公开技能={skills}"
                )
        if others:
            sections.append("场上角色：\n" + "\n".join(f"- {x}" for x in others))

        if player.hand:
            hand = "、".join(f"{i}:{c.name}({c.suit}{c.rank})" for i, c in enumerate(player.hand))
            sections.append(f"你的手牌：{hand}")
        return "\n\n".join(sections)

    def build_full_worldbook(self, player, game_state, available_actions: List[Dict]) -> str:
        """保留旧接口：静态层与局势层的拼接，老调用点行为不变。"""
        static_part = self.build_static_worldbook(player)
        situation = self.build_situation(player, game_state, available_actions)
        return "\n\n".join(x for x in (static_part, situation) if x)



class AIDecision:
    """AI只能从引擎生成的操作列表中选择，不允许自行构造规则外操作。"""

    def __init__(self, game_engine):
        self.engine = game_engine
        self.gateway = AIGateway()
        self.worldbook_manager = WorldbookManager()
        # 每个AI玩家整局一个会话窗口，只追加不重排，出牌/响应/聊天共用。
        self._sessions: Dict[int, Dict] = {}
        config = getattr(game_engine, "game_config", {}) or {}
        self.session_max_l2 = int(config.get("session_max_l2", 24))
        self.session_max_chars = int(config.get("session_max_chars", 12000))
        self.cache_stats_path = os.path.join(
            os.path.dirname(__file__), "..", "logs", "runtime", "ai_cache_stats.jsonl"
        )

    # ---------- 会话窗口 ----------

    SUMMARY_MARK = "【前情概要】"

    def _session_signature(self, player) -> str:
        """任一影响前缀的配置变了，签名就变，窗口整体重建（R13）。"""
        config = player.ai_config or {}
        settings = self.engine.game_config.get("global_settings") or {}
        return "|".join([
            str(config.get("provider", "")), str(config.get("model", "")),
            str(config.get("api_url") or config.get("base_url") or ""),
            str(bool(settings.get("worldbook_enabled", True))),
        ])

    def get_session(self, player) -> Dict:
        signature = self._session_signature(player)
        session = self._sessions.get(player.id)
        if session is None or session["signature"] != signature:
            session = {
                "signature": signature,
                "messages": [
                    {"role": "system", "content": self.worldbook_manager.build_global_rules()},
                    {"role": "system", "content": self.worldbook_manager.build_static_worldbook(
                        player, self.engine.game_state)},
                ],
                "prefix_len": 2,
                "has_summary": False,
                "l2_count": 0,
                "compressions": 0,
            }
            self._sessions[player.id] = session
        return session

    def reset_session(self, player_id: int):
        self._sessions.pop(player_id, None)

    @staticmethod
    def _session_chars(session: Dict) -> int:
        return sum(len(m.get("content", "")) for m in session["messages"])

    def maybe_compress(self, session: Dict):
        """超限时**一次性**把最老的一批压成一条摘要并重建，而不是逐条滑窗删除（R12）。

        摘要恒定只有一条：再次压缩时把旧摘要一起卷进新摘要，不让摘要越堆越多。
        prefix_len 始终是 L0/L1 两条 —— 摘要每次压缩都会变，不能算进缓存断点。
        """
        over_count = session["l2_count"] >= self.session_max_l2
        over_chars = self._session_chars(session) > self.session_max_chars
        if not (over_count or over_chars):
            return False

        base = session["prefix_len"]
        body = session["messages"][base:]
        old_summary = body.pop(0)["content"] if session["has_summary"] else ""
        old_summary = old_summary.replace(self.SUMMARY_MARK, "", 1)
        keep = max(1, len(body) // 3)          # 保留最近三分之一的原文
        old, recent = body[:-keep], body[-keep:]
        if not old:
            return False

        digest = " / ".join(
            m["content"].replace("\n", " ")[:80] for m in old if m.get("role") != "system"
        )
        merged = (old_summary + " / " + digest) if old_summary else digest
        # 截断保留**最近**的内容，且标记必须留在最前面，否则下次识别不出这是摘要。
        summary = {"role": "user", "content": self.SUMMARY_MARK + merged[-1500:]}
        session["messages"] = session["messages"][:base] + [summary] + recent
        session["has_summary"] = True
        session["l2_count"] = len(recent)
        session["compressions"] += 1
        print(f"  🗜️ 会话窗口压缩：{len(old)}条 → 并入摘要（第{session['compressions']}次）")
        return True

    def push_user(self, player, content: str) -> List[Dict]:
        """追加一条 L2 局势消息，返回本次要发送的完整消息列表。"""
        session = self.get_session(player)
        self.maybe_compress(session)
        session["messages"].append({"role": "user", "content": content})
        session["l2_count"] += 1
        return list(session["messages"])

    def push_assistant(self, player, content: str):
        if content:
            self.get_session(player)["messages"].append({"role": "assistant", "content": content})

    def record_outcome(self, player, text: str):
        """把引擎的实际执行结果回灌进窗口，让AI记得自己刚干了什么。"""
        if not text or player.id not in self._sessions:
            return
        self._sessions[player.id]["messages"].append({"role": "user", "content": text})

    def _log_cache_stats(self, player, kind: str, usage: Optional[Dict]):
        """把真实 usage 落盘。取不到就写 null，绝不用估算值冒充实测值。"""
        usage = usage or {}
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "player_id": player.id,
            "provider": (player.ai_config or {}).get("provider"),
            "model": (player.ai_config or {}).get("model"),
            "kind": kind,
            "prompt_tokens": usage.get("prompt_tokens"),
            "cached_tokens": usage.get("cached_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
        }
        try:
            os.makedirs(os.path.dirname(self.cache_stats_path), exist_ok=True)
            with open(self.cache_stats_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            print(f"  ⚠️ 缓存统计写入失败: {type(exc).__name__}: {exc}")

    async def _call_with_session(self, player, kind: str, content: str) -> str:
        """统一的带会话窗口调用：追加L2 → 调API → 追加assistant → 记账。"""
        messages = self.push_user(player, content)
        reply, usage = await self.gateway.call_ai(
            provider=player.ai_config.get("provider", "deepseek"),
            model=player.ai_config.get("model", "deepseek-chat"),
            api_key=player.ai_config.get("api_key", ""),
            messages=messages,
            temperature=player.ai_config.get("temperature", 0.8),
            base_url=player.ai_config.get("api_url") or player.ai_config.get("base_url"),
            return_usage=True,
            cache_prefix_len=self.get_session(player)["prefix_len"],
        )
        self.push_assistant(player, reply)
        self._log_cache_stats(player, kind, usage)
        return reply

    async def make_decision(self, player, available_actions: List[Dict]) -> Dict:
        api_key = player.ai_config.get("api_key", "")
        if not api_key or api_key == "test_key":
            return self.simple_ai_decision(player, available_actions)

        try:
            response = await self._call_with_session(
                player, "decision", self.build_decision_turn_message(player, available_actions)
            )
            return self.parse_ai_response(response, player, available_actions)
        except Exception as exc:
            print(f"  ⚠️ AI调用失败，切换规则AI: {type(exc).__name__}: {exc}")
            return self.simple_ai_decision(player, available_actions)

    def _custom_worldbook_text(self, player) -> str:
        """自定义世界书按关键词命中，内容随手牌/阶段变化，因此归 L2 而不进前缀。"""
        settings = self.engine.game_config.get("global_settings") or {}
        if not settings.get("custom_worldbook_enabled", True):
            return ""
        custom_entries = self.engine.game_config.get("custom_worldbook") or []
        context = " ".join(
            [self.worldbook_manager._hero_id(player), self.engine.game_state.current_phase.value]
            + [c.name for c in player.hand]
        ).lower()
        selected = []
        for entry in custom_entries:
            keywords = [str(k).lower() for k in entry.get("keywords", [])]
            if entry.get("constant") or any(k and k in context for k in keywords):
                selected.append(f"【自定义世界书·{entry.get('title', entry.get('id', '条目'))}】{entry.get('content', '')}")
            if sum(len(x) for x in selected) >= 3000:
                break
        return "\n".join(selected)

    def build_decision_turn_message(self, player, available_actions: List[Dict]) -> str:
        """L2 局势层：只含每次都变的内容，追加在会话窗口末尾。"""
        settings = self.engine.game_config.get("global_settings") or {}
        if settings.get("worldbook_enabled", True):
            situation = self.worldbook_manager.build_situation(player, self.engine.game_state, available_actions)
        else:
            situation = "内置世界书已在全局设置中关闭。"

        custom = self._custom_worldbook_text(player)
        if custom:
            situation += "\n\n" + custom

        action_lines = [f"{i}. {self.format_action(action)}" for i, action in enumerate(available_actions)]
        return f"""{situation}

当前局势：第{self.engine.game_state.round_number}轮，你的体力为{player.hp}/{player.max_hp}。

合法操作列表（索引从0开始）：
{chr(10).join(action_lines)}

只返回JSON：
{{"action_index": 0, "target_ids": [1], "chat_message": "可选短句", "reasoning": "简短理由"}}
目标必须来自所选操作的合法目标列表。不能新增操作、卡牌或目标。"""

    def build_decision_prompt_with_worldbook(self, player, available_actions: List[Dict]) -> str:
        """保留旧接口：静态层 + 局势层的单串拼接（不走会话窗口时使用）。"""
        settings = self.engine.game_config.get("global_settings") or {}
        static_part = ""
        if settings.get("worldbook_enabled", True):
            static_part = self.worldbook_manager.build_static_worldbook(player, self.engine.game_state)
        turn_part = self.build_decision_turn_message(player, available_actions)
        return "\n\n".join(x for x in (static_part, turn_part) if x)

    @staticmethod
    def format_action(action: Dict) -> str:
        action_type = action.get("type", "")
        if action_type == "play_card":
            card = action.get("card") or {}
            text = f"使用手牌#{action.get('card_index')}【{card.get('name', '未知')}】"
            if action.get("requires_target"):
                text += f"，合法目标={action.get('valid_targets', [])}"
            return text
        if action_type == "use_skill":
            text = f"发动【{action.get('skill_name')}】/{action.get('variant', 'default')}"
            if action.get("card_indices"):
                text += f"，消耗手牌索引={action.get('card_indices')}"
            if action.get("description"):
                text += f"，效果={action.get('description')}"
            if action.get("requires_target"):
                text += f"，合法目标={action.get('valid_targets', [])}"
            return text
        if action_type == "end_phase":
            return "结束出牌阶段"
        return json.dumps(action, ensure_ascii=False)

    def parse_ai_response(self, response: str, player, available_actions: List[Dict]) -> Dict:
        try:
            match = re.search(r"\{.*\}", response, re.DOTALL)
            payload = json.loads(match.group(0) if match else response)
            index = payload.get("action_index")

            # 兼容旧格式，但最终仍映射回引擎给出的某一项。
            if not isinstance(index, int):
                requested_type = payload.get("action") or payload.get("type")
                requested_card_index = payload.get("card_index")
                index = next(
                    (
                        i
                        for i, action in enumerate(available_actions)
                        if action.get("type") == requested_type
                        and (requested_card_index is None or action.get("card_index") == requested_card_index)
                    ),
                    None,
                )

            if not isinstance(index, int) or not 0 <= index < len(available_actions):
                raise ValueError("action_index不在合法操作范围内")

            action = dict(available_actions[index])
            target_ids = self._normalize_targets(action, payload.get("target_ids", []), player)
            return {
                "action": action,
                "target_ids": target_ids,
                "chat": str(payload.get("chat_message", ""))[:40],
                "reasoning": str(payload.get("reasoning", ""))[:200],
            }
        except Exception as exc:
            print(f"  ⚠️ AI响应解析失败，切换规则AI: {type(exc).__name__}: {exc}")
            return self.simple_ai_decision(player, available_actions)

    def _normalize_targets(self, action: Dict, requested: Any, player) -> List[int]:
        valid = list(action.get("valid_targets", []))
        if not action.get("requires_target"):
            return []
        if not isinstance(requested, list):
            requested = []
        chosen = [tid for tid in requested if tid in valid]
        if chosen:
            return chosen[:1]
        return self._choose_target(player, valid)

    def _choose_target(self, player, valid_ids: List[int]) -> List[int]:
        if not valid_ids:
            return []
        players = {p.id: p for p in self.engine.game_state.players}
        candidates = [players[pid] for pid in valid_ids if pid in players]
        if not candidates:
            return []

        # 规则AI也只能使用公开身份，不能读取其他玩家的隐藏身份。
        enemies = []
        if player and player.identity == "rebel":
            enemies = [p for p in candidates if p.identity_revealed and p.identity == "lord"]
        elif player and player.identity in ("lord", "loyalist"):
            enemies = [p for p in candidates if p.identity_revealed and p.identity in ("rebel", "spy")]
            if not enemies:
                enemies = [p for p in candidates if not (p.identity_revealed and p.identity == "lord")]
        elif player and player.identity == "spy":
            enemies = [p for p in candidates if not (p.identity_revealed and p.identity == "spy")]

        pool = enemies or candidates
        pool.sort(key=lambda p: (p.hp, len(p.hand), p.id))
        return [pool[0].id]

    def simple_ai_decision(self, player, available_actions: List[Dict]) -> Dict:
        if not available_actions:
            return {"action": {"type": "end_phase"}, "target_ids": []}

        playable = [a for a in available_actions if a.get("type") != "end_phase"]
        priorities = []
        if player and player.hp < player.max_hp:
            priorities.append("桃")
        priorities.extend(["杀", "过河拆桥", "顺手牵羊"])

        selected: Optional[Dict] = None
        for name in priorities:
            selected = next(
                (a for a in playable if (a.get("card") or {}).get("name") == name),
                None,
            )
            if selected:
                break
        if not selected:
            skill_priority = ["替身", "仁德", "集智", "武圣", "龙胆", "激将", "义绝"]
            for skill_name in skill_priority:
                selected = next((a for a in playable if a.get("type") == "use_skill" and a.get("skill_name") == skill_name), None)
                if selected:
                    break
        if not selected and playable:
            selected = playable[0]
        if not selected:
            selected = next((a for a in available_actions if a.get("type") == "end_phase"), available_actions[-1])

        action = dict(selected)
        return {
            "action": action,
            "target_ids": self._normalize_targets(action, [], player),
            "chat": "",
            "reasoning": "规则AI兜底",
        }

    # ---------- 场外响应的真决策 ----------

    RESPONSE_SYSTEM_PROMPT = (
        "你是三国杀玩家，现在轮到你做一次回合外响应。"
        "游戏引擎是唯一规则来源：你只能从下面给出的候选里挑一个索引，不能自造牌、自造技能、自造目标。"
    )

    @staticmethod
    def _describe_context(context: Dict) -> str:
        parts = []
        source = (context or {}).get("source")
        target = (context or {}).get("target")
        card = (context or {}).get("card")
        if source is not None:
            parts.append(f"来源：{getattr(source, 'name', source)}")
        if target is not None:
            parts.append(f"目标：{getattr(target, 'name', target)}")
        if card is not None:
            parts.append(f"触发牌：{getattr(card, 'name', card)}")
        return "；".join(parts)

    def build_response_prompt(self, player, request: Dict) -> str:
        """L2 局势层（响应版）：与出牌决策共用同一会话窗口，因此不重复静态人设。"""
        settings = self.engine.game_config.get("global_settings") or {}
        if settings.get("worldbook_enabled", True):
            situation = self.worldbook_manager.build_situation(player, self.engine.game_state, [])
        else:
            situation = "内置世界书已在全局设置中关闭。"

        options = request.get("options") or []
        option_lines = [f"{i}. {option_label(option)}" for i, option in enumerate(options)]
        context_text = self._describe_context(request.get("context") or {})
        return f"""{self.RESPONSE_SYSTEM_PROMPT}

{situation}

当前局势：第{self.engine.game_state.round_number}轮，你的体力为{player.hp}/{player.max_hp}。

响应请求：{request.get('prompt', '')}
需要打出：{request.get('requested_name') or '（无指定）'}
{('触发情境：' + context_text) if context_text else ''}

候选列表（索引从0开始，最后一项是放弃响应）：
{chr(10).join(option_lines)}

只返回JSON：
{{"option_index": 0, "reasoning": "简短理由"}}
索引必须来自上面的候选列表，不能新增任何选项。"""

    async def make_response_decision(self, player, request: Dict) -> Optional[int]:
        """回合外响应的AI真决策。返回候选索引；None 表示不响应。"""
        api_key = player.ai_config.get("api_key", "")
        if not api_key or api_key == "test_key":
            return self.simple_response_decision(player, request)
        if not (self.engine.game_config.get("global_settings") or {}).get("response_ai_enabled", True):
            return self.simple_response_decision(player, request)

        try:
            response = await self._call_with_session(
                player, "response", self.build_response_prompt(player, request)
            )
            return self.parse_response_choice(response, player, request)
        except Exception as exc:
            print(f"  ⚠️ 响应AI调用失败，切换规则AI: {type(exc).__name__}: {exc}")
            return self.simple_response_decision(player, request)

    def parse_response_choice(self, response: str, player, request: Dict) -> Optional[int]:
        options = request.get("options") or []
        try:
            match = re.search(r"\{.*\}", response, re.DOTALL)
            payload = json.loads(match.group(0) if match else response)
            index = payload.get("option_index")
            if not isinstance(index, int) or not 0 <= index < len(options):
                raise ValueError(f"option_index={index!r} 不在候选范围 0..{len(options) - 1}")
            reasoning = str(payload.get("reasoning", ""))[:200]
            if reasoning:
                print(f"  💭 {player.name} 响应理由: {reasoning}")
            return index
        except Exception as exc:
            print(f"  ⚠️ 响应解析失败，切换规则AI: {type(exc).__name__}: {exc}")
            return self.simple_response_decision(player, request)

    # ---------- 场外响应的规则决策（同时用作真人托管兜底） ----------

    @staticmethod
    def _playable_options(request: Dict) -> List[int]:
        """返回真正带牌的候选索引；技能转化项排在普通牌之后，避免无谓地发动技能。"""
        options = request.get("options") or []
        indices = [i for i, option in enumerate(options) if option.get("card") is not None]
        indices.sort(key=lambda i: (options[i].get("skill_name") is not None, i))
        return indices

    def simple_response_decision(self, player, request: Dict) -> Optional[int]:
        """规则脚本兜底：不调用任何 API，返回候选索引；None 表示不响应。

        这是 CHRONICLE 13.5.3 四种托管来源里的第 4 种，本批只实现这一种。
        """
        indices = self._playable_options(request)
        if not indices:
            return None

        kind = request.get("kind", "respond")

        if kind == "dying":
            # 自己濒死一定救；替别人花桃则保守放弃，不擅自替玩家做人情。
            dying = (request.get("context") or {}).get("target")
            if dying is None or dying is player:
                return indices[0]
            return None

        if kind == "wuxie":
            # 无懈保守：只在锦囊直接指向自己时才拦。
            targets = (request.get("context") or {}).get("targets") or []
            if any(t is player for t in targets):
                return indices[0]
            return None

        # 普通响应（闪 / 杀 / 桃）：能挡就挡，优先不消耗技能的那张。
        return indices[0]


class AIGateway:
    """AI API网关。当前重点保证OpenAI兼容接口可用。"""

    DEFAULT_BASES = {
        "openai": "https://api.openai.com/v1",
        "deepseek": "https://api.deepseek.com/v1",
        "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "glm": "https://open.bigmodel.cn/api/paas/v4",
        "grok": "https://api.x.ai/v1",
        "doubao": "https://ark.cn-beijing.volces.com/api/v3",
    }

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    @staticmethod
    def extract_usage(data: Dict) -> Dict:
        """各家 cached tokens 字段名不同，统一成三个键。

        取不到就写 None —— **绝不用估算值冒充实测值**，否则缓存命中率报告会自欺。
        """
        usage = (data or {}).get("usage") or {}
        cached = usage.get("prompt_cache_hit_tokens")                       # DeepSeek
        if cached is None:
            cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")  # OpenAI
        if cached is None:
            cached = usage.get("cache_read_input_tokens")                   # Anthropic
        return {
            "prompt_tokens": usage.get("prompt_tokens") or usage.get("input_tokens"),
            "cached_tokens": cached,
            "completion_tokens": usage.get("completion_tokens") or usage.get("output_tokens"),
        }

    @staticmethod
    def apply_cache_breakpoints(messages: List[Dict], provider: str, prefix_len: int) -> List[Dict]:
        """Anthropic 需要显式断点；OpenAI/DeepSeek 是自动前缀缓存，原样返回。

        只在稳定前缀（L0 末尾与 L1 末尾）打 2 个断点，L2 不打 —— L2 每次都变，
        打了也命不中，还会白占 Anthropic 的 4 个断点配额。

        注意：本网关目前只走 OpenAI 兼容端点，Anthropic 原生协议尚未接入，
        因此本函数在当前代码路径上处于**休眠状态**，接入原生协议后才会真正生效。
        """
        if (provider or "").lower() not in ("claude", "anthropic"):
            return messages
        marked = [dict(m) for m in messages]
        for index in {0, prefix_len - 1}:
            if 0 <= index < len(marked):
                marked[index]["cache_control"] = {"type": "ephemeral"}
        return marked

    async def call_ai(
        self,
        provider: str,
        model: str,
        api_key: str,
        messages: List[Dict],
        temperature: float = 0.8,
        base_url: Optional[str] = None,
        return_usage: bool = False,
        cache_prefix_len: int = 0,
    ):
        """return_usage=False 时返回字符串（老调用点行为不变）；True 时返回 (content, usage)。"""
        provider = (provider or "openai").lower()
        if provider in ("claude", "gemini") and not base_url:
            raise ValueError(f"{provider}原生协议尚未接入，请提供OpenAI兼容API地址")

        if cache_prefix_len:
            messages = self.apply_cache_breakpoints(messages, provider, cache_prefix_len)

        root = (base_url or self.DEFAULT_BASES.get(provider) or self.DEFAULT_BASES["openai"]).rstrip("/")
        endpoint = root if root.endswith("/chat/completions") else root + "/chat/completions"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "temperature": temperature},
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            if return_usage:
                return content, self.extract_usage(data)
            return content

    # 兼容旧聊天模块调用名。
    async def call_api(self, **kwargs) -> str:
        return await self.call_ai(**kwargs)


__all__ = ["AIDecision", "AIGateway", "WorldbookManager"]


if __name__ == "__main__":
    wb = WorldbookManager()
    print(f"武将:{len(wb.cache.get('heroes', []))} 卡牌:{len(wb.cache.get('cards', []))} 阶段:{len(wb.cache.get('phases', []))}")
