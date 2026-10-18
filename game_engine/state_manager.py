#!/usr/bin/env python3
"""
游戏引擎核心 - StateManager（状态管理器）
"""

from dataclasses import asdict, dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum
from pathlib import Path
import random
import json
import logging

from .deck_manager import DeckManager


logger = logging.getLogger(__name__)


class Phase(Enum):
    """游戏阶段"""
    PREPARE = "prepare"        # 准备阶段
    JUDGE = "judge"            # 判定阶段
    DRAW = "draw"              # 摸牌阶段
    PLAY = "play"              # 出牌阶段
    DISCARD = "discard"        # 弃牌阶段
    END = "end"                # 结束阶段

class PlayerStatus(Enum):
    """玩家状态"""
    NORMAL = "normal"
    CHAINED = "chained"        # 连环
    TURNED = "turned"          # 翻面
    DYING = "dying"            # 濒死

@dataclass
class Card:
    """卡牌"""
    id: str
    name: str
    suit: str                  # spade/heart/club/diamond
    rank: int                  # 1-13
    card_type: str             # basic/trick/equipment
    effect: Optional[str] = None
    target_rule: Optional[Dict] = None
    sub_type: Optional[str] = None
    nature: Optional[str] = None

    def __repr__(self):
        suit_symbol = {
            'spade': '♠', 'heart': '♥', 'club': '♣', 'diamond': '♦'
        }.get(self.suit, '?')
        return f"{suit_symbol}{self.rank} {self.name}"


@dataclass(frozen=True)
class CardMoveEvent:
    """一次已提交的实体牌移动事实。"""

    card_id: str
    from_owner: Optional[int]
    from_zone: str
    to_owner: Optional[int]
    to_zone: str
    reason: str
    actor_id: Optional[int]
    effect_id: Optional[str]
    visibility: str
    sequence: int

    def to_dict(self) -> Dict[str, Any]:
        """返回仅含 JSON 基本类型的事件表示。"""
        return asdict(self)

@dataclass
class Player:
    """玩家"""
    id: int
    name: str
    hero: Optional[Dict[str, Any]] = None
    identity: Optional[str] = None    # lord/loyalist/rebel/spy
    identity_revealed: bool = False
    
    # 状态
    hp: int = 4
    max_hp: int = 4
    status: PlayerStatus = PlayerStatus.NORMAL
    # 横置与翻面是两个独立状态，不能用一个互斥枚举同时表示。
    chained: bool = False
    alive: bool = True
    is_ai: bool = False
    ai_config: Dict[str, Any] = field(default_factory=dict)
    flags: Dict[str, Any] = field(default_factory=dict)  # 技能、回合和临时效果状态
    
    # 卡牌
    hand: List[Card] = field(default_factory=list)
    equipment: Dict[str, Card] = field(default_factory=dict)  # weapon/armor/plus_horse/minus_horse
    judge_area: List[Card] = field(default_factory=list)
    shown: List[Card] = field(default_factory=list)
    temporary: List[Card] = field(default_factory=list)
    treasure_cards: List[Card] = field(default_factory=list)  # 木牛流马扣置区，不计手牌
    
    # 统计
    sha_count: int = 0         # 本回合已出杀的次数
    max_sha: int = 1           # 本回合可出杀的次数
    
    def get_hand_count(self):
        return len(self.hand)
    
    def get_equipment_range(self):
        """获取武器攻击范围（单一真相源：CARD_TABLE.weapon_range）"""
        from .card_table import CARD_TABLE
        weapon = self.equipment.get('weapon')
        if weapon:
            spec = CARD_TABLE.get(weapon.name)
            return spec.weapon_range if spec else 1
        return 1

