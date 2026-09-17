"""体检首页：评分、一句话结论、白话问题卡片。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.models import Snapshot
from core.runner import run_powershell
from fixes.catalog import ACTIONS
from fixes.engine import run_fix
from rules.plain import FIX_COPY, IssueCard, health_score, issue_cards, summary_line, verdict
from ui.cards import IssueCardWidget, ScoreRing
from ui.charts import RttChart
from ui.theme import CARD_GAP, PAGE_MARGIN
from ui.topology import TopologyView


class Fold(QWidget):
    def __init__(self, title: str, inner: QWidget, *, open_: bool = False) -> None:
        super().__init__()
        self.btn = QToolButton()
        self.btn.setObjectName("fold")
        self.btn.setCheckable(True)
        self.btn.setChecked(open_)
        self.btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn.setArrowType(Qt.DownArrow if open_ else Qt.RightArrow)
        self.btn.setText(title)
        self.inner = inner
        self.inner.setVisible(open_)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self.btn)
        lay.addWidget(self.inner)
        self.btn.toggled.connect(self._toggle)

    def _toggle(self, on: bool) -> None:
        self.inner.setVisible(on)
        self.btn.setArrowType(Qt.DownArrow if on else Qt.RightArrow)

    def set_title(self, title: str) -> None:
        self.btn.setText(title)


class VerdictPage(QWidget):
    banner_requested = Signal(str, object)
    retest_requested = Signal()
    ask_ai = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._snap: Snapshot | None = None
        self._detecting = True
        self.ring = ScoreRing()
        self.verdict_label = QLabel("正在检测这台电脑的远程桌面通路…")
        self.verdict_label.setObjectName("verdictTitle")
        self.verdict_label.setWordWrap(True)
        self.summary = QLabel("下面会显示当前做到哪一步，不用看左下角。")
        self.summary.setObjectName("muted")
        self.summary.setWordWrap(True)
        self.band = QLabel("")
        self.band.setObjectName("eyebrow")

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0/8  0%")
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(18)
        self.progress_label = QLabel("即将开始检测")
        self.progress_label.setObjectName("muted")
        self.progress_label.setWordWrap(True)
        self.progress_wrap = QWidget()
        prog_l = QVBoxLayout(self.progress_wrap)
        prog_l.setContentsMargins(0, 6, 0, 0)
        prog_l.setSpacing(4)
        prog_l.addWidget(self.progress_bar)
        prog_l.addWidget(self.progress_label)

        score_box = QFrame()
        score_box.setObjectName("scoreCard")
        score_l = QHBoxLayout(score_box)
        score_l.setContentsMargins(14, 12, 16, 12)
        score_l.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(4)
        left.addWidget(self.ring, 0, Qt.AlignHCenter)
        left.addWidget(self.band, 0, Qt.AlignHCenter)
        score_l.addLayout(left)
        right = QVBoxLayout()
        right.setSpacing(6)
        right.addWidget(self.verdict_label)
        right.addWidget(self.summary)
        self.btn_ask_verdict = QPushButton("问 AI")
        self.btn_ask_verdict.setObjectName("ghost")
        self.btn_ask_verdict.setVisible(False)
        self.btn_ask_verdict.clicked.connect(self._ask_verdict)
        ask_row = QHBoxLayout()
        ask_row.addWidget(self.btn_ask_verdict)
        ask_row.addStretch()
        right.addLayout(ask_row)
        right.addWidget(self.progress_wrap)
        score_l.addLayout(right, 1)

        self.urgent_title = QLabel("立即处理")
        self.urgent_title.setObjectName("cardTitle")
        self.urgent_title.setVisible(False)
        self.urgent_host = QVBoxLayout()
        self.urgent_host.setSpacing(CARD_GAP)
        self.other_inner = QWidget()
        self.other_layout = QVBoxLayout(self.other_inner)
        self.other_layout.setContentsMargins(0, 0, 0, 0)
        self.other_layout.setSpacing(CARD_GAP)
        self.other_fold = Fold("其他发现", self.other_inner, open_=False)
        self.other_fold.setVisible(False)

        tech_inner = QWidget()
        tech_l = QVBoxLayout(tech_inner)
        tech_l.setContentsMargins(0, 0, 0, 0)
        tech_l.setSpacing(8)
        hint = QLabel("以下内容供排查用，看不懂可以忽略。")
        hint.setObjectName("muted")
        tech_l.addWidget(hint)
        hide_row = QHBoxLayout()
        self.hide_offline = QPushButton("隐藏离线电脑")
        self.hide_offline.setCheckable(True)
        self.hide_offline.setChecked(True)
        hide_row.addWidget(self.hide_offline)
        hide_row.addStretch()
        tech_l.addLayout(hide_row)
        split = QHBoxLayout()
        split.setSpacing(10)
        self.topo = TopologyView()
        self.chart = RttChart()
        self.chart.setVisible(False)
        split.addWidget(self.topo, 3)
        split.addWidget(self.chart, 2)
        tech_l.addLayout(split)
        self.tech_fold = Fold("技术细节", tech_inner, open_=False)
        self.tech_fold.setVisible(False)
        self.hide_offline.toggled.connect(self._toggle_offline)

        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(PAGE_MARGIN, 12, PAGE_MARGIN, 16)
        col.setSpacing(12)
        col.addWidget(score_box)
        col.addWidget(self.urgent_title)
        col.addLayout(self.urgent_host)
        col.addWidget(self.other_fold)
        col.addWidget(self.tech_fold)
        col.addStretch()

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(inner)
        page = QVBoxLayout(self)
        page.setContentsMargins(0, 0, 0, 0)
        page.addWidget(self.scroll)

    def begin_detect(self) -> None:
        self._detecting = True
        self.progress_wrap.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0/8  0%")
        self.progress_label.setText("正在启动检测")
        if self._snap is None:
            self.urgent_title.setVisible(False)
            self.other_fold.setVisible(False)
            self.tech_fold.setVisible(False)
            self.chart.setVisible(False)
            self.verdict_label.setText("正在检测这台电脑的远程桌面通路…")
            self.summary.setText("下面会显示当前做到哪一步。")

    def set_progress(self, index: int, total: int, label: str, elapsed_sec: float) -> None:
        total = max(int(total) or 8, 1)
        index = max(0, min(int(index), total))
        pct = int(round(index / total * 100))
        self.progress_wrap.setVisible(True)
        self.progress_bar.setValue(pct)
        self.progress_bar.setFormat(f"{index}/{total}  {pct}%")
        used = max(0, int(elapsed_sec))
        self.progress_label.setText(f"{label} · 已用 {used} 秒")

    def end_detect(self) -> None:
        self._detecting = False
        self.progress_wrap.setVisible(False)

    def update_snapshot(self, snap: Snapshot) -> None:
        bar = self.scroll.verticalScrollBar()
        y = bar.value()
        self._snap = snap
        score, band = health_score(snap)
        self.ring.set_score(score, band)
        self.band.setText(band)
        self.verdict_label.setText(verdict(snap))
        self.summary.setText(summary_line(snap))
        self.btn_ask_verdict.setVisible(True)
        cards = issue_cards(snap)
        urgent = cards[:3]
        rest = cards[3:]
        self.urgent_title.setVisible(bool(urgent))
        self._fill_list(self.urgent_host, urgent, empty_ok=True)
        self._fill_list(self.other_layout, rest, empty_ok=True)
        self.other_fold.setVisible(bool(rest))
        self.other_fold.set_title(f"其他发现（{len(rest)}）" if rest else "其他发现")
        self.tech_fold.setVisible(True)
        self.topo.hide_offline = self.hide_offline.isChecked()
        self.topo.render_snapshot(snap)
        self.chart.update_snapshot(snap)
        has_rtt = any(p.ping_rtt_ms is not None for p in snap.online_peers())
        self.chart.setVisible(has_rtt)
        bar.setValue(y)

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _fill_list(self, layout: QVBoxLayout, cards: list[IssueCard], *, empty_ok: bool = False) -> None:
        self._clear_layout(layout)
        for card in cards:
            widget = IssueCardWidget(card)
            widget.fix_clicked.connect(self._on_fix)
            widget.manual_clicked.connect(self._on_manual)
            widget.ask_ai.connect(self.ask_ai.emit)
            layout.addWidget(widget)
        if not cards and not empty_ok and not self._detecting:
            empty = QLabel("没有需要立刻处理的事项。")
            empty.setObjectName("muted")
            layout.addWidget(empty)

    def _toggle_offline(self, hide: bool) -> None:
        self.topo.hide_offline = hide
        if self._snap:
            self.topo.render_snapshot(self._snap)

    def _on_manual(self, card: IssueCard) -> None:
        QMessageBox.information(self, card.title, card.next_step + "\n\n" + card.meaning)

    def _ask_verdict(self) -> None:
        if not self._snap:
            return
        score, band = health_score(self._snap)
        self.ask_ai.emit(
            "请解释当前体检结论和评分，告诉我最该先做的一件事。\n"
            f"结论：{self.verdict_label.text()}\n评分：{score}（{band}）\n摘要：{self.summary.text()}"
        )

    def _on_fix(self, fix_id: str) -> None:
        if not self._snap:
            QMessageBox.information(self, "请先检测", "还没有检测结果。")
            return
        copy = FIX_COPY.get(fix_id)
        action = ACTIONS.get(fix_id)
        name = copy.name if copy else fix_id
        what = copy.what_changes if copy else ""
        risk = copy.risk if copy else (action.risk if action else "")
        text = (
            f"将执行：{name}\n\n"
            f"会改什么：{what}\n\n"
            f"风险：{risk}\n\n"
            "随时可以撤销。"
        )
        if QMessageBox.question(self, "确认修改", text) != QMessageBox.Yes:
            return
        result = run_fix(fix_id, self._snap, confirmed=True)
        box = QMessageBox(self)
        box.setWindowTitle("处理结果")
        if result.ok:
            box.setText(result.message or "已经改好。")
        else:
            box.setText("没有改成功。\n" + (result.message or ""))
        undo = None
        if result.rollback_path:
            undo = box.addButton("撤销这次修改", QMessageBox.ActionRole)
        box.addButton("知道了", QMessageBox.AcceptRole)
        box.exec()
        if undo is not None and box.clickedButton() == undo:
            rb = run_powershell(f'& "{result.rollback_path}"', timeout=40)
            QMessageBox.information(self, "已撤销", rb.stdout or rb.stderr or "已执行撤销脚本。")
            return
        post = (copy.post_action if copy else "") or ""
        if result.ok:
            self.banner_requested.emit(post, self._snap)
            if not post:
                self.retest_requested.emit()
