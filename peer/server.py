"""仅绑定 Tailscale 地址的快照 HTTP 端点。"""

from __future__ import annotations

import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from core.config import PEER_HTTP_PORT
from core.models import Snapshot
from core.settings import load_settings, peer_token
from probes.tailscale_probe import ip_v4

_latest: Optional[Snapshot] = None
_lock = threading.Lock()
_server: Optional[ThreadingHTTPServer] = None
_thread: Optional[threading.Thread] = None


def set_latest(snapshot: Snapshot) -> None:
    global _latest
    with _lock:
        _latest = snapshot


def get_latest() -> Optional[Snapshot]:
    with _lock:
        return _latest


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return

    def _unauthorized(self) -> None:
        self.send_response(401)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(b'{"error":"unauthorized"}')

    def _json(self, code: int, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        token = (parse_qs(parsed.query).get("token") or [""])[0]
        if not hmac.compare_digest(token.encode(), peer_token().encode()):
            self._unauthorized()
            return
        if parsed.path in ("/health", "/"):
            self._json(200, {"ok": True, "app": "RdpOptimizer"})
            return
        if parsed.path == "/snapshot":
            snap = get_latest()
            if not snap:
                self._json(404, {"error": "no snapshot yet"})
                return
            self._json(200, compact_snapshot(snap))
            return
        self._json(404, {"error": "not found"})


def compact_snapshot(snap: Snapshot) -> dict:
    return {
        "ts": snap.ts,
        "hostname": snap.hostname,
        "self_ip": snap.self_ip,
        "global_v4": snap.netcheck.global_v4,
        "preferred_derp": snap.netcheck.preferred_derp,
        "preferred_derp_code": snap.netcheck.preferred_derp_code,
        "preferred_derp_latency_ms": snap.netcheck.preferred_derp_latency_ms,
        "tun_up": snap.proxy.tun_up,
        "tun_ifaces": snap.proxy.tun_ifaces,
        "default_exit_iface": snap.route.default_exit_iface,
        "findings": [f.to_dict() for f in snap.findings],
    }


def start_server(*, host: Optional[str] = None, port: Optional[int] = None) -> tuple[str, int]:
    global _server, _thread
    bind = host or ip_v4() or "127.0.0.1"
    listen_port = int(port or load_settings().get("peer_port") or PEER_HTTP_PORT)
    if _server:
        return bind, int(_server.server_address[1])
    server = ThreadingHTTPServer((bind, listen_port), _Handler)
    _server = server

    def _run() -> None:
        server.serve_forever(poll_interval=0.5)

    _thread = threading.Thread(target=_run, name="rdpopt-http", daemon=True)
    _thread.start()
    return bind, listen_port


def stop_server() -> None:
    global _server, _thread
    if _server:
        _server.shutdown()
        _server.server_close()
    _server = None
    _thread = None


def fetch_peer(ip: str, token: str, port: int, timeout: float = 3.0) -> Optional[dict]:
    import urllib.error
    import urllib.request

    url = f"http://{ip}:{port}/snapshot?token={token}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
