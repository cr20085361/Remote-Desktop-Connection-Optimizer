"""本地设置：JSON + Windows 凭据管理器中的 API Key。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai.catalog import DEEPSEEK_BASE_URL, migrate_ai_settings
from core.config import KEYRING_SERVICE, PEER_HTTP_PORT, SETTINGS_PATH, ensure_app_dirs

DEFAULTS: dict[str, Any] = {
    "interval_sec": 60,
    "ping_count": 2,
    "probe_pmtu": False,
    "v2rayn_path": "",
    "peer_port": PEER_HTTP_PORT,
    "peer_server_enabled": True,
    "ai_provider": "deepseek",
    "ai_base_url": DEEPSEEK_BASE_URL,
    "ai_model": "deepseek-flash",
    "ai_enabled": True,
    "assistant_open": True,
    "check_updates": True,
}


def load_settings() -> dict[str, Any]:
    ensure_app_dirs()
    data = dict(DEFAULTS)
    from_file: dict[str, Any] = {}
    if SETTINGS_PATH.exists():
        try:
            loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                from_file = loaded
                data.update(loaded)
        except json.JSONDecodeError:
            pass
    changed = False
    if not from_file.get("fast_collect_v2"):
        if int(data.get("interval_sec") or 0) == 20:
            data["interval_sec"] = 60
        if int(data.get("ping_count") or 0) == 5:
            data["ping_count"] = 2
        data["fast_collect_v2"] = True
        changed = True
    before_model = data.get("ai_model")
    before_url = data.get("ai_base_url")
    before_provider = data.get("ai_provider")
    data = migrate_ai_settings(data)
    if (
        data.get("ai_model") != before_model
        or data.get("ai_base_url") != before_url
        or data.get("ai_provider") != before_provider
    ):
        changed = True
    if changed:
        try:
            save_settings(data)
        except Exception:
            pass
    return data


def save_settings(data: dict[str, Any]) -> None:
    ensure_app_dirs()
    current: dict[str, Any] = {}
    if SETTINGS_PATH.exists():
        try:
            loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                current = loaded
        except json.JSONDecodeError:
            pass
    payload = {**DEFAULTS, **current, **data}
    payload.pop("ai_api_key", None)
    SETTINGS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def get_api_key() -> str:
    try:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, "ai_api_key") or ""
    except Exception:
        return ""


def set_api_key(value: str) -> None:
    import keyring

    if value:
        keyring.set_password(KEYRING_SERVICE, "ai_api_key", value)
    else:
        try:
            keyring.delete_password(KEYRING_SERVICE, "ai_api_key")
        except Exception:
            pass


def peer_token() -> str:
    try:
        import keyring

        token = keyring.get_password(KEYRING_SERVICE, "peer_token")
        if token:
            return token
    except Exception:
        token = None
    import secrets

    token = secrets.token_urlsafe(18)
    try:
        import keyring

        keyring.set_password(KEYRING_SERVICE, "peer_token", token)
    except Exception:
        path = Path(SETTINGS_PATH).with_name("peer_token.txt")
        path.write_text(token, encoding="utf-8")
    return token
