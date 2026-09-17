"""R01-R11 规则定义。每条规则返回 Finding 或 None。"""

from __future__ import annotations

from typing import Callable, Optional

from core.config import ASIA_DERP, OVERSEAS_DERP_HINT
from core.models import Finding, Snapshot
from probes.proxy_probe import same_slash24

RuleFn = Callable[[Snapshot], Optional[Finding]]


def _slash24(ip: str) -> str:
    parts = ip.split(".")
    return ".".join(parts[:3]) + ".0/24" if len(parts) == 4 else ip


def r01_proxy_hijack(snap: Snapshot) -> Optional[Finding]:
    g4 = snap.netcheck.global_v4
    proxy = snap.proxy
    if not g4:
        return None
    matched_node = ""
    for addr in proxy.node_addresses:
        if g4 == addr or same_slash24(g4, addr):
            matched_node = addr
            break
    default_is_tun = any(
        route.iface.lower() in {n.lower() for n in proxy.tun_ifaces} or "tun" in route.iface.lower()
        for route in snap.route.default_routes[:1]
    )
    hijacked = False
    reasons: list[str] = []
    if matched_node:
        hijacked = True
        reasons.append(f"netcheck 公网出口 {g4} 与代理节点 {matched_node} 同网段 {_slash24(g4)}")
    if proxy.tun_up and default_is_tun:
        hijacked = True
        reasons.append(
            f"Tun 已启用且默认路由出口为 {snap.route.default_exit_iface}（跃点最优）"
        )
        if not proxy.tailscale_direct_in_rules:
            reasons.append("sing-box/v2rayN 规则中未见 tailscaled.exe → direct")
    if not hijacked:
        return None
    reasons.append(f"STUN/端点探测地址 {g4}:{snap.netcheck.global_v4_port or '?'}")
    if snap.netcheck.preferred_derp:
        reasons.append(
            f"最近 DERP={snap.netcheck.preferred_derp} "
            f"({snap.netcheck.preferred_derp_code or '?'}, "
            f"{snap.netcheck.preferred_derp_latency_ms}ms)"
        )
    return Finding(
        id="R01",
        severity="critical",
        title="代理隧道劫持了 Tailscale 端点探测",
        evidence="；".join(reasons),
        fix_ids=["F01", "F02", "F04"],
        hint="Tailscale 会把代理出口 IP 通告给对端，直连质量下降或回落到海外 DERP。",
    )


def r02_derp_overseas(snap: Snapshot) -> Optional[Finding]:
    code = (snap.netcheck.preferred_derp_code or "").lower()
    name = (snap.netcheck.preferred_derp or "").lower()
    ms = snap.netcheck.preferred_derp_latency_ms
    overseas = code in OVERSEAS_DERP_HINT or any(k in name for k in ("los angeles", "san francisco", "london", "frankfurt"))
    asia = code in ASIA_DERP
    if ms is None:
        return None
    if (overseas or not asia) and ms > 200:
        return Finding(
            id="R02",
            severity="critical",
            title="DERP 中继落在高延迟海外区域",
            evidence=(
                f"最近 DERP={snap.netcheck.preferred_derp or code} "
                f"code={code or '?'} 延迟={ms}ms。"
                f" 各区域: "
                + ", ".join(f"{k}:{v:.0f}ms" for k, v in list(snap.netcheck.region_latency.items())[:8])
            ),
            fix_ids=["F01", "F02"],
            hint="国内正常应优先东京/香港，延迟通常 30–80ms。一旦直连失败，RDP 会不可用。",
        )
    return None


def r03_peer_on_derp(snap: Snapshot) -> Optional[Finding]:
    relayed = [
        p for p in snap.online_peers()
        if (p.relay and not p.cur_addr) or (p.ping_via.lower().startswith("derp") if p.ping_via else False)
    ]
    if not relayed:
        return None
    lines = [f"{p.hostname}({p.ip}) relay={p.relay or p.ping_via} rtt={p.ping_rtt_ms}" for p in relayed]
    return Finding(
        id="R03",
        severity="critical",
        title="有节点正走 DERP 中继而非直连",
        evidence="；".join(lines),
        fix_ids=["F01", "F09"],
        hint="DERP 中继会把流量送到最近中继区。若最近区在海外，远程桌面会严重卡顿。",
    )


