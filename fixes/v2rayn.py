"""v2rayN 配置定位与路由规则写入。"""

from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.config import APP_DATA, TAILSCALE_PROCS
from probes.proxy_probe import inspect_v2rayn

DIRECT_PROCESSES = ["tailscaled.exe", "tailscale.exe", "tailscale-ipn.exe"]
CGNAT_CIDR = "100.64.0.0/10"


def _backup(path: Path) -> dict[str, str]:
    APP_DATA.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = APP_DATA / "backups"
    dest.mkdir(exist_ok=True)
    copied = dest / f"{path.name}.{stamp}.bak"
    shutil.copy2(path, copied)
    return {"src": str(path), "bak": str(copied)}


def _rule_direct_process() -> dict[str, Any]:
    return {
        "Id": str(uuid.uuid4().int)[:18],
        "OutboundTag": "direct",
        "Process": list(DIRECT_PROCESSES),
        "Enabled": True,
        "Remarks": "RdpOptimizer-Tailscale-process-direct",
    }


def _rule_cgnat() -> dict[str, Any]:
    return {
        "Id": str(uuid.uuid4().int)[:18],
        "OutboundTag": "direct",
        "Ip": [CGNAT_CIDR],
        "Enabled": True,
        "Remarks": "RdpOptimizer-Tailscale-cgnat-direct",
    }


def _is_our_rule(item: dict, kind: str) -> bool:
    remarks = str(item.get("remarks") or item.get("Remarks") or "")
    if kind == "process":
        return "RdpOptimizer-Tailscale-process" in remarks
    return "RdpOptimizer-Tailscale-cgnat" in remarks


def _rules_from_value(raw: Any) -> Optional[list]:
    if raw is None:
        return None
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(obj, list):
            return obj
        if isinstance(obj, dict):
            for key in ("rules", "Rules", "ruleSet", "RuleSet"):
                if isinstance(obj.get(key), list):
                    return obj[key]
    return None


def _insert_rule(rules: list, new_rule: dict, kind: str) -> list:
    rules = [r for r in rules if not (isinstance(r, dict) and _is_our_rule(r, kind))]
    return [new_rule, *rules]


def _apply_inserts(rules: list, add_process: bool, add_cgnat: bool) -> list:
    new_rules = list(rules)
    if add_cgnat:
        new_rules = _insert_rule(new_rules, _rule_cgnat(), "cgnat")
    if add_process:
        new_rules = _insert_rule(new_rules, _rule_direct_process(), "process")
    return new_rules


def patch_routing(root: str, *, add_process: bool, add_cgnat: bool) -> dict[str, Any]:
    base = Path(root)
    if not base.exists():
        return {"ok": False, "message": f"找不到 v2rayN 目录: {root}"}
    backups: list[str] = []
    changed = False
    notes: list[str] = []

    json_files = list((base / "guiConfigs").glob("*.json")) if (base / "guiConfigs").exists() else []
    json_files += list(base.glob("*routing*.json"))
    for path in json_files:
        if path.name.lower() == "guinconfig.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
        except Exception:
            continue
        mutated, did = _patch_obj(data, add_process, add_cgnat)
        if did:
            backups.append(_backup(path))
            path.write_text(json.dumps(mutated, ensure_ascii=False, indent=2), encoding="utf-8")
            changed = True
            notes.append(f"已写入 {path.name}")

    db_files: list[Path] = []
    for folder in (base / "guiConfigs", base):
        if folder.exists():
            db_files.extend(folder.glob("*.db"))
            db_files.extend(folder.glob("*.sqlite"))
    for db in db_files:
        did, msg = _patch_sqlite(db, add_process, add_cgnat, backups)
        if did:
            changed = True
            notes.append(msg)

    if add_cgnat:
        tun = add_tun_exclude(root, [CGNAT_CIDR])
        if tun.get("changed"):
            changed = True
            notes.append(str(tun.get("message")))
            backups.extend(tun.get("backups") or [])

    if not changed:
        _, has_direct, config_path, hint = inspect_v2rayn(root)
        if has_direct and add_process:
            return {
                "ok": True,
                "changed": False,
                "message": "规则中已包含 tailscale 直连，无需修改。",
                "backups": backups,
            }
        return {
            "ok": False,
            "changed": False,
            "message": (
                "未能自动改写 v2rayN 路由库。请在 v2rayN → 设置 → 路由设置 顶部新增一条："
                "出站=direct，进程名=tailscaled.exe,tailscale.exe（不要填域名/IP）。"
                f" 扫描结果: {hint} {config_path}"
            ),
            "manual": True,
            "backups": backups,
        }
    return {
        "ok": True,
        "changed": True,
        "message": "；".join(notes) + "。请在 v2rayN 中重启 Tun 或重启软件使规则生效。",
        "backups": backups,
    }


