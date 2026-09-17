"""全局 DeepSeek 流式对话。"""

from __future__ import annotations

import json

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.models import Snapshot
from core.settings import get_api_key, load_settings
from ui.theme import OK


class ChatThread(QThread):
    chunk = Signal(str, str)
    failed = Signal(str)
    done = Signal()

    def __init__(self, messages: list[dict[str, str]], parent=None) -> None:
        super().__init__(parent)
        self._messages = messages

    def run(self) -> None:
        try:
            from ai.advisor import stream_chat
            from ai.catalog import model_uses_thinking

            settings = load_settings()
            key = get_api_key()
            model = str(settings.get("ai_model") or "deepseek-flash")
            for kind, text in stream_chat(
                base_url=str(settings.get("ai_base_url") or ""),
                model=model,
                api_key=key,
                messages=self._messages,
                thinking=model_uses_thinking(model),
            ):
                if kind == "error":
                    self.failed.emit(text)
                    return
                self.chunk.emit(kind, text)
            self.done.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class UserBubble(QFrame):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.setObjectName("userBubble")
        body = QLabel(text)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.addWidget(body)
        self.setMaximumWidth(320)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Minimum)


class AssistantMessage(QFrame):
    content_fitted = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("botBubble")
        self._md = ""
        self._reason = ""
        self.think_btn = QToolButton()
        self.think_btn.setObjectName("fold")
        self.think_btn.setText("思考中")
        self.think_btn.setCheckable(True)
        self.think_btn.setVisible(False)
        self.think_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.think_btn.setArrowType(Qt.RightArrow)
        self.think_body = QLabel("")
        self.think_body.setObjectName("muted")
        self.think_body.setWordWrap(True)
        self.think_body.setVisible(False)
        self.think_btn.toggled.connect(self._toggle_think)
        self.view = QTextBrowser()
        self.view.setObjectName("mdView")
        self.view.setOpenExternalLinks(False)
        self.view.setOpenLinks(False)
        self.view.setReadOnly(True)
        self.view.setFrameShape(QFrame.NoFrame)
        self.view.setLineWrapMode(QTextBrowser.WidgetWidth)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.view.document().setDocumentMargin(4)
        self.view.setPlainText("正在写…")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(4)
        lay.addWidget(self.think_btn)
        lay.addWidget(self.think_body)
        lay.addWidget(self.view)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    def _toggle_think(self, on: bool) -> None:
        self.think_body.setVisible(on)
        self.think_btn.setArrowType(Qt.DownArrow if on else Qt.RightArrow)

    def append_reason(self, text: str) -> None:
        self._reason += text
        self.think_btn.setVisible(True)
        self.think_btn.setText("思考过程（默认可收起）")
        self.think_body.setText(self._reason[-1200:])

    def append_content(self, text: str) -> None:
        self._md += text
        self._render()

    def set_plain(self, text: str) -> None:
        self._md = text
        self.view.setPlainText(text)
        self._fit()

    def text(self) -> str:
        return self._md.strip()

    def _render(self) -> None:
        md = self._md or "正在写…"
        if hasattr(self.view, "setMarkdown"):
            self.view.setMarkdown(md)
        else:
            self.view.setPlainText(md)
        self._fit()

    def _fit(self) -> None:
        width = max(self.view.viewport().width(), self.width() - 24, 280)
        self.view.document().setTextWidth(width)
        height = max(int(self.view.document().size().height()) + 16, 36)
        if abs(self.view.height() - height) > 1:
            self.view.setFixedHeight(height)
            self.updateGeometry()
        self.content_fitted.emit()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit()


