"""Tailscale 状态 / netcheck / ping / prefs。"""

from __future__ import annotations

import json
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from core.config import TAILSCALE_EXE_CANDIDATES
from core.models import NetcheckState, PeerState, TailscalePrefs
from core.runner import redact_obj, run

ProgressCb = Optional[Callable[[str], None]]

_PONG_RE = re.compile(
    r"pong from\s+(?P<name>\S+)\s+\((?P<ip>[0-9.]+)\)\s+via\s+(?P<via>.+?)\s+in\s+(?P<ms>[\d.]+)ms",
    re.I,
)
_IPV4_PORT_RE = re.compile(r"(?P<ip>\d+\.\d+\.\d+\.\d+):(?P<port>\d+)")


def find_tailscale() -> Optional[str]:
    found = shutil.which("tailscale")
    if found:
        return found
    for candidate in TAILSCALE_EXE_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    return None


def _ts(args: list[str], timeout: float = 30) -> "tuple":
    exe = find_tailscale()
    if not exe:
        from core.runner import RunResult

        return RunResult(["tailscale"], 127, "", "未找到 tailscale.exe")
    return run([exe, *args], timeout=timeout)


def collect_status() -> tuple[str, list[PeerState], str]:
    result = _ts(["status", "--json"], timeout=20)
    if not result.ok:
        return "", [], result.stderr or result.stdout or "tailscale status 失败"
    data = redact_obj(result.json())
    self_info = data.get("Self") or {}
    self_ip = ""
    addrs = self_info.get("TailscaleIPs") or []
    if addrs:
        self_ip = addrs[0]
    peers: list[PeerState] = []
    self_peer = _peer_from_status(self_info, is_self=True)
    if self_peer:
        peers.append(self_peer)
    peer_map = data.get("Peer") or {}
    for _key, item in peer_map.items():
        peer = _peer_from_status(item, is_self=False)
        if peer:
            peers.append(peer)
    return self_ip, peers, ""


def _peer_from_status(item: dict, *, is_self: bool) -> Optional[PeerState]:
    if not item:
        return None
    ips = item.get("TailscaleIPs") or []
    ip = ips[0] if ips else ""
    dns = item.get("DNSName") or ""
    hostname = (item.get("HostName") or dns.split(".")[0] or ip).rstrip(".")
    relay = item.get("Relay") or ""
    cur = item.get("CurAddr") or item.get("curAddr") or ""
    online = bool(item.get("Online"))
    active = bool(item.get("Active"))
    last_seen = str(item.get("LastSeen") or "")
    tx = int(item.get("TxBytes") or 0)
    rx = int(item.get("RxBytes") or 0)
    os_name = str(item.get("OS") or "")
    return PeerState(
        hostname=hostname,
        ip=ip,
        os=os_name,
        online=online or is_self,
        active=active,
        last_seen=last_seen,
        cur_addr=cur,
        relay=relay if not cur else "",
        tx_bytes=tx,
        rx_bytes=rx,
        is_self=is_self,
    )


def collect_netcheck() -> NetcheckState:
    text = _ts(["netcheck"], timeout=25)
    state = _parse_netcheck_text(text.stdout if text.ok else (text.stderr or ""))
    if state.global_v4 and state.preferred_derp:
        return state
    js = _ts(["netcheck", "--format=json"], timeout=25)
    if not js.ok:
        if not state.global_v4:
            state.raw_error = state.raw_error or (js.stderr or "netcheck 失败")
        return state
    try:
        other = _netcheck_from_json(js.json())
    except Exception:
        return state
    if not state.global_v4:
        state.global_v4 = other.global_v4
        state.global_v4_port = other.global_v4_port
    if not state.preferred_derp:
        state.preferred_derp = other.preferred_derp
        state.preferred_derp_code = other.preferred_derp_code
        state.preferred_derp_latency_ms = other.preferred_derp_latency_ms
    if not state.region_latency:
        state.region_latency = other.region_latency
    if state.udp is None:
        state.udp = other.udp
    if not state.port_mapping:
        state.port_mapping = other.port_mapping
    return state


