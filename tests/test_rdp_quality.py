"""RDP 实时质量：会话识别、UDP 回退、主机侧计数器、规则与修复。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from core.collector import annotate_sessions
from core.models import PeerState, RdpState, Snapshot
from fixes.catalog import ACTIONS
from probes.rdp_probe import build_sessions
from rules.engine import evaluate
from rules.plain import issue_cards, session_rows
from tests.test_hotfix_151 import _fixed_snapshot


def _ctr(inst: str, **values: float) -> list[dict]:
    names = {
        "tcp_rtt": "current tcp rtt",
        "udp_rtt": "current udp rtt",
        "loss": "loss rate",
        "retrans": "retransmission rate",
        "udp_pps": "udp packets received/sec",
    }
    return [{"inst": inst, "name": names[k], "v": v} for k, v in values.items()]


class BuildSessionsTest(unittest.TestCase):
    def test_outbound_with_udp_socket_is_udp(self) -> None:
        data = {
            "sess": [{"dir": "out", "remote": "100.82.26.106", "pid": 33192, "age": 851}],
            "udpPids": [33192],
        }
        (s,) = build_sessions(data)
        self.assertEqual((s["direction"], s["transport"], s["peer_ip"]), ("out", "udp", "100.82.26.106"))

    def test_outbound_without_udp_socket_is_tcp(self) -> None:
        data = {"sess": [{"dir": "out", "remote": "100.1.1.2", "pid": 7, "age": 60}], "udpPids": [99]}
        self.assertEqual(build_sessions(data)[0]["transport"], "tcp")

    def test_single_pid_value_from_powershell_is_handled(self) -> None:
        # ConvertTo-Json 会把单元素数组/单个对象展开成标量
        data = {"sess": {"dir": "out", "remote": "::ffff:100.1.1.2", "pid": 5, "age": 30}, "udpPids": 5}
        (s,) = build_sessions(data)
        self.assertEqual(s["peer_ip"], "100.1.1.2")
        self.assertEqual(s["transport"], "udp")

    def test_inbound_maps_host_counters(self) -> None:
        data = {
            "sess": [{"dir": "in", "remote": "100.1.1.2", "pid": 4, "age": 100}],
            "ctr": _ctr("RDP-Tcp 1", tcp_rtt=40, udp_rtt=35, loss=0.5, retrans=1, udp_pps=800)
            + _ctr("_Total", tcp_rtt=99),
        }
        (s,) = build_sessions(data)
        self.assertEqual(s["transport"], "udp")
        self.assertEqual(s["udp_rtt_ms"], 35)
        self.assertEqual(s["loss_pct"], 0.5)

    def test_inbound_without_udp_traffic_is_tcp(self) -> None:
        data = {
            "sess": [{"dir": "in", "remote": "100.1.1.2", "pid": 4, "age": 100}],
            "ctr": _ctr("RDP-Tcp 1", tcp_rtt=80, udp_rtt=0, loss=0, retrans=0, udp_pps=0),
        }
        self.assertEqual(build_sessions(data)[0]["transport"], "tcp")

    def test_inbound_counter_mismatch_stays_unknown(self) -> None:
        data = {
            "sess": [
                {"dir": "in", "remote": "100.1.1.2", "pid": 4, "age": 100},
                {"dir": "in", "remote": "100.1.1.3", "pid": 4, "age": 90},
            ],
            "ctr": _ctr("RDP-Tcp 1", tcp_rtt=40, udp_pps=10),
        }
        self.assertTrue(all(s["transport"] == "unknown" for s in build_sessions(data)))

    def test_no_sessions(self) -> None:
        self.assertEqual(build_sessions({}), [])


def _with_sessions(*sessions: dict) -> Snapshot:
    snap = _fixed_snapshot()
    snap.rdp = RdpState(select_transport=0, sessions=list(sessions))
    return snap


def _ids(snap: Snapshot) -> set[str]:
    return {f.id for f in evaluate(snap)}


class RdpRulesTest(unittest.TestCase):
    def test_tcp_only_session_triggers_r14(self) -> None:
        snap = _with_sessions({"direction": "out", "peer_ip": "100.1.1.2", "age_sec": 90, "transport": "tcp"})
        self.assertIn("R14", _ids(snap))
        finding = next(f for f in evaluate(snap) if f.id == "R14")
        self.assertEqual(finding.fix_ids, [])  # 出站：要在对方机器上处理

    def test_inbound_tcp_only_offers_firewall_fix(self) -> None:
        snap = _with_sessions({"direction": "in", "peer_ip": "100.1.1.2", "age_sec": 90, "transport": "tcp"})
        finding = next(f for f in evaluate(snap) if f.id == "R14")
        self.assertEqual(finding.fix_ids, ["F10"])
        snap.findings = evaluate(snap)
        card = next(c for c in issue_cards(snap) if c.finding_id == "R14")
        self.assertEqual(card.primary_fix, "F10")

    def test_fresh_session_is_not_flagged(self) -> None:
        snap = _with_sessions({"direction": "out", "peer_ip": "100.1.1.2", "age_sec": 5, "transport": "tcp"})
        self.assertNotIn("R14", _ids(snap))

    def test_udp_session_is_healthy(self) -> None:
        snap = _with_sessions({"direction": "out", "peer_ip": "100.1.1.2", "age_sec": 900, "transport": "udp"})
        ids = _ids(snap)
        self.assertNotIn("R14", ids)
        self.assertNotIn("R15", ids)
        self.assertIn("R11", ids)  # 仍提示可用优化配置（low）

    def test_policy_disabled_udp_is_left_to_r07(self) -> None:
        snap = _with_sessions({"direction": "out", "peer_ip": "100.1.1.2", "age_sec": 90, "transport": "tcp"})
        snap.rdp.client_disable_udp = 1
        ids = _ids(snap)
        self.assertNotIn("R14", ids)
        self.assertIn("R07", ids)

    def test_bad_host_counters_trigger_r15(self) -> None:
        snap = _with_sessions(
            {"direction": "in", "peer_ip": "100.1.1.2", "age_sec": 300, "transport": "udp",
             "udp_rtt_ms": 220.0, "loss_pct": 4.0, "retrans_pct": 1.0, "peer_name": "office"}
        )
        finding = next(f for f in evaluate(snap) if f.id == "R15")
        self.assertIn("延迟 220ms", finding.evidence)
        self.assertIn("丢包 4.0%", finding.evidence)

    def test_good_host_counters_do_not_trigger_r15(self) -> None:
        snap = _with_sessions(
            {"direction": "in", "peer_ip": "100.1.1.2", "age_sec": 300, "transport": "udp",
             "udp_rtt_ms": 35.0, "loss_pct": 0.2, "retrans_pct": 0.5}
        )
        self.assertNotIn("R15", _ids(snap))

    def test_no_sessions_no_r11(self) -> None:
        self.assertNotIn("R11", _ids(_with_sessions()))


class F10Test(unittest.TestCase):
    def test_precheck_only_for_inbound_tcp_sessions(self) -> None:
        inbound = _with_sessions({"direction": "in", "peer_ip": "100.1.1.2", "age_sec": 90, "transport": "tcp"})
        outbound = _with_sessions({"direction": "out", "peer_ip": "100.1.1.2", "age_sec": 90, "transport": "tcp"})
        with patch("fixes.catalog.is_admin", return_value=True):
            self.assertTrue(ACTIONS["F10"].precheck(inbound)[0])
            ok, msg = ACTIONS["F10"].precheck(outbound)
        self.assertFalse(ok)
        self.assertIn("入站", msg)

    def test_apply_creates_scoped_rule_and_rollback(self) -> None:
        inbound = _with_sessions({"direction": "in", "peer_ip": "100.1.1.2", "age_sec": 90, "transport": "tcp"})
        with patch("fixes.catalog.run_powershell") as ps, patch("fixes.catalog._write_rollback", return_value="rb.ps1") as rb:
            ps.return_value.ok = True
            result = ACTIONS["F10"].apply(inbound)
        script = ps.call_args.args[0]
        self.assertIn("100.64.0.0/10", script)  # 只放行 Tailscale 网段
        self.assertIn("-Protocol UDP -LocalPort 3389", script)
        self.assertIn("Remove-NetFirewallRule", rb.call_args.args[1])
        self.assertTrue(result.ok)
        self.assertEqual(result.rollback_path, "rb.ps1")


class SessionDisplayTest(unittest.TestCase):
    def test_annotate_adds_peer_name_and_path(self) -> None:
        snap = _with_sessions({"direction": "out", "peer_ip": "100.126.112.7", "age_sec": 90, "transport": "udp"})
        snap.peers = [
            PeerState(hostname="me", ip="100.105.93.114", online=True, is_self=True),
            PeerState(hostname="cr-msi", ip="100.126.112.7", online=True, cur_addr="1.2.3.4:5",
                      ping_rtt_ms=9, ping_via="1.2.3.4:5"),
        ]
        annotate_sessions(snap)
        s = snap.rdp.sessions[0]
        self.assertEqual((s["peer_name"], s["peer_path"], s["peer_rtt_ms"]), ("cr-msi", "direct", 9))

    def test_rows_are_plain_language(self) -> None:
        snap = _with_sessions(
            {"direction": "out", "peer_ip": "100.1.1.2", "peer_name": "office", "age_sec": 851,
             "transport": "udp", "peer_path": "direct", "peer_rtt_ms": 14.0},
            {"direction": "in", "peer_ip": "100.1.1.3", "age_sec": 20, "transport": "tcp"},
        )
        rows = session_rows(snap)
        self.assertEqual(rows[0], ("office", "我连对方", "UDP（快）", "直连", "14 毫秒", "—", "14 分钟"))
        self.assertEqual(rows[1][:3], ("100.1.1.3", "对方连我", "仅 TCP（较慢）"))
        self.assertEqual(rows[1][-1], "20 秒")


if __name__ == "__main__":
    unittest.main()