class ChatPanel(QFrame):
    settings_requested = Signal()
    collapse_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("chatPanel")
        self._snap: Snapshot | None = None
        self._history: list[dict[str, str]] = []
        self._thread: ChatThread | None = None
        self._bot: AssistantMessage | None = None

        self.status = QLabel("未接通")
        self.status.setObjectName("eyebrow")
        self.model_label = QLabel("DeepSeek")
        self.model_label.setObjectName("cardTitle")
        self.btn_status = QPushButton("去设置")
        self.btn_status.setObjectName("ghost")
        self.btn_status.clicked.connect(self.settings_requested.emit)
        self.btn_collapse = QPushButton("收起")
        self.btn_collapse.setObjectName("ghost")
        self.btn_collapse.clicked.connect(self.collapse_requested.emit)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(self.model_label)
        titles.addWidget(self.status)
        head.addLayout(titles, 1)
        head.addWidget(self.btn_status, 0, Qt.AlignTop)
        head.addWidget(self.btn_collapse, 0, Qt.AlignTop)

        self.btn_first = QPushButton("根据这次检测先说一遍")
        self.btn_first.setObjectName("primary")
        chips = QHBoxLayout()
        chips.setSpacing(6)
        for label, prompt in (
            ("为什么绕路", "这次为什么绕路？结合当前检测快照说明。"),
            ("要不要关接管", "该不该关掉全局接管？请给明确建议。"),
            ("解释评分", "用白话解释当前评分和最该先做的一件事。"),
        ):
            btn = QPushButton(label)
            btn.setObjectName("chip")
            btn.clicked.connect(lambda _=False, text=prompt: self.send(text))
            chips.addWidget(btn)
        chips.addStretch()

        self.log = QWidget()
        self.log.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.log_l = QVBoxLayout(self.log)
        self.log_l.setContentsMargins(4, 4, 4, 4)
        self.log_l.setSpacing(10)
        self.log_l.addStretch()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.log)

        self.input = QLineEdit()
        self.input.setPlaceholderText("继续追问…")
        self.btn_send = QPushButton("发送")
        self.btn_send.setObjectName("primary")
        row = QHBoxLayout()
        row.addWidget(self.input, 1)
        row.addWidget(self.btn_send)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        root.addLayout(head)
        root.addWidget(self.btn_first)
        root.addLayout(chips)
        root.addWidget(self.scroll, 1)
        root.addLayout(row)

        self.btn_first.clicked.connect(self._diagnose)
        self.btn_send.clicked.connect(self._send_input)
        self.input.returnPressed.connect(self._send_input)
        self.refresh_status()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(400, 640)

    def set_snapshot(self, snap: Snapshot) -> None:
        self._snap = snap

    def refresh_status(self) -> None:
        settings = load_settings()
        model = str(settings.get("ai_model") or "deepseek-flash")
        provider = "DeepSeek" if "deepseek" in str(settings.get("ai_base_url") or "").lower() else "模型"
        self.model_label.setText(f"{provider} · {model}")
        ready = bool(get_api_key())
        if ready:
            self.status.setText("已接通")
            self.status.setStyleSheet(f"color: {OK};")
            self.btn_status.setVisible(False)
        else:
            self.status.setText("还没填密钥")
            self.status.setStyleSheet("")
            self.btn_status.setText("去设置")
            self.btn_status.setVisible(True)
        busy = bool(self._thread and self._thread.isRunning())
        self.input.setEnabled(ready and not busy)
        self.btn_send.setEnabled(ready and not busy)
        self.btn_first.setEnabled(ready and not busy)

    def _diagnose(self) -> None:
        self.send("请根据当前检测快照，用白话说明最可能的卡顿原因，以及我下一步该做什么。")

    def _send_input(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.send(text)

    def send(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        if self._thread and self._thread.isRunning():
            return
        if not get_api_key():
            self.settings_requested.emit()
            return
        if not self._snap:
            self._add_note("请先点「重新检测」，有结果后我才能对着快照说话。")
            return
        self._insert(UserBubble(text), align_right=True)
        self._bot = AssistantMessage()
        self._insert(self._bot, align_right=False)
        self._history.append({"role": "user", "content": text})
        self._set_busy(True)
        self._thread = ChatThread(self._api_messages())
        self._thread.chunk.connect(self._on_chunk)
        self._thread.failed.connect(self._on_fail)
        self._thread.done.connect(self._on_done)
        self._thread.start()

    def _api_messages(self) -> list[dict[str, str]]:
        from ai.advisor import sanitize_snapshot
        from ai.prompt import CHAT_PROMPT

        snap_json = json.dumps(sanitize_snapshot(self._snap), ensure_ascii=False)[:12000] if self._snap else "{}"
        return [
            {"role": "system", "content": CHAT_PROMPT + "\n\n当前检测快照（已脱敏）：\n" + snap_json},
            *self._history,
        ]

    def _on_chunk(self, kind: str, text: str) -> None:
        if not self._bot:
            return
        if kind == "reasoning":
            self._bot.append_reason(text)
        elif kind == "content":
            self._bot.append_content(text)
        self._refresh_scroll_extent()
        self._scroll_bottom()

    def _on_fail(self, msg: str) -> None:
        if self._bot:
            self._bot.set_plain("没能问到模型：\n" + msg)
        self._set_busy(False)
        self.refresh_status()

    def _on_done(self) -> None:
        if self._bot:
            self._bot._fit()
            answer = self._bot.text()
            if answer:
                self._history.append({"role": "assistant", "content": answer})
        self._bot = None
        self._set_busy(False)
        self.refresh_status()
        self._refresh_scroll_extent()
        self._scroll_bottom()

    def _set_busy(self, busy: bool) -> None:
        ready = bool(get_api_key())
        self.btn_send.setEnabled(ready and not busy)
        self.btn_first.setEnabled(ready and not busy)
        self.input.setEnabled(ready and not busy)

    def _add_note(self, text: str) -> None:
        note = AssistantMessage()
        note.set_plain(text)
        self._insert(note, align_right=False)

    def _insert(self, widget: QWidget, *, align_right: bool) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if align_right:
            row.addStretch()
            row.addWidget(widget, 0)
        else:
            row.addWidget(widget, 1)
        holder = QWidget()
        holder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        holder.setLayout(row)
        if hasattr(widget, "content_fitted"):
            widget.content_fitted.connect(self._refresh_scroll_extent)
        self.log_l.insertWidget(self.log_l.count() - 1, holder)
        self._refresh_scroll_extent()
        QTimer.singleShot(0, self._refresh_scroll_extent)
        self._scroll_bottom()

    def _refresh_scroll_extent(self) -> None:
        if getattr(self, "_extent_busy", False):
            return
        self._extent_busy = True
        try:
            self.log_l.activate()
            for i in range(self.log_l.count()):
                item = self.log_l.itemAt(i)
                child = item.widget() if item else None
                if child is None:
                    continue
                inner = child.layout()
                if inner:
                    child.setMinimumHeight(inner.totalMinimumSize().height())
            needed = max(self.log_l.totalMinimumSize().height(), self.log_l.sizeHint().height(), 1)
            self.log.setMinimumHeight(needed)
        finally:
            self._extent_busy = False

    def _scroll_bottom(self) -> None:
        QTimer.singleShot(30, lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))