class GameState:
    """游戏状态管理器"""
    
    def __init__(self):
        self.players: List[Player] = []
        self.current_player: Optional[Player] = None
        self.current_player_index: int = 0
        self.current_phase: Phase = Phase.PREPARE
        self.round_number: int = 1
        self.round_anchor_index: int = 0
        
        # 牌堆
        self.deck: List[Card] = []
        self.discard_pile: List[Card] = []
        self.card_move_events: List[CardMoveEvent] = []
        self._card_move_sequence: int = 0
        self.deck_id: str = "standard"
        self.initial_deck_count: int = 0
        
        # 游戏配置
        self.mode: str = "5人身份局"
        self.game_config: Dict = {}
        
        # 事件队列
        self.event_queue: List[Dict] = []
        
        # 游戏结束
        self.game_over: bool = False
        self.winner: Optional[str] = None

        # 统计口径辅助：玩家 id → 最近一次伤害来源 id（击杀归属用，None 表示无来源）
        self.last_damage_source: Dict[int, Optional[int]] = {}
        
    def init_game(self, config: Dict):
        """初始化游戏"""
        self.game_config = config
        self.mode = config.get('mode', '5人身份局')
        
        # 初始化玩家
        self._init_players(config)
        
        # 初始化牌堆
        self._init_deck()
        
        # 洗牌
        self.shuffle_deck()
        
        # 发牌
        self._deal_cards()
        
        # 设置第一个玩家（主公）
        self.current_player_index = 0
        self.current_player = self.players[0]
        
    def _init_players(self, config: Dict):
        """初始化玩家"""
        # 玩家自己
        player_cfg = config.get('player', {})
        player = Player(
            id=0,
            name=player_cfg.get('name', config.get('player_name', '玩家')),
            hero=player_cfg.get('hero'),
            is_ai=player_cfg.get('is_ai', False),
            ai_config=player_cfg.get('ai_config', {}),
            hp=player_cfg.get('hero', {}).get('max_hp', 4) if player_cfg.get('hero') else 4,
            max_hp=player_cfg.get('hero', {}).get('max_hp', 4) if player_cfg.get('hero') else 4
        )
        self.players.append(player)
        
        # AI玩家
        ai_configs = config.get('ais', [])
        for i, ai_config in enumerate(ai_configs):
            ai_hero = ai_config.get('hero', {})
            ai_player = Player(
                id=i+1,
                name=ai_config.get('name', f'AI{i+1}'),
                hero=ai_hero,
                is_ai=True,
                ai_config=ai_config,
                hp=ai_hero.get('max_hp', 4),
                max_hp=ai_hero.get('max_hp', 4)
            )
            self.players.append(ai_player)
    
    def _init_deck(self):
        """从权威 JSON 加载牌堆；缺失或损坏时立即终止开局。"""
        project_root = Path(__file__).resolve().parents[1]
        deck_manager = DeckManager(project_root)
        requested_deck_id = self.game_config.get("deck_id")
        self.deck_id = deck_manager.normalize_deck_id(
            requested_deck_id or deck_manager.get_active_deck_id()
        )
        raw_cards = deck_manager.load_deck_cards(self.deck_id)
        self.deck = [
            Card(
                id=raw["id"],
                name=raw["name"],
                suit=raw["suit"],
                rank=raw["rank"],
                card_type=raw["type"],
                effect=raw.get("effect"),
                target_rule=raw.get("target_rule"),
                sub_type=raw.get("sub_type"),
                nature=raw.get("nature"),
            )
            for raw in raw_cards
        ]
        self.initial_deck_count = len(self.deck)

    def shuffle_deck(self):
        """洗牌"""
        random.shuffle(self.deck)

    def refill_deck_if_empty(self) -> bool:
        """摸牌堆为空时把弃牌堆洗成新的摸牌堆；返回摸牌堆此刻是否有牌。

        摸牌、判定、技能亮牌和身份奖励共用这一条规则，避免某条路径在牌堆耗尽时少摸。
        """
        if not self.deck and self.discard_pile:
            self.deck = self.discard_pile.copy()
            self.discard_pile.clear()
            self.shuffle_deck()
        return bool(self.deck)
    
    def _deal_cards(self):
        """发牌"""
        for player in self.players:
            # 每人发4张牌
            for _ in range(4):
                if self.deck:
                    player.hand.append(self.deck.pop(0))
    
    def draw_card(self, player: Player, count: int = 1) -> List[Card]:
        """摸牌"""
        drawn_cards = []
        for _ in range(count):
            if self.refill_deck_if_empty():
                card = self.deck.pop(0)
                player.hand.append(card)
                drawn_cards.append(card)
        
        return drawn_cards
    
    def discard_card(self, player: Player, card: Card):
        """弃牌"""
        if card in player.hand:
            player.hand.remove(card)
            self.discard_pile.append(card)

    def move_card(
        self,
        card: Card,
        from_zone: str,
        to_zone: str,
        *,
        from_owner: Optional[Player] = None,
        to_owner: Optional[Player] = None,
        reason: str,
        actor_id: Optional[int] = None,
        effect_id: Optional[str] = None,
        visibility: str = "public",
        from_slot: Optional[str] = None,
        to_slot: Optional[str] = None,
        to_index: Optional[int] = None,
    ) -> Optional[CardMoveEvent]:
        """校验并原子移动一张实体牌，失败时不改状态也不产生事件.

        Player 牌区（hand/equipment/judge/shown/temporary）必须显式传 owner；
        deck/discard 为全局牌区，owner 必须为 None。装备目标槽位由 to_slot 或
        card.sub_type 指定。牌堆目标默认放到牌堆顶，其他列表目标默认追加。
        """
        player_zones = {"hand", "equipment", "judge", "shown", "temporary", "treasure"}
        global_zones = {"deck", "discard"}
        valid_zones = player_zones | global_zones
        if (
            not isinstance(card, Card)
            or not isinstance(card.id, str)
            or not card.id
            or not isinstance(from_zone, str)
            or from_zone not in valid_zones
            or not isinstance(to_zone, str)
            or to_zone not in valid_zones
            or from_zone == to_zone and from_owner is to_owner
            or not isinstance(reason, str)
            or not reason
            or not isinstance(visibility, str)
            or not visibility
            or (from_slot is not None and (from_zone != "equipment" or not isinstance(from_slot, str)))
            or (to_slot is not None and (to_zone != "equipment" or not isinstance(to_slot, str)))
            or (to_index is not None and to_zone == "equipment")
        ):
            return None
        if (from_zone in player_zones) != (from_owner is not None):
            return None
        if (to_zone in player_zones) != (to_owner is not None):
            return None
        if from_owner is not None and (
            not isinstance(from_owner, Player)
            or not any(player is from_owner for player in self.players)
        ):
            return None
        if to_owner is not None and (
            not isinstance(to_owner, Player)
            or not any(player is to_owner for player in self.players)
        ):
            return None
        if actor_id is not None and (not isinstance(actor_id, int) or isinstance(actor_id, bool)):
            return None
        if effect_id is not None and not isinstance(effect_id, str):
            return None

        def locate(zone: str, owner: Optional[Player], slot: Optional[str] = None):
            if zone == "deck":
                return self.deck
            if zone == "discard":
                return self.discard_pile
            if zone == "hand":
                return owner.hand
            if zone == "judge":
                return owner.judge_area
            if zone == "shown":
                return owner.shown
            if zone == "temporary":
                return owner.temporary
            if zone == "treasure":
                return owner.treasure_cards
            if zone == "equipment":
                if slot is not None:
                    return owner.equipment if owner.equipment.get(slot) is card else None
                slots = [key for key, value in owner.equipment.items() if value is card]
                return owner.equipment if len(slots) == 1 else None
            return None

        source_container = locate(from_zone, from_owner, from_slot)
        if source_container is None:
            return None
        if from_zone == "equipment":
            source_slots = [key for key, value in from_owner.equipment.items() if value is card]
            if len(source_slots) != 1 or (from_slot is not None and source_slots[0] != from_slot):
                return None
            source_slot = source_slots[0]
        else:
            source_slot = None
            if not isinstance(source_container, list) or sum(value is card for value in source_container) != 1:
                return None

        # 同一实体牌 ID 在全部受管牌区必须恰好出现一次，且必须就是传入对象。
        stored_cards = []
        for stored in (self.deck, self.discard_pile):
            stored_cards.extend(stored)
        for player in self.players:
            for stored in (player.hand, player.judge_area, player.shown,
                           player.temporary, player.treasure_cards):
                stored_cards.extend(stored)
            stored_cards.extend(player.equipment.values())
        if (
            sum(stored.id == card.id for stored in stored_cards) != 1
            or not any(stored is card for stored in stored_cards)
        ):
            return None

        destination_container = locate(to_zone, to_owner, to_slot)
        if to_zone == "equipment":
            slot = to_slot or card.sub_type
            if not isinstance(slot, str) or not slot or slot in to_owner.equipment:
                return None
            destination_container = to_owner.equipment
            destination_slot = slot
        else:
            destination_slot = None
            if destination_container is None or not isinstance(destination_container, list):
                return None
            if to_index is None:
                destination_index = 0 if to_zone == "deck" else len(destination_container)
            elif isinstance(to_index, int) and not isinstance(to_index, bool) and 0 <= to_index <= len(destination_container):
                destination_index = to_index
            else:
                return None

        if from_zone == "equipment":
            del from_owner.equipment[source_slot]
        else:
            source_container.remove(card)
        if to_zone == "equipment":
            destination_container[destination_slot] = card
        else:
            destination_container.insert(destination_index, card)

        self._card_move_sequence += 1
        event = CardMoveEvent(
            card_id=card.id,
            from_owner=None if from_owner is None else from_owner.id,
            from_zone=from_zone,
            to_owner=None if to_owner is None else to_owner.id,
            to_zone=to_zone,
            reason=reason,
            actor_id=actor_id,
            effect_id=effect_id,
            visibility=visibility,
            sequence=self._card_move_sequence,
        )
        self.card_move_events.append(event)
        return event

    def card_move_event_dicts(self) -> List[Dict[str, Any]]:
        """取得按提交顺序排列、可直接 JSON 序列化的移动事件快照。"""
        return [event.to_dict() for event in self.card_move_events]
    
    def next_turn(self):
        """下一回合"""
        # 重置当前玩家状态
        self.current_player.sha_count = 0
        self.current_player.jiu_used_this_turn = False
        self.current_player.jiu_buff = False
        self.current_player.flags.pop("muniu_stored_this_turn", None)
        
        # 下一个玩家
        self.current_player_index = (self.current_player_index + 1) % len(self.players)
        
        # 跳过死亡玩家
        while not self.players[self.current_player_index].alive:
            self.current_player_index = (self.current_player_index + 1) % len(self.players)
        
        self.current_player = self.players[self.current_player_index]
        self.current_phase = Phase.PREPARE
        
        # 回到首行动角色时，轮数+1。
        if self.current_player_index == self.round_anchor_index:
            self.round_number += 1
    
    def get_distance(self, from_player: Player, to_player: Player) -> int:
        """计算存活座位距离及马匹修正。"""
        if from_player == to_player:
            return 0
        alive_players = [p for p in self.players if p.alive]
        if from_player not in alive_players or to_player not in alive_players:
            return 999
        from_index = alive_players.index(from_player)
        to_index = alive_players.index(to_player)
        alive_count = len(alive_players)
        clockwise = (to_index - from_index) % alive_count
        counter_clockwise = (from_index - to_index) % alive_count
        distance = min(clockwise, counter_clockwise)

        # +1马装备在目标身上：其他角色计算到目标的距离+1。
        if 'plus_horse' in to_player.equipment:
            distance += 1
        # -1马装备在来源身上：来源计算到其他角色的距离-1。
        if 'minus_horse' in from_player.equipment:
            distance -= 1
        return max(1, distance)


