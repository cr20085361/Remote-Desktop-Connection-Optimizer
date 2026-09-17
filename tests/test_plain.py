from __future__ import annotations

import re
import unittest

from fixes.catalog import ACTIONS
from rules.engine import evaluate
from rules.plain import (
    FIX_COPY,
    RULE_COPY,
    catalog_rule_ids,
    health_score,
    issue_cards,
    verdict,
)
from tests.test_rules import _live_like_snapshot


_FORBIDDEN = re.compile(r"R0\d|F0\d|DERP", re.I)


class PlainLayerTest(unittest.TestCase):
    def test_every_rule_has_copy(self) -> None:
        for rid in catalog_rule_ids():
            self.assertIn(rid, RULE_COPY, f"规则 {rid} 缺少白话文案")

    def test_every_fix_has_copy(self) -> None:
        for fid in ACTIONS:
            self.assertIn(fid, FIX_COPY, f"修复 {fid} 缺少白话名称")
            self.assertTrue(FIX_COPY[fid].name)

    def test_hijack_snapshot_score_and_verdict(self) -> None:
        snap = _live_like_snapshot()
        snap.findings = evaluate(snap)
        score, band = health_score(snap)
        self.assertLess(score, 40)
        self.assertEqual(band, "严重")
        text = verdict(snap)
        self.assertTrue(text)
        self.assertIsNone(_FORBIDDEN.search(text), text)
        cards = issue_cards(snap)
        self.assertTrue(cards)
        self.assertEqual(cards[0].finding_id, "R01")
        self.assertIn("翻墙", cards[0].title)

    def test_clean_snapshot_score_and_verdict(self) -> None:
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
        snap.findings = evaluate(snap)
        score, band = health_score(snap)
        self.assertGreater(score, 85)
        self.assertEqual(band, "优秀")
        text = verdict(snap)
        self.assertTrue(text)
        self.assertIsNone(_FORBIDDEN.search(text), text)


if __name__ == "__main__":
    unittest.main()
