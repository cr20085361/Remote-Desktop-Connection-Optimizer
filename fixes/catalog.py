"""F01-F09 修复动作。"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from core.config import APP_DATA, ROLLBACK_DIR, TS_CGNAT_CIDR, TS_CGNAT_OVERRIDE, ensure_app_dirs
from core.models import Snapshot
from core.runner import is_admin, run, run_powershell
from fixes.base import FixAction, FixResult
from fixes import v2rayn
from probes.tailscale_probe import find_tailscale

ensure_app_dirs()


def _write_rollback(fix_id: str, body: str, meta: dict | None = None) -> str:
    """写回滚脚本。带 meta 时旁边再写一个 .json，程序内撤销优先用它（精确、不动别的改动）。"""
    ROLLBACK_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = ROLLBACK_DIR / f"{fix_id}_{stamp}.ps1"
    header = (
        "# RdpOptimizer rollback\n"
        f"# {fix_id} {stamp}\n"
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)\n"
    )
    if meta:
        header += "# 在程序里点「撤销」会精确删除本工具添加的规则；下面是整文件还原的备用方案。\n"
        path.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    path.write_text(header + body + "\n", encoding="utf-8")
    return str(path)


class F01TailscaleDirect(FixAction):
    def __init__(self) -> None:
        super().__init__(
            id="F01",
            title="v2rayN Tun 规则：tailscaled.exe 直连",
            summary="在路由规则最前插入进程直连，避免 WireGuard/STUN 进代理。",
            risk="修改 v2rayN 配置库，需重启 Tun 生效。",
        )

    def precheck(self, snapshot: Snapshot) -> tuple[bool, str]:
        if snapshot.proxy.tailscale_direct_in_rules:
            return False, "规则中已包含 tailscale 直连。"
        if not snapshot.proxy.v2rayn_path:
            return False, "未找到 v2rayN 安装目录。请在设置中指定路径。"
        return True, f"将修改 {snapshot.proxy.v2rayn_path} 的路由配置。"

    def apply(self, snapshot: Snapshot) -> FixResult:
        result = v2rayn.patch_routing(snapshot.proxy.v2rayn_path, add_process=True, add_cgnat=False)
        rollback = ""
        if result.get("backups"):
            rollback = _write_rollback(
                "F01",
                _backup_copy_script(result["backups"]) + "\nWrite-Host '已回滚 v2rayN 配置，请重启 v2rayN'",
                {"kind": "v2rayn", "root": snapshot.proxy.v2rayn_path, "kinds": ["process"]},
            )
        return FixResult(
            ok=bool(result.get("ok")),
            message=str(result.get("message") or ""),
            rollback_path=rollback,
            changed=bool(result.get("changed")),
            details=result,
        )

    def verify(self, snapshot: Snapshot) -> tuple[bool, str]:
        if snapshot.proxy.tailscale_direct_in_rules:
            return True, "配置中已出现 tailscale 直连规则。"
        return False, "配置尚未体现直连规则，可能需要重启 v2rayN 后再采集。"


class F02DisableTun(FixAction):
    def __init__(self) -> None:
        super().__init__(
            id="F02",
            title="关闭 Tun，改回系统代理模式",
            summary="F01 的备选方案。系统代理不会劫持 Tailscale UDP。",
            risk="关闭 Tun 后需依赖系统代理访问外网。",
        )

    def precheck(self, snapshot: Snapshot) -> tuple[bool, str]:
        if not snapshot.proxy.tun_up:
            return False, "当前未见 Tun 网卡处于活动状态。"
        return True, "将尝试关闭 v2rayN Tun 开关；失败则给出手动步骤。"

    def apply(self, snapshot: Snapshot) -> FixResult:
        result = {"ok": False, "message": "未找到 v2rayN"}
        if snapshot.proxy.v2rayn_path:
            result = v2rayn.disable_tun_flag(snapshot.proxy.v2rayn_path)
        backups = result.get("backups") or []
        rollback = _write_rollback(
            "F02",
            (_backup_copy_script(backups) + "\n" if backups else "")
            + "Write-Host '请在 v2rayN 主界面重新打开「启用 Tun」（配置已还原的话，重启 v2rayN 即可）'",
        )
        manual = (
            "手动步骤：打开 v2rayN → 关闭底部「启用 Tun」→ 路由模式保持「绕过大陆」。"
            "系统代理可保留，RDP/Tailscale 不走系统代理。"
        )
        msg = str(result.get("message") or "")
        if not result.get("ok"):
            msg = msg + " " + manual
        return FixResult(
            ok=bool(result.get("ok")),
            message=msg or manual,
            rollback_path=rollback,
            changed=bool(result.get("changed")),
            details=result,
        )


class F03ProxyOverride(FixAction):
    def __init__(self) -> None:
        super().__init__(
            id="F03",
            title="系统代理绕过 100.*",
            summary="在 ProxyOverride 中追加 Tailscale CGNAT 段。",
            risk="仅改当前用户 Internet Settings。",
            need_admin=False,
        )

    def precheck(self, snapshot: Snapshot) -> tuple[bool, str]:
        if snapshot.proxy.override_has_100:
            return False, "ProxyOverride 已包含 100.*"
        return True, f"当前: {snapshot.proxy.proxy_override or '(空)'}"

    def apply(self, snapshot: Snapshot) -> FixResult:
        current = _read_proxy_override(snapshot.proxy.proxy_override or "")
        parts = [p for p in current.split(";") if p]
        if TS_CGNAT_OVERRIDE not in parts:
            parts.append(TS_CGNAT_OVERRIDE)
        new_val = ";".join(parts)
        escaped = current.replace("'", "''")
        rollback = _write_rollback(
            "F03",
            "Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings' "
            f"-Name ProxyOverride -Value '{escaped}'",
        )
        ps = (
            "Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings' "
            f"-Name ProxyOverride -Value '{new_val.replace(chr(39), chr(39)*2)}'"
        )
        result = run_powershell(ps, timeout=15)
        return FixResult(
            ok=result.ok,
            message="已写入 ProxyOverride" if result.ok else (result.stderr or "写入失败"),
            rollback_path=rollback,
            changed=result.ok,
        )

    def verify(self, snapshot: Snapshot) -> tuple[bool, str]:
        return snapshot.proxy.override_has_100, "已包含 100.*" if snapshot.proxy.override_has_100 else "仍缺少 100.*"


class F04CgnatDirect(FixAction):
    def __init__(self) -> None:
        super().__init__(
            id="F04",
            title="分流直连 100.64.0.0/10",
            summary="在 v2rayN 路由最前插入 Tailscale CGNAT 直连。",
            risk="修改 v2rayN 路由。",
        )

    def precheck(self, snapshot: Snapshot) -> tuple[bool, str]:
        if not snapshot.proxy.v2rayn_path:
            return False, "未找到 v2rayN 目录。"
        return True, "将插入 100.64.0.0/10 → direct。"

    def apply(self, snapshot: Snapshot) -> FixResult:
        result = v2rayn.patch_routing(snapshot.proxy.v2rayn_path, add_process=False, add_cgnat=True)
        rollback = ""
        if result.get("backups"):
            rollback = _write_rollback(
                "F04",
                _backup_copy_script(result["backups"]),
                {
                    "kind": "v2rayn",
                    "root": snapshot.proxy.v2rayn_path,
                    "kinds": ["cgnat"],
                    "tun_exclude_added": result.get("tun_exclude_added") or [],
                },
            )
        return FixResult(
            ok=bool(result.get("ok")),
            message=str(result.get("message") or ""),
            rollback_path=rollback,
            changed=bool(result.get("changed")),
            details=result,
        )


class F05IfaceMetric(FixAction):
    def __init__(self) -> None:
        super().__init__(
            id="F05",
            title="提高 Tun 接口跃点",
            summary="把 singbox_tun 的 InterfaceMetric 调高，降低抢占默认路由的优先级。",
            risk="可能影响 Tun 全局接管，优先用 F01。",
        )

    def precheck(self, snapshot: Snapshot) -> tuple[bool, str]:
        if not is_admin():
            return False, "需要管理员权限。"
        tun = [i for i in snapshot.route.ifaces if i.is_tun]
        if not tun:
            return False, "未发现 Tun 网卡。"
        return True, "将把 Tun 网卡 InterfaceMetric 设为 80。"

    def apply(self, snapshot: Snapshot) -> FixResult:
        lines_apply = []
        lines_rb = []
        for iface in snapshot.route.ifaces:
            if not iface.is_tun:
                continue
            old = iface.metric if iface.metric is not None else 25
            lines_apply.append(
                f"Set-NetIPInterface -InterfaceAlias '{iface.name}' -AddressFamily IPv4 -InterfaceMetric 80"
            )
            lines_rb.append(
                f"Set-NetIPInterface -InterfaceAlias '{iface.name}' -AddressFamily IPv4 -InterfaceMetric {old}"
            )
        result = run_powershell("; ".join(lines_apply), timeout=20)
        rollback = _write_rollback("F05", "\n".join(lines_rb))
        return FixResult(result.ok, result.stderr or "已调整 Tun 跃点", rollback, result.ok)


class F06RdpTransport(FixAction):
    def __init__(self) -> None:
        super().__init__(
            id="F06",
            title="恢复 RDP TCP+UDP 双通道",
            summary="将 SelectTransport 置 0，并清除禁用 UDP 的策略。",
            risk="改 HKLM 注册表，需管理员。",
        )

    def precheck(self, snapshot: Snapshot) -> tuple[bool, str]:
        if not is_admin():
            return False, "需要管理员权限。"
        if snapshot.rdp.select_transport in (None, 0) and snapshot.rdp.client_disable_udp != 1:
            return False, "传输层已是默认/双通道。"
        return True, f"SelectTransport={snapshot.rdp.select_transport} fClientDisableUDP={snapshot.rdp.client_disable_udp}"

    def apply(self, snapshot: Snapshot) -> FixResult:
        old_st = snapshot.rdp.select_transport
        rb = []
        if old_st is None:
            rb.append(
                "Remove-ItemProperty -Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Terminal Server\\WinStations\\RDP-Tcp' "
                "-Name SelectTransport -ErrorAction SilentlyContinue"
            )
        else:
            rb.append(
                "Set-ItemProperty -Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Terminal Server\\WinStations\\RDP-Tcp' "
                f"-Name SelectTransport -Type DWord -Value {int(old_st)}"
            )
        apply = [
            "Set-ItemProperty -Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Terminal Server\\WinStations\\RDP-Tcp' "
            "-Name SelectTransport -Type DWord -Value 0"
        ]
        if snapshot.rdp.client_disable_udp == 1:
            apply.append(
                "Remove-ItemProperty -Path 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows NT\\Terminal Services' "
                "-Name fClientDisableUDP -ErrorAction SilentlyContinue"
            )
            rb.append(
                "New-Item -Path 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows NT\\Terminal Services' -Force | Out-Null; "
                "Set-ItemProperty -Path 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows NT\\Terminal Services' "
                "-Name fClientDisableUDP -Type DWord -Value 1"
            )
        result = run_powershell("; ".join(apply), timeout=20)
        rollback = _write_rollback("F06", "\n".join(rb))
        return FixResult(result.ok, "已写入 RDP 传输设置" if result.ok else result.stderr, rollback, result.ok)


class F07Mtu(FixAction):
    def __init__(self) -> None:
        super().__init__(
            id="F07",
            title="按实测 PMTU 调整 Tailscale MTU",
            summary="默认将 Tailscale 接口 MTU 设为 1280（WireGuard 安全值）。",
            risk="改接口 MTU。",
        )

    def precheck(self, snapshot: Snapshot) -> tuple[bool, str]:
        ts = [i for i in snapshot.route.ifaces if i.is_tailscale]
        if not ts:
            return False, "未找到 Tailscale 网卡。"
        return True, f"当前 MTU={ts[0].mtu}"

    def apply(self, snapshot: Snapshot) -> FixResult:
        ts = next(i for i in snapshot.route.ifaces if i.is_tailscale)
        target = 1280
        lows = [s.pmtu for s in snapshot.links if s.pmtu]
        if lows:
            target = min(1280, min(lows))
        old = ts.mtu or 1280
        result = run(
            ["netsh", "interface", "ipv4", "set", "subinterface", ts.name, f"mtu={target}", "store=persistent"],
            timeout=20,
        )
        rollback = _write_rollback(
            "F07",
            f'netsh interface ipv4 set subinterface "{ts.name}" mtu={old} store=persistent',
        )
        ok = result.ok or "确定" in result.stdout or result.returncode == 0
        return FixResult(ok, result.stdout or result.stderr or f"MTU -> {target}", rollback, ok)


class F08RdpFile(FixAction):
    def __init__(self) -> None:
        super().__init__(
            id="F08",
            title="生成优化版 .rdp 文件",
            summary="为每个在线节点生成弱网友好的远程桌面配置。",
            risk="只写文件，不改系统。",
            need_admin=False,
            reversible=True,
        )

    def precheck(self, snapshot: Snapshot) -> tuple[bool, str]:
        peers = _windows_peers(snapshot)
        if not peers:
            return False, "没有在线的 Windows 节点。"
        return True, f"将为 {len(peers)} 个节点生成 .rdp。"

    def apply(self, snapshot: Snapshot) -> FixResult:
        out_dir = APP_DATA / "rdp"
        out_dir.mkdir(parents=True, exist_ok=True)
        written = []
        for peer in _windows_peers(snapshot):
            safe = re.sub(r'[\\/:*?"<>|]', "_", peer.hostname or peer.ip)
            path = out_dir / f"{safe}.rdp"
            path.write_text(_rdp_body(peer.ip, peer.hostname), encoding="utf-8")
            written.append(str(path))
        rollback = _write_rollback(
            "F08",
            "\n".join(f'Remove-Item -Force "{p}"' for p in written),
        )
        return FixResult(True, "已生成: " + "；".join(written), rollback, True, {"files": written})


class F09DirectHarden(FixAction):
    def __init__(self) -> None:
        super().__init__(
            id="F09",
            title="固定 Tailscale UDP 端口",
            summary="设置固定端口 41641，配合本机已有的 UPnP 提升直连率。",
            risk="执行 tailscale set --port=41641。",
        )

    def precheck(self, snapshot: Snapshot) -> tuple[bool, str]:
        if not find_tailscale():
            return False, "未找到 tailscale.exe"
        return True, f"当前 PortMapping={snapshot.netcheck.port_mapping or '未知'}"

    def apply(self, snapshot: Snapshot) -> FixResult:
        exe = find_tailscale()
        result = run([exe, "set", "--port=41641"], timeout=20)
        rollback = _write_rollback("F09", f'& "{exe}" set --port=0')
        if "upnp" in (snapshot.netcheck.port_mapping or "").lower():
            extra = "本机 netcheck 显示路由器支持 UPnP，通常会自动映射；仍不直连时可手动映射 UDP 41641。"
        else:
            extra = "若路由器管理页可访问，建议把 UDP 41641 映射到这台电脑。"
        return FixResult(
            result.ok,
            (result.stdout or result.stderr or "已设置端口") + " " + extra,
            rollback,
            result.ok,
        )


def _read_proxy_override(fallback: str) -> str:
    """快照可能已过期（v2rayN 会改写这个值），apply 时重读一次。"""
    result = run_powershell(
        "(Get-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings' "
        "-ErrorAction SilentlyContinue).ProxyOverride",
        timeout=10,
    )
    return result.stdout.strip() if result.ok else fallback


def _windows_peers(snapshot: Snapshot) -> list:
    return [p for p in snapshot.online_peers() if not p.os or p.os.lower() == "windows"]


_FW_RULE = "RdpOptimizer RDP UDP 3389"


class F10RdpUdpFirewall(FixAction):
    def __init__(self) -> None:
        super().__init__(
            id="F10",
            title="放行 RDP UDP 3389（仅 Tailscale 网段）",
            summary="新增防火墙入站规则，让远程桌面能用上 UDP。",
            risk="只放行 100.64.0.0/10，可删除该规则撤销。",
        )

    def precheck(self, snapshot: Snapshot) -> tuple[bool, str]:
        if not is_admin():
            return False, "需要管理员权限。"
        inbound_tcp = [
            s for s in snapshot.rdp.sessions
            if s.get("direction") == "in" and s.get("transport") == "tcp"
        ]
        if not inbound_tcp:
            return False, "没有发现回退到 TCP 的入站会话（本修复只对被连接的这台电脑有效）。"
        return True, "将新增入站规则：UDP 3389，来源 100.64.0.0/10。"

    def apply(self, snapshot: Snapshot) -> FixResult:
        script = (
            f"$n = '{_FW_RULE}'; "
            "if (-not (Get-NetFirewallRule -DisplayName $n -ErrorAction SilentlyContinue)) { "
            "New-NetFirewallRule -DisplayName $n -Direction Inbound -Protocol UDP -LocalPort 3389 "
            f"-Action Allow -Profile Any -RemoteAddress {TS_CGNAT_CIDR} | Out-Null }}"
        )
        result = run_powershell(script, timeout=25)
        rollback = _write_rollback(
            "F10", f"Remove-NetFirewallRule -DisplayName '{_FW_RULE}' -ErrorAction SilentlyContinue"
        )
        return FixResult(
            result.ok,
            "已放行 UDP 3389（仅 Tailscale 网段）。请断开后重新连接远程桌面。" if result.ok else (result.stderr or "写入防火墙规则失败"),
            rollback,
            result.ok,
        )


def _backup_copy_script(backups: list) -> str:
    lines = []
    for item in backups:
        if isinstance(item, dict):
            src, bak = item.get("src", ""), item.get("bak", "")
        else:
            src, bak = "", str(item)
        if src and bak:
            lines.append(f'Copy-Item -Force "{bak}" "{src}"')
    return "\n".join(lines) if lines else "Write-Host '没有可回滚的备份文件'"


def _rdp_body(ip: str, hostname: str) -> str:
    return f"""full address:s:{ip}