def _netcheck_from_json(data: dict) -> NetcheckState:
    global_v4 = data.get("GlobalV4") or data.get("globalV4") or ""
    ip, port = "", 0
    if isinstance(global_v4, str) and global_v4:
        match = _IPV4_PORT_RE.search(global_v4)
        if match:
            ip, port = match.group("ip"), int(match.group("port"))
        else:
            ip = global_v4.split("/")[0]
    preferred = data.get("PreferredDERP") or data.get("preferredDERP") or 0
    region_latency_raw = data.get("RegionLatency") or data.get("regionLatency") or {}
    region_map = data.get("RegionName") or {}
    latency: dict[str, float] = {}
    preferred_code = ""
    preferred_name = ""
    preferred_ms = None
    for rid, val in region_latency_raw.items():
        ms = _latency_to_ms(val)
        code = str(region_map.get(str(rid)) or region_map.get(int(rid) if str(rid).isdigit() else rid) or rid)
        # RegionName 可能是 "Los Angeles"，也有 DerpMap
        latency[str(rid)] = ms
        if str(rid) == str(preferred) or (isinstance(preferred, int) and str(rid) == str(preferred)):
            preferred_ms = ms
    derp_map = data.get("DERPMap") or data.get("derpMap") or {}
    regions = derp_map.get("Regions") or derp_map.get("regions") or {}
    if regions and preferred:
        region = regions.get(str(preferred)) or regions.get(preferred) or {}
        preferred_code = str(region.get("RegionCode") or region.get("regionCode") or "")
        preferred_name = str(region.get("RegionName") or region.get("regionName") or preferred_code)
        if preferred_ms is None:
            lat = region_latency_raw.get(str(preferred)) or region_latency_raw.get(preferred)
            preferred_ms = _latency_to_ms(lat) if lat is not None else None
    if not preferred_code:
        preferred_code = str(preferred or "")
        preferred_name = preferred_code
    # 把 region latency 转成 code -> ms 便于规则判断
    coded: dict[str, float] = {}
    for rid, ms in latency.items():
        region = regions.get(str(rid)) or regions.get(int(rid) if str(rid).isdigit() else rid) or {}
        code = str(region.get("RegionCode") or region.get("regionCode") or rid).lower()
        coded[code] = ms
    if not coded:
        coded = {str(k).lower(): v for k, v in latency.items()}
    udp = data.get("UDP")
    if udp is None:
        udp = data.get("udp")
    mapping = data.get("MappingVariesByDestIP")
    if mapping is None:
        mapping = data.get("mappingVariesByDestIP")
    port_mapping = data.get("PreferredPortMapping") or data.get("portMapping") or ""
    if isinstance(port_mapping, dict):
        port_mapping = ",".join(k for k, v in port_mapping.items() if v) or json.dumps(port_mapping)
    return NetcheckState(
        udp=bool(udp) if udp is not None else None,
        global_v4=ip,
        global_v4_port=port,
        ipv6=bool(data.get("GlobalV6") or data.get("globalV6")) if (data.get("GlobalV6") or data.get("globalV6")) is not None else None,
        mapping_varies=bool(mapping) if mapping is not None else None,
        port_mapping=str(port_mapping or ""),
        preferred_derp=preferred_name or preferred_code,
        preferred_derp_code=preferred_code.lower(),
        preferred_derp_latency_ms=preferred_ms,
        region_latency=coded,
    )


