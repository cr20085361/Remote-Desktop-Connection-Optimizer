"""v1.5.1 热修回归：修好后转绿、ping 误报、无法判断、F02 诚实返回。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from core.models import (
    IfaceState,
    LinkSample,
    PeerState,
    RdpState,
    Snapshot,
    TailscalePrefs,
)
from fixes.catalog import ACTIONS
from probes.tailscale_probe import apply_ping_stats, parse_ping_output, summarize_pings
from rules.engine import evaluate
from rules.plain import data_gaps, health_score, issue_cards, summary_line, verdict
from tests.test_rules import _live_like_snapshot


def _ids(snap: Snapshot) -> set[str]:
    return {f.id for f in evaluate(snap)}


def _fixed_snapshot() -> Snapshot:
    """F01 已生效并重启 Tun：Tun 仍开着、默认路由仍是 Tun，但出口 IP 已回到宽带。"""
    snap = _live_like_snapshot()
    snap.netcheck.global_v4 = "211.137.1.2"
    snap.netcheck.preferred_derp = "Hong Kong"
    snap.netcheck.preferred_derp_code = "hkg"
    snap.netcheck.preferred_derp_latency_ms = 45
    snap.netcheck.region_latency = {"hkg": 45}
    snap.proxy.tailscale_direct_in_rules = True
    snap.proxy.override_has_100 = True
    snap.rdp = RdpState(select_transport=0)
    snap.peers = [
        PeerState(hostname="cr-x9", ip="100.105.93.114", online=True, is_self=True),
        PeerState(
            hostname="cr-msi",
            ip="100.126.112.7",
            online=True,
            cur_addr="211.137.110.19:1566",
            ping_rtt_ms=32,
            ping_via="211.137.110.19:1566",
            ping_loss_pct=0,
            ping_jitter_ms=3,
        ),
    ]
    snap.route.ifaces.append(IfaceState("Ethernet", "Up", "Realtek", ["192.168.1.9"], 25, 1500, is_physical=True))
    return snap


class FixedStateTest(unittest.TestCase):
    def test_no_hijack_after_direct_rule_even_if_tun_still_on(self) -> None:
        ids = _ids(_fixed_snapshot())
        self.assertNotIn("R01", ids)
        self.assertNotIn("R05", ids)

    def test_fixed_snapshot_scores_excellent(self) -> None:
        snap = _fixed_snapshot()
        snap.findings = evaluate(snap)
        score, band = health_score(snap)
        self.assertGreater(score, 85, [f.id for f in snap.findings])
        self.assertEqual(band, "优秀")

    def test_egress_in_node_subnet_still_flags_even_with_direct_rule(self) -> None:
        snap = _fixed_snapshot()
        snap.netcheck.global_v4 = "154.44.22.208"  # 与 node_addresses 同 /24
        self.assertIn("R01", _ids(snap))

    def test_tun_without_direct_rule_still_flags(self) -> None:
        snap = _fixed_snapshot()
        snap.proxy.tailscale_direct_in_rules = False
        ids = _ids(snap)
        self.assertIn("R01", ids)
        self.assertIn("R05", ids)


class PingReconcileTest(unittest.TestCase):
    OUTPUT = (
        "pong from cr-msi (100.126.112.7) via DERP(hkg) in 60ms\n"
        "pong from cr-msi (100.126.112.7) via 211.137.110.19:1566 in 30ms\n"
        "pong from cr-msi (100.126.112.7) via 211.137.110.19:1566 in 34ms\n"
    )

    def test_parse_and_summarize_uses_direct_samples(self) -> None:
        pongs = parse_ping_output(self.OUTPUT)
        self.assertEqual(len(pongs), 3)
        stats = summarize_pings(pongs, 3, self.OUTPUT)
        self.assertAlmostEqual(stats["rtt_ms"], 32.0)  # 不含首个 DERP 样本
        self.assertEqual(stats["via"], "211.137.110.19:1566")
        self.assertEqual(stats["loss_pct"], 0.0)
        self.assertAlmostEqual(stats["jitter_ms"], 4.0)

    def test_idle_peer_reported_as_relay_is_reconciled(self) -> None:
        peer = PeerState(hostname="p", ip="100.1.1.2", online=True, relay="hkg")
        apply_ping_stats(peer, summarize_pings(parse_ping_output(self.OUTPUT), 3, self.OUTPUT))
        self.assertEqual(peer.relay, "")
        self.assertTrue(peer.is_direct)
        snap = _fixed_snapshot()
        snap.peers = [PeerState(hostname="me", ip="100.1.1.1", online=True, is_self=True), peer]
        self.assertNotIn("R03", _ids(snap))

    def test_partial_loss_is_still_counted(self) -> None:
        text = "pong from p (100.1.1.2) via 1.2.3.4:5 in 30ms\n"
        stats = summarize_pings(parse_ping_output(text), 4, text)
        self.assertEqual(stats["loss_pct"], 75.0)

    def test_ipv6_direct_endpoint_clears_relay(self) -> None:
        text = "pong from p (100.1.1.2) via [2409:8a62::1]:41641 in 9ms\n"
        peer = PeerState(hostname="p", ip="100.1.1.2", online=True, relay="sin")
        apply_ping_stats(peer, summarize_pings(parse_ping_output(text), 1, text))
        self.assertEqual(peer.relay, "")
        self.assertTrue(peer.is_direct)

    def test_single_dropped_ping_is_not_unstable(self) -> None:
        snap = _fixed_snapshot()
        snap.peers[1].ping_loss_pct = 20.0  # 5 个里丢 1 个
        self.assertNotIn("R09", _ids(snap))
        snap.peers[1].ping_loss_pct = 40.0  # 丢 2 个
        self.assertIn("R09", _ids(snap))

    def test_ping_failure_falls_back_to_status_relay(self) -> None:
        snap = _fixed_snapshot()
        snap.peers[1] = PeerState(hostname="cr-msi", ip="100.126.112.7", online=True, relay="lax")
        self.assertIn("R03", _ids(snap))


class MtuRuleTest(unittest.TestCase):
    def test_tun_mtu_gap_alone_does_not_trigger_r08(self) -> None:
        self.assertNotIn("R08", _ids(_live_like_snapshot()))

    def test_measured_pmtu_still_triggers_r08(self) -> None:
        snap = _fixed_snapshot()
        snap.links = [LinkSample(peer_ip="100.126.112.7", hostname="cr-msi", pmtu=1200)]
        self.assertIn("R08", _ids(snap))


class TailscaleStateRulesTest(unittest.TestCase):
    def test_missing_tailscale_is_not_reported_as_healthy(self) -> None:
        snap = Snapshot(errors=["未找到 tailscale.exe"])
        snap.findings = evaluate(snap)
        self.assertIn("R12", {f.id for f in snap.findings})
        self.assertIn("没有连上", verdict(snap) + "".join(c.title for c in issue_cards(snap)))

    def test_disconnected_client_flags_r12(self) -> None:
        snap = _fixed_snapshot()
        snap.prefs = TailscalePrefs(want_running=False)
        self.assertIn("R12", _ids(snap))

    def test_exit_node_flags_r13_with_card(self) -> None:
        snap = _fixed_snapshot()
        snap.prefs = TailscalePrefs(exit_node_ip="100.9.9.9", want_running=True)
        snap.findings = evaluate(snap)
        self.assertIn("R13", {f.id for f in snap.findings})
        self.assertTrue(any(c.finding_id == "R13" for c in issue_cards(snap)))

    def test_data_gaps_soften_the_all_clear(self) -> None:
        snap = _fixed_snapshot()
        snap.route.error = "路由采集失败"
        snap.errors = ["proxy: powershell timeout"]
        snap.findings = evaluate(snap)
        self.assertEqual(data_gaps(snap), ["网卡与路由", "翻墙软件状态"])
        self.assertIn("结论不完整", verdict(snap))
        self.assertIn("没测到", summary_line(snap))


class FixHonestyTest(unittest.TestCase):
    def test_f02_reports_failure_when_v2rayn_missing(self) -> None:
        snap = _fixed_snapshot()
        snap.proxy.v2rayn_path = ""
        with patch("fixes.catalog._write_rollback", return_value=""):
            result = ACTIONS["F02"].apply(snap)
        self.assertFalse(result.ok)
        self.assertIn("手动", result.message)

    def test_f02_precheck_ignores_singbox_without_tun(self) -> None:
        snap = _fixed_snapshot()
        snap.proxy.tun_up = False
        snap.proxy.singbox_running = True
        ok, _msg = ACTIONS["F02"].precheck(snap)
        self.assertFalse(ok)

    def test_f08_only_targets_windows_peers(self) -> None:
        snap = _fixed_snapshot()
        snap.peers.append(PeerState(hostname="phone", ip="100.7.7.7", os="iOS", online=True))
        snap.peers[1].os = "windows"
        ok, msg = ACTIONS["F08"].precheck(snap)
        self.assertTrue(ok)
        self.assertIn("1 个", msg)


class ProbeHygieneTest(unittest.TestCase):
    def test_no_hardcoded_author_paths_in_v2rayn_candidates(self) -> None:
        from probes.proxy_probe import _candidate_roots

        blob = " ".join(str(p) for p in _candidate_roots(""))
        self.assertNotIn("科学上网", blob)
        self.assertNotIn("D:\\soft", blob)


if __name__ == "__main__":
    unittest.main()
