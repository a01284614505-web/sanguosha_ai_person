"""拉取服务商的可用模型列表，供大厅/局内的“模型名称”输入框选择。

只做只读的 GET 请求，结果只返回模型 ID；API Key 只用于本次请求头，
不写日志、不回传给前端。各家接口差异：

* OpenAI 兼容（DeepSeek、通义、OpenAI、智谱、Grok、豆包及大多数中转站）：
  ``GET {base}/models``，``Authorization: Bearer``，返回 ``data[].id``。
* Claude：``GET https://api.anthropic.com/v1/models``，需要 ``x-api-key`` 与
  ``anthropic-version`` 头，返回结构同样是 ``data[].id``。
* Gemini 原生地址（``.../v1beta``）：``GET {base}/models``，``x-goog-api-key`` 头，
  返回 ``models[].name``（带 ``models/`` 前缀），只保留支持 generateContent 的。
  若用户填的是 Gemini 的 OpenAI 兼容地址（含 ``/openai``），按 OpenAI 兼容处理。
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional
from urllib.parse import urlsplit

import httpx

from .protocol import PROVIDERS

DEFAULT_BASES = {p["value"]: p["default_url"] for p in PROVIDERS}
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_MODELS = 500


class ModelListError(Exception):
    """可直接展示给玩家的失败原因（不含 Key）。"""


def _base_url(provider: str, api_url: Optional[str]) -> str:
    root = (api_url or "").strip() or DEFAULT_BASES.get(provider) or DEFAULT_BASES["openai"]
    root = root.rstrip("/")
    for suffix in ("/chat/completions", "/completions", "/models"):
        if root.endswith(suffix):
            root = root[: -len(suffix)]
    parts = urlsplit(root)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ModelListError("API 地址必须以 http:// 或 https:// 开头")
    return root


def _request_spec(provider: str, root: str, api_key: str):
    if provider == "claude" or "anthropic.com" in root:
        return root + "/models?limit=1000", {
            "x-api-key": api_key, "anthropic-version": "2023-06-01",
            "Authorization": f"Bearer {api_key}",
        }, "openai"
    if (provider == "gemini" or "generativelanguage.googleapis.com" in root) and "/openai" not in root:
        return root + "/models?pageSize=1000", {"x-goog-api-key": api_key}, "gemini"
    return root + "/models", {"Authorization": f"Bearer {api_key}"}, "openai"


def parse_models(payload, style: str) -> List[str]:
    """把各家返回体整理成去重、排序后的模型 ID 列表。"""
    ids: List[str] = []
    if style == "gemini":
        for item in (payload or {}).get("models") or []:
            if not isinstance(item, dict):
                continue
            methods = item.get("supportedGenerationMethods")
            if methods is not None and "generateContent" not in methods:
                continue
            name = str(item.get("name") or "")
            ids.append(name[len("models/"):] if name.startswith("models/") else name)
    else:
        items = payload.get("data") if isinstance(payload, dict) else payload
        for item in items or []:
            if isinstance(item, dict):
                ids.append(str(item.get("id") or item.get("name") or ""))
            elif isinstance(item, str):
                ids.append(item)
    unique = sorted({i.strip() for i in ids if i and i.strip()})
    return unique[:MAX_MODELS]


def list_models(provider: str, api_url: Optional[str], api_key: str, *,
                timeout: float = 10.0, transport=None) -> Dict:
    provider = (provider or "openai").lower()
    api_key = (api_key or "").strip()
    if not api_key:
        raise ModelListError("请先填写 API Key")
    root = _base_url(provider, api_url)
    url, headers, style = _request_spec(provider, root, api_key)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, transport=transport) as client:
            with client.stream("GET", url, headers=headers) as response:
                if response.status_code in (401, 403):
                    raise ModelListError("API Key 无效或没有权限（HTTP %d）" % response.status_code)
                if response.status_code == 404:
                    raise ModelListError("该地址不支持拉取模型列表（HTTP 404），请手动填写模型名")
                if response.status_code >= 400:
                    raise ModelListError("服务商返回错误（HTTP %d）" % response.status_code)
                body = b""
                for chunk in response.iter_bytes():
                    body += chunk
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise ModelListError("返回内容过大，已放弃")
        payload = json.loads(body.decode("utf-8"))
    except ModelListError:
        raise
    except httpx.TimeoutException:
        raise ModelListError("连接超时，请检查网络或 API 地址") from None
    except httpx.HTTPError:
        raise ModelListError("无法连接到该 API 地址") from None
    except (ValueError, UnicodeDecodeError):
        raise ModelListError("返回内容不是合法 JSON，请确认 API 地址") from None
    models = parse_models(payload, style)
    if not models:
        raise ModelListError("没有拉取到可用模型，请手动填写")
    return {"models": models, "base_url": root}


__all__ = ["ModelListError", "list_models", "parse_models"]
