"""Fiori-Horizon-angelehntes Stylesheet."""

BLAU = "#0064D9"
BLAU_HELL = "#EBF8FF"
TEXT = "#1D2D3E"
TEXT2 = "#556B82"
LINIE = "#D9D9D9"
HG = "#F5F6F7"
OK = "#256F3A"
WARN = "#E76500"
FEHLER = "#AA0808"

QSS = f"""
* {{ font-family: "Segoe UI", "72", "Helvetica Neue", Arial; font-size: 10pt; color: {TEXT}; }}
QMainWindow, QWidget#page, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {HG}; }}

/* Shell Bar */
QFrame#shellbar {{ background: #FFFFFF; border-bottom: 1px solid {LINIE}; }}
QLabel#shelltitle {{ font-size: 13pt; font-weight: 600; }}
QLabel#shellsub {{ color: {TEXT2}; }}

/* Seitennavigation */
QListWidget#sidenav {{ background: #FFFFFF; border: none; border-right: 1px solid {LINIE}; outline: 0; padding-top: 6px; }}
QListWidget#sidenav::item {{ padding: 10px 14px; margin: 2px 8px; border-radius: 8px; }}
QListWidget#sidenav::item:hover {{ background: #EAECEE; }}
QListWidget#sidenav::item:selected {{ background: {BLAU_HELL}; color: {BLAU}; font-weight: 600; }}

/* Karten */
QFrame#card {{ background: #FFFFFF; border: 1px solid #E5E5E5; border-radius: 12px; }}
QFrame#tile {{ background: #FFFFFF; border: 1px solid #E5E5E5; border-radius: 16px; }}
QFrame#tile:hover {{ border: 1px solid {BLAU}; }}
QLabel#tiletitle {{ font-size: 11pt; font-weight: 600; }}
QLabel#tilesub {{ color: {TEXT2}; }}
QLabel#tilekpi {{ font-size: 24pt; font-weight: 300; color: {BLAU}; }}
QLabel#h1 {{ font-size: 16pt; font-weight: 600; }}
QLabel#h2 {{ font-size: 11.5pt; font-weight: 600; }}
QLabel#sub {{ color: {TEXT2}; }}
QLabel#kpi {{ font-size: 15pt; font-weight: 600; }}
QLabel#kpilabel {{ color: {TEXT2}; font-size: 9pt; }}

/* Objektkopf */
QFrame#objheader {{ background: #FFFFFF; border-bottom: 1px solid {LINIE}; }}

/* Buttons */
QPushButton {{ background: #FFFFFF; color: {BLAU}; border: 1px solid #BCC3CA; border-radius: 8px;
              padding: 6px 14px; min-height: 20px; font-weight: 600; }}
QPushButton:hover {{ background: #EAECEE; }}
QPushButton:disabled {{ color: #A9B4BE; border-color: #E5E5E5; }}
QPushButton[emph="true"] {{ background: {BLAU}; color: #FFFFFF; border: 1px solid {BLAU}; }}
QPushButton[emph="true"]:hover {{ background: #0054B6; }}
QPushButton[emph="true"]:disabled {{ background: #A9C7EE; border-color: #A9C7EE; }}
QPushButton[flat="true"] {{ border: none; background: transparent; }}
QPushButton[flat="true"]:hover {{ background: #EAECEE; }}
QPushButton[neg="true"] {{ color: {FEHLER}; }}
QPushButton[neg="true"]:disabled {{ color: #A9B4BE; }}

/* Eingaben */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QPlainTextEdit, QTextEdit {{
    background: #FFFFFF; border: 1px solid #89919A; border-radius: 6px; padding: 4px 8px; min-height: 20px; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus {{
    border: 2px solid {BLAU}; }}
QLineEdit:read-only {{ background: #F2F2F2; border-color: #D5D5D5; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: #FFFFFF; selection-background-color: {BLAU_HELL}; selection-color: {TEXT}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; }}
QLabel#formlabel {{ color: {TEXT2}; }}

/* Tabellen */
QTableWidget, QTableView, QListWidget {{ background: #FFFFFF; border: 1px solid #E5E5E5; border-radius: 8px;
    gridline-color: #EEEEEE; selection-background-color: {BLAU_HELL}; selection-color: {TEXT}; }}
QHeaderView::section {{ background: #FFFFFF; color: {TEXT2}; font-weight: 600; border: none;
    border-bottom: 1px solid {LINIE}; padding: 6px; }}
QListWidget#masterlist::item {{ padding: 8px 10px; border-bottom: 1px solid #F0F0F0; }}
QListWidget#masterlist::item:selected {{ background: {BLAU_HELL}; color: {TEXT}; border-left: 3px solid {BLAU}; }}

/* Tabs (Icon-Tab-Bar) */
QTabWidget::pane {{ border: none; background: {HG}; }}
QTabBar::tab {{ background: transparent; padding: 10px 16px; border: none; color: {TEXT2}; font-weight: 600; }}
QTabBar::tab:selected {{ color: {BLAU}; border-bottom: 3px solid {BLAU}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}

/* Message Strips */
QLabel[strip="info"] {{ background: #E1F4FF; border: 1px solid #0070F2; border-radius: 8px; padding: 8px 12px; }}
QLabel[strip="warn"] {{ background: #FFF3B8; border: 1px solid {WARN}; border-radius: 8px; padding: 8px 12px; }}
QLabel[strip="ok"] {{ background: #F5FAE5; border: 1px solid {OK}; border-radius: 8px; padding: 8px 12px; }}
QLabel[strip="error"] {{ background: #FFEAF4; border: 1px solid {FEHLER}; border-radius: 8px; padding: 8px 12px; }}

QLabel#badge_ok {{ background: #F5FAE5; color: {OK}; border-radius: 10px; padding: 2px 10px; font-weight: 600; }}
QLabel#badge_draft {{ background: #FFF3B8; color: #8D2A00; border-radius: 10px; padding: 2px 10px; font-weight: 600; }}
QLabel#badge_none {{ background: #EAECEE; color: {TEXT2}; border-radius: 10px; padding: 2px 10px; font-weight: 600; }}

QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: #C5C5C5; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{ background: #FFFFFF; border: 1px solid {LINIE}; padding: 4px; }}
"""
