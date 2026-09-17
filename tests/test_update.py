from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.update import (
    LATEST_JSON_URL,
    UpdateError,
    download_installer,
    format_size,
    installer_url,
    is_allowed_download_url,
    is_allowed_manifest_url,
    is_newer,
    parse_latest_json,
    parse_version,
)


def _info(**overrides):
    data = {
        "version": "1.5.0",
        "installer": "RdpOptimizer-Setup-1.5.0.exe",
        "sha256": "a" * 64,
        "size": 12,
        "notes": "test",
    }
    data.update(overrides)
    return parse_latest_json(data)


class VersionCompareTest(unittest.TestCase):
    def test_parse_and_strip_v(self) -> None:
        self.assertEqual(parse_version("v1.4.0"), (1, 4, 0))
        self.assertEqual(parse_version("1.5.0"), (1, 5, 0))
        with self.assertRaises(UpdateError):
            parse_version("1.5")

    def test_newer(self) -> None:
        self.assertTrue(is_newer("1.5.0", "1.4.0"))
        self.assertFalse(is_newer("1.4.0", "1.4.0"))
        self.assertFalse(is_newer("1.3.9", "1.4.0"))


class LatestJsonTest(unittest.TestCase):
    def test_parse_fixture_and_default_url(self) -> None:
        info = _info()
        self.assertEqual(info.version, "1.5.0")
        self.assertEqual(info.installer, "RdpOptimizer-Setup-1.5.0.exe")
        self.assertEqual(
            info.url,
            installer_url("1.5.0", "RdpOptimizer-Setup-1.5.0.exe"),
        )
        self.assertTrue(is_allowed_download_url(info.url))

    def test_rejects_foreign_url(self) -> None:
        with self.assertRaises(UpdateError):
            _info(url="https://evil.example/RdpOptimizer-Setup-1.5.0.exe")
        with self.assertRaises(UpdateError):
            _info(url="https://github.com/other/other/releases/latest/download/RdpOptimizer-Setup-1.5.0.exe")

    def test_rejects_name_mismatch(self) -> None:
        with self.assertRaises(UpdateError):
            _info(installer="RdpOptimizer-Setup-1.4.0.exe")
        with self.assertRaises(UpdateError):
            _info(installer="setup.exe")
        with self.assertRaises(UpdateError):
            _info(sha256="not-a-hash")

    def test_manifest_url_is_this_repo(self) -> None:
        self.assertTrue(is_allowed_manifest_url(LATEST_JSON_URL))
        self.assertFalse(
            is_allowed_manifest_url(
                "https://github.com/other/other/releases/latest/download/latest.json"
            )
        )

    def test_format_size(self) -> None:
        self.assertEqual(format_size(0), "未知大小")
        self.assertIn("MB", format_size(5 * 1024 * 1024))


class DownloadHashTest(unittest.TestCase):
    def test_hash_mismatch_deletes_file(self) -> None:
        payload = b"hello-world"
        digest = hashlib.sha256(payload).hexdigest()
        info = _info(sha256="b" * 64, size=len(payload))

        class _Resp:
            status_code = 200

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def iter_content(self, _size):
                yield payload

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            with patch("requests.get", return_value=_Resp()):
                with self.assertRaises(UpdateError):
                    download_installer(info, dest)
            leftover = list(dest.glob("*.exe"))
            self.assertEqual(leftover, [])

        info_ok = _info(sha256=digest, size=len(payload))
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            with patch("requests.get", return_value=_Resp()):
                path = download_installer(info_ok, dest)
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_bytes(), payload)

    def test_rejects_download_url_not_this_repo(self) -> None:
        info = _info()
        bad = info.__class__(
            version=info.version,
            installer=info.installer,
            sha256=info.sha256,
            size=info.size,
            notes=info.notes,
            url="https://example.com/RdpOptimizer-Setup-1.5.0.exe",
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UpdateError):
                download_installer(bad, Path(tmp))


if __name__ == "__main__":
    unittest.main()
