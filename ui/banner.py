"""执行修复后的常驻引导条。"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from ui.theme import ACCENT, TEXT


class GuideBanner(QFrame):
    retest_clicked = Signal()
    dismissed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("banner")
        self.setVisible(False)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 10, 16, 10)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setStyleSheet(f"color: {TEXT};")
        self.btn = QPushButton("我已完成，重新检测")
        self.btn.setObjectName("primary")
        hide = QPushButton("稍后")
        hide.setObjectName("ghost")
        row.addWidget(self.message, 1)
        row.addWidget(self.btn)
        row.addWidget(hide)
        self.btn.clicked.connect(self.retest_clicked.emit)
        hide.clicked.connect(self._hide)

    def show_message(self, text: str, *, action: str = "我已完成，重新检测") -> None:
        self.message.setText(text)
        self.btn.setText(action)
        self.btn.setEnabled(True)
        self.setVisible(True)

    def set_busy(self, text: str) -> None:
        self.message.setText(text)
        self.btn.setEnabled(False)
        self.setVisible(True)

    def _hide(self) -> None:
        self.setVisible(False)
        self.dismissed.emit()
