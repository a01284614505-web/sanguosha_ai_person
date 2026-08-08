#!/usr/bin/env python3
"""
游戏引擎核心 - StateManager（状态管理器）
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum
import random
import json

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

@dataclass
class Skill:
    """技能"""
    name: str
    skill_type: str            # active/passive/lord/forced/limited
    trigger: str               # 触发时机
    description: str
    effect: Optional[Any] = None

@dataclass
class Hero:
    """武将"""
    id: str
    name: str
    faction: str               # wei/shu/wu/qun
    max_hp: int
    skills: List[Skill] = field(default_factory=list)
    title: str = ""
    artist: str = ""
    worldbook: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Player:
    """玩家"""
    id: int
    name: str
    hero: Optional[Hero] = None
    identity: Optional[str] = None    # lord/loyalist/rebel/spy
    identity_revealed: bool = False
    
    # 状态
    hp: int = 4
    max_hp: int = 4
    status: PlayerStatus = PlayerStatus.NORMAL
    alive: bool = True
    is_ai: bool = False
    ai_config: Dict[str, Any] = field(default_factory=dict)
    
    # 卡牌
    hand: List[Card] = field(default_factory=list)
    equipment: Dict[str, Card] = field(default_factory=dict)  # weapon/armor/plus_horse/minus_horse
    judge_area: List[Card] = field(default_factory=list)
    
    # 统计
    sha_count: int = 0         # 本回合已出杀的次数
    max_sha: int = 1           # 本回合可出杀的次数
    
    def get_hand_count(self):
        return len(self.hand)
    
    def get_equipment_range(self):
        """获取武器攻击范围"""
        weapon = self.equipment.get('weapon')
        if weapon:
            # 武器范围映射
            ranges = {
                '诸葛连弩': 1,
                '青釭剑': 2,
                '青龙偃月刀': 3,
                '丈八蛇矛': 3,
                '贯石斧': 3,
                '麒麟弓': 5
            }
            return ranges.get(weapon.name, 1)
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
        
        # 游戏配置
        self.mode: str = "5人身份局"
        self.game_config: Dict = {}
        
        # 事件队列
        self.event_queue: List[Dict] = []
        
        # 游戏结束
        self.game_over: bool = False
        self.winner: Optional[str] = None
        
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
        """初始化108张标准牌堆"""
        cards = []
        
        # 杀(30张)
        for suit in ['spade', 'club', 'heart', 'diamond']:
            for rank in [7, 8, 9, 10]:
                cards.append(Card(f"sha_{suit}_{rank}", '杀', suit, rank, 'basic', 
                             target_rule={'target_count': 1, 'distance_limit': 1}))
        for rank in [2, 3, 4, 5, 6]:
            for suit in ['spade', 'club']:
                cards.append(Card(f"sha_{suit}_{rank}", '杀', suit, rank, 'basic',
                             target_rule={'target_count': 1, 'distance_limit': 1}))
        
        # 闪(15张)
        for suit in ['heart', 'diamond']:
            for rank in [2, 11, 13]:
                cards.append(Card(f"shan_{suit}_{rank}", '闪', suit, rank, 'basic'))
        for suit, ranks in [('heart', [8, 9]), ('diamond', [6, 7, 8, 9, 10])]:
            for rank in ranks:
                cards.append(Card(f"shan_{suit}_{rank}", '闪', suit, rank, 'basic'))
        
        # 桃(8张)
        for suit in ['heart', 'diamond']:
            for rank in [3, 4, 12]:
                cards.append(Card(f"tao_{suit}_{rank}", '桃', suit, rank, 'basic'))
        cards.append(Card(f"tao_heart_6", '桃', 'heart', 6, 'basic'))
        cards.append(Card(f"tao_diamond_12", '桃', 'diamond', 12, 'basic'))
        
        # 过河拆桥(6张)
        for suit, ranks in [('spade', [3, 4, 12]), ('club', [3, 4]), ('heart', [12])]:
            for rank in ranks:
                cards.append(Card(f"guohe_{suit}_{rank}", '过河拆桥', suit, rank, 'trick',
                             target_rule={'target_count': 1}))
        
        # 填充到108张（用杀和闪）
        while len(cards) < 108:
            suit = ['spade', 'club', 'heart', 'diamond'][len(cards) % 4]
            rank = (len(cards) % 13) + 1
            name = '杀' if len(cards) % 2 == 0 else '闪'
            cards.append(Card(f"filler_{len(cards)}", name, suit, rank, 'basic'))
        
        self.deck = cards
        random.shuffle(self.deck)
    def shuffle_deck(self):
        """洗牌"""
        random.shuffle(self.deck)
    
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
            if not self.deck:
                # 牌堆空了，洗弃牌堆
                self.deck = self.discard_pile.copy()
                self.discard_pile.clear()
                self.shuffle_deck()
            
            if self.deck:
                card = self.deck.pop(0)
                player.hand.append(card)
                drawn_cards.append(card)
        
        return drawn_cards
    
    def discard_card(self, player: Player, card: Card):
        """弃牌"""
        if card in player.hand:
            player.hand.remove(card)
            self.discard_pile.append(card)
    
    def next_phase(self):
        """进入下一阶段"""
        phases = list(Phase)
        current_index = phases.index(self.current_phase)
        
        if current_index < len(phases) - 1:
            self.current_phase = phases[current_index + 1]
        else:
            # 回合结束，下一个玩家
            self.next_turn()
    
    def next_turn(self):
        """下一回合"""
        # 重置当前玩家状态
        self.current_player.sha_count = 0
        
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
    
    def to_dict(self) -> Dict:
        """序列化为字典（用于前端显示）"""
        return {
            "round_number": self.round_number,
            "current_phase": self.current_phase.value,
            "current_turn": self.current_player_index,
            "mode": self.mode,
            "deck_count": len(self.deck),
            "discard_count": len(self.discard_pile),
            "players": [
                {
                    "id": p.id,
                    "name": p.name,
                    "hp": p.hp,
                    "max_hp": p.max_hp,
                    "hand_count": p.get_hand_count(),
                    "alive": p.alive,
                    "status": p.status.value,
                    "equipment": {k: {"name": v.name} for k, v in p.equipment.items()},
                    "judge_area": [{"name": c.name} for c in p.judge_area],
                    "hand": [
                        {
                            "id": c.id,
                            "name": c.name,
                            "suit": c.suit,
                            "rank": c.rank,
                            "type": c.card_type
                        } for c in p.hand
                    ] if p.id == 0 else []  # 只显示自己的手牌
                } for p in self.players
            ]
        }

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
    print(f"游戏初始化完成，当前回合: {game.round_number}")
    print(f"当前玩家: {game.current_player.name}")
    print(f"牌堆剩余: {len(game.deck)}张")
    
    # 测试摸牌
    game.draw_card(game.current_player, 2)
    print(f"摸牌后手牌数: {game.current_player.get_hand_count()}")
    
    # 输出状态
    print(json.dumps(game.to_dict(), ensure_ascii=False, indent=2))
