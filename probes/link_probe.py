"""对 Tailscale peer 做 ICMP / TCP 3389 / PMTU 探测。"""

from __future__ import annotations

import re
import socket
import statistics
import time
from typing import Callable, Optional

from core.models import LinkSample, PeerState
from core.runner import run

ProgressCb = Optional[Callable[[str], None]]

_RTT_RE = re.compile(r"时间[=<]?\s*(\d+)\s*ms|time[=<]?\s*(\d+)\s*ms", re.I)
_LOST_RE = re.compile(r"\((\d+)%\s*(丢失|loss)\)", re.I)


def _ping_windows(ip: str, count: int = 4, payload: int = 32, df: bool = False, timeout: float = 12) -> dict:
    argv = ["ping", "-n", str(count), "-w", "1000", "-l", str(payload)]
    if df:
        argv.append("-f")
    argv.append(ip)
    result = run(argv, timeout=timeout)
    text = result.stdout or ""
    rtts: list[float] = []
    for match in _RTT_RE.finditer(text):
        val = match.group(1) or match.group(2)
        if val:
            rtts.append(float(val))
    loss = None
    lost = _LOST_RE.search(text)
    if lost:
        loss = float(lost.group(1))
    elif count:
        loss = max(0.0, (count - len(rtts)) / float(count) * 100.0)
    jitter = None
    if len(rtts) >= 2:
        jitter = statistics.mean(abs(rtts[i] - rtts[i - 1]) for i in range(1, len(rtts)))
    avg = statistics.mean(rtts) if rtts else None
    return {"rtt": avg, "jitter": jitter, "loss": loss, "ok": bool(rtts), "raw": text[-400:]}


def _tcp_connect_ms(ip: str, port: int = 3389, timeout: float = 2.0) -> Optional[float]:
    start = time.perf_counter()
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return (time.perf_counter() - start) * 1000.0
    except OSError:
        return None


def _pmtu(ip: str) -> Optional[int]:
    lo, hi, best = 1000, 1472, None
    while lo <= hi:
        mid = (lo + hi) // 2
        probe = _ping_windows(ip, count=1, payload=mid, df=True, timeout=6)
        text = probe.get("raw") or ""
        fragmented = "需要拆分数据包" in text or "DF" in text.upper() and "fragment" in text.lower()
        if probe["ok"] and not fragmented:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best + 28 if best else None


def collect(
    peers: list[PeerState],
    *,
    probe_pmtu: bool = False,
    progress: ProgressCb = None,
) -> list[LinkSample]:
    samples: list[LinkSample] = []
    for peer in peers:
        if peer.is_self or not peer.online or not peer.ip:
            continue
        if progress:
            progress(f"链路探测 {peer.hostname}")
        icmp = _ping_windows(peer.ip, count=4)
        tcp_ms = _tcp_connect_ms(peer.ip)
        pmtu = _pmtu(peer.ip) if probe_pmtu else None
        samples.append(
            LinkSample(
                peer_ip=peer.ip,
                hostname=peer.hostname,
                icmp_rtt_ms=icmp["rtt"],
                jitter_ms=icmp["jitter"],
                loss_pct=icmp["loss"],
                pmtu=pmtu,
                tcp_3389_ms=tcp_ms,
            )
        )
    return samples
