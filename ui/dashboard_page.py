"""仪表盘：出口告警、拓扑、RTT 曲线。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from core.models import Snapshot
from core.store import HistoryStore
from ui.theme import AMBER, DANGER, MUTED, OK
from ui.topology import TopologyView


def _card(title: str, value: str, sub: str = "", danger: bool = False) -> QFrame:
    box = QFrame()
    box.setObjectName("cardDanger" if danger else "card")
    lay = QVBoxLayout(box)
    eyebrow = QLabel(title.upper())
    eyebrow.setObjectName("eyebrow")
    v = QLabel(value)
    v.setStyleSheet(f"font-size:22px; font-weight:700; color:{DANGER if danger else AMBER};")
    v.setWordWrap(True)
    s = QLabel(sub)
    s.setStyleSheet(f"color:{MUTED};")
    s.setWordWrap(True)
    lay.addWidget(eyebrow)
    lay.addWidget(v)
    lay.addWidget(s)
    return box


class DashboardPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.cards = QHBoxLayout()
        self.topo = TopologyView()
        self.plot_host = QFrame()
        self.plot_host.setObjectName("card")
        self.plot_layout = QVBoxLayout(self.plot_host)
        self.plot_label = QLabel("RTT 时序（最近 1 小时）")
        self.plot_layout.addWidget(self.plot_label)
        self._plot = None
        self._init_plot()

        root = QVBoxLayout(self)
        root.addLayout(self.cards)
        split = QHBoxLayout()
        split.addWidget(self.topo, 3)
        split.addWidget(self.plot_host, 2)
        root.addLayout(split, 1)
        self._placeholder_cards()

    def _init_plot(self) -> None:
        try:
            import os

            os.environ.setdefault("QT_API", "pyside6")
            import pyqtgraph as pg

            pg.setConfigOptions(antialias=True, background="#0b1116", foreground="#E7EDF3")
            plot = pg.PlotWidget()
            plot.showGrid(x=True, y=True, alpha=0.2)
            plot.setLabel("left", "ms")
            self.plot_layout.addWidget(plot)
            self._plot = plot
        except Exception:
            fallback = QLabel("未安装 pyqtgraph，曲线不可用")
            self.plot_layout.addWidget(fallback)

    def _placeholder_cards(self) -> None:
        while self.cards.count():
            item = self.cards.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for title, value in (("公网出口", "采集中…"), ("最近 DERP", "—"), ("在线节点", "—"), ("命中规则", "—")):
            self.cards.addWidget(_card(title, value))

    def update_snapshot(self, snap: Snapshot) -> None:
        while self.cards.count():
            item = self.cards.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        hijack = any(f.id == "R01" for f in snap.findings)
        derp_ms = snap.netcheck.preferred_derp_latency_ms
        self.cards.addWidget(
            _card(
                "公网出口 IP",
                snap.netcheck.global_v4 or "未知",
                f"端口 {snap.netcheck.global_v4_port or '-'}  ·  Tun={'开' if snap.proxy.tun_up else '关'}",
                danger=hijack,
            )
        )
        self.cards.addWidget(
            _card(
                "最近 DERP",
                snap.netcheck.preferred_derp or snap.netcheck.preferred_derp_code or "未知",
                f"{derp_ms:.0f} ms" if derp_ms is not None else "",
                danger=bool(derp_ms and derp_ms > 200),
            )
        )
        online = len(snap.online_peers())
        direct = sum(1 for p in snap.online_peers() if p.is_direct or (p.cur_addr and not p.relay))
        self.cards.addWidget(_card("在线节点", f"{online}", f"直连 {direct} · 本机 {snap.self_ip}"))
        crit = sum(1 for f in snap.findings if f.severity in {"critical", "high"})
        self.cards.addWidget(
            _card("诊断命中", str(len(snap.findings)), f"高危 {crit} 项", danger=crit > 0)
        )
        self.topo.render_snapshot(snap)
        self._update_plot(snap)

    def _update_plot(self, snap: Snapshot) -> None:
        if self._plot is None:
            return
        self._plot.clear()
        store = HistoryStore()
        colors = ["#6EC9E8", "#E8A838", "#3DDC97", "#FF5C5C", "#C792EA"]
        for i, peer in enumerate(snap.online_peers()[:5]):
            rows = store.series(peer.hostname or peer.ip)
            if not rows:
                continue
            xs = [r["ts"] for r in rows]
            ys = [r["rtt_ms"] or 0 for r in rows]
            if xs:
                base = xs[0]
                xs = [x - base for x in xs]
            self._plot.plot(xs, ys, pen=colors[i % len(colors)], name=peer.hostname)
        self.plot_label.setText("RTT 时序（秒相对轴，最近 1 小时）")
