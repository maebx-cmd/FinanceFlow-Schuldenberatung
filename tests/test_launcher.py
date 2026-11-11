"""Launcher nach der Anmeldung (keine Daten sichtbar) und „Beträge verbergen“."""
import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QListWidget, QTableWidget  # noqa: E402

from tests.demo_data import befuellen  # noqa: E402

APP = QApplication.instance() or QApplication([])
BETRAG = re.compile(r"\d,\d|\d\s?(€|THB|EUR)|\d\.\d{3}(?![\d.])")


@pytest.fixture
def fenster(db):
    from app.ui import diskret
    from app.ui.bereiche import BereichsFenster
    from app.ui.navigation import BEREICHE
    befuellen(db)
    db.con.execute("UPDATE setting SET value='Noah Muster' WHERE key='owner_name'")
    diskret.umschalten(False)
    w = BereichsFenster(db, BEREICHE)
    w.resize(1440, 900)
    w.show()
    APP.processEvents()
    yield w
    diskret.umschalten(False)
    w.hide()
    w.deleteLater()


def _sichtbare_betraege(w):
    out = [x.text() for x in w.findChildren(QLabel) if x.isVisibleTo(w) and BETRAG.search(x.text())]
    for t in w.findChildren(QTableWidget):
        if t.isVisibleTo(w):
            out += [t.item(r, c).text() for r in range(t.rowCount()) for c in range(t.columnCount())
                    if t.item(r, c) and BETRAG.search(t.item(r, c).text())]
    for li in w.findChildren(QListWidget):
        if li.isVisibleTo(w):
            out += [li.item(i).text() for i in range(li.count()) if BETRAG.search(li.item(i).text())]
    out += [c.currentText() for c in w.findChildren(QComboBox) if c.isVisibleTo(w) and BETRAG.search(c.currentText())]
    return out


def test_start_mit_launcher_ohne_daten(fenster):
    w = fenster
    assert w.stack.currentWidget() is w.launcher and w.wahl.currentText() == "Start"
    assert not w.nav.isVisible() and not w.shell_sub.isVisible()           # keine Navigation, kein Name
    assert _sichtbare_betraege(w) == []
    texte = " ".join(x.text() for x in w.launcher.findChildren(QLabel))
    assert "Noah" not in texte and not re.search(r"\d", texte)
    assert set(w.launcher.kacheln) >= {"bereich:finance", "kontakte", "verbindlichkeiten", "abgleich", "einstellungen"}
    assert not {"bereich:mobil", "devisen", "bereich:hr", "bereich:aviation", "bereich:tools"} & set(w.launcher.kacheln)
    assert [w.wahl.itemText(i) for i in range(w.wahl.count())] == ["Start", "FinanceFlow"]


def test_kachel_dropdown_und_logo(fenster):
    w = fenster
    w.launcher.kacheln["kontakte"].clicked.emit()
    APP.processEvents()
    assert w.wahl.currentData() == "finance" and w.nav.isVisible() and w.stack.currentWidget() is w.pages["kontakte"]
    w.launcher.kacheln["verbindlichkeiten"].clicked.emit()
    assert w.stack.currentWidget() is w.pages["verbindlichkeiten"]
    w.navigate("launcher")
    assert w.stack.currentWidget() is w.launcher and not w.nav.isVisible()
    w.wahl.setCurrentIndex(w.wahl.findData("finance"))
    assert w.stack.currentWidget() is w.pages["start"]
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    ev = QMouseEvent(QEvent.MouseButtonRelease, QPointF(2, 2), QPointF(2, 2), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(w.logo, ev)
    assert w.stack.currentWidget() is w.launcher and w.wahl.currentText() == "Start"


def test_betraege_verbergen(fenster, db):
    w = fenster
    w.navigate("start")
    APP.processEvents()
    vorher = _sichtbare_betraege(w)
    assert vorher                                                           # Übersicht zeigt Beträge
    w._diskret_umschalten()
    for key in ("start", "dashboard", "verbindlichkeiten", "offene_raten", "haushalt", "fixkosten", "privatkonkurs",
                "zahlungsplan", "forderungen", "kontoblatt"):
        w.navigate(key)
        APP.processEvents()
        assert _sichtbare_betraege(w) == [], key
    assert "•••••" in " ".join(x.text() for x in w.pages["start"].findChildren(QLabel))
    assert db.geraet_einstellung("betraege_verbergen") == "1"
    w._diskret_umschalten()
    w.navigate("start")
    APP.processEvents()
    assert sorted(_sichtbare_betraege(w)) == sorted(vorher)                 # Originale exakt zurück


def test_einstellung_wird_gemerkt(db):
    from app.ui import diskret
    from app.ui.bereiche import BereichsFenster
    from app.ui.navigation import BEREICHE
    befuellen(db)
    db.set_geraet_einstellung("betraege_verbergen", "1")
    w = BereichsFenster(db, BEREICHE)
    try:
        assert diskret.aktiv() and "zeigen" in w.b_diskret.text()
        w.navigate("verbindlichkeiten")
        w.show()
        APP.processEvents()
        assert _sichtbare_betraege(w) == []
    finally:
        diskret.umschalten(False)
        w.hide()
        w.deleteLater()


@pytest.mark.parametrize("text,erwartet", [
    ("25.465 €", "••••• €"), ("−57 €", "••••• €"), ("offen · 2.345,67 €", "offen · ••••• €"),
    ("12.000 THB / 300,00 €", "••••• THB / ••••• €"), ("12.000", "•••••"), ("Zins 3,5 %", "Zins ••••• %"),
    ("10.11.2026", "10.11.2026"), ("3 Raten", "3 Raten"), ("M-0012", "M-0012"), ("Konto 3121.01", "Konto 3121.01"),
    ("0:00", "0:00"), ("2026-11-10", "2026-11-10"),
])
def test_erkennung(text, erwartet):
    from app.ui import diskret
    diskret.umschalten(True)
    try:
        assert diskret.verdecken(text) == erwartet
    finally:
        diskret.umschalten(False)
