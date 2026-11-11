"""Seite „Abgleich“: verschlüsselte Datei *.ffsync zwischen Schuldner und Schuldenberatung (oder anderen Geräten)."""
from __future__ import annotations

import os

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QLineEdit, QMessageBox, QVBoxLayout

from ...abgleich import abgleich as ab
from ...abgleich.krypto import AbgleichFehler
from ..common import Card, Seite, hbox, label
from ..widgets import button


def ist_mandant(db) -> bool:
    return getattr(db, "mandant", None) is not None


class PasswortAbfrage(QDialog):
    def __init__(self, parent, titel, zweimal: bool, info: str = ""):
        super().__init__(parent)
        self.setWindowTitle(titel)
        self.setMinimumWidth(460)
        v = QVBoxLayout(self)
        if info:
            v.addWidget(label(info, "sub", wrap=True))
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText("Passwort (mind. 12 Zeichen)")
        v.addWidget(label("Passwort der Abgleich-Datei", "formlabel"))
        v.addWidget(self.pw)
        self.pw2 = None
        if zweimal:
            self.pw2 = QLineEdit()
            self.pw2.setEchoMode(QLineEdit.Password)
            self.pw2.setPlaceholderText("Passwort wiederholen")
            v.addWidget(label("Passwort wiederholen", "formlabel"))
            v.addWidget(self.pw2)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)


class AbgleichSeite(Seite):
    TITEL = "Abgleich"
    UNTERTITEL = "Verschlüsselte Abgleich-Datei (*.ffsync, AES-256-GCM) – per Datei (USB-Stick, E-Mail), ohne Server"

    def __init__(self, state):
        super().__init__(state)
        mandant = ist_mandant(self.db)
        c = Card("Stand")
        self.st = label("", "sub")
        c.lay.addWidget(self.st)
        c.lay.addWidget(label(
            "Die Datei des Schuldners ersetzt beim Einspielen den Datenstand dieses Mandanten vollständig. Vorher wird "
            "automatisch gesichert. Geändertes immer als neue Datei an den Schuldner zurückgeben, damit beide Seiten "
            "denselben Stand haben." if mandant else
            "So kommen deine Daten zur Schuldenberatung: Datei erstellen, ein Passwort ausdenken (mindestens 12 Zeichen) und "
            "die Datei deiner Beraterin oder deinem Berater geben – zum Beispiel per E-Mail oder USB-Stick. Das Passwort "
            "sagst du ihr bzw. ihm getrennt davon, am besten am Telefon oder persönlich.", "sub", wrap=True))
        self.body.addWidget(c)
        c2 = Card("Datei erstellen")
        self.geraet = QLineEdit()
        self.geraet.setMaximumWidth(260)
        self.geraet.editingFinished.connect(self._geraet_speichern)
        c2.lay.addLayout(hbox(label("Absender (Name dieses Geräts)", "formlabel"), self.geraet, None))
        c2.lay.addWidget(label("Die Datei enthält den gesamten Datenstand und ist mit dem Passwort verschlüsselt. Das Passwort "
                               "wird nirgends gespeichert – ohne Passwort ist die Datei nicht lesbar.", "sub", wrap=True))
        c2.lay.addLayout(hbox(button("Datei für den Schuldner erstellen …" if mandant else
                                     "Datei für die Schuldenberatung erstellen …", emph=True, cb=self.exportieren), None))
        self.body.addWidget(c2)
        c3 = Card("Datei einspielen")
        c3.lay.addWidget(label("Die Datei ersetzt den Stand auf diesem Gerät vollständig. Vorher wird automatisch gesichert.",
                               "sub", wrap=True))
        c3.lay.addLayout(hbox(button("Datei des Schuldners einspielen …" if mandant else
                                     "Datei der Schuldenberatung einspielen …", cb=self.importieren), None))
        self.body.addWidget(c3)
        self.body.addStretch()

    def _geraet_speichern(self):
        name = self.geraet.text().strip() or geraet_name(self.db)
        self.db.set_geraet_einstellung("geraet", name)

    def refresh(self):
        self.geraet.setText(geraet_name(self.db))
        self.st.setText(ab.status_text(ab.status(self.db)["finanzen"]))

    def exportieren(self) -> bool:
        self._geraet_speichern()
        ok = datei_exportieren(self)
        self.refresh()
        return ok

    def importieren(self):
        if datei_importieren(self):
            self.refresh()


# ── Abläufe, auch von Einstellungen → Datensicherung und der Mandantenübersicht genutzt ─────
def geraet_name(db) -> str:
    gespeichert = db.geraet_einstellung("geraet", "")
    if gespeichert:
        return gespeichert
    if ist_mandant(db) and getattr(db, "benutzer", None):
        return f"Schuldenberatung-{db.benutzer['name']}"
    return ab.geraetename_standard()


def _vermerken(db, richtung, geraet="", stand="", datei=""):
    verw = getattr(db, "mandanten_verwaltung", None)
    if verw is not None and ist_mandant(db):
        verw.vermerken(db.mandant["id"], richtung, geraet, stand, datei)


