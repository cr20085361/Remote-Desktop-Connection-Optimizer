"""主窗口：体检 / 技术细节 / 设置。"""

from __future__ import annotations

import time

from PySide6.QtCore import QProcess, QThread, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.config import APP_DISPLAY, ICON_PATH, VERSION
from core.models import Snapshot
from core.runner import is_admin
from core.settings import load_settings
from core.update import ReleaseInfo, UpdateError, check_for_update, download_installer, format_size
from rules.plain import snapshot_compare
from ui.assistant_drawer import AssistantDrawer
from ui.banner import GuideBanner
from ui.settings_page import SettingsPage
from ui.tech_page import TechPage
from ui.verdict_page import VerdictPage
from ui.worker import CollectorThread

_SPIN = "◐◓◑◒"


class UpdateCheckThread(QThread):
    found = Signal(object)
    already_latest = Signal()
    failed = Signal(str)

    def run(self) -> None:
        try:
            info = check_for_update(VERSION)
        except UpdateError as exc:
            self.failed.emit(str(exc))
            return
        except Exception:
            self.failed.emit("暂时无法检查更新")
            return
        if info:
            self.found.emit(info)
        else:
            self.already_latest.emit()


class UpdateDownloadThread(QThread):
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, info: ReleaseInfo, parent=None) -> None:
        super().__init__(parent)
        self._info = info

    def run(self) -> None:
        try:
            path = download_installer(self._info)
        except UpdateError as exc:
            self.failed.emit(str(exc))
            return
        except Exception:
            self.failed.emit("下载安装包失败")
            return
        self.done.emit(str(path))


class CompareDialog(QDialog):
    def __init__(self, before: Snapshot, after: Snapshot, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("修好了没有？")
        self.resize(640, 380)
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["看什么", "处理前", "处理后"])
        table.horizontalHeader().setStretchLastSection(True)
        for row in snapshot_compare(before, after):
            r = table.rowCount()
            table.insertRow(r)
            for c, text in enumerate(row):
                table.setItem(r, c, QTableWidgetItem(text))
        table.resizeColumnsToContents()
        lay = QVBoxLayout(self)
        hint = QLabel("如果「对外地址」不再是翻墙节点、绕路变成直连、毫秒数明显下降，就说明修好了。")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addWidget(table)
        close = QPushButton("知道了")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        lay.addWidget(close)