def card_to_dict(card: "Card", include_id: bool = True, name: Optional[str] = None) -> Dict:
    """卡牌序列化单点：id/name/suit/rank/card_type（include_id=False 用于操作候选）。

    与前端字段约定一致，统一用 card_type 字段名。手牌序列化另加 index/target_rule
    （见 main_engine.get_player_hand）。name 覆盖用于技能虚拟牌（如武圣红牌当杀）。"""
    d = {
        "name": name or card.name,
        "suit": card.suit,
        "rank": card.rank,
        "card_type": card.card_type,
    }
    # 牌图名称只从卡牌真相源派生；无对应资源时前端保留文字牌面。
    from .card_table import CARD_TABLE
    spec = CARD_TABLE.get(d["name"])
    if spec and spec.image and (
        Path(__file__).resolve().parents[1] / "frontend" / "assets" / "cards" / f"{spec.image}.png"
    ).is_file():
        d["image"] = spec.image
    # 属性（火/雷）是牌的公开字段；技能虚拟牌改了牌名（如红牌当杀）时视为普通牌，不继承原属性。
    if getattr(card, "nature", None) and (name is None or name == card.name):
        d["nature"] = card.nature
    if include_id:
        d["id"] = card.id
    return d

if __name__ == "__main__":
    # 测试
    game = GameState()
    config = {
        "mode": "5人身份局",
        "player_name": "测试玩家",
        "ais": [
            {"name": "AI1"},
            {"name": "AI2"},
            {"name": "AI3"},
            {"name": "AI4"}
        ]
    }
    
    game.init_game(config)
    logger.info(f"游戏初始化完成，当前回合: {game.round_number}")
    logger.info(f"当前玩家: {game.current_player.name}")
    logger.info(f"牌堆剩余: {len(game.deck)}张")
    
    # 测试摸牌
    game.draw_card(game.current_player, 2)
    logger.info(f"摸牌后手牌数: {game.current_player.get_hand_count()}")
    
    # 输出状态（卡牌序列化单点 card_to_dict）
    logger.info(json.dumps([game.card_to_dict(c) for c in game.current_player.hand], ensure_ascii=False, indent=2))