def _latency_to_ms(val: object) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        # JSON 里可能是纳秒（Go Duration）或毫秒
        if val > 10_000_000:
            return float(val) / 1_000_000.0
        if val > 10_000:
            return float(val) / 1_000_000.0 if val > 1_000_000 else float(val)
        return float(val)
    text = str(val).strip().lower()
    if text.endswith("ms"):
        return float(text[:-2])
    if text.endswith("s"):
        return float(text[:-1]) * 1000.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _parse_netcheck_text(text: str) -> NetcheckState:
    state = NetcheckState()
    if not text:
        state.raw_error = "netcheck 无输出"
        return state
    for line in text.splitlines():
        raw = line.strip()
        lower = raw.lower()
        if lower.startswith("* udp:"):
            state.udp = "true" in lower
        elif lower.startswith("* ipv4:"):
            match = _IPV4_PORT_RE.search(raw)
            if match:
                state.global_v4 = match.group("ip")
                state.global_v4_port = int(match.group("port"))
            elif "yes" in lower:
                parts = raw.split(",", 1)[0]
                ipport = parts.split()[-1]
                match = _IPV4_PORT_RE.search(ipport)
                if match:
                    state.global_v4 = match.group("ip")
                    state.global_v4_port = int(match.group("port"))
        elif lower.startswith("* ipv6:"):
            state.ipv6 = "yes" in lower
        elif "mappingvariesbydestip" in lower.replace(" ", ""):
            state.mapping_varies = "true" in lower
        elif lower.startswith("* portmapping:"):
            state.port_mapping = raw.split(":", 1)[-1].strip()
        elif lower.startswith("* nearest derp:"):
            state.preferred_derp = raw.split(":", 1)[-1].strip()
        elif raw.startswith("- "):
            # - lax: 654.1ms (Los Angeles)
            m = re.match(r"-\s+([a-z0-9]+):\s+([\d.]+)ms", raw, re.I)
            if m:
                code = m.group(1).lower()
                ms = float(m.group(2))
                state.region_latency[code] = ms
                name = ""
                nm = re.search(r"\((.+)\)", raw)
                if nm:
                    name = nm.group(1)
                if name and name.lower() == state.preferred_derp.lower() or (
                    state.preferred_derp and code in state.preferred_derp.lower()
                ):
                    state.preferred_derp_code = code
                    state.preferred_derp_latency_ms = ms
                if state.preferred_derp and (
                    state.preferred_derp.lower() == name.lower()
                    or state.preferred_derp.lower() == code
                ):
                    state.preferred_derp_code = code
                    state.preferred_derp_latency_ms = ms
    if state.preferred_derp and not state.preferred_derp_code:
        for code, ms in state.region_latency.items():
            if code in state.preferred_derp.lower():
                state.preferred_derp_code = code
                state.preferred_derp_latency_ms = ms
                break
        if not state.preferred_derp_code and state.region_latency:
            code, ms = min(state.region_latency.items(), key=lambda kv: kv[1])
            # 最近 DERP 名称匹配
            for line in text.splitlines():
                if state.preferred_derp.lower() in line.lower() and line.strip().startswith("-"):
                    m = re.match(r"-\s+([a-z0-9]+):", line.strip(), re.I)
                    if m:
                        state.preferred_derp_code = m.group(1).lower()
                        state.preferred_derp_latency_ms = state.region_latency.get(state.preferred_derp_code)
                        break
            if not state.preferred_derp_code:
                state.preferred_derp_code = code
                if state.preferred_derp_latency_ms is None:
                    state.preferred_derp_latency_ms = ms
    return state


def ping_peer(ip: str, count: int = 2) -> dict:
    result = _ts(["ping", "--c", str(count), ip], timeout=max(8, count * 3))
    rtts: list[float] = []
    vias: list[str] = []
    for line in (result.stdout or "").splitlines():
        match = _PONG_RE.search(line)
        if match:
            rtts.append(float(match.group("ms")))
            vias.append(match.group("via").strip())
    loss = None
    if count:
        loss = max(0.0, (count - len(rtts)) / float(count) * 100.0)
    jitter = None
    if len(rtts) >= 2:
        deltas = [abs(rtts[i] - rtts[i - 1]) for i in range(1, len(rtts))]
        jitter = sum(deltas) / len(deltas)
    avg = sum(rtts) / len(rtts) if rtts else None
    via = vias[0] if vias else (result.stdout or result.stderr or "")[:120]
    return {
        "rtt_ms": avg,
        "jitter_ms": jitter,
        "loss_pct": loss,
        "via": via,
        "samples": rtts,
        "ok": bool(rtts),
        "raw": result.stdout[-1000:],
    }


