"""远程桌面连接优化器入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from core.config import APP_DISPLAY, APP_NAME, ensure_app_dirs
from core.runner import is_admin


def _selftest(out_path: str) -> int:
    """打包后自检：能否加载 Qt 与全部业务模块。结果写文件（窗口版 exe 没有控制台）。"""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtCore import qVersion
        from PySide6.QtWidgets import QApplication

        import core.collector, fixes.catalog, keyring, peer.server, pyqtgraph, requests  # noqa: E401,F401
        import ui.main_window, ui.theme  # noqa: E401,F401

        QApplication.instance() or QApplication([])
        message, code = f"SELFTEST OK Qt {qVersion()}", 0
    except Exception as exc:  # noqa: BLE001
        message, code = f"SELFTEST FAIL {type(exc).__name__}: {exc}", 2
    if out_path:
        Path(out_path).write_text(message, encoding="utf-8")
    return code


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=APP_NAME)
    parser.add_argument("--selftest", metavar="OUTFILE", help="加载全部模块并把结果写入文件后退出")
    parser.add_argument("--cli", choices=["diagnose", "collect", "fixes"], help="命令行模式")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--ping-count", type=int, default=2)
    parser.add_argument("--no-ping", action="store_true")
    parser.add_argument("--pmtu", action="store_true")
    args = parser.parse_args(argv)
    if args.selftest:
        return _selftest(args.selftest)
    if not args.cli:
        return _gui()
    ensure_app_dirs()
    from core.collector import collect_snapshot

    def progress(*parts) -> None:
        if not args.json:
            print(parts[-1], file=sys.stderr)

    snap = collect_snapshot(
        ping_count=args.ping_count,
        ping_peers=not args.no_ping,
        probe_links=bool(args.pmtu),
        probe_pmtu=args.pmtu,
        include_rdp_events=False,
        progress=progress,
    )
    if args.cli == "collect" or args.json:
        print(json.dumps(snap.to_dict(), ensure_ascii=False, indent=2))
        return 0
    if args.cli == "fixes":
        from fixes.catalog import ACTIONS

        for action in ACTIONS.values():
            ok, msg = action.precheck(snap)
            print(f"{action.id}\t{'READY' if ok else 'SKIP'}\t{action.title}\t{msg}")
        return 0
    print(APP_DISPLAY)
    from rules.plain import health_score, issue_cards, verdict as plain_verdict

    score, band = health_score(snap)
    print(f"结论：{plain_verdict(snap)}")
    print(f"评分 {score}（{band}）")
    for card in issue_cards(snap)[:3]:
        print(f"  · {card.title}")
        print(f"    {card.next_step}")
    print(f"主机 {snap.hostname}  Tailscale {snap.self_ip}  管理员={snap.admin}")
    print(f"公网出口 {snap.netcheck.global_v4}:{snap.netcheck.global_v4_port or '-'}")
    print(
        f"最近 DERP {snap.netcheck.preferred_derp} "
        f"({snap.netcheck.preferred_derp_code}) {snap.netcheck.preferred_derp_latency_ms}ms"
    )
    print(f"Tun={snap.proxy.tun_up} 默认出口={snap.route.default_exit_iface} 系统代理={snap.proxy.proxy_enable}")
    print("节点:")
    for peer in snap.peers:
        if peer.is_self:
            continue
        state = "online" if peer.online else "offline"
        path = peer.cur_addr or peer.relay or "-"
        rtt = f"{peer.ping_rtt_ms:.0f}ms" if peer.ping_rtt_ms is not None else "-"
        print(f"  {peer.hostname:16} {peer.ip:16} {state:8} {path}  rtt={rtt} via={peer.ping_via}")
    print("诊断:")
    if not snap.findings:
        print("  未命中规则")
    for finding in snap.findings:
        print(f"  [{finding.severity:8}] {finding.id} {finding.title}")
        print(f"           {finding.evidence}")
        if finding.fix_ids:
            print(f"           修复: {', '.join(finding.fix_ids)}")
    if snap.errors:
        print("采集告警:")
        for err in snap.errors:
            print("  ", err)
    return 0


def _gui() -> int:
    ensure_app_dirs()
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QColor, QIcon, QPixmap
    from PySide6.QtWidgets import QApplication, QSplashScreen

    from core.config import ICON_PATH, SPLASH_PATH
    from ui.main_window import MainWindow
    from ui.theme import apply_theme
    from core.settings import load_settings
    from peer.server import start_server

    app = QApplication(sys.argv)
    apply_theme(app)
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    splash = None
    if SPLASH_PATH.exists():
        pix = QPixmap(str(SPLASH_PATH))
        splash = QSplashScreen(pix)
        splash.show()
        splash.showMessage(
            APP_DISPLAY,
            Qt.AlignBottom | Qt.AlignHCenter,
            QColor("#F3EDE2"),
        )
        app.processEvents()
    win = MainWindow()
    settings = load_settings()
    if settings.get("peer_server_enabled", True):
        try:
            host, port = start_server(port=int(settings.get("peer_port") or 18765))
            win.statusBar().showMessage(f"快照端点 http://{host}:{port}/snapshot")
        except Exception as exc:
            win.statusBar().showMessage(f"快照端点未启动: {exc}")
    if not is_admin():
        win.statusBar().showMessage("普通权限 · 部分修复需管理员")
    win.show()
    if splash:
        def _close_splash() -> None:
            splash.close()

        win.first_ready.connect(_close_splash)
        QTimer.singleShot(2000, _close_splash)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
