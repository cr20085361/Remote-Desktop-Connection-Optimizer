"""后台采集线程。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QThread, Signal

from core.collector import collect_snapshot
from core.models import Snapshot
from core.settings import load_settings, peer_token
from core.store import HistoryStore
from fixes.base import FixResult
from fixes.engine import run_fix
from peer.server import fetch_peer, set_latest


class CollectorThread(QThread):
    snapshot_ready = Signal(object)
    progress = Signal(int, int, str)
    failed = Signal(str)

    def __init__(self, *, ping_peers: bool = True, probe_pmtu: bool = False) -> None:
        super().__init__()
        self.ping_peers = ping_peers
        self.probe_pmtu = probe_pmtu

    def run(self) -> None:
        try:
            settings = load_settings()
            probe_pmtu = bool(settings.get("probe_pmtu") or self.probe_pmtu)

            def on_partial(snap: Snapshot) -> None:
                if settings.get("v2rayn_path") and not snap.proxy.v2rayn_path:
                    snap.proxy.v2rayn_path = str(settings["v2rayn_path"])
                self.snapshot_ready.emit(snap)

            snap: Snapshot = collect_snapshot(
                ping_count=int(settings.get("ping_count") or 2),
                ping_peers=self.ping_peers,
                probe_links=probe_pmtu,
                probe_pmtu=probe_pmtu,
                include_rdp_events=False,
                progress=lambda i, t, label: self.progress.emit(i, t, label),
                on_snapshot=on_partial,
            )
            if settings.get("v2rayn_path") and not snap.proxy.v2rayn_path:
                snap.proxy.v2rayn_path = str(settings["v2rayn_path"])
            token = peer_token()
            port = int(settings.get("peer_port") or 18765)
            targets = snap.online_peers()
            if targets:
                # 未装本工具的对端会一直超时，并行 + 短超时，别拖慢整轮检测
                with ThreadPoolExecutor(max_workers=min(len(targets), 6)) as pool:
                    remotes = list(pool.map(lambda p: fetch_peer(p.ip, token, port, timeout=1.5), targets))
                for peer, remote in zip(targets, remotes):
                    if remote:
                        peer.remote_snapshot = remote
            set_latest(snap)
            HistoryStore().save_snapshot(snap)
            self.snapshot_ready.emit(snap)
        except Exception as exc:
            self.failed.emit(str(exc))


class FixThread(QThread):
    """修复动作可能要跑 20 秒的 PowerShell，放到后台，别卡住界面。"""

    done = Signal(object)

    def __init__(self, fix_id: str, snapshot: Snapshot, parent=None) -> None:
        super().__init__(parent)
        self._fix_id = fix_id
        self._snapshot = snapshot

    def run(self) -> None:
        try:
            result = run_fix(self._fix_id, self._snapshot, confirmed=True)
        except Exception as exc:
            result = FixResult(False, f"修复过程出错：{exc}")
        self.done.emit(result)
