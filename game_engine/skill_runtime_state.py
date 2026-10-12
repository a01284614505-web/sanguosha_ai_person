"""可序列化的最小技能运行状态。

该模块只负责技能实例状态与来源引用，不依赖引擎、玩家模型或 UI。
调用方通过显式传入阶段、当前角色、回合 ID 和轮数来计算次数作用域。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Union
import json


Id = Union[int, str]
SUPPORTED_USAGE_SCOPES = frozenset({"phase", "current_turn", "round", "game"})


@dataclass
class SkillInstance:
    """某角色从某来源获得的一份技能实例。"""

    owner_id: Id
    skill_id: str
    version_id: Optional[str] = None
    source: str = "native"
    enabled: bool = True
    charges: Optional[int] = None
    usage_scope: str = "game"
    usage_count: int = 0
    state: Dict[str, Any] = field(default_factory=dict)
    reference_count: int = 1
    usage_counts: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.usage_scope not in SUPPORTED_USAGE_SCOPES:
            raise ValueError(f"unsupported usage_scope: {self.usage_scope}")
        if self.charges is not None and self.charges < 0:
            raise ValueError("charges cannot be negative")
        if self.usage_count < 0:
            raise ValueError("usage_count cannot be negative")
        if self.reference_count < 1:
            raise ValueError("reference_count must be positive")
        self.state = dict(self.state or {})
        self.usage_counts = {
            str(key): int(value) for key, value in (self.usage_counts or {}).items()
        }

    def to_dict(self) -> Dict[str, Any]:
        """返回 JSON 兼容字典；拒绝无法持久化的 state 值。"""
        data = asdict(self)
        # 确保 state 和计数器不会悄悄带入运行时对象或集合。
        json.dumps(data, ensure_ascii=False)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillInstance":
        return cls(
            owner_id=data["owner_id"],
            skill_id=str(data["skill_id"]),
            version_id=data.get("version_id"),
            source=str(data.get("source", "native")),
            enabled=bool(data.get("enabled", True)),
            charges=data.get("charges"),
            usage_scope=str(data.get("usage_scope", "game")),
            usage_count=int(data.get("usage_count", 0)),
            state=dict(data.get("state") or {}),
            reference_count=int(data.get("reference_count", 1)),
            usage_counts=dict(data.get("usage_counts") or {}),
        )

    def scope_key(
        self,
        *,
        phase: Optional[str] = None,
        current_player_id: Optional[Id] = None,
        turn_id: Optional[Id] = None,
        round_number: Optional[int] = None,
        turn_policy: str = "owner",
    ) -> str:
        """生成次数计数键。

        对 ``current_turn``，``turn_policy='owner'`` 表示仅在技能拥有者
        自己的回合使用同一键；``'any'`` 则按每个当前角色回合分别计数。
        提供 turn_id 可区分同一角色在一轮中的额外回合。
        """
        if self.usage_scope == "game":
            return "game"
        if self.usage_scope == "round":
            if round_number is None:
                raise ValueError("round_number is required for round scope")
            return f"round:{round_number}"
        if self.usage_scope == "phase":
            if phase is None:
                raise ValueError("phase is required for phase scope")
            if turn_id is not None:
                turn = f"turn:{turn_id}"
            elif current_player_id is not None:
                turn = f"player:{current_player_id}:round:{round_number}"
            else:
                raise ValueError("turn_id or current_player_id is required for phase scope")
            return f"{turn}:phase:{phase}"

        if turn_policy == "owner":
            if turn_id is not None:
                turn = f"turn:{turn_id}"
            elif current_player_id is not None:
                turn = f"player:{current_player_id}:round:{round_number}"
            else:
                raise ValueError("turn_id or current_player_id is required for owner-turn scope")
            return f"turn:owner:{self.owner_id}:{turn}"
        if turn_policy == "any":
            if turn_id is not None:
                return f"turn:any:player:{current_player_id}:turn:{turn_id}"
            if current_player_id is None:
                raise ValueError("current_player_id or turn_id is required for any-turn scope")
            return f"turn:any:player:{current_player_id}:round:{round_number}"
        raise ValueError("turn_policy must be 'owner' or 'any'")


class SkillStateStore:
    """按拥有者、技能版本和来源存取技能实例。"""

    def __init__(self, instances: Optional[Iterable[SkillInstance]] = None) -> None:
        self._instances: Dict[tuple, SkillInstance] = {}
        for instance in instances or ():
            key = self._key(
                instance.owner_id, instance.skill_id, instance.version_id, instance.source
            )
            if key in self._instances:
                raise ValueError(f"duplicate skill instance: {key!r}")
            self._instances[key] = instance

    @staticmethod
    def _key(owner_id: Id, skill_id: str, version_id: Optional[str], source: str) -> tuple:
        return owner_id, skill_id, version_id, source

    def register(
        self,
        owner_id: Id,
        skill_id: str,
        *,
        version_id: Optional[str] = None,
        source: str = "native",
        enabled: bool = True,
        charges: Optional[int] = None,
        usage_scope: str = "game",
        state: Optional[Dict[str, Any]] = None,
    ) -> SkillInstance:
        """注册来源；重复注册同一来源增加引用数并返回既有实例。"""
        key = self._key(owner_id, skill_id, version_id, source)
        existing = self._instances.get(key)
        if existing is not None:
            existing.reference_count += 1
            return existing
        instance = SkillInstance(
            owner_id=owner_id,
            skill_id=skill_id,
            version_id=version_id,
            source=source,
            enabled=enabled,
            charges=charges,
            usage_scope=usage_scope,
            state=dict(state or {}),
        )
        self._instances[key] = instance
        return instance

    def get(
        self,
        owner_id: Id,
        skill_id: str,
        *,
        version_id: Optional[str] = None,
        source: Optional[str] = None,
    ) -> Optional[SkillInstance]:
        """精确来源查询，或按技能名查询首个匹配实例。"""
        if source is not None:
            return self._instances.get(self._key(owner_id, skill_id, version_id, source))
        return next(
            (item for item in self._instances.values()
             if item.owner_id == owner_id and item.skill_id == skill_id
             and (version_id is None or item.version_id == version_id)),
            None,
        )

    def find(self, owner_id: Id, skill_id: str) -> List[SkillInstance]:
        """查询某角色同名技能的所有来源实例。"""
        return [item for item in self._instances.values()
                if item.owner_id == owner_id and item.skill_id == skill_id]

    def for_owner(self, owner_id: Id) -> List[SkillInstance]:
        """取得某角色全部技能实例，保持注册顺序。"""
        return [item for item in self._instances.values() if item.owner_id == owner_id]

    def has_enabled(self, owner_id: Id, skill_id: str) -> bool:
        return any(item.enabled for item in self.find(owner_id, skill_id))

    def add_source(
        self,
        owner_id: Id,
        skill_id: str,
        source: str,
        **instance_options: Any,
    ) -> SkillInstance:
        return self.register(owner_id, skill_id, source=source, **instance_options)

    def remove_source(
        self,
        owner_id: Id,
        skill_id: str,
        source: str,
        *,
        version_id: Optional[str] = None,
    ) -> bool:
        """减少来源引用；引用归零时移除实例。返回是否找到来源。"""
        key = self._key(owner_id, skill_id, version_id, source)
        instance = self._instances.get(key)
        if instance is None:
            return False
        instance.reference_count -= 1
        if instance.reference_count <= 0:
            del self._instances[key]
        return True

    def consume(
        self,
        owner_id: Id,
        skill_id: str,
        *,
        version_id: Optional[str] = None,
        source: Optional[str] = None,
        phase: Optional[str] = None,
        current_player_id: Optional[Id] = None,
        turn_id: Optional[Id] = None,
        round_number: Optional[int] = None,
        turn_policy: str = "owner",
        limit: Optional[int] = 1,
        charges: int = 1,
    ) -> bool:
        """消耗一次技能使用额度；额度不足或技能禁用时不改变状态。

        ``limit=None`` 表示该作用域没有次数上限。``charges`` 是本次效果
        确认后消耗的限定次数，设为 0 可只记录 usage_count。
        """
        candidates = ([self.get(owner_id, skill_id, version_id=version_id, source=source)]
                      if source is not None or version_id is not None
                      else self.find(owner_id, skill_id))
        instance = next((item for item in candidates if item is not None and item.enabled), None)
        if instance is None or charges < 0:
            return False
        key = instance.scope_key(
            phase=phase,
            current_player_id=current_player_id,
            turn_id=turn_id,
            round_number=round_number,
            turn_policy=turn_policy,
        )
        used = instance.usage_counts.get(key, 0)
        if limit is not None and used >= limit:
            return False
        if instance.charges is not None and instance.charges < charges:
            return False
        instance.usage_counts[key] = used + 1
        instance.usage_count += 1
        if instance.charges is not None:
            instance.charges -= charges
        return True

    def disable(
        self, owner_id: Id, skill_id: str, *, version_id: Optional[str] = None,
        source: Optional[str] = None,
    ) -> int:
        """禁用匹配实例，返回变更数量。"""
        instances = self._matching(owner_id, skill_id, version_id, source)
        changed = 0
        for item in instances:
            if item.enabled:
                item.enabled = False
                changed += 1
        return changed

    def restore(
        self, owner_id: Id, skill_id: str, *, version_id: Optional[str] = None,
        source: Optional[str] = None,
    ) -> int:
        """恢复匹配实例，返回变更数量。"""
        instances = self._matching(owner_id, skill_id, version_id, source)
        changed = 0
        for item in instances:
            if not item.enabled:
                item.enabled = True
                changed += 1
        return changed

    def set_state(
        self,
        owner_id: Id,
        skill_id: str,
        state_key: str,
        value: Any,
        *,
        version_id: Optional[str] = None,
        source: Optional[str] = None,
    ) -> int:
        """写入技能持久状态；调用序列化时会验证 JSON 兼容性。"""
        instances = self._matching(owner_id, skill_id, version_id, source)
        for item in instances:
            item.state[state_key] = value
        return len(instances)

    def _matching(
        self, owner_id: Id, skill_id: str, version_id: Optional[str], source: Optional[str]
    ) -> List[SkillInstance]:
        return [item for item in self._instances.values()
                if item.owner_id == owner_id and item.skill_id == skill_id
                and (version_id is None or item.version_id == version_id)
                and (source is None or item.source == source)]

    def to_dict(self) -> Dict[str, Any]:
        """导出可 JSON 序列化的存储快照。"""
        return {"instances": [item.to_dict() for item in self._instances.values()]}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillStateStore":
        return cls(SkillInstance.from_dict(row) for row in data.get("instances", []))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, value: str) -> "SkillStateStore":
        return cls.from_dict(json.loads(value))

    def __len__(self) -> int:
        return len(self._instances)


__all__ = ["SkillInstance", "SkillStateStore", "SUPPORTED_USAGE_SCOPES"]
