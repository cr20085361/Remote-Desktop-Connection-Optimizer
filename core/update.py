"""从本仓库 GitHub Release 探测并下载离线安装包。不访问其它域名。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from core.config import (
    APP_ID,
    GITHUB_OWNER,
    GITHUB_REPO,
    UPDATES_DIR,
    VERSION,
    ensure_app_dirs,
)

INSTALLER_RE = re.compile(r"^RdpOptimizer-Setup-(\d+\.\d+\.\d+)\.exe$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
LATEST_JSON_URL = (
    f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest/download/latest.json"
)
_DOWNLOAD_RE = re.compile(
    rf"^https://github\.com/{re.escape(GITHUB_OWNER)}/{re.escape(GITHUB_REPO)}"
    rf"/releases/(?:latest/download|download/v\d+\.\d+\.\d+)/"
    rf"RdpOptimizer-Setup-\d+\.\d+\.\d+\.exe$"
)
_LATEST_JSON_RE = re.compile(
    rf"^https://github\.com/{re.escape(GITHUB_OWNER)}/{re.escape(GITHUB_REPO)}"
    rf"/releases/latest/download/latest\.json$"
)
_USER_AGENT = f"{APP_ID}/{VERSION}"


class UpdateError(ValueError):
    """探测或下载更新失败。"""


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    installer: str
    sha256: str
    size: int
    notes: str
    url: str


def parse_version(text: str) -> tuple[int, int, int]:
    raw = (text or "").strip().lstrip("vV")
    parts = raw.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise UpdateError(f"版本号无法识别：{text}")
    return int(parts[0]), int(parts[1]), int(parts[2])


def format_version(ver: tuple[int, int, int]) -> str:
    return f"{ver[0]}.{ver[1]}.{ver[2]}"


def is_newer(remote: str, local: str) -> bool:
    return parse_version(remote) > parse_version(local)


def is_allowed_download_url(url: str) -> bool:
    return bool(_DOWNLOAD_RE.match((url or "").strip()))


def is_allowed_manifest_url(url: str) -> bool:
    return bool(_LATEST_JSON_RE.match((url or "").strip()))


def installer_url(version: str, installer: str) -> str:
    ver = format_version(parse_version(version))
    if not INSTALLER_RE.match(installer):
        raise UpdateError("安装包文件名不合法")
    return (
        f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
        f"/releases/download/v{ver}/{installer}"
    )


def parse_latest_json(data: Any) -> ReleaseInfo:
    if not isinstance(data, dict):
        raise UpdateError("latest.json 格式不对")
    version = format_version(parse_version(str(data.get("version") or "")))
    installer = str(data.get("installer") or "").strip()
    match = INSTALLER_RE.match(installer)
    if not match or match.group(1) != version:
        raise UpdateError("安装包文件名与版本不一致")
    digest = str(data.get("sha256") or "").strip().lower()
    if not SHA256_RE.match(digest):
        raise UpdateError("缺少有效的 SHA256")
    try:
        size = int(data.get("size") or 0)
    except (TypeError, ValueError) as exc:
        raise UpdateError("体积字段无效") from exc
    if size < 0:
        raise UpdateError("体积字段无效")
    notes = str(data.get("notes") or "").strip()
    url = str(data.get("url") or "").strip() or installer_url(version, installer)
    if not is_allowed_download_url(url):
        raise UpdateError("安装包地址不是本仓库")
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise UpdateError("安装包地址不是本仓库")
    return ReleaseInfo(
        version=version,
        installer=installer,
        sha256=digest,
        size=size,
        notes=notes,
        url=url,
    )


def format_size(num: int) -> str:
    if num <= 0:
        return "未知大小"
    mb = num / (1024 * 1024)
    if mb < 0.1:
        return f"{max(num // 1024, 1)} KB"
    return f"{mb:.1f} MB"


def fetch_latest(*, timeout: float = 20) -> ReleaseInfo | None:
    import requests

    if not is_allowed_manifest_url(LATEST_JSON_URL):
        raise UpdateError("更新地址不是本仓库")
    try:
        resp = requests.get(
            LATEST_JSON_URL,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
        )
    except requests.RequestException as exc:
        raise UpdateError("暂时无法检查更新") from exc
    if resp.status_code == 404:
        return None
    if resp.status_code >= 400:
        raise UpdateError("暂时无法检查更新")
    try:
        payload = resp.json()
    except json.JSONDecodeError as exc:
        raise UpdateError("更新说明无法解析") from exc
    return parse_latest_json(payload)


def check_for_update(local_version: str | None = None) -> ReleaseInfo | None:
    current = local_version if local_version is not None else VERSION
    info = fetch_latest()
    if info is None:
        return None
    if not is_newer(info.version, current):
        return None
    return info


def download_installer(info: ReleaseInfo, dest_dir: Path | None = None) -> Path:
    import requests

    if not is_allowed_download_url(info.url):
        raise UpdateError("安装包地址不是本仓库")
    ensure_app_dirs()
    folder = dest_dir or UPDATES_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / info.installer
    hasher = hashlib.sha256()
    written = 0
    try:
        with requests.get(
            info.url,
            stream=True,
            timeout=60,
            allow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as resp:
            if resp.status_code >= 400:
                raise UpdateError("下载安装包失败")
            with path.open("wb") as handle:
                for chunk in resp.iter_content(64 * 1024):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    hasher.update(chunk)
                    written += len(chunk)
    except requests.RequestException as exc:
        path.unlink(missing_ok=True)
        raise UpdateError("下载安装包失败") from exc
    digest = hasher.hexdigest()
    if digest != info.sha256.lower():
        path.unlink(missing_ok=True)
        raise UpdateError("安装包校验失败")
    if info.size and written != info.size:
        path.unlink(missing_ok=True)
        raise UpdateError("安装包大小不匹配")
    return path
