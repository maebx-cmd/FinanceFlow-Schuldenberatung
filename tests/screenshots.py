"""Headless: Demo-DB anlegen, jede Seite öffnen, Screenshot speichern, Ladefehler melden.
Aufruf: QT_QPA_PLATFORM=offscreen python tests/screenshots.py <zielordner>"""
import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.excepthook = lambda *a: (traceback.print_exception(*a), None)

from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.db import DB  # noqa: E402
from app.ui.bereiche import BereichsFenster  # noqa: E402
from app.ui.navigation import BEREICHE  # noqa: E402
from app.ui.style import QSS  # noqa: E402
from tests.demo_data import befuellen  # noqa: E402

ziel = sys.argv[1] if len(sys.argv) > 1 else "/tmp/shots"
os.makedirs(ziel, exist_ok=True)
app = QApplication(sys.argv)
app.setStyle("Fusion")
app.setFont(QFont("DejaVu Sans", 9))
app.setStyleSheet(QSS)
db = DB(os.path.join(tempfile.mkdtemp(), "demo.db"))
befuellen(db)
w = BereichsFenster(db, BEREICHE)
w.resize(1440, 900)
w.show()
fehler = []
for bkey, _t, eintraege in BEREICHE:
    for e in eintraege:
        if not e:
            continue
        key = e[0]
        w.navigate(key)
        app.processEvents()
        p = w.pages[key]
        if hasattr(p, "liste") and p.liste.count():
            p.liste.setCurrentRow(0)
            app.processEvents()
        msg = getattr(p, "msg", None)
        if msg is not None and msg.isVisible() and msg.property("strip") == "error":
            fehler.append((key, msg.text()))
        app.processEvents()
        app.processEvents()
        w.grab().save(os.path.join(ziel, f"{key}.png"))
print("FEHLER:", fehler if fehler else "keine")
