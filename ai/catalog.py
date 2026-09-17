"""DeepSeek / 通义千问接入目录。默认按官网当前可用模型预填，用户只需填 API Key。"""

from __future__ import annotations

from typing import Any

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# 官网 2026-09：正式模型仅 deepseek-flash（V4.1 Flash）与 deepseek-v4-pro。
# 旧名 deepseek-chat / deepseek-reasoner 已下线；v4-flash 别名仍转发到 Flash。
DEEPSEEK_MODELS: list[dict[str, Any]] = [
    {
        "id": "deepseek-flash",
        "label": "deepseek-flash（推荐 · V4.1 Flash）",
        "thinking": True,
    },
    {
        "id": "deepseek-v4-pro",
        "label": "deepseek-v4-pro（V4 Pro · 更强更贵）",
        "thinking": True,
    },
    {
        "id": "deepseek-v4-flash",
        "label": "deepseek-v4-flash（兼容别名 → Flash）",
        "thinking": True,
    },
    {
        "id": "deepseek-v4-flash-vision-exp",
        "label": "deepseek-v4-flash-vision-exp（兼容别名 → Flash）",
        "thinking": True,
    },
]

QWEN_MODELS: list[dict[str, Any]] = [
    {"id": "qwen-plus", "label": "qwen-plus", "thinking": False},
    {"id": "qwen-max", "label": "qwen-max", "thinking": False},
    {"id": "qwen-turbo", "label": "qwen-turbo", "thinking": False},
]

PROVIDERS: dict[str, dict[str, Any]] = {
    "deepseek": {
        "id": "deepseek",
        "label": "DeepSeek",
        "base_url": DEEPSEEK_BASE_URL,
        "models": DEEPSEEK_MODELS,
        "default_model": "deepseek-flash",
    },
    "qwen": {
        "id": "qwen",
        "label": "通义千问（可选）",
        "base_url": QWEN_BASE_URL,
        "models": QWEN_MODELS,
        "default_model": "qwen-plus",
    },
}

_LEGACY_DEEPSEEK = {
    "deepseek-chat",
    "deepseek-reasoner",
    "deepseek-coder",
}


def provider_id_for(base_url: str, model: str = "") -> str:
    url = (base_url or "").lower()
    mid = (model or "").lower()
    if "dashscope" in url or "qwen" in url or mid.startswith("qwen"):
        return "qwen"
    return "deepseek"


def models_for(provider: str) -> list[dict[str, Any]]:
    return list(PROVIDERS.get(provider, PROVIDERS["deepseek"])["models"])


def default_model(provider: str) -> str:
    return str(PROVIDERS.get(provider, PROVIDERS["deepseek"])["default_model"])


def base_url_for(provider: str) -> str:
    return str(PROVIDERS.get(provider, PROVIDERS["deepseek"])["base_url"])


def model_uses_thinking(model: str) -> bool:
    mid = (model or "").lower()
    for item in DEEPSEEK_MODELS:
        if item["id"] == mid:
            return bool(item.get("thinking"))
    return mid.startswith("deepseek-")


def migrate_ai_settings(data: dict[str, Any]) -> dict[str, Any]:
    """把停用的 deepseek-chat 等迁到当前官网模型，并写回官方 Base URL。"""
    model = str(data.get("ai_model") or "")
    url = str(data.get("ai_base_url") or "")
    provider = str(data.get("ai_provider") or "") or provider_id_for(url, model)
    if provider == "deepseek":
        if not url or "deepseek.com" in url.lower() or model in _LEGACY_DEEPSEEK or not model:
            data["ai_base_url"] = DEEPSEEK_BASE_URL
        if not model or model in _LEGACY_DEEPSEEK:
            data["ai_model"] = "deepseek-flash"
        data["ai_provider"] = "deepseek"
    else:
        data["ai_provider"] = provider
        if not url:
            data["ai_base_url"] = base_url_for(provider)
        if not model:
            data["ai_model"] = default_model(provider)
    return data


def chat_completions_url(base_url: str) -> str:
    base = (base_url or "").rstrip("/")
    if not base:
        raise ValueError("未配置 API Base URL")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"