def r04_direct_but_slow(snap: Snapshot) -> Optional[Finding]:
    slow = []
    for peer in snap.online_peers():
        rtt = peer.ping_rtt_ms
        if rtt is None:
            continue
        via_direct = bool(peer.cur_addr) or (peer.ping_via and "derp" not in peer.ping_via.lower())
        if via_direct and rtt > 120:
            slow.append(f"{peer.hostname} via {peer.ping_via or peer.cur_addr} RTT={rtt:.0f}ms")
    if not slow:
        return None
    return Finding(
        id="R04",
        severity="high",
        title="已直连但 RTT 远超国内预期",
        evidence="；".join(slow) + "。国内异地直连通常 20–60ms，>120ms 说明 UDP 仍可能绕行代理或跨网拥塞。",
        fix_ids=["F01", "F04"],
        hint="先排除代理劫持，再看运营商跨网与无线干扰。",
    )


def r05_tun_steals_default(snap: Snapshot) -> Optional[Finding]:
    if not snap.route.default_routes:
        return None
    best = snap.route.default_routes[0]
    tun_names = {n.lower() for n in snap.proxy.tun_ifaces}
    if "tun" not in best.iface.lower() and best.iface.lower() not in tun_names and not any(
        i.is_tun and i.name.lower() == best.iface.lower() for i in snap.route.ifaces
    ):
        return None
    physical = [i for i in snap.route.ifaces if i.is_physical]
    phys_txt = ", ".join(f"{i.name} metric={i.metric}" for i in physical[:4]) or "未识别到物理网卡"
    return Finding(
        id="R05",
        severity="high",
        title="隧道网卡抢占了系统默认路由",
        evidence=(
            f"最优默认路由: {best.iface} nexthop={best.nexthop} "
            f"RouteMetric={best.route_metric} IfaceMetric={best.iface_metric} "
            f"有效跃点={best.effective_metric}。物理网卡: {phys_txt}"
        ),
        fix_ids=["F01", "F02", "F05"],
        hint="Tun 作为 0.0.0.0/0 出口时，STUN/WireGuard UDP 很容易被送进代理。",
    )


def r06_proxy_override_missing_cgnat(snap: Snapshot) -> Optional[Finding]:
    if not snap.proxy.proxy_enable:
        return None
    if snap.proxy.override_has_100:
        return None
    return Finding(
        id="R06",
        severity="medium",
        title="系统代理绕过列表缺少 Tailscale 地址段",
        evidence=(
            f"ProxyEnable=1 ProxyServer={snap.proxy.proxy_server} "
            f"ProxyOverride={snap.proxy.proxy_override or '(空)'}"
        ),
        fix_ids=["F03"],
        hint="mstsc 若走系统代理访问 100.x，会把 RDP 送进 v2rayN。",
    )


def r07_rdp_transport(snap: Snapshot) -> Optional[Finding]:
    st = snap.rdp.select_transport
    udp_off = snap.rdp.client_disable_udp
    issues = []
    if st not in (None, 0):
        issues.append(f"SelectTransport={st}（非默认 0=TCP+UDP）")
    if udp_off == 1:
        issues.append("策略 fClientDisableUDP=1，客户端禁用 UDP")
    if not issues:
        return None
    return Finding(
        id="R07",
        severity="medium",
        title="RDP 传输层配置异常",
        evidence="；".join(issues),
        fix_ids=["F06"],
        hint="UDP 被禁后 RDP 只能走 TCP，弱网下更容易卡顿。",
    )


