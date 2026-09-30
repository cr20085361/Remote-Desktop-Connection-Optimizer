"""F01/F04 撤销只删本工具添加的规则，不覆盖用户之后在 v2rayN 里做的改动。"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fixes import v2rayn
from fixes.catalog import _write_rollback
from fixes.engine import run_rollback

_SCHEMA = (
    "CREATE TABLE RoutingItem (Id TEXT, Remarks TEXT, RuleSet TEXT, RuleNum INTEGER, IsActive INTEGER)"
)


def _make_root(raw: str) -> Path:
    root = Path(raw)
    gui = root / "guiConfigs"
    gui.mkdir()
    conn = sqlite3.connect(str(gui / "guiNDB.db"))
    conn.execute(_SCHEMA)
    rules = [{"Id": "1", "OutboundTag": "direct", "Ip": ["geoip:private"], "Remarks": "private"}]
    conn.execute(
        "INSERT INTO RoutingItem VALUES(?,?,?,?,?)", ("r1", "V4", json.dumps(rules), 1, 1)
    )
    conn.commit()
    conn.close()
    (gui / "guiNConfig.json").write_text(
        json.dumps({"TunModeItem": {"EnableTun": True, "RouteExcludeAddress": ["10.0.0.0/8"]}}),
        encoding="utf-8",
    )
    return root


def _remarks(root: Path) -> list[str]:
    conn = sqlite3.connect(str(root / "guiConfigs" / "guiNDB.db"))
    raw = conn.execute("SELECT RuleSet FROM RoutingItem").fetchone()[0]
    conn.close()
    return [r.get("Remarks") for r in json.loads(raw)]


class PreciseRollbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = _make_root(self._tmp.name)
        backup_dir = Path(self._tmp.name) / "_bak"
        backup_dir.mkdir()

        def fake_backup(path: Path) -> dict[str, str]:
            dest = backup_dir / f"{path.name}.bak"
            dest.write_bytes(path.read_bytes())
            return {"src": str(path), "bak": str(dest)}

        patcher = patch("fixes.v2rayn._backup", side_effect=fake_backup)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_undo_keeps_rules_added_after_the_fix(self) -> None:
        result = v2rayn.patch_routing(str(self.root), add_process=True, add_cgnat=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["tun_exclude_added"], ["100.64.0.0/10"])

        # 修复之后用户在 v2rayN 里又加了一条自己的规则
        db = self.root / "guiConfigs" / "guiNDB.db"
        conn = sqlite3.connect(str(db))
        raw = conn.execute("SELECT RuleSet FROM RoutingItem").fetchone()[0]
        rules = json.loads(raw)
        rules.append({"Id": "9", "OutboundTag": "proxy", "Domain": ["example.com"], "Remarks": "user-rule"})
        conn.execute("UPDATE RoutingItem SET RuleSet=?", (json.dumps(rules),))
        conn.commit()
        conn.close()

        ok, message = v2rayn.undo_from_meta(
            {
                "kind": "v2rayn",
                "root": str(self.root),
                "kinds": ["process", "cgnat"],
                "tun_exclude_added": result["tun_exclude_added"],
            }
        )
        self.assertTrue(ok, message)
        remarks = _remarks(self.root)
        self.assertIn("user-rule", remarks)  # 整库还原会把它抹掉
        self.assertIn("private", remarks)
        self.assertFalse([r for r in remarks if r and r.startswith("RdpOptimizer-")])
        cfg = json.loads((self.root / "guiConfigs" / "guiNConfig.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["TunModeItem"]["RouteExcludeAddress"], ["10.0.0.0/8"])

    def test_undo_is_safe_to_run_twice(self) -> None:
        v2rayn.patch_routing(str(self.root), add_process=True, add_cgnat=False)
        meta = {"kind": "v2rayn", "root": str(self.root), "kinds": ["process"]}
        self.assertTrue(v2rayn.undo_from_meta(meta)[0])
        ok, message = v2rayn.undo_from_meta(meta)
        self.assertTrue(ok)
        self.assertIn("没有找到", message)

    def test_undo_reports_locked_database(self) -> None:
        v2rayn.patch_routing(str(self.root), add_process=True, add_cgnat=False)
        with patch("fixes.v2rayn._strip_sqlite", side_effect=sqlite3.OperationalError("database is locked")):
            ok, message = v2rayn.undo_from_meta({"kind": "v2rayn", "root": str(self.root), "kinds": ["process"]})
        self.assertFalse(ok)
        self.assertIn("退出 v2rayN", message)

    def test_run_rollback_prefers_sidecar_over_script(self) -> None:
        v2rayn.patch_routing(str(self.root), add_process=True, add_cgnat=False)
        rollback_dir = Path(self._tmp.name) / "rollback"
        with patch("fixes.catalog.ROLLBACK_DIR", rollback_dir):
            script = _write_rollback(
                "F01", "throw 'must not run'", {"kind": "v2rayn", "root": str(self.root), "kinds": ["process"]}
            )
        self.assertTrue(Path(script).with_suffix(".json").is_file())
        with patch("fixes.engine.run_powershell") as ps:
            ok, _message = run_rollback(script)
        self.assertTrue(ok)
        ps.assert_not_called()
        self.assertFalse([r for r in _remarks(self.root) if r and r.startswith("RdpOptimizer-")])

    def test_run_rollback_falls_back_to_script_without_sidecar(self) -> None:
        script = Path(self._tmp.name) / "F03_x.ps1"
        script.write_text("Write-Host hi", encoding="utf-8")
        with patch("fixes.engine.run_powershell") as ps:
            ps.return_value.ok = True
            ps.return_value.stdout = "done"
            ps.return_value.stderr = ""
            ok, message = run_rollback(str(script))
        self.assertTrue(ok)
        self.assertEqual(message, "done")
        ps.assert_called_once()


if __name__ == "__main__":
    unittest.main()
