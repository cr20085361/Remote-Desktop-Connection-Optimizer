from __future__ import annotations

import unittest

from core.models import Finding, Snapshot, TailscalePrefs
from rules.plain import health_score


def _snap(*items: tuple[str, str]) -> Snapshot:
    snap = Snapshot()
    snap.findings = [Finding(id=i, severity=sev, title=i, evidence="") for i, sev in items]
    return snap


class ScoringTest(unittest.TestCase):
    def test_same_root_cause_is_not_counted_five_times(self) -> None:
        one = health_score(_snap(("R01", "critical")))[0]
        five = health_score(
            _snap(("R01", "critical"), ("R02", "critical"), ("R03", "critical"), ("R04", "high"), ("R05", "high"))
        )[0]
        self.assertEqual(one, 75)
        self.assertGreater(five, 30)  # 旧算法会扣到 13 分
        self.assertLess(five, one)  # 现象越多仍应略低

    def test_independent_problems_still_add_up(self) -> None:
        score = health_score(_snap(("R01", "critical"), ("R06", "medium"), ("R10", "low")))[0]
        self.assertEqual(score, 100 - 25 - 6 - 2)

    def test_tailscale_down_caps_score(self) -> None:
        snap = _snap(("R12", "critical"))
        snap.prefs = TailscalePrefs(want_running=False)
        self.assertLessEqual(health_score(snap)[0], 40)


if __name__ == "__main__":
    unittest.main()
