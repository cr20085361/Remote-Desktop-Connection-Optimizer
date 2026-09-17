"""主窗口右侧可收起的助理抽屉。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QToolButton, QWidget

from core.settings import load_settings, save_settings
from ui.chat_panel import ChatPanel

OPEN_WIDTH = 400
STRIP_WIDTH = 44


class AssistantDrawer(QWidget):
    settings_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.chat = ChatPanel()
        self.chat.settings_requested.connect(self.settings_requested.emit)
        self.chat.collapse_requested.connect(lambda: self.set_open(False))

        self.strip = QToolButton()
        self.strip.setObjectName("drawerStrip")
        self.strip.setText("助\n理")
        self.strip.setToolTip("展开助理")
        self.strip.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.strip.clicked.connect(lambda: self.set_open(True))

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.chat, 1)
        lay.addWidget(self.strip)
        opened = bool(load_settings().get("assistant_open", True))
        self.set_open(opened, persist=False)

    def set_open(self, on: bool, *, persist: bool = True) -> None:
        self._open = bool(on)
        self.chat.setVisible(self._open)
        self.strip.setVisible(not self._open)
        self.setFixedWidth(OPEN_WIDTH if self._open else STRIP_WIDTH)
        if persist:
            save_settings({"assistant_open": self._open})
        if self._open:
            self.chat.refresh_status()

    def is_open(self) -> bool:
        return getattr(self, "_open", True)

    def ask(self, text: str) -> None:
        self.set_open(True)
        self.chat.send(text)