def collect_prefs() -> TailscalePrefs:
    result = _ts(["debug", "prefs"], timeout=15)
    if not result.ok:
        return TailscalePrefs(raw_error=result.stderr or "prefs 读取失败")
    try:
        data = redact_obj(json.loads(result.stdout))
    except json.JSONDecodeError:
        return TailscalePrefs(raw_error="prefs JSON 解析失败")
    return TailscalePrefs(
        exit_node_ip=str(data.get("ExitNodeIP") or ""),
        exit_node_id=str(data.get("ExitNodeID") or ""),
        route_all=data.get("RouteAll"),
        want_running=data.get("WantRunning"),
    )


def apply_ping_stats(peer: PeerState, stats: dict) -> None:
    peer.ping_rtt_ms = stats.get("rtt_ms")
    peer.ping_via = str(stats.get("via") or "")
    peer.ping_loss_pct = stats.get("loss_pct")
    peer.ping_jitter_ms = stats.get("jitter_ms")


def ping_online_peers(
    peers: list[PeerState],
    *,
    ping_count: int = 2,
    progress: ProgressCb = None,
    max_workers: int = 6,
) -> list[str]:
    errors: list[str] = []
    targets = [p for p in peers if not p.is_self and p.online and p.ip]
    if not targets:
        return errors
    workers = max(1, min(max_workers, len(targets)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(ping_peer, peer.ip, ping_count): peer for peer in targets}
        for fut in as_completed(futs):
            peer = futs[fut]
            if progress:
                progress(f"正在测和{peer.hostname}的往返时间")
            try:
                apply_ping_stats(peer, fut.result())
            except Exception as exc:
                errors.append(f"ping {peer.hostname}: {exc}")
    return errors


def collect(
    *,
    ping_count: int = 2,
    ping_peers: bool = True,
    progress: ProgressCb = None,
) -> dict:
    errors: list[str] = []
    self_ip, peers, status_err = collect_status()
    if status_err:
        errors.append(status_err)
    with ThreadPoolExecutor(max_workers=4) as pool:
        fut_netcheck = pool.submit(collect_netcheck)
        fut_prefs = pool.submit(collect_prefs)
        ping_futs = {}
        if ping_peers:
            targets = [p for p in peers if not p.is_self and p.online and p.ip]
            ping_futs = {pool.submit(ping_peer, peer.ip, ping_count): peer for peer in targets}
        if progress:
            progress("采集 netcheck")
        try:
            netcheck = fut_netcheck.result()
        except Exception as exc:
            netcheck = NetcheckState(raw_error=str(exc))
            errors.append(f"netcheck: {exc}")
        try:
            prefs = fut_prefs.result()
        except Exception as exc:
            prefs = TailscalePrefs(raw_error=str(exc))
            errors.append(f"prefs: {exc}")
        for fut, peer in ping_futs.items():
            if progress:
                progress(f"ping {peer.hostname}")
            try:
                apply_ping_stats(peer, fut.result())
            except Exception as exc:
                errors.append(f"ping {peer.hostname}: {exc}")
    return {
        "self_ip": self_ip,
        "peers": peers,
        "netcheck": netcheck,
        "prefs": prefs,
        "errors": errors,
    }


def ip_v4() -> str:
    result = _ts(["ip", "-4"], timeout=10)
    return (result.stdout or "").strip().splitlines()[0] if result.ok else ""
