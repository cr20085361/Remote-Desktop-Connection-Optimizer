"""诊断页：规则命中 + 可选 AI。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.models import Snapshot
from ui.theme import AMBER, DANGER, MUTED, OK

_COLOR = {
    "critical": DANGER,
    "high": AMBER,
    "medium": "#F0C14B",
    "low": MUTED,
    "info": OK,
}


class DiagnosePage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["规则", "级别", "结论", "建议修复"])
        self.tree.setColumnWidth(0, 70)
        self.tree.setColumnWidth(1, 80)
        self.tree.setColumnWidth(2, 520)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.ai_out = QPlainTextEdit()
        self.ai_out.setReadOnly(True)
        self.ai_out.setPlaceholderText("本地规则已足够给出修复项。可选：配置国内模型后点「让 AI 分析」。")
        self.btn_ai = QPushButton("让 AI 分析")
        self.btn_ai.setObjectName("primary")

        top = QVBoxLayout(self)
        head = QHBoxLayout()
        title = QLabel("诊断命中")
        title.setObjectName("appTitle")
        head.addWidget(title)
        head.addStretch()
        head.addWidget(self.btn_ai)
        top.addLayout(head)
        top.addWidget(self.tree, 3)
        top.addWidget(QLabel("证据"))
        top.addWidget(self.detail, 2)
        top.addWidget(QLabel("AI 顾问（可选）"))
        top.addWidget(self.ai_out, 2)
        self.tree.currentItemChanged.connect(self._show_detail)
        self._snap: Snapshot | None = None

    def update_snapshot(self, snap: Snapshot) -> None:
        self._snap = snap
        self.tree.clear()
        for finding in snap.findings:
            item = QTreeWidgetItem(
                [finding.id, finding.severity, finding.title, ",".join(finding.fix_ids)]
            )
            item.setData(0, Qt.UserRole, finding.evidence + ("\n\n" + finding.hint if finding.hint else ""))
            item.setForeground(1, _COLOR.get(finding.severity, MUTED))
            self.tree.addTopLevelItem(item)
        if snap.errors:
            err = QTreeWidgetItem(["SYS", "info", "采集告警", ""])
            err.setData(0, Qt.UserRole, "\n".join(snap.errors))
            self.tree.addTopLevelItem(err)
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def _show_detail(self, current, _prev) -> None:
        if not current:
            return
        self.detail.setPlainText(str(current.data(0, Qt.UserRole) or ""))
