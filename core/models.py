"""诊断快照与规则命中的数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Optional


def _to_plain(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_plain(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(v) for v in obj]
    return obj


@dataclass
class Finding:
    id: str
    severity: str
    title: str
    evidence: str
    fix_ids: list[str] = field(default_factory=list)
    hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Finding":
        return cls(
            id=str(data.get("id", "")),
            severity=str(data.get("severity", "info")),
            title=str(data.get("title", "")),
            evidence=str(data.get("evidence", "")),
            fix_ids=list(data.get("fix_ids") or []),
            hint=str(data.get("hint", "")),
        )


@dataclass
class PeerState:
    hostname: str
    ip: str
    os: str = ""
    online: bool = False
    active: bool = False
    last_seen: str = ""
    cur_addr: str = ""
    relay: str = ""
    tx_bytes: int = 0
    rx_bytes: int = 0
    ping_rtt_ms: Optional[float] = None
    ping_via: str = ""
    ping_loss_pct: Optional[float] = None
    ping_jitter_ms: Optional[float] = None
    is_self: bool = False
    remote_snapshot: Optional[dict[str, Any]] = None

    @property
    def is_direct(self) -> bool:
        return bool(self.cur_addr) and not self.relay

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PeerState":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class NetcheckState:
    udp: Optional[bool] = None
    global_v4: str = ""
    global_v4_port: int = 0
    ipv6: Optional[bool] = None
    mapping_varies: Optional[bool] = None
    port_mapping: str = ""
    preferred_derp: str = ""
    preferred_derp_code: str = ""
    preferred_derp_latency_ms: Optional[float] = None
    region_latency: dict[str, float] = field(default_factory=dict)
    raw_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DefaultRoute:
    dest: str
    nexthop: str
    route_metric: int
    iface: str
    iface_metric: Optional[int]
    effective_metric: int
    mtu: Optional[int] = None


@dataclass
class IfaceState:
    name: str
    status: str = ""
    description: str = ""
    ipv4: list[str] = field(default_factory=list)
    metric: Optional[int] = None
    mtu: Optional[int] = None
    speed: str = ""
    is_tun: bool = False
    is_tailscale: bool = False
    is_physical: bool = False
    is_wifi: bool = False


@dataclass
class RouteState:
    default_routes: list[DefaultRoute] = field(default_factory=list)
    default_exit_iface: str = ""
    ifaces: list[IfaceState] = field(default_factory=list)
    peer_routes_on_tailscale: dict[str, bool] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _to_plain(self)


@dataclass
class ProxyState:
    tun_up: bool = False
    tun_ifaces: list[str] = field(default_factory=list)
    tun_metric: Optional[int] = None
    v2rayn_running: bool = False
    singbox_running: bool = False
    xray_running: bool = False
    v2rayn_path: str = ""
    singbox_config_path: str = ""
    proxy_enable: bool = False
    proxy_server: str = ""
    proxy_override: str = ""
    override_has_100: bool = False
    node_addresses: list[str] = field(default_factory=list)
    tailscale_direct_in_rules: bool = False
    routing_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RdpState:
    port: int = 3389
    select_transport: Optional[int] = None
    deny_connections: Optional[int] = None
    client_disable_udp: Optional[int] = None
    tcp_sessions: list[dict[str, Any]] = field(default_factory=list)
    udp_endpoints: list[dict[str, Any]] = field(default_factory=list)
    # 活动会话：direction(out/in)、peer_ip、age_sec、transport(udp/tcp/unknown)，
    # 主机侧另有 tcp_rtt_ms / udp_rtt_ms / loss_pct / retrans_pct；collector 会补 peer_name / peer_path。
    sessions: list[dict[str, Any]] = field(default_factory=list)
    recent_events: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LinkSample:
    peer_ip: str
    hostname: str = ""
    icmp_rtt_ms: Optional[float] = None
    jitter_ms: Optional[float] = None
    loss_pct: Optional[float] = None
    pmtu: Optional[int] = None
    tcp_3389_ms: Optional[float] = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TailscalePrefs:
    exit_node_ip: str = ""
    exit_node_id: str = ""
    route_all: Optional[bool] = None
    want_running: Optional[bool] = None
    raw_error: str = ""


@dataclass
class Snapshot:
    ts: float = 0.0
    hostname: str = ""
    self_ip: str = ""
    self_os: str = "windows"
    admin: bool = False
    netcheck: NetcheckState = field(default_factory=NetcheckState)
    peers: list[PeerState] = field(default_factory=list)
    prefs: TailscalePrefs = field(default_factory=TailscalePrefs)
    route: RouteState = field(default_factory=RouteState)
    proxy: ProxyState = field(default_factory=ProxyState)
    rdp: RdpState = field(default_factory=RdpState)
    links: list[LinkSample] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def self_peer(self) -> Optional[PeerState]:
        for peer in self.peers:
            if peer.is_self:
                return peer
        return None

    def online_peers(self) -> list[PeerState]:
        return [p for p in self.peers if p.online and not p.is_self]

    def to_dict(self) -> dict[str, Any]:
        return _to_plain(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Snapshot":
        netcheck = data.get("netcheck") or {}
        prefs = data.get("prefs") or {}
        route = data.get("route") or {}
        proxy = data.get("proxy") or {}
        rdp = data.get("rdp") or {}
        default_routes = [
            DefaultRoute(**item) if not isinstance(item, DefaultRoute) else item
            for item in route.get("default_routes") or []
        ]
        ifaces = [
            IfaceState(**item) if not isinstance(item, IfaceState) else item
            for item in route.get("ifaces") or []
        ]
        return cls(
            ts=float(data.get("ts") or 0),
            hostname=str(data.get("hostname") or ""),
            self_ip=str(data.get("self_ip") or ""),
            self_os=str(data.get("self_os") or "windows"),
            admin=bool(data.get("admin")),
            netcheck=NetcheckState(**{k: v for k, v in netcheck.items() if k in NetcheckState.__dataclass_fields__}),
            peers=[PeerState.from_dict(p) for p in data.get("peers") or []],
            prefs=TailscalePrefs(**{k: v for k, v in prefs.items() if k in TailscalePrefs.__dataclass_fields__}),
            route=RouteState(
                default_routes=default_routes,
                default_exit_iface=str(route.get("default_exit_iface") or ""),
                ifaces=ifaces,
                peer_routes_on_tailscale=dict(route.get("peer_routes_on_tailscale") or {}),
                error=str(route.get("error") or ""),
            ),
            proxy=ProxyState(**{k: v for k, v in proxy.items() if k in ProxyState.__dataclass_fields__}),
            rdp=RdpState(**{k: v for k, v in rdp.items() if k in RdpState.__dataclass_fields__}),
            links=[LinkSample(**item) for item in data.get("links") or []],
            findings=[Finding.from_dict(item) for item in data.get("findings") or []],
            errors=list(data.get("errors") or []),
        )
