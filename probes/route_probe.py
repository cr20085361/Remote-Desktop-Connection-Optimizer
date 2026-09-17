"""路由表、接口跃点、默认出口判定。"""

from __future__ import annotations

from core.config import TUN_IFACE_HINTS
from core.models import DefaultRoute, IfaceState, RouteState
from core.runner import powershell_json


_SCRIPT = r"""
$ifaces = @(Get-NetIPInterface -AddressFamily IPv4 | Select-Object InterfaceAlias,InterfaceMetric,NlMtu,ConnectionState,InterfaceIndex)
$addrs = @(Get-NetIPAddress -AddressFamily IPv4 | Select-Object InterfaceAlias,IPAddress)
$adapters = @(Get-NetAdapter | Select-Object Name,InterfaceDescription,Status,LinkSpeed,InterfaceIndex)
$routes = @(Get-NetRoute -AddressFamily IPv4 | Select-Object DestinationPrefix,NextHop,RouteMetric,InterfaceAlias,InterfaceIndex)
$obj = [ordered]@{
  ifaces = $ifaces
  addrs = $addrs
  adapters = $adapters
  routes = $routes
}
$obj | ConvertTo-Json -Depth 5 -Compress
"""


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _metric(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_tun(name: str, desc: str) -> bool:
    blob = f"{name} {desc}".lower()
    return any(hint in blob for hint in TUN_IFACE_HINTS) or "tun" in blob and "tunnel" in blob


def _is_physical(name: str, desc: str) -> bool:
    blob = f"{name} {desc}".lower()
    if any(x in blob for x in ("tailscale", "wintun", "tun", "hyper-v", "vethernet", "loopback", "bluetooth")):
        return False
    return any(x in blob for x in ("wi-fi", "wifi", "wlan", "ethernet", "realtek", "intel", "killer", "broadcom"))


def collect() -> RouteState:
    data = powershell_json(_SCRIPT, timeout=40) or {}
    iface_rows = _as_list(data.get("ifaces"))
    addr_rows = _as_list(data.get("addrs"))
    adapter_rows = _as_list(data.get("adapters"))
    route_rows = _as_list(data.get("routes"))

    addrs_by_iface: dict[str, list[str]] = {}
    for row in addr_rows:
        alias = str(row.get("InterfaceAlias") or "")
        ip = str(row.get("IPAddress") or "")
        if alias and ip:
            addrs_by_iface.setdefault(alias, []).append(ip)

    adapter_by_name = {str(r.get("Name") or ""): r for r in adapter_rows}
    metric_by_name: dict[str, int | None] = {}
    mtu_by_name: dict[str, int | None] = {}
    ifaces: list[IfaceState] = []
    for row in iface_rows:
        name = str(row.get("InterfaceAlias") or "")
        if not name:
            continue
        adapter = adapter_by_name.get(name) or {}
        desc = str(adapter.get("InterfaceDescription") or "")
        status = str(adapter.get("Status") or row.get("ConnectionState") or "")
        metric = _metric(row.get("InterfaceMetric"))
        mtu = _metric(row.get("NlMtu"))
        metric_by_name[name] = metric
        mtu_by_name[name] = mtu
        lower = name.lower()
        ifaces.append(
            IfaceState(
                name=name,
                status=status,
                description=desc,
                ipv4=addrs_by_iface.get(name, []),
                metric=metric,
                mtu=mtu,
                speed=str(adapter.get("LinkSpeed") or ""),
                is_tun=_is_tun(name, desc),
                is_tailscale="tailscale" in lower,
                is_physical=_is_physical(name, desc),
                is_wifi=any(x in f"{name} {desc}".lower() for x in ("wi-fi", "wifi", "wlan")),
            )
        )

    defaults: list[DefaultRoute] = []
    peer_routes: dict[str, bool] = {}
    for row in route_rows:
        dest = str(row.get("DestinationPrefix") or "")
        iface = str(row.get("InterfaceAlias") or "")
        nexthop = str(row.get("NextHop") or "")
        rmetric = _metric(row.get("RouteMetric")) or 0
        imetric = metric_by_name.get(iface)
        effective = rmetric + (imetric if imetric is not None else 0)
        if dest in ("0.0.0.0/0", "::/0"):
            defaults.append(
                DefaultRoute(
                    dest=dest,
                    nexthop=nexthop,
                    route_metric=rmetric,
                    iface=iface,
                    iface_metric=imetric,
                    effective_metric=effective,
                    mtu=mtu_by_name.get(iface),
                )
            )
        if dest.endswith("/32") and dest.startswith("100."):
            peer_ip = dest[:-3]
            peer_routes[peer_ip] = "tailscale" in iface.lower()

    defaults.sort(key=lambda item: item.effective_metric)
    exit_iface = defaults[0].iface if defaults else ""
    return RouteState(
        default_routes=defaults,
        default_exit_iface=exit_iface,
        ifaces=ifaces,
        peer_routes_on_tailscale=peer_routes,
    )
