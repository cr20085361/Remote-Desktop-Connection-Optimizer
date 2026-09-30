"""技术细节：四个子标签，一次只看一块。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.config import ROLLBACK_DIR
from core.models import Snapshot
from fixes.engine import run_rollback
from rules.plain import SESSION_HEADERS, issue_cards, session_rows
from ui.charts import RttChart
from ui.theme import MUTED, PAGE_MARGIN, SEVERITY_COLOR
from ui.topology import TopologyView


class TechPage(QWidget):
    ask_ai = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._snap: Snapshot | None = None
        self.topo = TopologyView()
        self.chart = RttChart()
        self.hide_offline = QPushButton("隐藏离线电脑")
        self.hide_offline.setCheckable(True)
        self.hide_offline.setChecked(True)

        title = QLabel("通路对照")
        title.setObjectName("cardTitle")
        hint = QLabel("一次只看一块。结论请回「体检」。")
        hint.setObjectName("muted")
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(title)
        titles.addWidget(hint)
        head.addLayout(titles, 1)
        head.addWidget(self.hide_offline, 0, Qt.AlignTop)

        topo_card = QFrame()
        topo_card.setObjectName("card")
        topo_l = QVBoxLayout(topo_card)
        topo_l.setContentsMargins(12, 12, 12, 12)
        topo_cap = QLabel("电脑怎么连着")
        topo_cap.setObjectName("eyebrow")
        topo_l.addWidget(topo_cap)
        topo_l.addWidget(self.topo, 1)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["问题", "程度"])
        self.tree.setColumnWidth(0, 320)
        self.tree.setRootIsDecorated(False)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("点左侧一条，这里显示这条的原始探测。")
        self.btn_ask_item = QPushButton("问 AI")
        self.btn_ask_item.setObjectName("ghost")
        detail_box = QWidget()
        detail_l = QVBoxLayout(detail_box)
        detail_l.setContentsMargins(0, 0, 0, 0)
        detail_l.setSpacing(6)
        detail_l.addWidget(self.detail, 1)
        ask_row = QHBoxLayout()
        ask_row.addStretch()
        ask_row.addWidget(self.btn_ask_item)
        detail_l.addLayout(ask_row)
        evidence = QSplitter(Qt.Horizontal)
        evidence.addWidget(self.tree)
        evidence.addWidget(detail_box)
        evidence.setStretchFactor(0, 2)
        evidence.setStretchFactor(1, 3)

        self.sessions = QTableWidget(0, len(SESSION_HEADERS))
        self.sessions.setHorizontalHeaderLabels(SESSION_HEADERS)
        self.sessions.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.sessions.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.sessions.verticalHeader().setVisible(False)
        self.sessions.horizontalHeader().setStretchLastSection(True)
        self.sessions_empty = QLabel("现在没有正在进行的远程桌面连接。连上后这里会显示走的是 UDP 还是 TCP、当前延迟和丢包。")
        self.sessions_empty.setObjectName("muted")
        self.sessions_empty.setWordWrap(True)
        self.sessions_empty.setAlignment(Qt.AlignCenter)
        sess_inner = QWidget()
        sess_l = QVBoxLayout(sess_inner)
        sess_l.setContentsMargins(12, 12, 12, 12)
        sess_l.addWidget(self.sessions_empty)
        sess_l.addWidget(self.sessions, 1)

        self.rollbacks = QListWidget()
        self.rollback_empty = QLabel("还没有可撤销的修改。")
        self.rollback_empty.setObjectName("muted")
        self.rollback_empty.setAlignment(Qt.AlignCenter)
        self.btn_rollback = QPushButton("撤销选中的那次修改")
        self.btn_refresh = QPushButton("刷新")
        rb_btns = QHBoxLayout()
        rb_btns.addStretch()
        rb_btns.addWidget(self.btn_refresh)
        rb_btns.addWidget(self.btn_rollback)
        rb_inner = QWidget()
        rb_l = QVBoxLayout(rb_inner)
        rb_l.setContentsMargins(12, 12, 12, 12)
        rb_l.addWidget(self.rollback_empty)
        rb_l.addWidget(self.rollbacks, 1)
        rb_l.addLayout(rb_btns)

        self.tabs = QTabWidget()
        self.tabs.addTab(topo_card, "关系图")
        self.tabs.addTab(self.chart, "延迟曲线")
        self.tabs.addTab(sess_inner, "远程桌面")
        self.tabs.addTab(evidence, "问题记录")
        self.tabs.addTab(rb_inner, "撤销")

        root = QVBoxLayout(self)
        root.setContentsMargins(PAGE_MARGIN, 12, PAGE_MARGIN, 12)
        root.setSpacing(10)
        root.addLayout(head)
        root.addWidget(self.tabs, 1)

        self.tree.currentItemChanged.connect(self._show_detail)
        self.hide_offline.toggled.connect(self._toggle_offline)
        self.btn_refresh.clicked.connect(self._load_rollbacks)
        self.btn_rollback.clicked.connect(self._run_rollback)
        self.btn_ask_item.clicked.connect(self._ask_selected)
        self._load_rollbacks()

    def update_snapshot(self, snap: Snapshot) -> None:
        self._snap = snap
        self.topo.hide_offline = self.hide_offline.isChecked()
        self.topo.render_snapshot(snap)
        self.chart.update_snapshot(snap, hide_when_empty=False)
        rows = session_rows(snap)
        self.sessions.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                self.sessions.setItem(r, c, QTableWidgetItem(text))
        self.sessions.setVisible(bool(rows))
        self.sessions_empty.setVisible(not rows)
        self.tree.clear()
        for card in issue_cards(snap):
            item = QTreeWidgetItem([card.title, card.severity_label])
            item.setData(0, Qt.UserRole, card.evidence or "没有额外原始记录。")
            item.setData(1, Qt.UserRole, card.title)
            item.setForeground(1, QColor(SEVERITY_COLOR.get(card.severity, MUTED)))
            self.tree.addTopLevelItem(item)
        if snap.errors:
            err = QTreeWidgetItem(["采集时有告警", "提示"])
            err.setData(0, Qt.UserRole, "\n".join(snap.errors))
            err.setData(1, Qt.UserRole, "采集告警")
            self.tree.addTopLevelItem(err)
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        else:
            self.detail.setPlainText("这一轮没有需要对照的问题。")
        self._load_rollbacks()

    def _show_detail(self, current, _prev) -> None:
        if current:
            self.detail.setPlainText(str(current.data(0, Qt.UserRole) or ""))

    def _ask_selected(self) -> None:
        item = self.tree.currentItem()
        if not item:
            return
        title = str(item.data(1, Qt.UserRole) or item.text(0))
        evidence = str(item.data(0, Qt.UserRole) or "")
        self.ask_ai.emit(
            f"请详细解释这条探测记录，用白话说明它是什么、对远程桌面有什么影响、下一步该怎么做。\n"
            f"标题：{title}\n原始记录：{evidence}"
        )

    def _toggle_offline(self, hide: bool) -> None:
        self.topo.hide_offline = hide
        if self._snap:
            self.topo.render_snapshot(self._snap)

    def _load_rollbacks(self) -> None:
        self.rollbacks.clear()
        items: list[str] = []
        if ROLLBACK_DIR.exists():
            items = [str(path) for path in sorted(ROLLBACK_DIR.glob("*.ps1"), reverse=True)[:40]]
        for path in items:
            self.rollbacks.addItem(path)
        has = bool(items)
        self.rollbacks.setVisible(has)
        self.rollback_empty.setVisible(not has)
        self.btn_rollback.setEnabled(has)

    def _run_rollback(self) -> None:
        item = self.rollbacks.currentItem()
        if not item:
            return
        path = item.text()
        if QMessageBox.question(self, "撤销", f"要撤销这份修改吗？\n{path}") != QMessageBox.Yes:
            return
        _ok, message = run_rollback(path)
        QMessageBox.information(self, "撤销结果", message)
        self._load_rollbacks()
