from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fixes.v2rayn import patch_routing


class V2raynPatchTest(unittest.TestCase):
    def test_inserts_process_rule_into_routingitem(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            gui = root / "guiConfigs"
            gui.mkdir()
            db = gui / "guiNDB.db"
            conn = sqlite3.connect(str(db))
            conn.execute(
                "CREATE TABLE RoutingItem (Id TEXT, Remarks TEXT, Url TEXT, RuleSet TEXT, RuleNum INTEGER, Enabled INTEGER, Locked INTEGER, CustomIcon TEXT, CustomRulesetPath4Singbox TEXT, DomainStrategy TEXT, DomainStrategy4Singbox TEXT, Sort INTEGER, IsActive INTEGER)"
            )
            original = [
                {
                    "Id": "1",
                    "OutboundTag": "direct",
                    "Ip": ["geoip:private"],
                    "Enabled": True,
                    "Remarks": "private",
                }
            ]
            conn.execute(
                "INSERT INTO RoutingItem(Id, Remarks, RuleSet, RuleNum, Enabled, IsActive) VALUES(?,?,?,?,?,?)",
                ("rid1", "V4", json.dumps(original, ensure_ascii=False), 1, 1, 1),
            )
            conn.commit()
            conn.close()
            (gui / "guiNConfig.json").write_text(
                json.dumps({"TunModeItem": {"EnableTun": True, "RouteExcludeAddress": None}}),
                encoding="utf-8",
            )
            result = patch_routing(str(root), add_process=True, add_cgnat=True)
            self.assertTrue(result["ok"], result)
            conn = sqlite3.connect(str(db))
            rules = json.loads(conn.execute("SELECT RuleSet FROM RoutingItem").fetchone()[0])
            conn.close()
            remarks = [r.get("Remarks") for r in rules]
            self.assertIn("RdpOptimizer-Tailscale-process-direct", remarks)
            self.assertIn("RdpOptimizer-Tailscale-cgnat-direct", remarks)
            proc = next(r for r in rules if r.get("Remarks") == "RdpOptimizer-Tailscale-process-direct")
            self.assertEqual(proc["OutboundTag"], "direct")
            self.assertEqual(proc["Process"], ["tailscaled.exe", "tailscale.exe", "tailscale-ipn.exe"])
            self.assertEqual(rules[0]["Remarks"], "RdpOptimizer-Tailscale-process-direct")
            cfg = json.loads((gui / "guiNConfig.json").read_text(encoding="utf-8"))
            self.assertIn("100.64.0.0/10", cfg["TunModeItem"]["RouteExcludeAddress"])


if __name__ == "__main__":
    unittest.main()
