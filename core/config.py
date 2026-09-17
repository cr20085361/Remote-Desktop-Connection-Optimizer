"""应用常量与路径。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "远程桌面连接优化器"
APP_ID = "RdpOptimizer"
GITHUB_OWNER = "cr20085361"
GITHUB_REPO = "Remote-Desktop-Connection-Optimizer"
GITHUB_REPO_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"


def _app_root() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _read_version(root: Path) -> str:
    candidates = [root / "VERSION"]
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "VERSION")
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.insert(0, Path(meipass) / "VERSION")
    for path in candidates:
        try:
            if path.is_file():
                text = path.read_text(encoding="utf-8").strip()
                if text:
                    return text
        except OSError:
            continue
    return "1.0.0"


ROOT_DIR = _app_root()
VERSION_FILE = ROOT_DIR / "VERSION"
VERSION = _read_version(ROOT_DIR)
APP_DISPLAY = f"{APP_NAME} {VERSION}"

ASSETS_DIR = ROOT_DIR / "assets"
ICON_PATH = ASSETS_DIR / "icon.png"
SPLASH_PATH = ASSETS_DIR / "splash.png"

APP_DATA = Path(os.environ.get("APPDATA", str(ROOT_DIR))) / APP_ID
DB_PATH = APP_DATA / "history.db"
SETTINGS_PATH = APP_DATA / "settings.json"
ROLLBACK_DIR = APP_DATA / "rollback"
LOG_DIR = APP_DATA / "logs"
UPDATES_DIR = APP_DATA / "updates"

TAILSCALE_EXE_CANDIDATES = [
    Path(r"C:\Program Files\Tailscale\tailscale.exe"),
    Path(r"C:\Program Files (x86)\Tailscale\tailscale.exe"),
]

PEER_HTTP_PORT = 18765
KEYRING_SERVICE = APP_ID

TS_CGNAT_CIDR = "100.64.0.0/10"
TS_CGNAT_OVERRIDE = "100.*"

ASIA_DERP = {"hkg", "tok", "sin", "blr", "nrt", "sel"}
OVERSEAS_DERP_HINT = {
    "lax", "sfo", "sea", "den", "dfw", "ord", "iad", "nyc", "mia", "hnl",
    "tor", "ams", "lhr", "par", "fra", "mad", "nue", "waw", "hel",
    "syd", "sao", "dbi", "jnb", "nai",
}

TUN_IFACE_HINTS = ("singbox_tun", "sing-tun", "wintun", "meta", "tun")
PROXY_PROC_HINTS = ("v2rayn", "sing-box", "singbox", "xray", "v2ray")
TAILSCALE_PROCS = ("tailscaled.exe", "tailscale.exe", "tailscale-ipn.exe")

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def ensure_app_dirs() -> None:
    for path in (APP_DATA, ROLLBACK_DIR, LOG_DIR, UPDATES_DIR):
        path.mkdir(parents=True, exist_ok=True)
