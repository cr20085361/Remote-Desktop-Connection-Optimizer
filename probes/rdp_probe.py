"""RDP 传输层注册表、3389 会话、相关事件。"""

from __future__ import annotations

from core.models import RdpState
from core.runner import powershell_json


_SCRIPT = r"""
$rdp = $null
try {
  $rdp = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp' |
    Select-Object PortNumber,SelectTransport
} catch {}
$deny = $null
try { $deny = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server').fDenyTSConnections } catch {}
$udp = $null
try { $udp = (Get-ItemProperty 'HKLM:\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services').fClientDisableUDP } catch {}
$tcp = @()
try { $tcp = @(Get-NetTCPConnection -RemotePort 3389 -ErrorAction SilentlyContinue | Select-Object LocalAddress,RemoteAddress,State,OwningProcess) } catch {}
$udpConn = @()
try { $udpConn = @(Get-NetUDPEndpoint -LocalPort 3389 -ErrorAction SilentlyContinue | Select-Object LocalAddress,LocalPort,OwningProcess) } catch {}
$events = @()
if ($includeEvents) {
  try {
    $logNames = @(
      'Microsoft-Windows-RemoteDesktopServices-RdpCoreTS/Operational',
      'Microsoft-Windows-TerminalServices-ClientActiveXCore/Operational'
    )
    foreach ($log in $logNames) {
      $events += @(Get-WinEvent -LogName $log -MaxEvents 12 -ErrorAction SilentlyContinue |
        Select-Object TimeCreated,Id,Message)
    }
  } catch {}
}
$obj = [ordered]@{
  rdp = $rdp
  deny = $deny
  udp = $udp
  tcp = $tcp
  udpConn = $udpConn
  events = $events
}
$obj | ConvertTo-Json -Depth 5 -Compress
"""


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def collect(*, include_events: bool = False) -> RdpState:
    flag = "$true" if include_events else "$false"
    script = f"$includeEvents = {flag}\n" + _SCRIPT
    data = powershell_json(script, timeout=20 if include_events else 12) or {}
    rdp = data.get("rdp") or {}
    events = []
    if include_events:
        for item in _as_list(data.get("events")):
            msg = str(item.get("Message") or "").replace("\r", " ").replace("\n", " ")
            events.append(f"{item.get('TimeCreated','')} [{item.get('Id','')}] {msg[:180]}")
    port = rdp.get("PortNumber")
    select = rdp.get("SelectTransport")
    return RdpState(
        port=int(port) if port is not None else 3389,
        select_transport=int(select) if select is not None else None,
        deny_connections=int(data["deny"]) if data.get("deny") is not None else None,
        client_disable_udp=int(data["udp"]) if data.get("udp") is not None else None,
        tcp_sessions=[dict(x) for x in _as_list(data.get("tcp"))],
        udp_endpoints=[dict(x) for x in _as_list(data.get("udpConn"))],
        recent_events=events[:20],
    )
