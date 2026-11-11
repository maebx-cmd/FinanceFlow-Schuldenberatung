"""Anmeldemaske und Ersteinrichtung (Fiori-Stil). Zeigt keine Benutzerliste an."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QFileDialog, QFrame, QLineEdit, QVBoxLayout

from .. import APP_NAME, APP_TITEL, APP_VERSION
from ..konten import SCHULDNER_KONTO, KontoFehler
from .widgets import Card, Form, button, hbox, label, set_strip, strip


class _Basis(QDialog):
    def __init__(self, titel, untertitel):
        super().__init__()
        self.setWindowTitle(f"{APP_TITEL} {APP_VERSION}")
        self.setObjectName("page")
        self.setMinimumWidth(420)
        v = QVBoxLayout(self)
        v.setContentsMargins(32, 28, 32, 28)
        v.setSpacing(10)
        logo = label("◆")
        logo.setStyleSheet("color:#0064D9; font-size:22pt;")
        v.addLayout(hbox(logo, label(APP_NAME, "h1"), label("Schuldenberatung", "sub"), None))
        v.addWidget(label(titel, "h2"))
        v.addWidget(label(untertitel, "sub", wrap=True))
        self.card = Card()
        self.form = Form(1)
        self.card.lay.addWidget(self.form)
        v.addWidget(self.card)
        self.msg = strip("")
        self.msg.setVisible(False)
        v.addWidget(self.msg)
        self.ok = button("Anmelden", emph=True, cb=self._ok)
        self.ok.setDefault(True)
        self.unten = hbox(None, button("Beenden", flat=True, cb=self.reject), self.ok)
        v.addLayout(self.unten)

    def showEvent(self, e):
        super().showEvent(e)
        # Höhe erst nach dem Stylesheet bekannt → anpassen, damit die Felder nicht zusammengedrückt werden
        self.setMinimumHeight(self.layout().sizeHint().height())
        self.adjustSize()

    def fehler(self, text):
        set_strip(self.msg, text, "error")
        self.setMinimumHeight(self.layout().sizeHint().height())
        self.adjustSize()

    def feld(self, key, text, passwort=False):
        e = QLineEdit()
        if passwort:
            e.setEchoMode(QLineEdit.Password)
        e.returnPressed.connect(self._ok)
        return self.form.add(key, text, e)

    def _ok(self):
        pass


class AnmeldeDialog(_Basis):
    def __init__(self, konten):
        self.schuldner = konten.ist_schuldner()
        super().__init__("Anmelden", "Bitte dein Passwort eingeben." if self.schuldner else
                         "Bitte Benutzername und Passwort eingeben.")
        self.konten = konten
        self.benutzer = None
        self.name = self.feld("name", "Benutzername")
        if self.schuldner:            # ein einziger Zugang: nur Passwort
            self.name.setText(SCHULDNER_KONTO)
            self.form.verbergen("name")
        self.pw = self.feld("pw", "Passwort", True)
        self.passwort = ""
        self.unten.insertWidget(0, button("Passwort vergessen …", flat=True, cb=self._vergessen))
        (self.pw if self.schuldner else self.name).setFocus()


    def _vergessen(self):
        d = VergessenDialog(self.konten, self.name.text(), schuldner=self.schuldner)
        if d.exec() == QDialog.Accepted:
            self.name.setText(d.name.text())
            self.pw.clear()
            set_strip(self.msg, "Neues Passwort gesetzt – bitte damit anmelden.", "ok")
            self.msg.setVisible(True)
            self.pw.setFocus()

    def _ok(self):
        self.ok.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            u = self.konten.anmelden(self.name.text(), self.pw.text())
        finally:
            QApplication.restoreOverrideCursor()
            self.ok.setEnabled(True)
        if not u:
            self.pw.clear()
            self.pw.setFocus()
            self.fehler("Anmeldung fehlgeschlagen. Das Passwort ist falsch." if self.schuldner else
                        "Anmeldung fehlgeschlagen. Benutzername oder Passwort ist falsch.")
            return
        self.benutzer = u
        self.passwort = self.pw.text()
        self.accept()


class _ModusKarte(QFrame):
    """Große, anklickbare Auswahlkarte mit Überschrift und umbrochenem Text."""

    def __init__(self, titel, text, cb):
        super().__init__()
        self.cb = cb
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setStyleSheet("_ModusKarte, QFrame#modus_schuldner, QFrame#modus_berater { border:1px solid #D5DADD; "
                           "border-radius:12px; background:#FFFFFF; } QFrame#modus_schuldner:hover, "
                           "QFrame#modus_berater:hover { border:2px solid #0064D9; background:#F5FAFF; }")
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        t = label(titel, "h2")
        t.setStyleSheet("border:none; background:transparent;")
        b = label(text, "sub", wrap=True)
        b.setStyleSheet("border:none; background:transparent; font-size:10.5pt;")
        v.addWidget(t)
        v.addWidget(b)

    def mouseReleaseEvent(self, e):
        self.cb()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.cb()
        else:
            super().keyPressEvent(e)


class ModusDialog(_Basis):
    """Erster Start: Wer verwendet FinanceFlow auf diesem Computer?"""

    def __init__(self):
        super().__init__("Willkommen – wer verwendet FinanceFlow?",
                         "Diese Auswahl gilt für diesen Computer und kann später nicht geändert werden.")
        self.setMinimumWidth(640)
        self.modus = None
        self.card.setVisible(False)
        self.ok.setVisible(False)
        v = self.layout()
        self.karten = {}
        for modus, titel, text in (
                ("SCHULDNER", "Ich bin Schuldnerin / Schuldner",
                 "Ich trage meine Schulden selbst ein und gebe die Datei meiner Schuldenberatung. "
                 "Ein Zugang mit Passwort – ohne Benutzer- und Mandantenverwaltung."),
                ("BERATER", "Ich bin Schuldenberaterin / Schuldenberater",
                 "Ich verwalte Mandanten und spiele die Dateien ein, die Schuldner auf ihrem eigenen Gerät erfasst haben. "
                 "Mit Benutzerverwaltung für Kolleginnen und Kollegen.")):
            k = _ModusKarte(titel, text, lambda m=modus: self._waehlen(m))
            k.setObjectName("modus_" + modus.lower())
            self.karten[modus] = k
            v.insertWidget(v.count() - 2, k)

    def _waehlen(self, modus):
        self.modus = modus
        self.accept()


class SchuldnerEinrichtungDialog(_Basis):
    """Ersteinrichtung für Schuldner: nur Name (für Ausdrucke) und Passwort."""

    def __init__(self, konten):
        super().__init__("Einrichten – dein Zugang",
                         "Deine Daten werden verschlüsselt auf diesem Computer gespeichert. Dafür brauchst du ein Passwort. "
                         "Merke es dir gut – ohne Passwort kommst du nicht mehr zu deinen Daten.")
        self.ok.setText("Einrichten")
        self.konten = konten
        self.benutzer = None
        self.anzeige = self.feld("anzeige", "Dein Name (steht auf Ausdrucken, freiwillig)")
        self.pw = self.feld("pw", "Passwort (mindestens 8 Zeichen)", True)
        self.pw2 = self.feld("pw2", "Passwort wiederholen", True)
        self.anzeige.setFocus()

    def _ok(self):
        if self.pw.text() != self.pw2.text():
            self.fehler("Die Passwörter stimmen nicht überein.")
            return
        try:
            self.benutzer = self.konten.schuldner_einrichten(self.pw.text())
        except KontoFehler as e:
            self.fehler(str(e))
            return
        if self.anzeige.text().strip():           # wird beim ersten Öffnen als Name im PDF-Kopf übernommen
            self.konten.einrichtung_setzen("anzeigename", self.anzeige.text().strip()[:120])
        self.accept()


class ErsteinrichtungDialog(_Basis):
    """Ersteinrichtung für die Schuldenberatung: Administrator-Zugang."""

    def __init__(self, konten, daten_vorhanden: bool = False):
        super().__init__("Schuldenberatung einrichten – Administrator anlegen",
                         "Lege den Administrator-Zugang an. Er kann danach Zugänge für Kolleginnen und Kollegen anlegen. "
                         "Jeder Zugang hat eigene, getrennt verschlüsselte Mandanten.")
        self.ok.setText("Anlegen")
        self.konten = konten
        self.benutzer = None
        self.name = self.feld("name", "Benutzername")
        self.name.setText("admin")
        self.pw = self.feld("pw", "Passwort (mindestens 8 Zeichen)", True)
        self.pw2 = self.feld("pw2", "Passwort wiederholen", True)
        self.pw.setFocus()

    def _ok(self):
        if self.pw.text() != self.pw2.text():
            self.fehler("Die Passwörter stimmen nicht überein.")
            return
        try:
            self.benutzer = self.konten.berater_einrichten(self.name.text(), self.pw.text())
        except KontoFehler as e:
            self.fehler(str(e))
            return
        self.accept()


class PasswortDialog(_Basis):
    """Neues Passwort festlegen (Admin setzt zurück oder legt Benutzer an)."""

    def __init__(self, titel, untertitel, mit_name=False, mit_rk=False):
        super().__init__(titel, untertitel)
        self.ok.setText("Übernehmen")
        self.name = self.feld("name", "Benutzername") if mit_name else None
        self.rk = self.feld("rk", "Wiederherstellungsschlüssel des Benutzers") if mit_rk else None
        self.pw = self.feld("pw", "Passwort (mindestens 8 Zeichen)", True)
        self.pw2 = self.feld("pw2", "Passwort wiederholen", True)
        (self.name or self.pw).setFocus()
        self.werte = None

    def _ok(self):
        if self.pw.text() != self.pw2.text():
            self.fehler("Die Passwörter stimmen nicht überein.")
            return
        self.werte = {"name": self.name.text().strip() if self.name else None, "pw": self.pw.text(),
                      "rk": self.rk.text() if self.rk else None}
        self.accept()


class VergessenDialog(_Basis):
    """Neues Passwort mit dem Wiederherstellungsschlüssel – die Daten bleiben erhalten."""

    def __init__(self, konten, name="", schuldner=False):
        super().__init__("Passwort vergessen", "Mit dem Wiederherstellungsschlüssel (beim Einrichten angezeigt, Form "
                                               "XXXX-XXXX-…) ein neues Passwort festlegen. Ohne ihn sind die Daten nicht lesbar.")
        self.ok.setText("Passwort setzen")
        self.unten.itemAt(1).widget().setText("Abbrechen")
        self.konten = konten
        self.name = self.feld("name", "Benutzername")
        self.name.setText(SCHULDNER_KONTO if schuldner else name)
        if schuldner:
            self.form.verbergen("name")
            name = SCHULDNER_KONTO
        self.rk = self.feld("rk", "Wiederherstellungsschlüssel")
        self.rk.setFont(QFont("Consolas", 10))
        self.pw = self.feld("pw", "Neues Passwort (mindestens 8 Zeichen)", True)
        self.pw2 = self.feld("pw2", "Neues Passwort wiederholen", True)
        (self.rk if name else self.name).setFocus()

    def _ok(self):
        if self.pw.text() != self.pw2.text():
            self.fehler("Die Passwörter stimmen nicht überein.")
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.konten.passwort_vergessen(self.name.text(), self.rk.text(), self.pw.text())
        except KontoFehler as e:
            self.fehler(str(e))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.accept()


class WiederherstellungDialog(_Basis):
    """Zeigt den Wiederherstellungsschlüssel einmalig an. Weiter erst nach Bestätigung."""

    def __init__(self, rk: str, fuer: str = "", titel="Wiederherstellungsschlüssel – bitte notieren"):
        wer = f" für „{fuer}“" if fuer else ""
        super().__init__(titel, f"Die Daten{wer} sind verschlüsselt. Mit diesem Schlüssel lässt sich ein vergessenes Passwort "
                                "ersetzen. Er wird nur jetzt angezeigt. Ohne Passwort UND ohne diesen Schlüssel sind die Daten "
                                "endgültig verloren – auch für den Administrator. Ausdrucken oder notieren und getrennt vom "
                                "Laptop aufbewahren.")
        self.rk = rk
        self.setMinimumWidth(560)
        f = QLineEdit(rk)
        f.setReadOnly(True)
        f.setAlignment(Qt.AlignCenter)
        f.setFont(QFont("Consolas", 15, QFont.Bold))
        f.setMinimumHeight(44)
        self.form.add("rk", "Wiederherstellungsschlüssel", f)
        self.card.lay.addLayout(hbox(button("In Zwischenablage kopieren", cb=self._kopieren),
                                     button("Als Textdatei speichern …", cb=self._speichern), None))
        self.haken = QCheckBox("Ich habe den Wiederherstellungsschlüssel sicher notiert.")
        self.haken.toggled.connect(lambda an: self.ok.setEnabled(an))
        self.card.lay.addWidget(self.haken)
        self.ok.setText("Weiter")
        self.ok.setEnabled(False)
        self.unten.itemAt(1).widget().setVisible(False)       # kein „Beenden“ – der Schlüssel ist bereits gültig

    def reject(self):
        if self.haken.isChecked():
            self.accept()

    def _kopieren(self):
        QApplication.clipboard().setText(self.rk)
        set_strip(self.msg, "Kopiert. Zwischenablage danach leeren (anderen Text kopieren).", "info")
        self.msg.setVisible(True)

    def _speichern(self):
        pfad, _ = QFileDialog.getSaveFileName(self, "Wiederherstellungsschlüssel speichern",
                                              os.path.join(os.path.expanduser("~"), "FinanceFlow-Wiederherstellung.txt"),
                                              "Textdatei (*.txt)")
        if not pfad:
            return
        with open(pfad, "w", encoding="utf-8") as f:
            f.write(f"FinanceFlow – Wiederherstellungsschlüssel\n\n{self.rk}\n\nNicht auf demselben Laptop aufbewahren "
                    "(USB-Stick, Ausdruck, Passwort-Manager).\n")
        set_strip(self.msg, f"Gespeichert: {pfad} – am besten auf einen USB-Stick verschieben oder ausdrucken.", "warn")
        self.msg.setVisible(True)

    def _ok(self):
        if self.haken.isChecked():
            self.accept()