def _patch_obj(data: Any, add_process: bool, add_cgnat: bool) -> tuple[Any, bool]:
    did = False

    def walk(obj: Any) -> Any:
        nonlocal did
        if isinstance(obj, dict):
            for key in ("rules", "Rules", "ruleSet", "RuleSet"):
                if isinstance(obj.get(key), list):
                    obj[key] = _apply_inserts(list(obj[key]), add_process, add_cgnat)
                    did = True
            if str(obj.get("remarks") or "") == "RdpOptimizer-skip":
                return obj
            for k, v in list(obj.items()):
                obj[k] = walk(v)
            return obj
        if isinstance(obj, list):
            # 可能本身就是规则数组
            if obj and all(isinstance(x, dict) and ("outboundTag" in x or "process" in x or "ip" in x) for x in obj):
                rules = _apply_inserts(list(obj), add_process, add_cgnat)
                did = True
                return rules
            return [walk(x) for x in obj]
        return obj

    return walk(data), did


def _patch_sqlite(db: Path, add_process: bool, add_cgnat: bool, backups: list) -> tuple[bool, str]:
    conn = sqlite3.connect(str(db))
    changed = False
    updated = 0
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "RoutingItem" not in tables:
            return False, f"{db.name} 无 RoutingItem 表"
        backups.append(_backup(db))
        rows = conn.execute("SELECT Id, RuleSet FROM RoutingItem").fetchall()
        for rid, raw in rows:
            rules = _rules_from_value(raw)
            if rules is None:
                continue
            new_rules = _apply_inserts(rules, add_process, add_cgnat)
            payload = json.dumps(new_rules, ensure_ascii=False)
            old = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
            if payload != old:
                conn.execute(
                    "UPDATE RoutingItem SET RuleSet=?, RuleNum=? WHERE Id=?",
                    (payload, len(new_rules), rid),
                )
                changed = True
                updated += 1
        conn.commit()
    finally:
        conn.close()
    return changed, f"已更新 {db.name} 中 {updated} 条 RoutingItem" if changed else f"{db.name} 路由未变化"


def add_tun_exclude(root: str, cidrs: list[str]) -> dict[str, Any]:
    path = Path(root) / "guiConfigs" / "guiNConfig.json"
    if not path.exists():
        return {"ok": False, "changed": False, "message": "无 guiNConfig.json", "backups": []}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    tun = data.setdefault("TunModeItem", {})
    existing = list(tun.get("RouteExcludeAddress") or [])
    added = False
    for cidr in cidrs:
        if cidr not in existing:
            existing.append(cidr)
            added = True
    if not added:
        return {"ok": True, "changed": False, "message": "Tun 排除地址已包含 CGNAT", "backups": []}
    tun["RouteExcludeAddress"] = existing
    bak = _backup(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "changed": True,
        "message": f"TunModeItem.RouteExcludeAddress 已加入 {', '.join(cidrs)}",
        "backups": [bak],
    }


def disable_tun_flag(root: str) -> dict[str, Any]:
    base = Path(root)
    if not base.exists():
        return {"ok": False, "message": "v2rayN 目录不存在"}
    changed = False
    backups: list = []
    for path in (base / "guiConfigs").glob("*.json") if (base / "guiConfigs").exists() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        mutated, did = _set_tun_false(data)
        if did:
            backups.append(_backup(path))
            path.write_text(json.dumps(mutated, ensure_ascii=False, indent=2), encoding="utf-8")
            changed = True
    if not changed:
        return {
            "ok": False,
            "manual": True,
            "message": "未能改写 EnableTun。请在 v2rayN 主界面关闭「启用 Tun」开关。",
            "backups": backups,
        }
    return {
        "ok": True,
        "changed": True,
        "message": "已将配置中的 Tun 开关置为关闭，请重启 v2rayN。",
        "backups": backups,
    }


def _set_tun_false(obj: Any) -> tuple[Any, bool]:
    did = False

    def walk(x: Any) -> Any:
        nonlocal did
        if isinstance(x, dict):
            for key in ("EnableTun", "enableTun", "EnableTunMode"):
                if key in x and x[key]:
                    x[key] = False
                    did = True
            if "TunModeItem" in x and isinstance(x["TunModeItem"], dict):
                if x["TunModeItem"].get("EnableTun"):
                    x["TunModeItem"]["EnableTun"] = False
                    did = True
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        return x

    return walk(obj), did
