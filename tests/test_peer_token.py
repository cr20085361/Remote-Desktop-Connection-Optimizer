"""双端令牌：可设置、格式校验、服务端按令牌放行。"""

from __future__ import annotations

import socket
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import core.settings as settings
from core.models import NetcheckState, Snapshot
from peer import server


def _fake_keyring(store: dict) -> types.ModuleType:
    mod = types.ModuleType("keyring")
    mod.get_password = lambda service, name: store.get((service, name))
    mod.set_password = lambda service, name, value: store.__setitem__((service, name), value)
    mod.delete_password = lambda service, name: store.pop((service, name), None)
    return mod


class TokenSettingsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store: dict = {}
        for p in (
            patch.dict(sys.modules, {"keyring": _fake_keyring(self.store)}),
            patch.object(settings, "SETTINGS_PATH", Path(self._tmp.name) / "settings.json"),
        ):
            p.start()
            self.addCleanup(p.stop)

    def test_token_is_generated_once_and_stable(self) -> None:
        first = settings.peer_token()
        self.assertTrue(settings.is_valid_peer_token(first))
        self.assertEqual(settings.peer_token(), first)

    def test_user_can_paste_peer_token(self) -> None:
        settings.set_peer_token("shared-token-1234")
        self.assertEqual(settings.peer_token(), "shared-token-1234")

    def test_invalid_token_rejected(self) -> None:
        for bad in ("", "short", "has space in it!!", "x" * 65):
            with self.assertRaises(ValueError):
                settings.set_peer_token(bad)

    def test_file_fallback_survives_keyring_failure(self) -> None:
        broken = types.ModuleType("keyring")

        def boom(*_a, **_k):
            raise RuntimeError("no backend")

        broken.get_password = boom
        broken.set_password = boom
        with patch.dict(sys.modules, {"keyring": broken}):
            token = settings.peer_token()
            self.assertEqual(settings.peer_token(), token)  # 重启后不会换新令牌


class PeerServerAuthTest(unittest.TestCase):
    def test_snapshot_requires_matching_token(self) -> None:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        snap = Snapshot(ts=1.0, hostname="home", self_ip="100.1.1.1", netcheck=NetcheckState(global_v4="1.2.3.4"))
        server.set_latest(snap)
        with patch.object(server, "peer_token", return_value="shared-token-1234"):
            server.start_server(host="127.0.0.1", port=port)
            self.addCleanup(server.stop_server)
            ok = server.fetch_peer("127.0.0.1", "shared-token-1234", port)
            bad = server.fetch_peer("127.0.0.1", "wrong-token-99999", port)
        self.assertIsNotNone(ok)
        self.assertEqual(ok["global_v4"], "1.2.3.4")
        self.assertIsNone(bad)


if __name__ == "__main__":
    unittest.main()