username:s:
prompt for credentials:i:1
session bpp:i:16
compression:i:1
networkautodetect:i:1
bandwidthautodetect:i:1
connection type:i:7
displayconnectionbar:i:1
disable wallpaper:i:1
allow font smoothing:i:0
allow desktop composition:i:0
disable full window drag:i:1
disable menu anims:i:1
disable themes:i:0
bitmapcachepersistenable:i:1
audiomode:i:2
redirectclipboard:i:1
redirectprinters:i:0
redirectcomports:i:0
redirectsmartcards:i:0
autoreconnection enabled:i:1
authentication level:i:2
enablecredsspsupport:i:1
negotiate security layer:i:1
videoplaybackmode:i:1
use redirection server name:i:0
gatewayprofileusagemethod:i:1
screen mode id:i:2
smart sizing:i:1
dynamic resolution:i:1
enablerdsaadauth:i:0
"""


ACTIONS: dict[str, FixAction] = {
    a.id: a
    for a in (
        F01TailscaleDirect(),
        F02DisableTun(),
        F03ProxyOverride(),
        F04CgnatDirect(),
        F05IfaceMetric(),
        F06RdpTransport(),
        F07Mtu(),
        F08RdpFile(),
        F09DirectHarden(),
        F10RdpUdpFirewall(),
    )
}
