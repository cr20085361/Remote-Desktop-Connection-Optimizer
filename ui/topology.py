"""节点关系图：白话标签、错开文字、同名加后缀、离线可隐藏。"""

from __future__ import annotations

import math
from collections import Counter

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from core.models import PeerState, Snapshot
from rules.plain import is_relaying, region_zh
from ui.theme import ACCENT, BG, DANGER, HIGH, MUTED, OK, TEXT


def display_name(peer: PeerState, counts: Counter) -> str:
    name = peer.hostname or peer.ip or "未命名"
    if counts.get(peer.hostname or "", 0) > 1:
        return f"{name} ({peer.ip})"
    return name


def path_label(peer: PeerState) -> str:
    rtt = peer.ping_rtt_ms
    rtt_txt = f"{rtt:.0f}ms" if rtt is not None else "未测到"
    if is_relaying(peer):
        place = region_zh(peer.relay, peer.ping_via)
        grade = "很差" if rtt is not None and rtt > 300 else "偏慢"
        return f"经{place}中转 · {rtt_txt} · {grade}"
    if rtt is not None and rtt > 120:
        return f"直连 · {rtt_txt} · 偏慢"
    if rtt is not None:
        return f"直连 · {rtt_txt} · 良好"
    return "直连"


class TopologyView(QGraphicsView):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setBackgroundBrush(QBrush(QColor(BG)))
        self.setFrameShape(QGraphicsView.NoFrame)
        self.hide_offline = True

    def render_snapshot(self, snap: Snapshot) -> None:
        self._scene.clear()
        peers = [p for p in snap.peers if not p.is_self]
        if self.hide_offline:
            visible = [p for p in peers if p.online] or peers
        else:
            visible = peers
        names = Counter((p.hostname or "") for p in visible)
        self_name = snap.hostname or "本机"
        cx, cy = 340.0, 220.0
        radius = 155.0
        self._node(QPointF(cx, cy), self_name, snap.self_ip or "", ACCENT, True)
        n = max(len(visible), 1)
        for i, peer in enumerate(visible):
            angle = -math.pi / 2 + (2 * math.pi * i / n)
            pos = QPointF(cx + radius * math.cos(angle) * 1.55, cy + radius * math.sin(angle))
            color = OK if peer.online else MUTED
            if peer.online and is_relaying(peer):
                color = DANGER
            elif peer.online and peer.ping_rtt_ms and peer.ping_rtt_ms > 120:
                color = HIGH
            self._node(pos, display_name(peer, names), peer.ip, color, peer.online)
            if peer.online:
                relaying = is_relaying(peer)
                pen = QPen(QColor(DANGER if relaying else OK), 2, Qt.DashLine if relaying else Qt.SolidLine)
                self._scene.addLine(cx, cy, pos.x(), pos.y(), pen)
                mid = QPointF((cx + pos.x()) / 2, (cy + pos.y()) / 2)
                dx, dy = pos.x() - cx, pos.y() - cy
                length = math.hypot(dx, dy) or 1.0
                # 沿线法线方向错开，避免压在连线上
                ox, oy = -dy / length * 16, dx / length * 16
                label = path_label(peer)
                text = self._scene.addText(label, QFont("Microsoft YaHei UI", 8))
                text.setDefaultTextColor(QColor(TEXT))
                br = text.boundingRect()
                text.setPos(mid.x() + ox - br.width() / 2, mid.y() + oy - br.height() / 2)
            remote = peer.remote_snapshot or {}
            if remote.get("global_v4") or remote.get("tun_up"):
                extra = self._scene.addText(
                    f"对端对外地址 {remote.get('global_v4', '?')}"
                    + (" · 翻墙全局接管开着" if remote.get("tun_up") else ""),
                    QFont("Microsoft YaHei UI", 8),
                )
                extra.setDefaultTextColor(QColor(HIGH))
                extra.setPos(pos.x() - 80, pos.y() + 32)
        self._scene.setSceneRect(QRectF(0, 0, 680, 460))

    def _node(self, pos: QPointF, name: str, ip: str, color: str, online: bool) -> None:
        radius = 16 if online else 10
        self._scene.addEllipse(
            pos.x() - radius,
            pos.y() - radius,
            radius * 2,
            radius * 2,
            QPen(QColor(color), 2),
            QBrush(QColor(color).darker(165)),
        )
        label = self._scene.addText(f"{name}\n{ip}", QFont("Microsoft YaHei UI", 8))
        label.setDefaultTextColor(QColor(TEXT if online else MUTED))
        br = label.boundingRect()
        if br.width() > 150:
            label.setTextWidth(150)
            br = label.boundingRect()
        label.setPos(pos.x() - br.width() / 2, pos.y() + radius + 4)