class MainWindow(QMainWindow):
    first_ready = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_DISPLAY)
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.resize(1280, 800)
        self._thread: CollectorThread | None = None
        self._snap: Snapshot | None = None
        self._before: Snapshot | None = None
        self._awaiting_retest = False
        self._busy = False
        self._announced_ready = False
        self._banner_kind = "retest"
        self._pending_release: ReleaseInfo | None = None
        self._update_check: UpdateCheckThread | None = None
        self._update_download: UpdateDownloadThread | None = None
        self._manual_update_check = False
        self._spin_i = 0
        self._prog: tuple[int, int, str] = (0, 8, "即将开始检测")
        self._detect_t0 = time.monotonic()

        rail = QWidget()
        rail.setObjectName("rail")
        rail.setFixedWidth(148)
        rail_l = QVBoxLayout(rail)
        rail_l.setContentsMargins(10, 14, 10, 12)
        rail_l.setSpacing(6)
        brand = QLabel("通路体检")
        brand.setObjectName("appTitle")
        sub = QLabel("远程桌面")
        sub.setObjectName("eyebrow")
        rail_l.addWidget(brand)
        rail_l.addWidget(sub)
        self.btn_home = QPushButton("体检")
        self.btn_tech = QPushButton("技术细节")
        self.btn_set = QPushButton("设置")
        self.nav_group = QButtonGroup(self)
        for i, btn in enumerate((self.btn_home, self.btn_tech, self.btn_set)):
            btn.setObjectName("nav")
            btn.setCheckable(True)
            self.nav_group.addButton(btn, i)
            rail_l.addWidget(btn)
        rail_l.addStretch()
        self.btn_collect = QPushButton("重新检测")
        self.btn_collect.setObjectName("primary")
        rail_l.addWidget(self.btn_collect)
        admin = QLabel("管理员" if is_admin() else "普通权限 · 部分修复需管理员")
        admin.setObjectName("eyebrow")
        admin.setWordWrap(True)
        rail_l.addWidget(admin)

        self.stack = QStackedWidget()
        self.page_home = VerdictPage()
        self.page_tech = TechPage()
        self.page_set = SettingsPage()
        for page in (self.page_home, self.page_tech, self.page_set):
            self.stack.addWidget(page)
        self.btn_home.setChecked(True)
        self.nav_group.idClicked.connect(self.stack.setCurrentIndex)

        self.banner = GuideBanner()
        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(10, 10, 10, 6)
        right_l.setSpacing(8)
        right_l.addWidget(self.banner)
        right_l.addWidget(self.stack, 1)

        self.drawer = AssistantDrawer()

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(rail)
        layout.addWidget(right, 1)
        layout.addWidget(self.drawer)
        self.setCentralWidget(root)

        bar = QStatusBar()
        self.setStatusBar(bar)
        bar.showMessage("正在准备第一次检测")

        self.btn_collect.clicked.connect(self.start_collect)
        self.drawer.settings_requested.connect(self._goto_settings)
        self.page_home.ask_ai.connect(self._ask_ai)
        self.page_tech.ask_ai.connect(self._ask_ai)
        self.page_set.saved.connect(self.drawer.chat.refresh_status)
        self.page_set.check_update_requested.connect(lambda: self._check_updates(manual=True))
        self.page_home.banner_requested.connect(self._on_banner)
        self.page_home.retest_requested.connect(self.start_collect)
        self.banner.retest_clicked.connect(self._on_banner_action)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.start_collect)
        interval = int(load_settings().get("interval_sec") or 60) * 1000
        self.timer.start(max(interval, 15000))
        self.spin_timer = QTimer(self)
        self.spin_timer.setInterval(140)
        self.spin_timer.timeout.connect(self._tick_busy)
        QTimer.singleShot(400, self.start_collect)
        QTimer.singleShot(2000, lambda: self._check_updates(manual=False))

    def start_collect(self) -> None:
        if self._thread and self._thread.isRunning():
            return
        self._busy = True
        self._detect_t0 = time.monotonic()
        self._prog = (0, 8, "正在启动检测")
        self.page_home.begin_detect()
        self._render_busy()
        self.statusBar().showMessage("正在检测")
        self.btn_collect.setEnabled(False)
        self.spin_timer.start()
        self._thread = CollectorThread()
        self._thread.progress.connect(self._on_progress)
        self._thread.snapshot_ready.connect(self._on_snap)
        self._thread.failed.connect(self._on_fail)
        self._thread.finished.connect(self._on_collect_finished)
        self._thread.start()

    def _on_progress(self, index: int, total: int, label: str) -> None:
        if not self._busy:
            return
        self._prog = (int(index), int(total) or 8, str(label))
        self._render_busy()
        self.statusBar().showMessage(label)

    def _tick_busy(self) -> None:
        if not self._busy:
            return
        self._spin_i = (self._spin_i + 1) % len(_SPIN)
        self._render_busy()

    def _render_busy(self) -> None:
        index, total, label = self._prog
        elapsed = time.monotonic() - self._detect_t0
        self.page_home.set_progress(index, total, label, elapsed)
        if self._busy:
            self.btn_collect.setText(f"{_SPIN[self._spin_i]} 检测中 {index}/{total}")

    def _on_collect_finished(self) -> None:
        self._busy = False
        self.spin_timer.stop()
        self.btn_collect.setEnabled(True)
        self.btn_collect.setText("重新检测")
        self.page_home.end_detect()
        if self._snap:
            self.statusBar().showMessage("检测完成")
        self._emit_first_ready()

    def _on_snap(self, snap: Snapshot) -> None:
        before = self._before
        self._snap = snap
        try:
            self.page_home.update_snapshot(snap)
            self.page_tech.update_snapshot(snap)
            self.drawer.chat.set_snapshot(snap)
            self.drawer.chat.refresh_status()
        except Exception as exc:
            self.statusBar().showMessage(f"界面刷新失败：{exc}")
            return
        self._emit_first_ready()
        if self._awaiting_retest and before is not None and snap.netcheck.global_v4:
            self._awaiting_retest = False
            self._before = None
            self.banner.setVisible(False)
            CompareDialog(before, snap, self).exec()
        if not self.timer.isActive():
            interval = int(load_settings().get("interval_sec") or 60) * 1000
            self.timer.start(max(interval, 15000))

    def _on_fail(self, msg: str) -> None:
        self.statusBar().showMessage("检测失败")
        QMessageBox.warning(self, "检测失败", msg)

    def _on_banner(self, post_action: str, before: Snapshot) -> None:
        self._before = before
        self._awaiting_retest = True
        self._banner_kind = "retest"
        self.timer.stop()
        if post_action:
            self.banner.show_message(post_action + " 做完后点右侧按钮，我再测一遍并告诉你有没有好转。")

    def _on_banner_action(self) -> None:
        if self._banner_kind == "update":
            self._start_update_download()
            return
        self.start_collect()

    def _check_updates(self, *, manual: bool) -> None:
        if self._update_check and self._update_check.isRunning():
            return
        if self._update_download and self._update_download.isRunning():
            return
        if not manual and not load_settings().get("check_updates", True):
            return
        self._manual_update_check = manual
        if manual:
            self.statusBar().showMessage("正在检查更新")
        self._update_check = UpdateCheckThread(self)
        self._update_check.found.connect(self._on_update_found)
        self._update_check.already_latest.connect(self._on_already_latest)
        self._update_check.failed.connect(self._on_update_failed)
        self._update_check.start()

    def _on_update_found(self, info: object) -> None:
        if not isinstance(info, ReleaseInfo):
            return
        self._pending_release = info
        if self._awaiting_retest:
            self.statusBar().showMessage(f"发现新版本 {info.version}，可到设置里检查更新")
            return
        self._banner_kind = "update"
        size = format_size(info.size)
        self.banner.show_message(
            f"发现新版本 {info.version}（约 {size}）。当前是 {APP_DISPLAY}。确认后才会下载安装包。",
            action="下载并安装",
        )
        self.statusBar().showMessage(f"发现新版本 {info.version}")

    def _on_already_latest(self) -> None:
        if self._manual_update_check:
            QMessageBox.information(self, "检查更新", f"已经是最新版本：{APP_DISPLAY}。")
        self.statusBar().showMessage(f"已是最新 {APP_DISPLAY}")

    def _on_update_failed(self, msg: str) -> None:
        text = msg or "暂时无法检查更新"
        self.statusBar().showMessage(text)
        if self._manual_update_check:
            QMessageBox.information(self, "检查更新", text)

    def _start_update_download(self) -> None:
        info = self._pending_release
        if info is None:
            return
        if self._update_download and self._update_download.isRunning():
            return
        self.banner.set_busy(f"正在下载 {info.installer} …")
        self.statusBar().showMessage("正在下载安装包")
        self._update_download = UpdateDownloadThread(info, self)
        self._update_download.done.connect(self._on_update_downloaded)
        self._update_download.failed.connect(self._on_update_download_failed)
        self._update_download.start()

    def _on_update_downloaded(self, path: str) -> None:
        started = QProcess.startDetached(path, [])
        if not started:
            self._banner_kind = "update"
            self.banner.show_message("安装包已下载，但没能启动。请到下载目录手动打开。", action="下载并安装")
            QMessageBox.warning(self, "更新", f"没能启动安装包：\n{path}")
            return
        self.close()

    def _on_update_download_failed(self, msg: str) -> None:
        self._banner_kind = "update"
        self.banner.show_message(msg or "下载安装包失败", action="下载并安装")
        self.statusBar().showMessage(msg or "下载安装包失败")

    def _emit_first_ready(self) -> None:
        if self._announced_ready:
            return
        self._announced_ready = True
        self.first_ready.emit()

    def _goto_settings(self) -> None:
        self.stack.setCurrentWidget(self.page_set)
        self.btn_set.setChecked(True)

    def _ask_ai(self, text: str) -> None:
        self.drawer.ask(text)
