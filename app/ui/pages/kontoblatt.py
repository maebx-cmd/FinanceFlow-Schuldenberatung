"""Seite „Kontoblatt-Import“ (nur EXE): neue Buchungen aus einem Kontoblatt (CSV) als Korrekturen bei Verbindlichkeiten."""
from __future__ import annotations

import os
from decimal import Decimal

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFileDialog, QGridLayout, QHeaderView, QTableWidget,
                               QTableWidgetItem, QWidget, QHBoxLayout)

from ...db_base import FachFehler
from ...services import kontoblatt as kb
from .. import diskret
from ..common import Card, Seite, eur, frage, hbox, label
from ..widgets import combo, combo_set

SPALTEN = ["Ignorieren", "Status", "Datum", "Beleg", "Konto", "Text", "Gegenkonto", "Soll", "Haben", "Änderung Saldo",
           "Korrekturart"]
BREITEN = [80, 200, 84, 110, 74, 0, 160, 84, 84, 116, 190]
STATUS_FARBE = {kb.NEU: "#0A6ED1", kb.FEHLT: "#E9730C", kb.GEBUCHT: "#107E3E", kb.IGNORIERT: "#6A6D70", kb.NULL: "#6A6D70"}
GRAU = "#6A6D70"


class KontoblattSeite(Seite):
    TITEL = "Kontoblatt-Import"
    UNTERTITEL = ("Neue Buchungen aus einem Kontoblatt (CSV aus der Buchhaltung, inkl. Subkonten) als Korrekturen bei den "
                  "zugeordneten Verbindlichkeiten einbuchen – Gebuchtes und Ignoriertes wird gemerkt")

    def __init__(self, state):
        super().__init__(state)
        self.zeilen: list[kb.Zeile] = []
        self.vorschau: list[dict] = []
        self.datei = ""
        self.wahl: dict = {}            # schluessel → {"ignorieren": bool, "typ": str}
        self.aktion("Kontoblatt öffnen …", self.oeffnen)
        self.b_buchen = self.aktion("Buchen …", self.buchen, emph=True)
        self.b_buchen.setEnabled(False)

        self.c_zuo = Card("Zuordnung Konto → Verbindlichkeit (wird gemerkt)")
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(16)
        self.c_zuo.lay.addLayout(self.grid)
        self.body.addWidget(self.c_zuo)

        self.c_tab = Card("Buchungen im Kontoblatt")
        self.alle = QCheckBox("Bereits gebuchte und übersprungene Zeilen anzeigen")
        self.alle.toggled.connect(self._tabelle)
        self.info = label("", "sub")
        self.c_tab.lay.addLayout(hbox(self.alle, None, self.info))
        self.t = QTableWidget(0, len(SPALTEN))
        self.t.setHorizontalHeaderLabels(SPALTEN)
        self.t.verticalHeader().setVisible(False)
        self.t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.t.setSelectionMode(QAbstractItemView.NoSelection)
        self.t.setShowGrid(False)
        self.t.verticalHeader().setDefaultSectionSize(32)
        h = self.t.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Interactive)
        for i, b in enumerate(BREITEN):
            if b:
                self.t.setColumnWidth(i, b)
            else:
                h.setSectionResizeMode(i, QHeaderView.Stretch)
        self.t.setMinimumHeight(420)
        self.c_tab.lay.addWidget(self.t)
        hinweis = label("Verbindlichkeit = Passivkonto: Haben erhöht den Saldo, Soll vermindert ihn. Eröffnungsbuchungen (EB) "
                        "sind zum Ignorieren vorgeschlagen, weil der Anfangssaldo bei der Verbindlichkeit schon erfasst ist. "
                        "Ignorierte Zeilen werden beim nächsten Import automatisch wieder ignoriert (Haken entfernen = doch buchen).",
                        "sub")
        hinweis.setWordWrap(True)
        self.c_tab.lay.addWidget(hinweis)
        self.body.addWidget(self.c_tab)
        self.body.addStretch()
        self._sichtbar()

    def _sichtbar(self):
        da = bool(self.zeilen)
        self.c_zuo.setVisible(da)
        self.c_tab.setVisible(da)

    # ── Laden ─────────────────────────────────────────────────────────────────
    def oeffnen(self):
        start = os.path.join(os.path.expanduser("~"), "Downloads")
        pfad, _ = QFileDialog.getOpenFileName(self, "Kontoblatt öffnen", start if os.path.isdir(start) else "",
                                              "Kontoblatt (*.csv);;Alle Dateien (*)")
        if pfad:
            self.laden(pfad)

    def laden(self, pfad: str):
        try:
            with open(pfad, "rb") as f:
                zeilen = kb.lesen(f.read())
        except (OSError, FachFehler) as e:
            self.meldung(f"Kontoblatt nicht lesbar: {e}", "error")
            return
        self.zeilen, self.datei, self.wahl = zeilen, os.path.basename(pfad), {}
        self._neu_berechnen()
        neu = sum(1 for v in self.vorschau if v["status"] in (kb.NEU, kb.FEHLT))
        self.meldung(f"{self.datei}: {len(zeilen)} Zeilen, davon {neu} neu.", "info")

    def refresh(self):
        if self.zeilen:
            self._neu_berechnen()

    def _neu_berechnen(self):
        self.vorschau = self.db.kb_vorschau(self.zeilen)
        for v in self.vorschau:
            s = v["zeile"].schluessel
            if s not in self.wahl:
                self.wahl[s] = {"ignorieren": v["ignorieren"], "typ": v["typ"]}
        self._sichtbar()
        self._zuordnung()
        self._tabelle()

    # ── Zuordnung + Abstimmung ────────────────────────────────────────────────
    def _offen(self, v) -> bool:
        return v["status"] in (kb.NEU, kb.FEHLT, kb.IGNORIERT)

    def _zuordnung(self):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        for c, t in enumerate(["Konto", "Verbindlichkeit", "Saldo Kontoblatt", "FinanceFlow jetzt", "nach dem Buchen",
                               "Differenz danach"]):
            l = label(t, "formlabel")
            if c >= 2:
                l.setAlignment(Qt.AlignRight)
            self.grid.addWidget(l, 0, c)
        items = [(None, "— nicht zuordnen —")] + [
            (l["id"], f"{l['contactName']} · {l['name']} ({eur(l['currentBalance'])})"
             + (" – bezahlt" if l["status"] == "BEZAHLT" else "")) for l in self.db.kb_verbindlichkeiten()]
        for r, a in enumerate(self.db.kb_abstimmung(self.zeilen), start=1):
            cb = combo(items)
            cb.setMinimumWidth(380)
            combo_set(cb, a["liabilityId"])
            cb.currentIndexChanged.connect(lambda _i, k=a["konto"], cb=cb: QTimer.singleShot(0, lambda: self._zuordnen(k, cb.currentData())))
            nachher = None
            if a["financeflow"] is not None:
                plus = sum((v["zeile"].aenderung for v in self.vorschau if v["zeile"].konto == a["konto"] and self._offen(v)
                            and not self.wahl[v["zeile"].schluessel]["ignorieren"]), Decimal("0.00"))
                nachher = a["financeflow"] + plus
            diff = None if nachher is None else nachher - a["kontoblatt"]
            werte = [eur(a["kontoblatt"]), eur(a["financeflow"]), eur(nachher), eur(diff, sign=True)]
            self.grid.addWidget(label(a["konto"]), r, 0)
            self.grid.addWidget(cb, r, 1)
            for c, w in enumerate(werte, start=2):
                l = label(w)
                l.setAlignment(Qt.AlignRight)
                if c == 5 and diff is not None:
                    l.setStyleSheet(f"color:{'#107E3E' if diff == 0 else '#E9730C'};")
                self.grid.addWidget(l, r, c)
        n = self.grid.rowCount()
        erkl = label("Differenz danach ≠ 0 ist normal, wenn ignorierte Zeilen (z. B. EB) oder frühere Korrekturen in "
                     "FinanceFlow nicht im Kontoblatt stehen – sonst die Zeilen prüfen.", "sub")
        erkl.setWordWrap(True)
        self.grid.addWidget(erkl, n, 0, 1, 6)

    def _zuordnen(self, konto, lid):
        try:
            self.db.kb_zuordnen(konto, lid)
        except FachFehler as e:
            self.meldung(str(e), "error")
            return
        self._neu_berechnen()

    # ── Tabelle ───────────────────────────────────────────────────────────────
    def _tabelle(self):
        zeige = [v for v in self.vorschau if self.alle.isChecked() or self._offen(v)]
        self.t.setRowCount(0)
        self.t.setRowCount(len(zeige))
        typen = kb.TYPEN_IMPORT
        for r, v in enumerate(zeige):
            z, s, offen = v["zeile"], v["zeile"].schluessel, self._offen(v)
            w = self.wahl[s]
            ohne = offen and not w["ignorieren"] and not v["liabilityId"]
            texte = [None, kb.STATUS_TEXT[v["status"]] + (" – Konto nicht zugeordnet" if ohne else ""),
                     z.datum.strftime("%d.%m.%Y"), z.beleg, z.konto, z.text + (" (Storno)" if z.storno else ""),
                     z.gegenkonto, eur(z.soll) if z.soll else "", eur(z.haben) if z.haben else "", eur(z.aenderung, sign=True)]
            for c, tx in enumerate(texte):
                if tx is None:
                    continue
                it = diskret.listen_text(QTableWidgetItem(tx))
                it.setToolTip(it.text())
                if c >= 7:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 1:
                    it.setForeground(QColor(STATUS_FARBE[v["status"]] if not ohne else "#BB0000"))
                elif not offen or (w["ignorieren"]):
                    it.setForeground(QColor(GRAU))
                self.t.setItem(r, c, it)
            if offen:
                hb = QWidget()
                hl = QHBoxLayout(hb)
                hl.setContentsMargins(0, 0, 0, 0)
                hl.setAlignment(Qt.AlignCenter)
                ch = QCheckBox()
                ch.setChecked(w["ignorieren"])
                ch.toggled.connect(lambda an, s=s: self._ignorieren(s, an))
                hl.addWidget(ch)
                self.t.setCellWidget(r, 0, hb)
                if w["ignorieren"]:
                    it = QTableWidgetItem("wird nicht gebucht")
                    it.setForeground(QColor(GRAU))
                    self.t.setItem(r, 10, it)
                else:
                    cb = combo(typen)
                    combo_set(cb, w["typ"])
                    cb.currentIndexChanged.connect(lambda _i, s=s, cb=cb: self.wahl[s].update(typ=cb.currentData()))
                    self.t.setCellWidget(r, 10, cb)
            else:
                gem = v["gemerkt"]
                it = QTableWidgetItem(dict(typen).get(gem["correctionType"], "") if gem and gem["correctionType"] else "")
                it.setForeground(QColor(GRAU))
                self.t.setItem(r, 10, it)
        self._zaehlen()

    def _ignorieren(self, s, an):
        self.wahl[s]["ignorieren"] = an
        self._zuordnung()
        self._tabelle()

    def _entscheidungen(self):
        e, fehlend = {}, 0
        for v in self.vorschau:
            if not self._offen(v):
                continue
            s, w = v["zeile"].schluessel, self.wahl[v["zeile"].schluessel]
            if w["ignorieren"]:
                if v["status"] != kb.IGNORIERT:          # schon gemerkt → nichts zu tun
                    e[s] = {"aktion": "IGNORIEREN"}
            elif v["liabilityId"]:
                e[s] = {"aktion": "BUCHEN", "typ": w["typ"]}
            else:
                fehlend += 1
        return e, fehlend

    def _zaehlen(self):
        e, fehlend = self._entscheidungen()
        buchen = [v for v in self.vorschau if e.get(v["zeile"].schluessel, {}).get("aktion") == "BUCHEN"]
        summe = sum((v["zeile"].aenderung for v in buchen), Decimal("0.00"))
        ign = sum(1 for x in e.values() if x["aktion"] == "IGNORIEREN")
        txt = f"Zu buchen: {len(buchen)} ({eur(summe, sign=True)}) · neu zu ignorieren: {ign}"
        if fehlend:
            txt += f" · ohne Zuordnung: {fehlend}"
        self.info.setText(txt)
        self.b_buchen.setEnabled(bool(e))

    # ── Buchen ────────────────────────────────────────────────────────────────
    def buchen(self):
        e, fehlend = self._entscheidungen()
        if not e:
            self.meldung("Nichts zu buchen.", "info")
            return
        n_b = sum(1 for x in e.values() if x["aktion"] == "BUCHEN")
        n_i = len(e) - n_b
        txt = f"{n_b} Buchung(en) als Korrektur einbuchen und {n_i} Zeile(n) als ignoriert merken?"
        if fehlend:
            txt += f"\n\n{fehlend} Zeile(n) ohne Zuordnung bleiben offen und erscheinen beim nächsten Import wieder."
        txt += "\n\nVorher wird automatisch gesichert."
        if not frage(self, "Kontoblatt buchen", txt):
            return
        try:
            erg = self.db.kb_buchen(self.zeilen, e, self.datei)
        except FachFehler as ex:
            self.meldung(f"Nichts gebucht: {ex}", "error")
            return
        self.wahl = {}
        self.meldung(f"{erg['gebucht']} Buchung(en) bei {erg['verbindlichkeiten']} Verbindlichkeit(en) eingebucht "
                     f"({eur(erg['summe'], sign=True)}), {erg['ignoriert']} Zeile(n) als ignoriert gemerkt.", "ok")
        self.state.daten_geaendert.emit()
        self._neu_berechnen()
