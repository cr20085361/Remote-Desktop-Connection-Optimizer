"""采集调度：并行探针、两阶段出快照、固定 8 档进度。"""

from __future__ import annotations

import copy
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Optional

from core.models import (
    NetcheckState,
    ProxyState,
    RdpState,
    RouteState,
    Snapshot,
    TailscalePrefs,
)
from core.runner import is_admin
from probes import link_probe, proxy_probe, rdp_probe, route_probe, tailscale_probe
from rules.engine import evaluate


TOTAL_STEPS = 8
ProgressCb = Callable[..., None]
SnapshotCb = Callable[[Snapshot], None]


def _note(progress: Optional[ProgressCb], index: int, label: str) -> None:
    if not progress:
        return
    try:
        progress(index, TOTAL_STEPS, label)
    except TypeError:
        progress(label)


def _take(fut, fallback, errors: list[str], key: str):
    try:
        return fut.result()
    except Exception as exc:
        errors.append(f"{key}: {exc}")
        return fallback


def _apply_proxy_route(proxy: ProxyState, route: RouteState) -> None:
    tun_ifaces = [
        iface
        for iface in route.ifaces
        if iface.is_tun and str(iface.status).lower() in {"up", "connected"}
    ]
    proxy.tun_ifaces = [iface.name for iface in tun_ifaces]
    proxy.tun_up = bool(tun_ifaces) or (proxy.singbox_running and any(i.is_tun for i in route.ifaces))
    if tun_ifaces:
        proxy.tun_metric = tun_ifaces[0].metric
    elif proxy.singbox_running:
        proxy.tun_up = True
    try:
        from core.settings import load_settings

        configured = str(load_settings().get("v2rayn_path") or "").strip()
        if configured and not proxy.v2rayn_path:
            proxy.v2rayn_path = configured
    except Exception:
        pass


def _assemble(
    *,
    self_ip: str,
    peers: list,
    netcheck: NetcheckState,
    prefs: TailscalePrefs,
    route: RouteState,
    proxy: ProxyState,
    rdp: RdpState,
    links: list,
    errors: list[str],
) -> Snapshot:
    _apply_proxy_route(proxy, route)
    snapshot = Snapshot(
        ts=time.time(),
        hostname=socket.gethostname(),
        self_ip=self_ip or "",
        self_os="windows",
        admin=is_admin(),
        netcheck=netcheck,
        peers=peers,
        prefs=prefs,
        route=route,
        proxy=proxy,
        rdp=rdp,
        links=links,
        errors=list(errors),
    )
    snapshot.findings = evaluate(snapshot)
    return snapshot


def collect_snapshot(
    *,
    ping_count: int = 2,
    ping_peers: bool = True,
    probe_links: bool = False,
    probe_pmtu: bool = False,
    include_rdp_events: bool = False,
    progress: Optional[ProgressCb] = None,
    on_snapshot: Optional[SnapshotCb] = None,
) -> Snapshot:
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=8) as pool:
        fut_netcheck = pool.submit(tailscale_probe.collect_netcheck)
        fut_status = pool.submit(tailscale_probe.collect_status)
        fut_prefs = pool.submit(tailscale_probe.collect_prefs)
        fut_route = pool.submit(route_probe.collect)
        fut_proxy = pool.submit(proxy_probe.collect)
        fut_rdp = pool.submit(lambda: rdp_probe.collect(include_events=include_rdp_events))

        _note(progress, 1, "正在读取组网名单")
        status = _take(fut_status, ("", [], "tailscale status 失败"), errors, "status")
        self_ip, peers, status_err = status
        if status_err:
            errors.append(status_err)

        ping_futs: dict[Any, Any] = {}
        if ping_peers:
            targets = [p for p in peers if not p.is_self and p.online and p.ip]
            ping_futs = {
                pool.submit(tailscale_probe.ping_peer, peer.ip, ping_count): peer for peer in targets
            }

        _note(progress, 2, "正在查本机出路")
        route = _take(fut_route, RouteState(error="路由采集失败"), errors, "route")

        _note(progress, 3, "正在查翻墙状态")
        proxy = _take(fut_proxy, ProxyState(), errors, "proxy")

        _note(progress, 4, "正在查远程桌面设置")
        rdp = _take(fut_rdp, RdpState(error="RDP 采集失败"), errors, "rdp")
        prefs = _take(fut_prefs, TailscalePrefs(raw_error="prefs 读取失败"), errors, "prefs")

        if on_snapshot:
            phase1 = _assemble(
                self_ip=self_ip,
                peers=copy.deepcopy(peers),
                netcheck=NetcheckState(),
                prefs=prefs,
                route=route,
                proxy=copy.deepcopy(proxy),
                rdp=rdp,
                links=[],
                errors=errors,
            )
            on_snapshot(phase1)

        _note(progress, 5, "正在测中转站位置")
        netcheck = _take(fut_netcheck, NetcheckState(raw_error="netcheck 失败"), errors, "netcheck")

        if ping_futs:
            names = "、".join(peer.hostname for peer in list(ping_futs.values())[:3])
            _note(progress, 6, f"正在测和{names}的往返时间" if names else "正在测各电脑往返时间")
            for fut in as_completed(ping_futs):
                peer = ping_futs[fut]
                _note(progress, 6, f"正在测和{peer.hostname}的往返时间")
                try:
                    tailscale_probe.apply_ping_stats(peer, fut.result())
                except Exception as exc:
                    errors.append(f"ping {peer.hostname}: {exc}")
        else:
            _note(progress, 6, "没有在线电脑需要测延迟")

        links: list = []
        if probe_links or probe_pmtu:
            _note(progress, 6, "正在做补充链路探测")

            def _link_progress(msg: str) -> None:
                _note(progress, 6, msg)

            try:
                links = link_probe.collect(
                    peers,
                    probe_pmtu=probe_pmtu,
                    progress=_link_progress,
                )
            except Exception as exc:
                errors.append(f"link: {exc}")

        _note(progress, 7, "正在汇总结果")
        snapshot = _assemble(
            self_ip=self_ip,
            peers=peers,
            netcheck=netcheck,
            prefs=prefs,
            route=route,
            proxy=proxy,
            rdp=rdp,
            links=links,
            errors=errors,
        )
        _note(progress, 8, "检测完成")
        return snapshot
