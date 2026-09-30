"""代理进程、Tun 网卡、系统代理、v2rayN / sing-box 分流规则。"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from core.config import TAILSCALE_PROCS, TS_CGNAT_OVERRIDE
from core.models import ProxyState
from core.runner import powershell_json


_SCRIPT = r"""
$procs = @(Get-CimInstance Win32_Process | Where-Object {
  $_.Name -match 'v2rayN|sing-box|singbox|xray|v2ray'
} | Select-Object Name,ProcessId,ExecutablePath,CommandLine)
$proxy = Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' |
  Select-Object ProxyEnable,ProxyServer,ProxyOverride
$obj = [ordered]@{ procs = $procs; proxy = $proxy }
$obj | ConvertTo-Json -Depth 5 -Compress
"""

_root_cache: str = ""


def _common_roots() -> list[Path]:
    home = Path(os.environ.get("USERPROFILE", ""))
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    roots = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "v2rayN",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "v2rayN",
        Path(r"C:2rayN"),
    ]
    if str(local):
        roots.append(local / "Programs" / "v2rayN")
    if str(home):
        roots.append(home / "v2rayN")
    return roots


def _candidate_roots(proc_path: str) -> list[Path]:
    """v2rayN 目录候选：运行进程 → 设置里的路径 → 上次成功的路径 → 常见安装位置。不做磁盘递归扫描。"""
    found: list[Path] = []
    if proc_path:
        p = Path(proc_path)
        found.append(p.parent if p.is_file() else p)
    try:
        from core.settings import load_settings

        configured = str(load_settings().get("v2rayn_path") or "").strip()
        if configured:
            found.append(Path(configured))
    except Exception:
        pass
    if _root_cache:
        found.append(Path(_root_cache))
    found.extend(_common_roots())
    uniq: list[Path] = []
    seen = set()
    for item in found:
        key = str(item).lower()
        if key in seen or not str(item):
            continue
        seen.add(key)
        uniq.append(item)
    return uniq


def _find_v2rayn_root(proc_path: str) -> str:
    scored: list[tuple[float, str]] = []
    for root in _candidate_roots(proc_path):
        cfg = root / "guiConfigs" / "guiNConfig.json"
        db = root / "guiConfigs" / "guiNDB.db"
        exe = root / "v2rayN.exe"
        if not (cfg.exists() or db.exists() or exe.exists()):
            continue
        mtime = 0.0
        if cfg.exists():
            mtime = max(mtime, cfg.stat().st_mtime)
        if db.exists():
            mtime = max(mtime, db.stat().st_mtime)
        scored.append((mtime, str(root)))
    if not scored:
        return ""
    scored.sort(reverse=True)
    global _root_cache
    _root_cache = scored[0][1]
    return _root_cache


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _override_has_100(text: str) -> bool:
    blob = (text or "").replace(" ", "").lower()
    return "100.*" in blob or "100.64.0.0/10" in blob or "<local>" in blob and "100." in blob


def _iter_config_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for folder in (root / "guiConfigs", root / "binConfigs", root):
        if not folder.exists():
            continue
        for pattern in ("*.json", "*.db", "*.sqlite", "*.db3"):
            files.extend(folder.glob(pattern))
        for child in folder.glob("*"):
            if child.is_dir():
                files.extend(child.glob("*.json"))
    return files


def _rules_have_tailscale_direct(obj) -> bool:
    if isinstance(obj, dict):
        process_fields = []
        for key in ("process_name", "Process", "process", "processName"):
            val = obj.get(key)
            if isinstance(val, str):
                process_fields.append(val)
            elif isinstance(val, list):
                process_fields.extend(str(x) for x in val)
        outbound = str(obj.get("outbound") or obj.get("outboundTag") or obj.get("OutboundTag") or "").lower()
        blob = " ".join(process_fields).lower()
        if any(p.replace(".exe", "") in blob for p in ("tailscaled", "tailscale")) and "direct" in outbound:
            return True
        return any(_rules_have_tailscale_direct(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_rules_have_tailscale_direct(v) for v in obj)
    if isinstance(obj, str):
        lower = obj.lower()
        return "tailscaled" in lower and "direct" in lower
    return False


def _extract_node_ips(obj, acc: list[str]) -> None:
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key in ("address", "Address", "server", "Server", "remote_dns_server") and isinstance(val, str):
                if _looks_ipv4(val):
                    acc.append(val)
            else:
                _extract_node_ips(val, acc)
    elif isinstance(obj, list):
        for item in obj:
            _extract_node_ips(item, acc)


def _looks_ipv4(text: str) -> bool:
    parts = text.strip().split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(p) <= 255 for p in parts)
    except ValueError:
        return False


def inspect_v2rayn(root: str) -> tuple[list[str], bool, str, str]:
    """返回 node_ips, tailscale_direct, config_path, hint。"""
    if not root:
        return [], False, "", ""
    base = Path(root)
    node_ips: list[str] = []
    has_direct = False
    used = ""
    hint_parts: list[str] = []
    for path in _iter_config_files(base):
        try:
            if path.suffix.lower() in {".db", ".sqlite", ".db3"}:
                has_direct = has_direct or _inspect_sqlite(path, node_ips)
                used = used or str(path)
                hint_parts.append(path.name)
            else:
                data = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
                _extract_node_ips(data, node_ips)
                if _rules_have_tailscale_direct(data):
                    has_direct = True
                    used = str(path)
                hint_parts.append(path.name)
                if not used and path.suffix.lower() == ".json":
                    used = str(path)
        except Exception:
            continue
    uniq = []
    for ip in node_ips:
        if ip not in uniq and not ip.startswith(("127.", "0.")):
            uniq.append(ip)
    hint = "已扫描: " + ", ".join(hint_parts[:8]) if hint_parts else "未找到 guiConfigs"
    return uniq, has_direct, used, hint


def _inspect_sqlite(path: Path, node_ips: list[str]) -> bool:
    has_direct = False
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            try:
                rows = conn.execute(f"SELECT * FROM [{table}] LIMIT 200").fetchall()
                cols = [d[0] for d in conn.execute(f"PRAGMA table_info([{table}])").fetchall()]
            except sqlite3.Error:
                continue
            for row in rows:
                mapping = dict(zip(cols, row))
                for val in mapping.values():
                    if not isinstance(val, str):
                        continue
                    text = val.strip()
                    if text.startswith("{") or text.startswith("["):
                        try:
                            obj = json.loads(text)
                        except json.JSONDecodeError:
                            continue
                        _extract_node_ips(obj, node_ips)
                        if _rules_have_tailscale_direct(obj):
                            has_direct = True
                    else:
                        if _looks_ipv4(text):
                            node_ips.append(text)
                        if "tailscaled" in text.lower() and "direct" in text.lower():
                            has_direct = True
    finally:
        conn.close()
    return has_direct


def collect() -> ProxyState:
    data = powershell_json(_SCRIPT, timeout=35) or {}
    procs = _as_list(data.get("procs"))
    proxy = data.get("proxy") or {}
    v2rayn_running = False
    singbox_running = False
    xray_running = False
    v2rayn_path = ""
    for proc in procs:
        name = str(proc.get("Name") or "").lower()
        path = str(proc.get("ExecutablePath") or "")
        if "v2rayn" in name:
            v2rayn_running = True
            v2rayn_path = path or v2rayn_path
        if "sing-box" in name or "singbox" in name:
            singbox_running = True
        if name.startswith("xray"):
            xray_running = True
    root = _find_v2rayn_root(v2rayn_path)
    node_ips, has_direct, config_path, hint = inspect_v2rayn(root)
    override = str(proxy.get("ProxyOverride") or "")
    enable = proxy.get("ProxyEnable")
    return ProxyState(
        v2rayn_running=v2rayn_running,
        singbox_running=singbox_running,
        xray_running=xray_running,
        v2rayn_path=root or v2rayn_path,
        singbox_config_path=config_path,
        proxy_enable=bool(enable) if enable is not None else False,
        proxy_server=str(proxy.get("ProxyServer") or ""),
        proxy_override=override,
        override_has_100=_override_has_100(override),
        node_addresses=node_ips,
        tailscale_direct_in_rules=has_direct,
        routing_hint=hint,
    )


def same_slash24(a: str, b: str) -> bool:
    pa, pb = a.split("."), b.split(".")
    if len(pa) != 4 or len(pb) != 4:
        return False
    return pa[:3] == pb[:3]


def ts_process_names() -> tuple[str, ...]:
    return TAILSCALE_PROCS


def cgnat_override_token() -> str:
    return TS_CGNAT_OVERRIDE
