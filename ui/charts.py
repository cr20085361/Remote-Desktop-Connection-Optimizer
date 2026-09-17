"""延迟曲线，横轴为真实时钟。"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from core.models import Snapshot
from core.store import HistoryStore
from ui.theme import MUTED, PANEL


def _series_name(peer) -> str:
    host = peer.hostname or "未命名"
    parts = (peer.ip or "").split(".")
    if len(parts) == 4:
        return f"{host} ({'.'.join(parts[-2:])})"
    return f"{host} ({peer.ip})" if peer.ip else host


class RttChart(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._plot = None
        lay = QVBoxLayout(self)
        self.caption = QLabel("各电脑往返时间（真实时钟）")
        self.caption.setObjectName("eyebrow")
        lay.addWidget(self.caption)
        try:
            import os

            os.environ.setdefault("QT_API", "pyside6")
            import pyqtgraph as pg

            pg.setConfigOptions(antialias=True, background="#0E0D0B", foreground="#F3EDE2")
            try:
                from pyqtgraph.graphicsItems.DateAxisItem import DateAxisItem
            except ImportError:
                DateAxisItem = getattr(pg, "DateAxisItem", None)
            axis_items = {"bottom": DateAxisItem(orientation="bottom")} if DateAxisItem else None
            plot = pg.PlotWidget(axisItems=axis_items) if axis_items else pg.PlotWidget()
            plot.showGrid(x=True, y=True, alpha=0.15)
            plot.setLabel("left", "毫秒")
            plot.addLegend(offset=(8, 8))
            lay.addWidget(plot)
            self._plot = plot
        except Exception:
            lay.addWidget(QLabel("曲线组件未就绪"))

    def update_snapshot(self, snap: Snapshot, *, hide_when_empty: bool = True) -> None:
        if self._plot is None:
            return
        self._plot.clear()
        store = HistoryStore()
        colors = ["#C4A574", "#6FAF8A", "#D85A4A", "#E08A3C", "#8AA0B3"]
        drawn = 0
        for i, peer in enumerate(snap.online_peers()[:5]):
            rows = store.series(peer.hostname or peer.ip)
            xs = [r["ts"] for r in rows if r.get("rtt_ms") is not None]
            ys = [r["rtt_ms"] for r in rows if r.get("rtt_ms") is not None]
            if len(xs) < 1:
                if peer.ping_rtt_ms is not None:
                    xs = [snap.ts or datetime.now().timestamp()]
                    ys = [peer.ping_rtt_ms]
                else:
                    continue
            self._plot.plot(xs, ys, pen=colors[i % len(colors)], name=_series_name(peer))
            drawn += 1
        if hide_when_empty:
            self.setVisible(drawn > 0)
        else:
            self.setVisible(True)
        if drawn:
            self.caption.setText("各电脑往返时间（横轴是钟表时间，单位毫秒）")
        else:
            self.caption.setText("还没有延迟曲线。检测完成后会出现。")
