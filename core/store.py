"""SQLite 时序存储。"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from core.config import DB_PATH, ensure_app_dirs
from core.models import Snapshot


class HistoryStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        ensure_app_dirs()
        self.path = Path(path or DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS samples (
                    ts REAL NOT NULL,
                    peer TEXT NOT NULL,
                    rtt_ms REAL,
                    jitter_ms REAL,
                    loss_pct REAL,
                    direct INTEGER,
                    derp TEXT,
                    global_v4 TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_samples_ts ON samples(ts);
                CREATE INDEX IF NOT EXISTS idx_samples_peer ON samples(peer, ts);
                CREATE TABLE IF NOT EXISTS snapshots (
                    ts REAL PRIMARY KEY,
                    json TEXT NOT NULL
                );
                """
            )

    def save_snapshot(self, snapshot: Snapshot, *, keep_json: bool = True) -> None:
        ts = snapshot.ts or time.time()
        with self._connect() as conn:
            if keep_json:
                conn.execute(
                    "INSERT OR REPLACE INTO snapshots(ts, json) VALUES(?, ?)",
                    (ts, json.dumps(snapshot.to_dict(), ensure_ascii=False)),
                )
            for peer in snapshot.peers:
                if peer.is_self:
                    continue
                conn.execute(
                    """
                    INSERT INTO samples(ts, peer, rtt_ms, jitter_ms, loss_pct, direct, derp, global_v4)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ts,
                        peer.hostname or peer.ip,
                        peer.ping_rtt_ms,
                        peer.ping_jitter_ms,
                        peer.ping_loss_pct,
                        1 if peer.is_direct else 0,
                        peer.relay,
                        snapshot.netcheck.global_v4,
                    ),
                )
            conn.execute("DELETE FROM samples WHERE ts < ?", (ts - 86400,))
            conn.execute("DELETE FROM snapshots WHERE ts < ?", (ts - 86400,))

    def series(self, peer: str, *, since_s: float = 3600) -> list[dict[str, Any]]:
        cutoff = time.time() - since_s
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ts, rtt_ms, jitter_ms, loss_pct, direct, derp
                FROM samples WHERE peer = ? AND ts >= ? ORDER BY ts
                """,
                (peer, cutoff),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_snapshot(self) -> Optional[Snapshot]:
        with self._connect() as conn:
            row = conn.execute("SELECT json FROM snapshots ORDER BY ts DESC LIMIT 1").fetchone()
        if not row:
            return None
        return Snapshot.from_dict(json.loads(row["json"]))
