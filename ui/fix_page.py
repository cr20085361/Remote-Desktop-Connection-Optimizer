"""修复页：勾选确认后执行，并列出回滚脚本。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.config import ROLLBACK_DIR
from core.models import Snapshot
from core.runner import run_powershell
from fixes.catalog import ACTIONS
from fixes.engine import run_fix


class FixPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.NoSelection)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.rollbacks = QListWidget()
        self.btn_apply = QPushButton("执行已勾选修复")
        self.btn_apply.setObjectName("primary")
        self.btn_rollback = QPushButton("运行选中回滚脚本")
        self.btn_refresh = QPushButton("刷新回滚列表")

        root = QVBoxLayout(self)
        title = QLabel("修复动作（需逐项勾选确认）")
        title.setObjectName("appTitle")
        root.addWidget(title)
        root.addWidget(self.list, 3)
        btns = QHBoxLayout()
        btns.addWidget(self.btn_apply)
        btns.addStretch()
        root.addLayout(btns)
        root.addWidget(QLabel("执行日志"))
        root.addWidget(self.log, 2)
        rb = QHBoxLayout()
        rb.addWidget(QLabel("回滚脚本"))
        rb.addStretch()
        rb.addWidget(self.btn_refresh)
        rb.addWidget(self.btn_rollback)
        root.addLayout(rb)
        root.addWidget(self.rollbacks, 1)

        self.btn_apply.clicked.connect(self._apply)
        self.btn_refresh.clicked.connect(self._load_rollbacks)
        self.btn_rollback.clicked.connect(self._run_rollback)
        self._snap: Snapshot | None = None
        self._recommended: set[str] = set()
        self._load_rollbacks()

    def update_snapshot(self, snap: Snapshot) -> None:
        self._snap = snap
        self._recommended = {fid for f in snap.findings for fid in f.fix_ids}
        self.list.clear()
        for action in ACTIONS.values():
            rec = " [建议]" if action.id in self._recommended else ""
            item = QListWidgetItem(f"{action.id}  {action.title}{rec}  — {action.summary}")
            item.setFlags(item.flags() | item.flags() | item.flags())
            item.setCheckState(item.checkState())  # keep unchecked
            from PySide6.QtCore import Qt

            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item.setCheckState(Qt.Unchecked)
            item.setData(256, action.id)
            item.setToolTip(action.risk)
            self.list.addItem(item)

    def _apply(self) -> None:
        if not self._snap:
            QMessageBox.warning(self, "尚未采集", "请先在仪表盘完成一次采集。")
            return
        from PySide6.QtCore import Qt

        selected = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.checkState() == Qt.Checked:
                selected.append(item.data(256))
        if not selected:
            QMessageBox.information(self, "未勾选", "请勾选要执行的修复项。")
            return
        if QMessageBox.question(self, "确认执行", "将执行：\n" + "\n".join(selected) + "\n\n每项都会生成回滚脚本。") != QMessageBox.Yes:
            return
        for fid in selected:
            result = run_fix(fid, self._snap, confirmed=True)
            line = f"[{fid}] {'OK' if result.ok else 'FAIL'} {result.message}"
            if result.rollback_path:
                line += f"\n  rollback: {result.rollback_path}"
            self.log.appendPlainText(line)
        self._load_rollbacks()

    def _load_rollbacks(self) -> None:
        self.rollbacks.clear()
        if not ROLLBACK_DIR.exists():
            return
        for path in sorted(ROLLBACK_DIR.glob("*.ps1"), reverse=True)[:40]:
            self.rollbacks.addItem(str(path))

    def _run_rollback(self) -> None:
        item = self.rollbacks.currentItem()
        if not item:
            return
        path = item.text()
        if QMessageBox.question(self, "回滚", f"运行 {path} ?") != QMessageBox.Yes:
            return
        result = run_powershell(f'& "{path}"', timeout=40)
        self.log.appendPlainText(result.stdout or result.stderr or "已执行回滚")
