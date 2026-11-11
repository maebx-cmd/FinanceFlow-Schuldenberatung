"""Seite „Zahlungsdatei“: SEPA-Überweisungen (pain.001) für die nächste offene Rate je Verbindlichkeit."""
from __future__ import annotations

import os
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QLineEdit, QWidget

from ...calc import iban as ib
from ...calc import ratenplan_cent as rc
from ...calc import sepa
from ...db_base import FachFehler
from ..common import Card, Felder, KpiReihe, Seite, Tabelle, berichte_ordner, dat, dialog, eur, frage, hbox, label
from ..widgets import button, de_to_iso

FORMATE = [("09", "pain.001.001.09 (Standard seit 11/2025)"), ("03", "pain.001.001.03 (ältere Banksoftware)")]
STATUS_TON = {"offen": "amber", "teilweise erfasst": "amber", "bezahlt erfasst": "green", "verworfen": None}


def _cent_eur(c: int) -> str:
    return eur(rc.cents_to_dec(c))


class ZahlungsdateiSeite(Seite):
    TITEL = "Zahlungsdatei"
    UNTERTITEL = ("SEPA-Überweisungen (pain.001) für die nächste offene Rate je Verbindlichkeit – "
                  "zum Import ins Online-Banking (z. B. George Business)")

    def __init__(self, state):
        super().__init__(state)
        self.posten: list[dict] = []
        self.exporte: list[dict] = []
        self._auftraggeber_karte()
        self._raten_karte()
        self._dateien_karte()
        self.body.addStretch()

    @staticmethod
    def _umbruch(l):
        l.setWordWrap(True)
        return l

    # ── Auftraggeber ──────────────────────────────────────────────────────────
    def _auftraggeber_karte(self):
        c = Card("Auftraggeber (Ihr Konto)")
        self.a_info = label("", "sub")
        self.b_aendern = button("Ändern", flat=True, cb=lambda: self._formular(True))
        c.lay.addLayout(hbox(self.a_info, None, self.b_aendern))
        self.a_form = QWidget()
        from PySide6.QtWidgets import QVBoxLayout
        v = QVBoxLayout(self.a_form)
        v.setContentsMargins(0, 0, 0, 0)
        self.fa = Felder([("name", "Kontoinhaber", "text"), ("iban", "IBAN", "text"), ("bic", "BIC (optional)", "text"),
                          ("version", "Format", "combo", FORMATE),
                          ("sammelbuchung", "Buchung", "bool", "Sammelbuchung (eine Abbuchung am Konto)"),
                          ("vorlage", "Standard-Verwendungszweck", "text")])
        self.fa.felder["iban"].textChanged.connect(self._a_pruefen)
        self.fa.felder["bic"].textChanged.connect(self._a_pruefen)
        v.addWidget(self.fa)
        self.a_fehler = label("", "sub")
        self.a_fehler.setStyleSheet("color:#BB0000;")
        v.addWidget(self.a_fehler)
        v.addWidget(self._umbruch(label("Platzhalter im Verwendungszweck: {bezeichnung} {glaeubiger} {rate} {faellig} (TT.MM.JJJJ) "
                          "{monat} (MM/JJJJ). Eine Zahlungsreferenz an der Verbindlichkeit hat Vorrang.", "sub")))
        v.addLayout(hbox(None, button("Auftraggeber speichern", emph=True, cb=self._a_speichern)))
        c.lay.addWidget(self.a_form)
        self.body.addWidget(c)

    def _a_gueltig(self, e) -> bool:
        return bool(sepa.name(e["name"])) and ib.gueltig(e["iban"]) and (not e["bic"] or sepa.bic_gueltig(e["bic"]))

    def _a_pruefen(self):
        iban, bic = self.fa.felder["iban"].text(), self.fa.felder["bic"].text()
        f = []
        if ib.normalisieren(iban) and not ib.gueltig(iban):
            f.append(ib.FEHLER)
        if sepa.bic_normalisieren(bic) and not sepa.bic_gueltig(bic):
            f.append("BIC ungültig")
        self.a_fehler.setText(" · ".join(f))
        self.a_fehler.setVisible(bool(f))

    def _formular(self, offen: bool):
        self.a_form.setVisible(offen)
        self.b_aendern.setVisible(not offen)

    def _a_laden(self):
        e = self.db.sepa_einstellungen()
        self.fa.set({**e, "iban": ib.formatieren(e["iban"])})
        self._a_pruefen()
        fmt = dict(FORMATE)[e["version"]].split(" ")[0]
        if self._a_gueltig(e):
            self.a_info.setText(f"{e['name']} · {ib.formatieren(e['iban'])}" + (f" · BIC {e['bic']}" if e["bic"] else "")
                                + f" · {fmt} · {'Sammelbuchung' if e['sammelbuchung'] else 'Einzelbuchungen'}"
                                + f" · Zweck: {e['vorlage']}")
            self._formular(False)
        else:
            self.a_info.setText("Bitte Kontoinhaber und IBAN des Kontos eintragen, von dem überwiesen wird.")
            self._formular(True)

    def _a_speichern(self):
        try:
            w = self.fa.get()
        except FachFehler as e:
            self.meldung(str(e), "error")
            return
        if self.tu(self.db.sepa_einstellungen_speichern, w, ok="Auftraggeber gespeichert."):
            self._a_laden()

    # ── Fällige Raten ─────────────────────────────────────────────────────────
    def _raten_karte(self):
        c = Card("Fällige Raten")
        heute = date.today()
        self.bis = QLineEdit(sepa.monatsende(heute).strftime("%d.%m.%Y"))
        self.ausf = QLineEdit(self._werktag().strftime("%d.%m.%Y"))
        for w in (self.bis, self.ausf):
            w.setMaximumWidth(120)
        c.lay.addLayout(hbox(label("Fällig bis", "formlabel"), self.bis, label("Ausführung am", "formlabel"), self.ausf,
                             button("Neu laden", cb=self.refresh), None))
        self.kpi = KpiReihe(["Ausgewählt", "Summe"])
        c.lay.addWidget(self.kpi)
        self.t = Tabelle(["", "Empfänger / Bezeichnung", ">Rate", "Fällig", ">Betrag", "IBAN", "Verwendungszweck", "Status"],
                         [34, 220, 50, 90, 100, 285, None, 190])
        self.t.setMinimumHeight(300)
        self.t.itemChanged.connect(self._auswahl_geaendert)
        c.lay.addWidget(self.t)
        self.b_xml = button("XML-Datei erstellen", emph=True, cb=self.erstellen)
        c.lay.addLayout(hbox(button("Alle wählen", flat=True, cb=lambda: self._alle(True)),
                             button("Keine", flat=True, cb=lambda: self._alle(False)), None, self.b_xml))
        c.lay.addWidget(self._umbruch(label("Die Datei bucht noch nichts: Erst nach dem Einreichen bei der Bank unter „Erstellte Dateien“ "
                              "→ „Als bezahlt erfassen“ werden die Raten als bezahlt gebucht (Korrektur „Ratenzahlung“).",
                              "sub")))
        self.body.addWidget(c)

    def _werktag(self) -> date:
        try:
            feiertage = {date.fromisoformat(r["date"][:10]) for r in self.db.rows("SELECT date FROM holiday")}
        except Exception:  # noqa: BLE001
            feiertage = set()
        return sepa.naechster_werktag(date.today(), feiertage)

    def _laden_raten(self):
        try:
            bis = de_to_iso(self.bis.text())
        except ValueError as e:
            self.meldung(f"Fällig bis: {e}", "error")
            return
        self.posten = self.db.sepa_auswahl(bis)
        self.t.blockSignals(True)
        rows = []
        for p in self.posten:
            if p["problem"]:
                status = (p["problem"], "red")
            elif p["exportiertAm"]:
                status = (f"bereits exportiert am {dat(p['exportiertAm'][:10])}", "amber")
            else:
                status = ("bereit", "green")
            iban = ib.formatieren(p["iban"]) + (" (aus Kontakt)" if p["ibanQuelle"] == "kontakt" else "") if p["iban"] else "–"
            zw = f"Ref. {p['referenz']}" if p["referenz"] else (p["zweck"] or "–")
            rows.append(["", f"{p['empfaenger']} – {p['bezeichnung']}", str(p["monthNo"]), dat(p["faellig"]),
                         (_cent_eur(p["betrag"]), None, True), iban, zw, status])
        self.t.set_rows(rows, list(range(len(self.posten))))
        for r, p in enumerate(self.posten):
            it = self.t.item(r, 0)
            self.t.item(r, 6).setToolTip(f"Zahlungsreferenz (strukturiert): {p['referenz']}" if p["referenz"]
                                         else f"Verwendungszweck in der Datei: {sepa.zweck(p['zweck'])}")
            self.t.item(r, 5).setToolTip(self.t.item(r, 5).text())
            waehlbar = not p["problem"]
            it.setFlags((Qt.ItemIsUserCheckable | Qt.ItemIsEnabled) if waehlbar else Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if waehlbar and not p["exportiertAm"] else Qt.Unchecked)
        self.t.blockSignals(False)
        self._auswahl_geaendert()

    def _gewaehlt(self) -> list[dict]:
        return [p for r, p in enumerate(self.posten) if self.t.item(r, 0) and self.t.item(r, 0).checkState() == Qt.Checked]

    def _auswahl_geaendert(self, *_):
        g = self._gewaehlt()
        self.kpi.set("Ausgewählt", f"{len(g)} von {len(self.posten)}")
        self.kpi.set("Summe", _cent_eur(sum(p["betrag"] for p in g)), "red" if g else None)
        self.b_xml.setText(f"XML-Datei erstellen ({len(g)})")
        self.b_xml.setEnabled(bool(g))

    def _alle(self, an: bool):
        self.t.blockSignals(True)
        for r, p in enumerate(self.posten):
            if not p["problem"]:
                self.t.item(r, 0).setCheckState(Qt.Checked if an else Qt.Unchecked)
        self.t.blockSignals(False)
        self._auswahl_geaendert()

    def erstellen(self):
        g = self._gewaehlt()
        if not g:
            return
        try:
            ausf = de_to_iso(self.ausf.text())
        except ValueError as e:
            self.meldung(f"Ausführung am: {e}", "error")
            return
        msg = sepa.msg_id()
        pfad, _ = QFileDialog.getSaveFileName(self, "Zahlungsdatei speichern",
                                              os.path.join(berichte_ordner(self.db), f"sepa-{msg}.xml"), "SEPA-XML (*.xml)")
        if not pfad:
            return
        res = self.tu(self.db.sepa_erstellen, [(p["liabilityId"], p["monthNo"]) for p in g], ausf, msg)
        if not res:
            return
        try:
            with open(pfad, "w", encoding="utf-8") as f:
                f.write(res["xml"])
        except OSError as e:
            self.meldung(f"Datei angelegt, aber nicht gespeichert ({e}). Unter „Erstellte Dateien“ → „XML“ erneut speichern.",
                         "warn")
            return
        self.meldung(f"{res['anzahl']} Zahlungen über {_cent_eur(res['summe'])} gespeichert: {pfad}. "
                     "Datei im Online-Banking hochladen und danach „Als bezahlt erfassen“.", "ok")

    # ── Erstellte Dateien ─────────────────────────────────────────────────────
    def _dateien_karte(self):
        c = Card("Erstellte Dateien")
        self.te = Tabelle(["Erstellt", "Ausführung", ">Zahlungen", ">Summe", "Format", "Status"], [360, 110, 110, 130, 150, None])
        self.te.setMinimumHeight(200)
        c.lay.addWidget(self.te)
        c.lay.addLayout(hbox(button("XML", cb=self.xml_speichern), button("Als bezahlt erfassen …", emph=True, cb=self.bezahlt),
                             None, button("Verwerfen …", flat=True, neg=True, cb=self.verwerfen)))
        self.body.addWidget(c)

    def _laden_dateien(self):
        self.exporte = self.db.sepa_exporte()
        self.te.set_rows([[f"{dat(e['erstellt'][:10])} {e['erstellt'][11:16]} · {e['msgId']}", dat(e["ausfuehrung"]),
                           str(e["anzahl"]) + (f" ({e['erfasst']} erfasst)" if e["erfasst"] and e["erfasst"] < e["anzahl"] else ""),
                           eur(e["summe"]), sepa.VERSIONEN.get(e["version"], e["version"]),
                           (e["status"], STATUS_TON.get(e["status"]))] for e in self.exporte],
                         [e["id"] for e in self.exporte])

    def _export(self):
        i = self.te.sel_id()
        if not i:
            self.meldung("Bitte zuerst eine Datei markieren.", "warn")
        return next((e for e in self.exporte if e["id"] == i), None) if i else None

    def xml_speichern(self):
        e = self._export()
        if not e:
            return
        msg, xml = self.db.sepa_xml(e["id"])
        pfad, _ = QFileDialog.getSaveFileName(self, "Zahlungsdatei speichern",
                                              os.path.join(berichte_ordner(self.db), f"sepa-{msg}.xml"), "SEPA-XML (*.xml)")
        if pfad:
            with open(pfad, "w", encoding="utf-8") as f:
                f.write(xml)
            self.meldung(f"Gespeichert: {pfad}", "ok")

    def bezahlt(self):
        e = self._export()
        if not e:
            return
        w = dialog(self, "Als bezahlt erfassen", [("datum", "Zahlungsdatum", "date")], {"datum": e["ausfuehrung"]})
        if w:
            self.tu(self.db.sepa_als_bezahlt, e["id"], w["datum"],
                    ok=lambda r: f"{r['erfasst']} Raten als bezahlt erfasst (Korrektur „Ratenzahlung“)."
                                 + (" Übersprungen: " + "; ".join(r["uebersprungen"]) if r["uebersprungen"] else ""))

    def verwerfen(self):
        e = self._export()
        if e and frage(self, "Datei verwerfen", f"Datei {e['msgId']} verwerfen?\n\nNur wenn sie NICHT bei der Bank eingereicht "
                                                 "wurde! Die Raten werden danach wieder zur Auswahl angeboten."):
            self.tu(self.db.sepa_verwerfen, e["id"], ok="Datei verworfen – die Raten werden wieder angeboten.")

    def refresh(self):
        self._a_laden()
        self._laden_raten()
        self._laden_dateien()
