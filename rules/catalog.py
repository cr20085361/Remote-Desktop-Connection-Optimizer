"""R01-R11 规则定义。每条规则返回 Finding 或 None。"""

from __future__ import annotations

from typing import Callable, Optional

from core.config import (
    ASIA_DERP,
    JITTER_ALERT_MS,
    LOSS_ALERT_PCT,
    OVERSEAS_DERP_HINT,
    RDP_LOSS_ALERT_PCT,
    RDP_RETRANS_ALERT_PCT,
    RDP_RTT_ALERT_MS,
)
from core.models import Finding, Snapshot
from probes.proxy_probe import same_slash24
from rules.plain import is_relaying

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
    # Tun 抢默认路由只是"可能"，一旦规则里已有 tailscale 直连就不再视为劫持，
    # 否则修好后（Tun 仍开着）会永远报警。
    if proxy.tun_up and default_is_tun and not proxy.tailscale_direct_in_rules:
        hijacked = True
        reasons.append(
            f"Tun 已启用且默认路由出口为 {snap.route.default_exit_iface}（跃点最优）"
        )
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
    relayed = [p for p in snap.online_peers() if is_relaying(p)]
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
        if not is_relaying(peer) and rtt > 120:
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
    if snap.proxy.tailscale_direct_in_rules:
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
    ts_mtu = next((i.mtu for i in snap.route.ifaces if i.is_tailscale), None)
    pmtu_low = [s for s in snap.links if s.pmtu and ts_mtu and s.pmtu < ts_mtu]
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
        if peer.ping_jitter_ms is not None and peer.ping_jitter_ms > JITTER_ALERT_MS:
            bad.append(f"{peer.hostname} jitter={peer.ping_jitter_ms:.0f}ms")
        if peer.ping_loss_pct is not None and peer.ping_loss_pct > LOSS_ALERT_PCT:
            bad.append(f"{peer.hostname} loss={peer.ping_loss_pct:.1f}%")
    for sample in snap.links:
        if sample.jitter_ms is not None and sample.jitter_ms > JITTER_ALERT_MS:
            bad.append(f"{sample.hostname} ICMP jitter={sample.jitter_ms:.0f}ms")
        if sample.loss_pct is not None and sample.loss_pct > LOSS_ALERT_PCT:
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
    active = snap.rdp.sessions
    if not active:
        return None
    return Finding(
        id="R11",
        severity="low",
        title="存在活动 RDP 会话，建议使用优化过的 .rdp 配置",
        evidence=f"活动 RDP 会话 {len(active)} 条（出站 {sum(1 for s in active if s.get('direction') == 'out')}）。",
        fix_ids=["F08"],
        hint="降低色深、开启 AVC/硬件编码、关闭壁纸与字体平滑，弱网下更稳。",
    )


def r12_tailscale_down(snap: Snapshot) -> Optional[Finding]:
    if snap.prefs.want_running is False:
        return Finding(
            id="R12",
            severity="critical",
            title="Tailscale 已被断开",
            evidence="tailscale prefs: WantRunning=false（客户端处于 Disconnected 状态）",
            hint="远程组网没有连上，其他电脑当然找不到这台机器。",
        )
    if snap.self_ip or snap.self_peer() is not None:
        return None
    detail = next((e for e in snap.errors if "tailscale" in e.lower() or e.startswith("status")), "")
    return Finding(
        id="R12",
        severity="critical",
        title="没有读到 Tailscale 状态",
        evidence=detail or "tailscale status 没有返回本机信息（未安装、服务未运行或未登录）",
        hint="先确认 Tailscale 已安装、已登录并处于连接状态，其余检测才有意义。",
    )


def r13_exit_node(snap: Snapshot) -> Optional[Finding]:
    node = snap.prefs.exit_node_ip or snap.prefs.exit_node_id
    if not node:
        return None
    return Finding(
        id="R13",
        severity="high",
        title="本机正在使用 Tailscale 出口节点",
        evidence=f"ExitNode={node} RouteAll={snap.prefs.route_all}",
        hint="使用出口节点时，本机所有流量（含 UDP 打洞）都会绕到那台机器，远程桌面容易变慢。",
    )


def _session_label(session: dict) -> str:
    name = session.get("peer_name") or session.get("peer_ip") or "?"
    way = "连出去" if session.get("direction") == "out" else "被连入"
    return f"{name}（{way}，已连 {int(session.get('age_sec') or 0)} 秒）"


def r14_rdp_tcp_fallback(snap: Snapshot) -> Optional[Finding]:
    if snap.rdp.client_disable_udp == 1:
        return None  # 已被策略禁用，R07 会说明
    tcp_only = [
        s for s in snap.rdp.sessions
        if s.get("transport") == "tcp" and int(s.get("age_sec") or 0) >= 20
    ]
    if not tcp_only:
        return None
    inbound = any(s.get("direction") == "in" for s in tcp_only)
    return Finding(
        id="R14",
        severity="high",
        title="远程桌面没有用上 UDP，退回了 TCP",
        evidence="；".join(_session_label(s) for s in tcp_only) + "。仅 TCP 传输。",
        fix_ids=["F10"] if inbound else [],
        hint="被连的一侧没放行 UDP 3389（防火墙或路由器）是最常见原因；UDP 被挡后画面在丢包时会明显更卡。",
    )


def r15_rdp_session_quality(snap: Snapshot) -> Optional[Finding]:
    bad = []
    for s in snap.rdp.sessions:
        rtt = max(float(s.get("tcp_rtt_ms") or 0), float(s.get("udp_rtt_ms") or 0))
        loss = float(s.get("loss_pct") or 0)
        retrans = float(s.get("retrans_pct") or 0)
        problems = []
        if rtt > RDP_RTT_ALERT_MS:
            problems.append(f"延迟 {rtt:.0f}ms")
        if loss > RDP_LOSS_ALERT_PCT:
            problems.append(f"丢包 {loss:.1f}%")
        if retrans > RDP_RETRANS_ALERT_PCT:
            problems.append(f"重传 {retrans:.1f}%")
        if problems:
            bad.append(f"{_session_label(s)} " + "、".join(problems))
    if not bad:
        return None
    return Finding(
        id="R15",
        severity="high",
        title="正在进行的远程桌面会话质量差",
        evidence="；".join(bad) + "。（来自远程桌面自身的实时统计）",
        hint="这是 RDP 自己测到的真实体验；结合上面的绕路 / 丢包问题一起看。",
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
    r12_tailscale_down,
    r13_exit_node,
    r14_rdp_tcp_fallback,
    r15_rdp_session_quality,
]
