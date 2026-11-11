"""Hauptfenster mit Bereichsumschaltung in der Shell Bar (Schuldenberatungs-Ausgabe: nur FinanceFlow).

Baut auf dem unveränderten MainWindow aus shell.py auf: alle Seiten liegen im Stack, die Seitennavigation
zeigt nur die Einträge des gewählten Bereichs (entspricht Launcher + Modul-Layouts der Web-Version).
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QListWidgetItem

from . import diskret
from .pages.launcher import LauncherSeite
from .shell import MainWindow
from .widgets import combo, combo_set

LAUNCHER = "launcher"


class BereichsFenster(MainWindow):
    def __init__(self, db, bereiche):
        """bereiche: [(key, titel, [(seitenkey, titel, klasse) | None, ...])]"""
        self.bereich_von = {}
        nav = []
        for bkey, _btitel, eintraege in bereiche:
            if nav:
                nav.append(None)
            for e in eintraege:
                nav.append(e)
                if e:
                    self.bereich_von.setdefault(e[0], bkey)
        self._nav_def = nav
        self._sep_bereich = []
        cur = None
        for e in nav:
            if e is None:
                self._sep_bereich.append(cur)
            else:
                cur = self.bereich_von[e[0]]
        self.wahl = combo([(LAUNCHER, "Start")] + [(b[0], b[1]) for b in bereiche])
        self.wahl.setMinimumWidth(190)
        rechts = [self.wahl]
        self.abgemeldet = False
        self.mandant_wechseln = False
        self.modus = getattr(db, "modus", None)
        benutzer = getattr(db, "benutzer", None)
        mandant = getattr(db, "mandant", None)
        from .widgets import button, label
        if mandant:
            self.l_mandant = label(f"  Mandant: {mandant['name']}", "shellsub")
            rechts += [self.l_mandant, button("‹ Mandanten", flat=True, cb=self.zu_mandanten)]
        if benutzer:
            if self.modus != "SCHULDNER":
                rechts.append(label(f"  {benutzer['name']}", "shellsub"))
            rechts.append(button("Abmelden", flat=True, cb=self.abmelden))
        from .widgets import button as _b
        rechts.insert(1, _b("Abgleich", flat=True, cb=lambda: self.navigate("abgleich")))
        self.b_diskret = _b("", flat=True, cb=self._diskret_umschalten)
        self.b_diskret.setToolTip("Beträge in der Anzeige verbergen bzw. wieder zeigen (Strg+B)")
        rechts.insert(1, self.b_diskret)
        self.db = db
        diskret.umschalten(self._diskret_gemerkt())
        self._diskret_text()
        super().__init__(db, nav, shell_rechts=rechts)
        # Launcher: eigene Seite im Stapel, oberster Eintrag der Navigation, sonst ohne Daten
        self.launcher = LauncherSeite(self._oeffnen, self.modus, db)
        self.pages[LAUNCHER] = self.launcher
        self.stack.addWidget(self.launcher)
        it = QListWidgetItem("‹  Start")
        it.setData(Qt.UserRole, LAUNCHER)
        self.nav.insertItem(0, it)
        self.logo.setCursor(Qt.PointingHandCursor)
        self.logo.setToolTip("Zum Start")
        self.logo.installEventFilter(self)
        from PySide6.QtGui import QKeySequence, QShortcut
        QShortcut(QKeySequence("Ctrl+B"), self, activated=self._diskret_umschalten)
        from PySide6.QtCore import QSize
        for i in range(self.nav.count()):
            if self.nav.item(i).data(Qt.UserRole) is None:
                self.nav.item(i).setSizeHint(QSize(10, 10))
        self.shell_sub.setText("" if mandant else db.setting("owner_name", ""))
        self.wahl.currentIndexChanged.connect(lambda _i: self.bereich(self.wahl.currentData()))
        self.bereich(LAUNCHER)          # nach der Anmeldung immer zuerst der Launcher – keine Daten sichtbar
        if self.modus == "SCHULDNER" and db.geraet_einstellung("einfuehrung_gesehen", "") != "1":
            from PySide6.QtCore import QTimer
            QTimer.singleShot(300, self.einfuehrung)

    # ── Launcher ──────────────────────────────────────────────────────────────
    def eventFilter(self, obj, e):
        if obj is self.logo and e.type() == QEvent.MouseButtonRelease:
            self.bereich(LAUNCHER)
            return True
        return super().eventFilter(obj, e)

    def _oeffnen(self, ziel: str):
        if ziel.startswith("aktion:"):
            aktion = ziel.split(":", 1)[1]
            if aktion == "einfuehrung":
                self.einfuehrung()
            elif aktion == "mandanten":
                self.zu_mandanten()
            elif aktion.startswith("hilfe_"):
                self.hilfe(aktion.split("_", 1)[1])
            return
        if ziel.startswith("bereich:"):
            self.bereich(ziel.split(":", 1)[1])
        else:
            self.navigate(ziel)

    # ── Einführung, Anleitung, Mandanten ──────────────────────────────────────
    def einfuehrung(self):
        from .einfuehrung import EinfuehrungDialog
        d = EinfuehrungDialog(self)
        d.exec()
        try:
            self.db.set_geraet_einstellung("einfuehrung_gesehen", "1")
        except Exception:  # noqa: BLE001 – nur ein Merker
            pass
        if d.ziel == "kontakte_neu":
            self.navigate("kontakte")
            self.pages["kontakte"].neu()

    def hilfe(self, art):
        from .. import hilfe
        import os
        if not hilfe.oeffnen(art, os.path.dirname(os.path.abspath(self.db.path))):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Anleitung", "Die Anleitung ist in dieser Installation nicht enthalten.")

    def zu_mandanten(self):
        self.mandant_wechseln = True
        self.close()

    # ── Beträge verbergen ─────────────────────────────────────────────────────
    def _diskret_gemerkt(self) -> bool:
        try:
            return self.db.geraet_einstellung("betraege_verbergen", "0") == "1"
        except Exception:  # noqa: BLE001 – nur eine Anzeige-Einstellung
            return False

    def _diskret_text(self):
        self.b_diskret.setText("◉  Beträge zeigen" if diskret.aktiv() else "◎  Beträge verbergen")

    def _diskret_umschalten(self):
        an = diskret.umschalten()
        self._diskret_text()
        try:   # Anzeige-Einstellung dieses Geräts (nicht Teil des Abgleichs)
            self.db.set_geraet_einstellung("betraege_verbergen", "1" if an else "0")
        except Exception:  # noqa: BLE001
            pass

    def abmelden(self):
        self.abgemeldet = True
        self.close()

    def closeEvent(self, e):
        super().closeEvent(e)
        from PySide6.QtWidgets import QApplication
        QApplication.instance().quit()

    def bereich(self, key, seite=None):
        self.wahl.blockSignals(True)
        combo_set(self.wahl, key)
        self.wahl.blockSignals(False)
        start = key == LAUNCHER
        self.nav.setVisible(not start)
        self.shell_sub.setVisible(not start)        # Name im PDF-Kopf nicht am Start zeigen
        if start:
            MainWindow.navigate(self, LAUNCHER)
            return
        sep_i = 0
        erster = None
        for i in range(self.nav.count()):
            it = self.nav.item(i)
            k = it.data(Qt.UserRole)
            if k is None:
                # Trenner: innerhalb eines Bereichs sichtbar, Bereichsgrenzen ausblenden
                b = self._sep_bereich[sep_i] if sep_i < len(self._sep_bereich) else None
                nxt = self.nav.item(i + 1).data(Qt.UserRole) if i + 1 < self.nav.count() else None
                it.setHidden(not (b == key and nxt and self.bereich_von.get(nxt) == key))
                sep_i += 1
                continue
            sichtbar = self.bereich_von.get(k) == key or k == LAUNCHER
            it.setHidden(not sichtbar)
            if sichtbar and erster is None and k != LAUNCHER:
                erster = k
        ziel = seite or erster
        if ziel:
            MainWindow.navigate(self, ziel)

    def navigate(self, key):
        if key == LAUNCHER:
            self.bereich(LAUNCHER)
            return
        b = self.bereich_von.get(key)
        if b and b != self.wahl.currentData():
            self.wahl.blockSignals(True)
            self.bereich(b, key)
            self.wahl.blockSignals(False)
        else:
            MainWindow.navigate(self, key)
