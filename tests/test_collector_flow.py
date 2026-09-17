from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from core.collector import TOTAL_STEPS, collect_snapshot
from core.models import NetcheckState, PeerState, ProxyState, RdpState, RouteState, TailscalePrefs


class CollectorFlowTest(unittest.TestCase):
    def test_two_phase_and_fixed_progress(self) -> None:
        events: list[tuple[int, int, str]] = []
        snaps: list = []

        def progress(index: int, total: int, label: str) -> None:
            events.append((index, total, label))

        def slow_netcheck() -> NetcheckState:
            time.sleep(0.12)
            return NetcheckState(
                udp=True,
                global_v4="8.8.8.8",
                preferred_derp="Hong Kong",
                preferred_derp_code="hkg",
                preferred_derp_latency_ms=42,
            )

        self_peer = PeerState(hostname="me", ip="100.1.1.1", online=True, is_self=True)
        office = PeerState(hostname="office", ip="100.1.2.3", online=True)

        with (
            patch(
                "core.collector.tailscale_probe.collect_status",
                return_value=("100.1.1.1", [self_peer, office], ""),
            ),
            patch("core.collector.tailscale_probe.collect_netcheck", side_effect=slow_netcheck),
            patch("core.collector.tailscale_probe.collect_prefs", return_value=TailscalePrefs()),
            patch(
                "core.collector.tailscale_probe.ping_peer",
                return_value={"rtt_ms": 28.0, "via": "direct", "loss_pct": 0.0, "jitter_ms": 1.0},
            ),
            patch("core.collector.route_probe.collect", return_value=RouteState()),
            patch("core.collector.proxy_probe.collect", return_value=ProxyState()),
            patch("core.collector.rdp_probe.collect", return_value=RdpState()),
        ):
            final = collect_snapshot(
                ping_count=2,
                ping_peers=True,
                probe_links=False,
                progress=progress,
                on_snapshot=lambda snap: snaps.append(snap),
            )

        self.assertEqual(len(snaps), 1)
        self.assertEqual(snaps[0].netcheck.global_v4, "")
        self.assertEqual(final.netcheck.global_v4, "8.8.8.8")
        office_final = next(p for p in final.peers if p.hostname == "office")
        self.assertEqual(office_final.ping_rtt_ms, 28.0)
        self.assertTrue(events)
        self.assertTrue(all(total == TOTAL_STEPS for _i, total, _label in events))
        self.assertEqual(events[-1][0], TOTAL_STEPS)
        self.assertIn("完成", events[-1][2])


if __name__ == "__main__":
    unittest.main()
