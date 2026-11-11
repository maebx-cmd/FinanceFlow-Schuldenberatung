"""Mandantenübersicht der Schuldenberatung (nach der Anmeldung, Modus BERATER).

Von hier aus: Mandant anlegen/bearbeiten/archivieren/löschen, Datenstand eines Mandanten öffnen, die Abgleich-Datei
eines Schuldners einspielen (bestehender oder neuer Mandant), eine Datei für den Schuldner erstellen, Zugang und
Benutzer verwalten. Ergebnis: self.ergebnis = "oeffnen" (self.mandant_id) | "abmelden" | None (Beenden).
"""
from __future__ import annotations

import os
from contextlib import contextmanager

from PySide6.QtCore import QLockFile, Qt
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QLineEdit, QMessageBox, QVBoxLayout

from .. import APP_NAME, APP_TITEL, APP_VERSION
from ..mandanten import MandantFehler
from .common import Tabelle, dat, dialog, frage
from .pages import abgleich as agl
from .widgets import Card, button, combo, hbox, label, set_strip, strip

FELDER = [("name", "Name (Vor- und Nachname)", "text"), ("aktenzeichen", "Aktenzeichen / Klientennummer", "text"),
          ("geburtsdatum", "Geburtsdatum", "date"), ("telefon", "Telefon", "text"), ("email", "E-Mail", "text"),
          ("notiz", "Notiz", "multi")]


class _Sperre(Exception):
    pass