def r08_mtu(snap: Snapshot) -> Optional[Finding]:
    ts_mtu = None
    tun_mtu = None
    for iface in snap.route.ifaces:
        if iface.is_tailscale:
            ts_mtu = iface.mtu
        if iface.is_tun:
            tun_mtu = iface.mtu
    pmtu_low = [s for s in snap.links if s.pmtu and ts_mtu and s.pmtu < ts_mtu]
    if ts_mtu and tun_mtu and tun_mtu not in (0, None) and abs((tun_mtu or 0) - ts_mtu) > 200:
        return Finding(
            id="R08",
            severity="medium",
            title="MTU / PMTU 不匹配",
            evidence=f"Tailscale MTU={ts_mtu}，Tun MTU={tun_mtu}。差异过大会导致分片或黑洞。",
            fix_ids=["F07"],
        )
    if pmtu_low:
        ev = "；".join(f"{s.hostname} PMTU={s.pmtu}" for s in pmtu_low)
        return Finding(
            id="R08",
            severity="medium",
            title="实测 PMTU 小于 Tailscale 接口 MTU",
            evidence=f"Tailscale MTU={ts_mtu}；{ev}",
            fix_ids=["F07"],
        )
    return None


def r09_jitter_loss(snap: Snapshot) -> Optional[Finding]:
    bad = []
    for peer in snap.online_peers():
        if peer.ping_jitter_ms is not None and peer.ping_jitter_ms > 30:
            bad.append(f"{peer.hostname} jitter={peer.ping_jitter_ms:.0f}ms")
        if peer.ping_loss_pct is not None and peer.ping_loss_pct > 1:
            bad.append(f"{peer.hostname} loss={peer.ping_loss_pct:.1f}%")
    for sample in snap.links:
        if sample.jitter_ms is not None and sample.jitter_ms > 30:
            bad.append(f"{sample.hostname} ICMP jitter={sample.jitter_ms:.0f}ms")
        if sample.loss_pct is not None and sample.loss_pct > 1:
            bad.append(f"{sample.hostname} ICMP loss={sample.loss_pct:.1f}%")
    if not bad:
        return None
    return Finding(
        id="R09",
        severity="high",
        title="链路抖动或丢包偏高",
        evidence="；".join(dict.fromkeys(bad)),
        fix_ids=["F01", "F08"],
        hint="先确认不是代理绕行，再查 Wi-Fi 干扰与运营商跨网。",
    )


def r10_wifi(snap: Snapshot) -> Optional[Finding]:
    wifi_up = [i for i in snap.route.ifaces if i.is_wifi and str(i.status).lower() in {"up", "connected"}]
    wired_up = [
        i for i in snap.route.ifaces
        if i.is_physical and not i.is_wifi and str(i.status).lower() in {"up", "connected"}
    ]
    if wifi_up and not wired_up:
        names = ", ".join(f"{i.name}({i.speed})" for i in wifi_up)
        return Finding(
            id="R10",
            severity="low",
            title="当前走无线而非有线",
            evidence=f"活动无线网卡: {names}",
            fix_ids=["F08"],
            hint="RDP 对抖动敏感，有条件时用网线。",
        )
    return None


def r11_rdp_profile(snap: Snapshot) -> Optional[Finding]:
    if not snap.rdp.tcp_sessions:
        return None
    return Finding(
        id="R11",
        severity="low",
        title="存在活动 RDP 会话，建议使用优化过的 .rdp 配置",
        evidence=f"TCP 3389 会话 {len(snap.rdp.tcp_sessions)} 条；UDP 端点 {len(snap.rdp.udp_endpoints)} 条。",
        fix_ids=["F08"],
        hint="降低色深、开启 AVC/硬件编码、关闭壁纸与字体平滑，弱网下更稳。",
    )


RULES: list[RuleFn] = [
    r01_proxy_hijack,
    r02_derp_overseas,
    r03_peer_on_derp,
    r04_direct_but_slow,
    r05_tun_steals_default,
    r06_proxy_override_missing_cgnat,
    r07_rdp_transport,
    r08_mtu,
    r09_jitter_loss,
    r10_wifi,
    r11_rdp_profile,
]