def passwort_fuer_export(parent):
    d = PasswortAbfrage(parent, "Abgleich-Datei erstellen", True,
                        "Denk dir ein Passwort aus (mindestens 12 Zeichen) und gib es getrennt von der Datei weiter.")
    while True:
        if d.exec() != QDialog.Accepted:
            return None
        try:
            ab.pruefe_passwort(d.pw.text(), d.pw2.text())
            return d.pw.text()
        except AbgleichFehler as e:
            QMessageBox.warning(parent, "Abgleich", str(e))


def speicherort(parent, geraet, name_zusatz=""):
    datei = ab.dateiname(f"{name_zusatz}-{geraet}" if name_zusatz else geraet)
    vorschlag = os.path.join(os.path.expanduser("~"), "Downloads", datei)
    if not os.path.isdir(os.path.dirname(vorschlag)):
        vorschlag = datei
    pfad, _ = QFileDialog.getSaveFileName(parent, "Abgleich-Datei speichern", vorschlag, "FinanceFlow-Abgleich (*.ffsync)")
    if pfad and not pfad.lower().endswith(".ffsync"):
        pfad += ".ffsync"
    return pfad


def export_ablauf(parent, db, meldung) -> bool:
    """Passwort zweimal → Speicherort → *.ffsync."""
    geraet = geraet_name(db)
    pw = passwort_fuer_export(parent)
    if pw is None:
        return False
    zusatz = (db.mandant.get("name") or "") if ist_mandant(db) else ""
    pfad = speicherort(parent, geraet, zusatz)
    if not pfad:
        return False
    try:
        ab.exportieren(db, pfad, pw, geraet)
        _vermerken(db, "Export", geraet, datei=pfad)
    except (AbgleichFehler, OSError) as e:
        meldung(f"Export fehlgeschlagen: {e}", "error")
        return False
    meldung(f"Verschlüsselte Datei erstellt: {pfad}", "ok")
    return True


def datei_exportieren(seite) -> bool:
    return export_ablauf(seite, seite.db, seite.meldung)


def datei_waehlen(parent):
    pfad, _ = QFileDialog.getOpenFileName(parent, "Abgleich-Datei öffnen", os.path.join(os.path.expanduser("~"), "Downloads"),
                                          "FinanceFlow-Abgleich (*.ffsync);;Alle Dateien (*)")
    return pfad


def datei_lesen(parent, pfad, meldung):
    """Passwort abfragen und Datei entschlüsseln. Gibt den Inhalt oder None zurück."""
    d = PasswortAbfrage(parent, "Abgleich-Datei einspielen", False, os.path.basename(pfad))
    if d.exec() != QDialog.Accepted:
        return None
    try:
        return ab.lesen(pfad, d.pw.text())
    except AbgleichFehler as e:
        meldung(str(e), "error")
        return None


def info_text(nutz) -> str:
    i = ab.info(nutz)
    zeit = i["exportiert"][:16].replace("T", " ")
    return (f"Name in der Datei: {i['name'] or '–'}\nErstellt am: {zeit} auf „{i['geraet']}“ ({i['edition']})\n"
            f"Kontakte: {i['glaeubiger']} · offene Verbindlichkeiten: {i['verbindlichkeiten']}")


def einspielen(parent, db, nutz, pfad, meldung, nachfrage=True) -> bool:
    """Konfliktprüfung + Import in db. Gibt True bei Erfolg zurück."""
    if nachfrage:
        if QMessageBox.question(parent, "Datei einspielen", info_text(nutz) + "\n\nDiese Datei einspielen? Der bisherige "
                                "Datenstand wird ersetzt (vorher automatische Sicherung).",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return False
    trotz = False
    if ab.konflikte(db):
        box = QMessageBox(QMessageBox.Warning, "Abgleich", ab.warnung())
        b_exp = box.addButton("Zuerst exportieren", QMessageBox.AcceptRole)
        b_trotz = box.addButton("Trotzdem einspielen", QMessageBox.DestructiveRole)
        box.addButton("Abbrechen", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is b_exp:
            if not export_ablauf(parent, db, meldung):
                return False
        elif box.clickedButton() is not b_trotz:
            return False
        trotz = True
    try:
        ab.importieren(db, nutz, trotz_aenderungen=trotz)
        _vermerken(db, "Import", nutz.get("device") or "", nutz.get("exportedAt") or "", pfad)
    except (AbgleichFehler, ValueError) as e:
        meldung(f"Einspielen abgebrochen, nichts geändert: {e}", "error")
        return False
    meldung(f"Eingespielt von „{nutz.get('device')}“ ({nutz.get('exportedAt', '')[:16].replace('T', ' ')}).", "ok")
    return True


def datei_importieren(seite) -> bool:
    pfad = datei_waehlen(seite)
    if not pfad:
        return False
    nutz = datei_lesen(seite, pfad, seite.meldung)
    if nutz is None:
        return False
    if not einspielen(seite, seite.db, nutz, pfad, seite.meldung):
        return False
    seite.state.daten_geaendert.emit()
    return True
