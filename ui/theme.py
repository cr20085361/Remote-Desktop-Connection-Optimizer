"""温暖纸感体检报告主题：克制深色、单一强调色、语义状态色。"""

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

BG = "#12110E"
PANEL = "#1C1A16"
PANEL2 = "#26231D"
LINE = "#3A352C"
TEXT = "#F3EDE2"
MUTED = "#A89F90"
ACCENT = "#C4A574"
OK = "#6FAF8A"
DANGER = "#D85A4A"
HIGH = "#E08A3C"
WARN = "#D4A017"
CYAN = "#C4A574"

PAGE_MARGIN = 16
CARD_GAP = 10
RADIUS = 14

SEVERITY_COLOR = {
    "critical": DANGER,
    "high": HIGH,
    "medium": WARN,
    "low": MUTED,
    "info": OK,
}

STYLESHEET = f"""
QMainWindow, QWidget {{
  background: {BG};
  color: {TEXT};
  font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
  font-size: 13px;
}}
QLabel#scoreNum {{
  font-family: "Palatino Linotype", "Georgia", serif;
  font-size: 56px;
  font-weight: 600;
  color: {TEXT};
}}
QLabel#verdictTitle {{
  font-size: 20px;
  font-weight: 600;
  color: {TEXT};
}}
QLabel#cardTitle {{
  font-size: 15px;
  font-weight: 600;
  color: {TEXT};
}}
QLabel#body {{
  font-size: 13px;
  color: {TEXT};
}}
QLabel#muted, QLabel#eyebrow {{
  font-size: 11px;
  color: {MUTED};
  letter-spacing: 0.5px;
}}
QLabel#appTitle {{
  font-size: 16px;
  font-weight: 700;
  color: {TEXT};
}}
QFrame#card, QFrame#scoreCard, QFrame#issueCard {{
  background: {PANEL};
  border: 1px solid {LINE};
  border-radius: {RADIUS}px;
}}
QFrame#issueCard:hover {{
  background: {PANEL2};
}}
QFrame#rail {{
  background: #0E0D0B;
  border-right: 1px solid {LINE};
}}
QFrame#banner {{
  background: #2A2418;
  border: 1px solid {ACCENT};
  border-radius: 10px;
}}
QPushButton {{
  background: {PANEL2};
  border: 1px solid {LINE};
  border-radius: 10px;
  padding: 9px 16px;
  min-height: 32px;
  color: {TEXT};
}}
QPushButton:hover {{ background: #322E26; }}
QPushButton:pressed {{ background: #1A1814; }}
QPushButton:disabled {{ color: #6E675C; }}
QPushButton#primary {{
  background: {ACCENT};
  color: #1A140C;
  font-weight: 700;
  border: none;
  padding: 10px 18px;
}}
QPushButton#primary:hover {{ background: #D4B88A; }}
QPushButton#primary:pressed {{
  background: #A88B5C;
  padding: 12px 16px 8px 20px;
}}
QPushButton#primary:disabled {{
  background: {ACCENT};
  color: #1A140C;
}}
QProgressBar {{
  background: #0E0D0B;
  border: 1px solid {LINE};
  border-radius: 6px;
  height: 12px;
  text-align: center;
  color: {TEXT};
  font-size: 11px;
}}
QProgressBar::chunk {{
  background: {ACCENT};
  border-radius: 5px;
}}
QPushButton#ghost {{
  background: transparent;
  border: none;
  color: {MUTED};
  text-decoration: underline;
  padding: 4px 8px;
  min-height: 28px;
}}
QPushButton#ghost:hover {{ color: {TEXT}; }}
QPushButton#nav {{
  text-align: left;
  padding: 12px 16px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: {MUTED};
}}
QPushButton#nav:checked, QPushButton#nav:hover {{
  background: {PANEL2};
  color: {TEXT};
}}
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit {{
  background: #0E0D0B;
  border: 1px solid {LINE};
  border-radius: 8px;
  padding: 8px 10px;
  color: {TEXT};
  selection-background-color: {ACCENT};
  selection-color: #1A140C;
}}
QTreeWidget, QListWidget, QTableWidget {{
  background: #0E0D0B;
  border: 1px solid {LINE};
  border-radius: 10px;
  alternate-background-color: {PANEL};
}}
QHeaderView::section {{
  background: {PANEL2};
  color: {MUTED};
  border: none;
  padding: 8px;
}}
QCheckBox {{ spacing: 8px; color: {TEXT}; }}
QScrollBar:vertical {{
  background: transparent;
  width: 10px;
  margin: 4px;
}}
QScrollBar::handle:vertical {{
  background: #4A4338;
  border-radius: 4px;
}}
QStatusBar {{
  background: #0E0D0B;
  color: {MUTED};
}}
QToolButton#fold {{
  background: transparent;
  border: none;
  color: {MUTED};
  font-size: 13px;
  padding: 6px 0;
  text-align: left;
}}
QToolButton#fold:hover {{ color: {TEXT}; }}
QScrollArea {{ border: none; background: transparent; }}
QTabWidget::pane {{
  border: 1px solid {LINE};
  border-radius: 10px;
  background: {PANEL};
  top: -1px;
}}
QTabBar::tab {{
  background: transparent;
  color: {MUTED};
  padding: 8px 14px;
  margin-right: 4px;
  border: none;
}}
QTabBar::tab:selected {{
  color: {TEXT};
  background: {PANEL2};
  border-radius: 8px 8px 0 0;
}}
QFrame#chatPanel {{
  background: {PANEL};
  border-left: 1px solid {LINE};
  border-radius: 0;
}}
QFrame#userBubble {{
  background: #2A2418;
  border: 1px solid {LINE};
  border-radius: 12px;
}}
QFrame#botBubble {{
  background: {PANEL2};
  border: 1px solid {LINE};
  border-radius: 12px;
}}
QTextBrowser#mdView {{
  background: transparent;
  border: none;
  color: {TEXT};
  font-size: 13px;
  padding: 0;
}}
QToolButton#drawerStrip {{
  background: {PANEL};
  border: none;
  border-left: 1px solid {LINE};
  color: {MUTED};
  font-size: 13px;
  font-weight: 600;
}}
QToolButton#drawerStrip:hover {{ color: {TEXT}; background: {PANEL2}; }}
QPushButton#chip {{
  background: transparent;
  border: 1px solid {LINE};
  border-radius: 14px;
  padding: 4px 10px;
  min-height: 26px;
  color: {MUTED};
  font-size: 12px;
}}
QPushButton#chip:hover {{ color: {TEXT}; border-color: {ACCENT}; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor("#0E0D0B"))
    pal.setColor(QPalette.AlternateBase, QColor(PANEL))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor(PANEL2))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor("#1A140C"))
    pal.setColor(QPalette.ToolTipBase, QColor(PANEL2))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)
    app.setFont(QFont("Microsoft YaHei UI", 10))
