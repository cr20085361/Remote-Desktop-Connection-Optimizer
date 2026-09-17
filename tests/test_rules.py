from __future__ import annotations

import unittest

from core.models import (
    DefaultRoute,
    IfaceState,
    NetcheckState,
    PeerState,
    ProxyState,
    RdpState,
    RouteState,
    Snapshot,
)
from rules.engine import evaluate


def _live_like_snapshot() -> Snapshot:
    return Snapshot(
        ts=1,
        hostname="cr-x9",
        self_ip="100.105.93.114",
        netcheck=NetcheckState(
            udp=True,
            global_v4="154.44.22.208",
            global_v4_port=47935,
            preferred_derp="Los Angeles",
            preferred_derp_code="lax",
            preferred_derp_latency_ms=654.1,
            region_latency={"lax": 654.1, "hkg": 831.6, "tok": 831.6},
        ),
        peers=[
            PeerState(hostname="cr-x9", ip="100.105.93.114", online=True, is_self=True),
            PeerState(
                hostname="cr-msi",
                ip="100.126.112.7",
                online=True,
                active=True,
                cur_addr="211.137.110.19:1566",
                ping_rtt_ms=162,
                ping_via="211.137.110.19:1566",
                ping_loss_pct=0,
                ping_jitter_ms=8,
            ),
            PeerState(
                hostname="antenna",
                ip="100.80.118.120",
                online=True,
                relay="lax",
                ping_via="DERP(lax)",
                ping_rtt_ms=700,
            ),
        ],
        route=RouteState(
            default_routes=[
                DefaultRoute("0.0.0.0/0", "172.18.0.2", 0, "singbox_tun", 0, 0, 9000),
                DefaultRoute("0.0.0.0/0", "192.168.1.1", 0, "WLAN", 30, 30, 1500),
            ],
            default_exit_iface="singbox_tun",
            ifaces=[
                IfaceState("singbox_tun", "Up", "sing-tun Tunnel", ["172.18.0.1"], 0, 9000, is_tun=True),
                IfaceState("Tailscale", "Up", "Tailscale Tunnel", ["100.105.93.114"], 5, 1280, is_tailscale=True),
                IfaceState("WLAN", "Up", "Intel Wi-Fi", ["192.168.1.164"], 30, 1500, is_physical=True, is_wifi=True),
            ],
        ),
        proxy=ProxyState(
            tun_up=True,
            tun_ifaces=["singbox_tun"],
            tun_metric=0,
            v2rayn_running=True,
            singbox_running=True,
            proxy_enable=True,
            proxy_server="127.0.0.1:10808",
            proxy_override="<local>;localhost;127.*;10.*;172.16.*;192.168.*",
            override_has_100=False,
            node_addresses=["154.44.22.20"],
            tailscale_direct_in_rules=False,
        ),
        rdp=RdpState(port=3389, select_transport=2, deny_connections=0),
    )


class RulesTest(unittest.TestCase):
    def test_core_rules_match_live_evidence(self) -> None:
        findings = evaluate(_live_like_snapshot())
        ids = {f.id for f in findings}
        self.assertIn("R01", ids)
        self.assertIn("R02", ids)
        self.assertIn("R03", ids)
        self.assertIn("R04", ids)
        self.assertIn("R05", ids)
        self.assertIn("R06", ids)
        self.assertIn("R07", ids)
        self.assertIn("R10", ids)
        r01 = next(f for f in findings if f.id == "R01")
        self.assertEqual(r01.severity, "critical")
        self.assertIn("154.44.22.208", r01.evidence)

    def test_clean_snapshot_no_false_r01(self) -> None:
        snap = Snapshot(
            hostname="ok",
            self_ip="100.1.1.1",
            netcheck=NetcheckState(
                udp=True,
                global_v4="211.137.1.2",
                preferred_derp="Hong Kong",
                preferred_derp_code="hkg",
                preferred_derp_latency_ms=48,
                region_latency={"hkg": 48, "tok": 55},
            ),
            peers=[
                PeerState(hostname="ok", ip="100.1.1.1", is_self=True, online=True),
                PeerState(
                    hostname="peer",
                    ip="100.2.2.2",
                    online=True,
                    cur_addr="125.69.1.1:41641",
                    ping_rtt_ms=32,
                    ping_via="125.69.1.1:41641",
                    ping_loss_pct=0,
                    ping_jitter_ms=2,
                ),
            ],
            route=RouteState(
                default_routes=[DefaultRoute("0.0.0.0/0", "192.168.1.1", 0, "Ethernet", 25, 25, 1500)],
                default_exit_iface="Ethernet",
                ifaces=[
                    IfaceState("Ethernet", "Up", "Realtek", ["192.168.1.10"], 25, 1500, is_physical=True),
                    IfaceState("Tailscale", "Up", "Tailscale", ["100.1.1.1"], 5, 1280, is_tailscale=True),
                ],
            ),
            proxy=ProxyState(tun_up=False, proxy_enable=False, override_has_100=True),
            rdp=RdpState(select_transport=0),
        )
        ids = {f.id for f in evaluate(snap)}
        self.assertNotIn("R01", ids)
        self.assertNotIn("R02", ids)
        self.assertNotIn("R03", ids)
        self.assertNotIn("R04", ids)


if __name__ == "__main__":
    unittest.main()
