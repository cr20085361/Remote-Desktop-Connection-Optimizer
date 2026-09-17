"""评分圆环与白话问题卡片。"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from rules.plain import IssueCard
from ui.theme import ACCENT, DANGER, HIGH, MUTED, OK, SEVERITY_COLOR, TEXT, WARN


class ScoreRing(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._score = 0
        self._color = DANGER
        self.setFixedSize(132, 132)

    def set_score(self, score: int, band: str) -> None:
        self._score = max(0, min(100, int(score)))
        self._color = { "优秀": OK, "良好": ACCENT, "需要处理": HIGH, "严重": DANGER }.get(band, WARN)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(12, 12, 108, 108)
        track = QPen(QColor("#3A352C"), 10)
        track.setCapStyle(Qt.RoundCap)
        painter.setPen(track)
        painter.drawArc(rect, 0, 360 * 16)
        glow = QPen(QColor(self._color), 10)
        glow.setCapStyle(Qt.RoundCap)
        painter.setPen(glow)
        span = int(360 * 16 * (self._score / 100.0))
        painter.drawArc(rect, 90 * 16, -span)
        painter.setPen(QColor(TEXT))
        painter.setFont(QFont("Palatino Linotype", 28, QFont.DemiBold))
        painter.drawText(self.rect().adjusted(0, -6, 0, 0), Qt.AlignCenter, str(self._score))


class IssueCardWidget(QFrame):
    fix_clicked = Signal(str)
    manual_clicked = Signal(object)
    ask_ai = Signal(str)

    def __init__(self, card: IssueCard, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("issueCard")
        self.card = card
        color = SEVERITY_COLOR.get(card.severity, MUTED)
        self.setStyleSheet(
            f"QFrame#issueCard {{ border-left: 4px solid {color}; padding-left: 4px; }}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(6)

        head = QHBoxLayout()
        badge = QLabel(card.severity_label)
        badge.setObjectName("eyebrow")
        badge.setStyleSheet(f"color: {color}; font-weight: 600;")
        head.addWidget(badge)
        head.addStretch()
        root.addLayout(head)

        title = QLabel(card.title)
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        root.addWidget(title)

        meaning = QLabel(card.meaning)
        meaning.setObjectName("body")
        meaning.setWordWrap(True)
        root.addWidget(meaning)

        impact = QLabel("对你的影响：" + card.impact)
        impact.setObjectName("muted")
        impact.setWordWrap(True)
        root.addWidget(impact)

        self.why = QLabel(card.expected_gain + "\n\n原始探测：" + card.evidence)
        self.why.setObjectName("muted")
        self.why.setWordWrap(True)
        self.why.setVisible(False)
        root.addWidget(self.why)

        actions = QHBoxLayout()
        if card.auto_fix and card.primary_fix:
            btn = QPushButton("修复这个")
            btn.setObjectName("primary")
            btn.clicked.connect(lambda: self.fix_clicked.emit(card.primary_fix))
            actions.addWidget(btn)
        else:
            btn = QPushButton("怎么手动处理")
            btn.clicked.connect(lambda: self.manual_clicked.emit(card))
            actions.addWidget(btn)
        why_btn = QPushButton("为什么")
        why_btn.setObjectName("ghost")
        why_btn.clicked.connect(lambda: self.why.setVisible(not self.why.isVisible()))
        actions.addWidget(why_btn)
        ask_btn = QPushButton("问 AI")
        ask_btn.setObjectName("ghost")
        ask_btn.clicked.connect(self._ask_ai)
        actions.addWidget(ask_btn)
        actions.addStretch()
        root.addLayout(actions)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

    def _ask_ai(self) -> None:
        card = self.card
        self.ask_ai.emit(
            "请详细解释这个问题，用白话说明它是什么、对远程桌面有什么影响、下一步该怎么做。\n"
            f"标题：{card.title}\n说明：{card.meaning}\n影响：{card.impact}\n原始探测：{card.evidence}"
        )
