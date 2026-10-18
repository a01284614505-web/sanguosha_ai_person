"""按 AI 座位与调用类型累计 token 消耗（Stage T · W1b）。

调用类型：decision（出牌）/ response（响应）/ choice（选择）/ chat（聊天）。
统计只记实测值：usage 缺字段时不当 0，而是计入 unknown_usage_calls。
失败调用（网关抛异常）计入 calls 与 failures，没有响应，不计入 unknown。
"""

from typing import Dict, Optional

USAGE_KINDS = ("decision", "response", "choice", "chat")
USAGE_FIELDS = ("calls", "failures", "prompt_tokens", "cached_tokens",
                "completion_tokens", "unknown_usage_calls")


def empty_bucket() -> Dict[str, int]:
    return {field: 0 for field in USAGE_FIELDS}


def _count(value) -> Optional[int]:
    """只接受非负数值；其它（None、字符串、布尔）一律视为缺失。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return int(value)


def apply_usage(bucket: Dict[str, int], usage: Optional[Dict], failed: bool) -> None:
    """把一次调用累加进 bucket（原地修改）。"""
    bucket["calls"] += 1
    if failed:
        bucket["failures"] += 1
        return
    usage = usage or {}
    prompt = _count(usage.get("prompt_tokens"))
    completion = _count(usage.get("completion_tokens"))
    cached = _count(usage.get("cached_tokens"))
    if prompt is None or completion is None:
        bucket["unknown_usage_calls"] += 1
    if prompt is not None:
        bucket["prompt_tokens"] += prompt
    if completion is not None:
        bucket["completion_tokens"] += completion
    if cached is not None:
        bucket["cached_tokens"] += cached


__all__ = ["USAGE_KINDS", "USAGE_FIELDS", "empty_bucket", "apply_usage"]
