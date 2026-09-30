"""RDP 传输层注册表、3389 会话、传输通道（UDP/TCP）与实时质量。"""

from __future__ import annotations

from typing import Any

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

# 活动会话：本机作为客户端(out)与作为被连主机(in)
$sess = @()
try {
  $now = Get-Date
  $sess += @(Get-NetTCPConnection -RemotePort 3389 -State Established -ErrorAction SilentlyContinue | ForEach-Object {
    [pscustomobject]@{ dir = 'out'; remote = "$($_.RemoteAddress)"; pid = [int]$_.OwningProcess; age = [int]($now - $_.CreationTime).TotalSeconds }
  })
  $sess += @(Get-NetTCPConnection -LocalPort 3389 -State Established -ErrorAction SilentlyContinue | ForEach-Object {
    [pscustomobject]@{ dir = 'in'; remote = "$($_.RemoteAddress)"; pid = [int]$_.OwningProcess; age = [int]($now - $_.CreationTime).TotalSeconds }
  })
} catch {}
# 客户端 mstsc 一旦协商成功会为该会话绑定 UDP 套接字
$udpPids = @()
try {
  $outPids = @($sess | Where-Object { $_.dir -eq 'out' } | ForEach-Object { $_.pid })
  if ($outPids.Count) {
    $udpPids = @(Get-NetUDPEndpoint -ErrorAction SilentlyContinue | Where-Object { $outPids -contains $_.OwningProcess } |
      ForEach-Object { [int]$_.OwningProcess } | Select-Object -Unique)
  }
} catch {}
# 被连主机：RemoteFX Network 计数器（只有主机侧有实例）
$ctr = @()
try {
  if (@($sess | Where-Object { $_.dir -eq 'in' }).Count) {
    $names = '\RemoteFX Network(*)\Current TCP RTT','\RemoteFX Network(*)\Current UDP RTT',
      '\RemoteFX Network(*)\Loss Rate','\RemoteFX Network(*)\Retransmission Rate',
      '\RemoteFX Network(*)\UDP Packets Received/sec','\RemoteFX Network(*)\Current UDP Bandwidth'
    $ctr = @((Get-Counter -Counter $names -ErrorAction Stop).CounterSamples | ForEach-Object {
      [pscustomobject]@{ inst = "$($_.InstanceName)"; name = (($_.Path -split '\\')[-1]); v = [double]$_.CookedValue }
    })
  }
} catch {}
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
  sess = $sess
  udpPids = $udpPids
  ctr = $ctr
  events = $events
}
$obj | ConvertTo-Json -Depth 5 -Compress
"""

# 计数器名（小写）→ 会话字段
_COUNTER_FIELDS = {
    "current tcp rtt": "tcp_rtt_ms",
    "current udp rtt": "udp_rtt_ms",
    "loss rate": "loss_pct",
    "retransmission rate": "retrans_pct",
    "udp packets received/sec": "udp_pps",
    "current udp bandwidth": "udp_kbps",
}


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _clean_addr(addr: str) -> str:
    addr = (addr or "").strip()
    return addr[7:] if addr.lower().startswith("::ffff:") else addr


def _counter_instances(rows: list) -> list[dict[str, float]]:
    """把 Get-Counter 的扁平样本按实例归并，跳过 _Total 与空实例。"""
    by_inst: dict[str, dict[str, float]] = {}
    for row in rows:
        inst = str(row.get("inst") or "")
        if not inst or inst.startswith("_"):
            continue
        field = _COUNTER_FIELDS.get(str(row.get("name") or "").strip().lower())
        if field:
            by_inst.setdefault(inst, {})[field] = float(row.get("v") or 0)
    return [by_inst[k] for k in sorted(by_inst)]


def build_sessions(data: dict[str, Any]) -> list[dict[str, Any]]:
    """汇总活动 RDP 会话。

    出站：mstsc 进程有 UDP 套接字 → udp，否则 tcp。
    入站：只有实例数与会话数一致时才把计数器对上会话；有 UDP 流量/RTT → udp，否则 tcp；对不上则 unknown。
    """
    udp_pids = {int(p) for p in _as_list(data.get("udpPids"))}
    rows = [dict(r) for r in _as_list(data.get("sess"))]
    instances = _counter_instances(_as_list(data.get("ctr")))
    inbound = [r for r in rows if r.get("dir") == "in"]
    map_counters = bool(instances) and len(instances) == len(inbound)
    sessions: list[dict[str, Any]] = []
    in_index = 0
    for row in rows:
        item: dict[str, Any] = {
            "direction": str(row.get("dir") or ""),
            "peer_ip": _clean_addr(str(row.get("remote") or "")),
            "pid": int(row.get("pid") or 0),
            "age_sec": int(row.get("age") or 0),
            "transport": "unknown",
        }
        if item["direction"] == "out":
            item["transport"] = "udp" if item["pid"] in udp_pids else "tcp"
        elif map_counters:
            counters = instances[in_index]
            in_index += 1
            item.update(counters)
            has_udp = counters.get("udp_pps", 0) > 0 or counters.get("udp_rtt_ms", 0) > 0
            item["transport"] = "udp" if has_udp else "tcp"
        sessions.append(item)
    return sessions


def collect(*, include_events: bool = False) -> RdpState:
    flag = "$true" if include_events else "$false"
    script = f"$includeEvents = {flag}\n" + _SCRIPT
    data = powershell_json(script, timeout=25 if include_events else 18) or {}
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
        sessions=build_sessions(data),
        recent_events=events[:20],
    )