class MandantenFenster(QDialog):
    def __init__(self, verwaltung, konten, ich: dict):
        super().__init__()
        self.verw, self.konten, self.ich = verwaltung, konten, ich
        self.ergebnis = None
        self.mandant_id = None
        self.setWindowTitle(f"{APP_TITEL} {APP_VERSION} – Mandanten")
        self.setObjectName("page")
        self.resize(1280, 820)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinMaxButtonsHint)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        shell = QFrame()
        shell.setObjectName("shellbar")
        shell.setFixedHeight(52)
        logo = label("◆")
        logo.setStyleSheet("color:#0064D9; font-size:18pt;")
        rechts = [label(f"  {ich['name']}", "shellsub"), button("Smartphone-Version …", flat=True, cb=self._smartphone),
                  button("Handbuch", flat=True, cb=self._handbuch),
                  button("Zugang && Benutzer …", flat=True, cb=self._zugang), button("Abmelden", flat=True, cb=self._abmelden)]
        sh = hbox(logo, label(APP_NAME, "shelltitle"), label("Schuldenberatung", "shellsub"), None, *rechts)
        sh.setContentsMargins(16, 0, 16, 0)
        shell.setLayout(sh)
        root.addWidget(shell)

        head = QFrame()
        head.setObjectName("objheader")
        hv = QVBoxLayout(head)
        hv.setContentsMargins(24, 16, 24, 10)
        hv.addLayout(hbox(label("Mandanten", "h1"), None,
                          button("+ Neu aus Datei des Schuldners …", cb=self.neu_aus_datei),
                          button("+ Neuer Mandant", emph=True, cb=self.neu)))
        hv.addWidget(label("Jeder Mandant hat einen eigenen, verschlüsselten Datenstand. Den Stand, den ein Schuldner auf "
                           "seinem eigenen Gerät erfasst hat, über „Datei des Schuldners einspielen“ übernehmen.", "sub", wrap=True))
        self.msg = strip("")
        self.msg.setVisible(False)
        self.msg.setTextInteractionFlags(Qt.TextSelectableByMouse)
        hv.addWidget(self.msg)
        root.addWidget(head)

        body = QVBoxLayout()
        body.setContentsMargins(24, 16, 24, 24)
        body.setSpacing(12)
        c = Card()
        self.suche = QLineEdit()
        self.suche.setPlaceholderText("Suchen (Name, Aktenzeichen, Notiz)")
        self.suche.textChanged.connect(self.laden)
        self.filter = combo([("AKTIV", "Aktive Mandanten"), ("ARCHIV", "Archiv")])
        self.filter.currentIndexChanged.connect(self.laden)
        self.anzahl = label("", "sub")
        c.lay.addLayout(hbox(self.suche, self.filter, None, self.anzahl))
        self.t = Tabelle(["Name", "Aktenzeichen", "Geburtsdatum", "Letzte Datei vom Schuldner", "Datenstand vom",
                          "Letzte Datei an Schuldner", "Notiz"], [230, 150, 110, 210, 140, 170, None])
        self.t.setMinimumHeight(420)
        self.t.aktiviert.connect(lambda mid: mid and self.oeffnen(mid))
        c.lay.addWidget(self.t, 1)
        c.lay.addLayout(hbox(button("Öffnen", emph=True, cb=lambda: self.oeffnen(self._sel())),
                             button("Datei des Schuldners einspielen …", cb=self.einspielen),
                             button("Datei für Schuldner erstellen …", cb=self.datei_erstellen),
                             None,
                             button("Bearbeiten …", cb=self.bearbeiten),
                             button("Protokoll", flat=True, cb=self.protokoll),
                             button("Archivieren / Reaktivieren", flat=True, cb=self.archivieren),
                             button("Löschen …", flat=True, neg=True, cb=self.loeschen)))
        body.addWidget(c, 1)
        root.addLayout(body, 1)
        self.laden()

    # ── Anzeige ──────────────────────────────────────────────────────────────
    def meldung(self, text, art="info"):
        set_strip(self.msg, text, art)

    def laden(self):
        archiv = self.filter.currentData() == "ARCHIV"
        ms = self.verw.liste(archiv, self.suche.text())
        z = lambda v: (v or "")[:16].replace("T", " ")
        rows = []
        for m in ms:
            imp = f"{z(m['letzter_import'])} · {m['import_geraet']}" if m["letzter_import"] else "– noch keine –"
            rows.append([(m["name"], None, True), m["aktenzeichen"] or "", dat(m["geburtsdatum"]) if m["geburtsdatum"] else "",
                         imp, z(m["import_stand"]), z(m["letzter_export"]) or "–", (m["notiz"] or "").replace("\n", " ")[:80]])
        self.t.set_rows(rows, [m["id"] for m in ms])
        n = self.verw.anzahl()
        self.anzahl.setText(f"{n.get('AKTIV', 0)} aktiv · {n.get('ARCHIV', 0)} im Archiv")

    def _sel(self, warnen=True):
        mid = self.t.sel_id()
        if not mid and warnen:
            self.meldung("Bitte zuerst einen Mandanten in der Liste markieren.", "warn")
        return mid

    # ── Mandanten-Datenbank kurz öffnen (für Einspielen / Datei erstellen) ─────
    @contextmanager
    def _mandant_db(self, mid):
        pfad = self.verw.db_pfad(mid)
        lock = QLockFile(pfad + ".lock")
        lock.setStaleLockTime(0)
        if not lock.tryLock(100):
            raise _Sperre("Dieser Mandant ist gerade geöffnet (anderes Fenster oder anderer Benutzer).")
        db = None
        try:
            db = self.verw.oeffnen(mid)
            db.benutzer, db.modus, db.mandanten_verwaltung = self.ich, "BERATER", self.verw
            yield db
        finally:
            if db is not None:
                db.con.close()
            lock.unlock()

    # ── Aktionen ─────────────────────────────────────────────────────────────
    def oeffnen(self, mid):
        if not mid:
            return
        self.mandant_id = mid
        self.ergebnis = "oeffnen"
        self.accept()

    def neu(self):
        w = dialog(self, "Neuer Mandant", FELDER, {})
        if not w:
            return None
        try:
            m = self.verw.anlegen(w)
        except MandantFehler as e:
            self.meldung(str(e), "error")
            return None
        self.laden()
        self._markieren(m["id"])
        self.meldung(f"Mandant „{m['name']}“ angelegt. Jetzt öffnen oder die Datei des Schuldners einspielen.", "ok")
        return m

    def _markieren(self, mid):
        if mid in self.t.ids:
            self.t.selectRow(self.t.ids.index(mid))

    def bearbeiten(self):
        mid = self._sel()
        if not mid:
            return
        m = self.verw.get(mid)
        w = dialog(self, "Mandant bearbeiten", FELDER, m)
        if not w:
            return
        try:
            self.verw.aendern(mid, w)
        except MandantFehler as e:
            self.meldung(str(e), "error")
            return
        self.laden()
        self._markieren(mid)
        self.meldung("Gespeichert.", "ok")

    def archivieren(self):
        mid = self._sel()
        if not mid:
            return
        m = self.verw.get(mid)
        self.verw.archivieren(mid, m["status"] == "AKTIV")
        self.laden()
        self.meldung(f"„{m['name']}“ {'ins Archiv verschoben' if m['status'] == 'AKTIV' else 'wieder aktiv'}.", "ok")

    def loeschen(self):
        mid = self._sel()
        if not mid:
            return
        m = self.verw.get(mid)
        if not frage(self, "Mandant löschen", f"Mandant „{m['name']}“ löschen? Er verschwindet aus der Liste; der Datenordner "
                                              "wird nach „Gelöschte Mandanten“ verschoben (nicht vernichtet)."):
            return
        try:
            z = self.verw.loeschen(mid)
        except OSError as e:
            self.meldung(f"Löschen nicht möglich (Mandant geöffnet?): {e}", "error")
            return
        self.laden()
        self.meldung(f"„{m['name']}“ gelöscht. Daten verschoben nach: {z or '–'}", "ok")

    def protokoll(self):
        mid = self._sel()
        if not mid:
            return
        m = self.verw.get(mid)
        d = QDialog(self)
        d.setWindowTitle(f"Protokoll – {m['name']}")
        d.resize(760, 420)
        v = QVBoxLayout(d)
        t = Tabelle(["Zeit", "Aktion", "Details", "Benutzer"], [140, 110, None, 140])
        t.set_rows([[(p["zeit"] or "")[:16].replace("T", " "), p["aktion"], p["details"] or "", p["benutzer"] or ""]
                    for p in self.verw.protokoll(mid)])
        v.addWidget(t)
        v.addLayout(hbox(None, button("Schließen", emph=True, cb=d.accept)))
        d.exec()

    def einspielen(self, mid=None):
        mid = mid or self._sel()
        if not mid:
            return False
        pfad = agl.datei_waehlen(self)
        if not pfad:
            return False
        nutz = agl.datei_lesen(self, pfad, self.meldung)
        if nutz is None:
            return False
        return self._einspielen(mid, nutz, pfad, nachfrage=True)

    def _einspielen(self, mid, nutz, pfad, nachfrage):
        m = self.verw.get(mid)
        i = agl.ab.info(nutz)
        if nachfrage and i["name"] and i["name"].casefold() != m["name"].casefold():
            if not frage(self, "Anderer Name", f"Die Datei gehört laut PDF-Kopf zu „{i['name']}“, der Mandant heißt "
                                               f"„{m['name']}“. Trotzdem bei „{m['name']}“ einspielen?"):
                return False
        try:
            with self._mandant_db(mid) as db:
                QApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    ok = agl.einspielen(self, db, nutz, pfad, self.meldung, nachfrage=nachfrage)
                finally:
                    QApplication.restoreOverrideCursor()
        except _Sperre as e:
            self.meldung(str(e), "error")
            return False
        self.laden()
        self._markieren(mid)
        if ok:
            self.meldung(f"Datenstand von „{nutz.get('device')}“ ({(nutz.get('exportedAt') or '')[:16].replace('T', ' ')}) "
                         f"bei „{m['name']}“ eingespielt – {i['glaeubiger']} Kontakte, {i['verbindlichkeiten']} offene "
                         "Verbindlichkeiten.", "ok")
        return ok

    def neu_aus_datei(self):
        pfad = agl.datei_waehlen(self)
        if not pfad:
            return None
        nutz = agl.datei_lesen(self, pfad, self.meldung)
        if nutz is None:
            return None
        i = agl.ab.info(nutz)
        if QMessageBox.question(self, "Neuer Mandant aus Datei", agl.info_text(nutz) + "\n\nNeuen Mandanten anlegen und "
                                "diesen Datenstand einspielen?", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return None
        w = dialog(self, "Neuer Mandant", FELDER, {"name": i["name"]})
        if not w:
            return None
        try:
            m = self.verw.anlegen(w)
        except MandantFehler as e:
            self.meldung(str(e), "error")
            return None
        if not self._einspielen(m["id"], nutz, pfad, nachfrage=False):
            self.meldung(f"Mandant „{m['name']}“ angelegt, die Datei wurde aber nicht eingespielt.", "warn")
        return m

    def datei_erstellen(self):
        mid = self._sel()
        if not mid:
            return False
        try:
            with self._mandant_db(mid) as db:
                ok = agl.export_ablauf(self, db, self.meldung)
        except _Sperre as e:
            self.meldung(str(e), "error")
            return False
        self.laden()
        self._markieren(mid)
        return ok

    def _zugang(self):
        from .zugang import ZugangDialog
        ZugangDialog(self, self.konten, self.ich).exec()

    def _handbuch(self):
        from .. import hilfe
        if not hilfe.oeffnen("berater", os.path.dirname(self.verw.path)):
            QMessageBox.information(self, "Handbuch", "Das Handbuch ist in dieser Installation nicht enthalten.")

    def _smartphone(self):
        """Smartphone-Version (HTML) speichern, um sie einem Schuldner ohne Computer zu schicken oder online abzulegen."""
        import shutil
        from PySide6.QtWidgets import QFileDialog
        from .. import hilfe
        q = hilfe.smartphone_pfad()
        if not q:
            QMessageBox.information(self, "Smartphone-Version", "Die Smartphone-Version ist in dieser Installation nicht enthalten.")
            return
        ziel, _ = QFileDialog.getSaveFileName(self, "Smartphone-Version speichern",
                                              os.path.join(os.path.expanduser("~"), "Downloads", hilfe.SMARTPHONE),
                                              "HTML-Datei (*.html)")
        if not ziel:
            return
        try:
            shutil.copyfile(q, ziel)
        except OSError as e:
            self.meldung(f"Speichern nicht möglich: {e}", "error")
            return
        self.meldung(f"Gespeichert: {ziel} – per E-Mail an den Schuldner schicken (Android: mit Chrome öffnen) oder auf einem "
                     "Webspeicher ablegen und den Link schicken (iPhone). Online-Fassung: https://maebx-cmd.github.io/FinanceFlow-Light/ Daten verlassen das Handy nur als verschlüsselte Datei.",
                     "ok")

    def _abmelden(self):
        self.ergebnis = "abmelden"
        self.accept()
