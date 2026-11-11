"""Seiten: Privatkonkurs, Abschöpfung, Zahlungsplan, Postbuch, Reports, Kontakte, Kategorien, Einstellungen."""
from __future__ import annotations

import os
from datetime import date, timedelta
from decimal import Decimal

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QFileDialog, QGridLayout, QLineEdit

from ... import pdf
from ...calc import iban as ib
from ...calc import ratenplan_cent as rc
from ...dates import MONATE
from ...dates import add_months
from ...dec import D, d
from ...db_base import FachFehler
from ..common import (Card, Felder, KpiReihe, ListeDetail, Seite, Tabelle, berichte_ordner, dat, dialog, eur, frage, hbox,
                      kontakt_items, label, num_de, parse_dec, pct, set_badge, tone_of)
from ..widgets import button, combo, combo_set, de_to_iso, iso_to_de, set_strip, strip

INTERVALLE = [(1, "Monatlich"), (3, "Quartalsweise"), (6, "Halbjährlich"), (12, "Jährlich")]


def monate_items(vor=12, nach=3):
    h = date.today().replace(day=1)
    return [(f"{m.year}-{m.month:02d}", f"{MONATE[m.month - 1]} {m.year}") for m in (add_months(h, i) for i in range(nach, -vor - 1, -1))]


# ── Privatkonkurs ─────────────────────────────────────────────────────────────
def _je_rate_text(r) -> str:
    if r["lastInstallment"] != r["amountPerInstallment"]:
        return f"Betrag je Rate / letzte: {eur(r['amountPerInstallment'])} / {eur(r['lastInstallment'])}"
    return f"{eur(r['amountPerInstallment'])} je Rate"


def je_rate_glaeubiger(cs, modus) -> str:
    """„Je Rate“ eines Gläubigers: Rate, bei Abweichung „letzte …“, beim freien Monatsbetrag ggf. „min – max“."""
    if modus == "MONTHLY" and cs.get("zahlungMin") is not None and cs["zahlungMin"] != cs["zahlungMax"]:
        return f"{eur(cs['zahlungMin'])} – {eur(cs['zahlungMax'])}"
    letzte = cs.get("zahlungLetzteRate")
    if letzte is not None and D(letzte) != D(cs["zahlungJeRate"]):
        return f"{eur(cs['zahlungJeRate'])} · letzte {eur(letzte)}"
    return eur(cs["zahlungJeRate"])


class PrivatkonkursSeite(Seite):
    TITEL = "Privatkonkurs"
    UNTERTITEL = "Zahlungsplan-Angebote berechnen und mit dem Abschöpfungsverfahren vergleichen"

    def __init__(self, state):
        super().__init__(state)
        self.kpi = KpiReihe(["Pfändungsbasis/Mo", "Konkursfähige Schulden", "Abschöpfung gesamt", "Überschuss vor Schulden"])
        self.body.addWidget(self.kpi)
        self.warn = strip("")
        self.warn.setVisible(False)
        self.body.addWidget(self.warn)
        c = Card("Rechner")
        self.f = Felder([("scenarioType", "Szenariotyp", "combo", [("ZAHLUNGSPLAN", "Zahlungsplan (Verhandlung)"),
                                                                   ("TILGUNGSPLAN", "Tilgungsplan (Abschöpfung, 3 Jahre)")]),
                         ("inputMode", "Berechnungsmodus", "combo", [("MONTHLY", "Freier Monatsbetrag"), ("PERCENT", "% der Schuld")]),
                         ("monthlyAmount", "Betrag pro Monat (€)", "dec"), ("percentOfDebt", "% der Schuld", "dec"),
                         ("durationMonths", "Laufzeit (Monate)", "int"), ("intervalMonths", "Zahlungsintervall", "combo", INTERVALLE),
                         ("startDatum", "Erste Rate am", "date"), ("useExtended", "Erweitert", "bool",
                                                                   "Mehrbetrag über Sonderzahlungen (13./14.) abdecken")])
        self.f.set({"scenarioType": "ZAHLUNGSPLAN", "inputMode": "MONTHLY", "durationMonths": 36, "intervalMonths": 1,
                    "startDatum": date.today().isoformat()})
        for k, w in self.f.felder.items():
            sig = getattr(w, "textChanged", None) or getattr(w, "currentIndexChanged", None) or getattr(w, "toggled", None)
            sig.connect(lambda *_: self.eingabe_geaendert())
        c.lay.addWidget(self.f)
        self.live_lbl = label("", "sub")
        self.live_lbl.setWordWrap(True)
        self.verdict = label("")
        c.lay.addLayout(hbox(self.verdict, None))
        c.lay.addWidget(self.live_lbl)
        c.lay.addLayout(hbox(None, button("Berechnen", emph=True, cb=self.berechnen)))
        self.body.addWidget(c)
        self.c_res = Card("Ergebnis")
        self.kpi_r = KpiReihe(["Gesamtzahlung", "Quote", "Betrag je Rate", "Anzahl Raten"])
        self.c_res.lay.addWidget(self.kpi_r)
        self.ext = label("", "sub")
        self.ext.setWordWrap(True)
        self.c_res.lay.addWidget(self.ext)
        self.t_res = Tabelle(["Gläubiger", ">Forderung", ">Anteil", ">Quotierter Betrag", ">Je Rate"], [None, 130, 90, 140, 210])
        self.c_res.lay.addWidget(self.t_res)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Name des Szenarios (z. B. Angebot 60 Monate)")
        self.c_res.lay.addLayout(hbox(self.name, button("Szenario speichern", emph=True, cb=self.speichern)))
        self.c_res.setVisible(False)
        self.body.addWidget(self.c_res)
        c = Card("Gespeicherte Szenarien")
        self.t_sc = Tabelle(["Erstellt", "Name", "Typ", ">Monatl.", ">Laufzeit", ">Gesamtzahlung", ">Quote"],
                            [90, None, 120, 100, 80, 130, 80], mehrfach=True)
        self.t_sc.setMinimumHeight(220)
        self.t_sc.aktiviert.connect(lambda i: i and self.pdf(pdf.konkurs, f"privatkonkurs-{i}", i))
        c.lay.addWidget(self.t_sc)
        c.lay.addLayout(hbox(button("PDF", cb=lambda: self.t_sc.sel_id() and self.pdf(pdf.konkurs, "privatkonkurs", self.t_sc.sel_id())),
                             button("Vergleich (markierte) PDF", cb=self.vergleich),
                             button("Löschen", flat=True, neg=True, cb=self.loeschen), None,
                             label("Mehrfachauswahl mit Strg-Klick für den Vergleich.", "sub")))
        self.body.addWidget(c)
        self.res = None

    def refresh(self):
        self.b = self.db.konkurs_basis()
        b = self.b
        self.kpi.set("Pfändungsbasis/Mo", eur(b["seizableMonthlyBasis"]), "red")
        self.kpi.set("Konkursfähige Schulden", eur(b["totalEligible"]), "red")
        self.kpi.set("Abschöpfung gesamt", f"{eur(b['tilgungTotal'])} · {pct(b['tilgungQuote'])}")
        self.kpi.set("Überschuss vor Schulden", eur(b["surplusBeforeDebt"]), tone_of(b["surplusBeforeDebt"]))
        set_strip(self.warn, "" if b["hasSollLohn"] else "Kein SOLL-Lohn hinterlegt – bitte zuerst in der Lohnberechnung anlegen.", "warn")
        sc = b["scenarios"]
        self.t_sc.set_rows([[dat(s["createdAt"]), s["name"] or f"Szenario {s['id']}", s["scenarioType"], eur(s["monthlyAmount"]),
                             f"{s['durationMonths'] or '–'} Mo.", eur(s["totalPayment"]), pct(s["quote"])] for s in sc],
                           [s["id"] for s in sc])
        self.live()

    def _werte(self):
        return self.f.get()

    def eingabe_geaendert(self):
        """Ändert sich eine Eingabe, passt das berechnete Ergebnis nicht mehr – verwerfen."""
        self.res = None
        self.c_res.setVisible(False)
        self.live()

    def live(self):
        """Live-Kennzahlen wie im Web-Rechner (Tragfähigkeit, Vergleich mit Abschöpfung)."""
        if not hasattr(self, "b"):
            return
        try:
            w = self._werte()
        except FachFehler as e:
            self.live_lbl.setText(str(e))
            return
        zp = w["scenarioType"] == "ZAHLUNGSPLAN"
        for k in ("inputMode", "monthlyAmount", "percentOfDebt", "durationMonths", "intervalMonths", "startDatum", "useExtended"):
            self.f.enable(k, zp)
        self.f.enable("monthlyAmount", zp and w["inputMode"] == "MONTHLY")
        self.f.enable("percentOfDebt", zp and w["inputMode"] == "PERCENT")
        if not zp:
            self.verdict.setText("")
            self.live_lbl.setText(f"Abschöpfung: Pfändungsbasis {eur(self.b['seizableMonthlyBasis'])} × 36 = {eur(self.b['tilgungTotal'])}")
            return
        try:
            r = self.db.konkurs_berechnen(w, self.b)
        except (FachFehler, ArithmeticError, ValueError) as ex:
            self.live_lbl.setText(str(ex))
            return
        monthly, iv, n = r["monthlyAmount"], r["intervalMonths"], r["numInstallments"]
        surplus = self.b["surplusBeforeDebt"]
        abw = monthly - surplus
        je = (abw * 12 / 2) if abw > 0 else Decimal(0)
        r13, r14 = self.b["netSz13"] - je, self.b["netSz14"] - je
        saldo = surplus - monthly
        if not w["useExtended"]:
            v = "TRAGFAEHIG" if saldo >= 0 else ("GRENZWERTIG" if saldo >= -100 else "NICHT_TRAGFAEHIG")
        else:
            v = ("TRAGFAEHIG" if r13 >= 0 and r14 >= 0 and saldo >= -abw else
                 "GRENZWERTIG" if (r13 >= 0 or r14 >= 0) else "NICHT_TRAGFAEHIG")
        txt, art = {"TRAGFAEHIG": ("✓ Tragfähig", "badge_ok"), "GRENZWERTIG": ("⚠ Grenzwertig", "badge_draft"),
                    "NICHT_TRAGFAEHIG": ("✗ Nicht tragfähig", "badge_none")}[v]
        self.verdict.setText(txt)
        self.verdict.setObjectName(art)
        self.verdict.setStyleSheet("color:#AA0808;" if v == "NICHT_TRAGFAEHIG" else "")
        self.verdict.style().unpolish(self.verdict)
        self.verdict.style().polish(self.verdict)
        total = r["totalPayment"]
        diff = total - d(self.b["tilgungTotal"])
        vgl = "günstiger" if diff < 0 else ("teurer" if diff > 0 else "gleichauf")
        self.live_lbl.setText(f"{eur(monthly)}/Monat · {_je_rate_text(r)} · {n} Raten · Angebot {eur(total)} "
                              f"(Quote {pct(r['quote'])}) · vs. Abschöpfung {eur(diff, True)} → {vgl} · "
                              f"Monatssaldo {eur(saldo, True)}")

    def berechnen(self):
        try:
            w = self._werte()
            if w["scenarioType"] == "ZAHLUNGSPLAN" and w["inputMode"] == "MONTHLY" and not w["monthlyAmount"]:
                raise FachFehler("Bitte einen Monatsbetrag eingeben.")
            self.res = self.db.konkurs_berechnen(w, self.b)
        except FachFehler as e:
            self.meldung(str(e), "error")
            return
        r = self.res
        self.meldung("")
        self.c_res.setVisible(True)
        self.kpi_r.set("Gesamtzahlung", eur(r["totalPayment"]))
        self.kpi_r.set("Quote", pct(r["quote"]))
        kp = self.kpi_r.k["Betrag je Rate"]
        if r["scenarioType"] == "ZAHLUNGSPLAN":
            letzte = r["lastInstallment"] != r["amountPerInstallment"]
            kp.lab.setText("Betrag je Rate / letzte" if letzte else "Betrag je Rate")
            self.kpi_r.set("Betrag je Rate", f"{eur(r['amountPerInstallment'])} / {eur(r['lastInstallment'])}" if letzte
                           else eur(r["amountPerInstallment"]))
            self.kpi_r.set("Anzahl Raten", str(r["numInstallments"]))
            self.t_res.set_rows([[cs["liability"]["contact"]["name"]
                                  + (f" · {ib.formatieren(cs['liability']['contact']['iban'])}"
                                     if cs["liability"]["contact"].get("iban") else ""), (eur(cs["balance"]), "red"),
                                  f"{cs['anteilPct']} %".replace(".", ","),
                                  (eur(cs["zahlungGesamt"]), None, True), je_rate_glaeubiger(cs, r.get("inputMode"))]
                                 for cs in r["creditorShares"]], hoehe_auto=True)
            e = r.get("extended")
            self.ext.setText((f"Sonderzahlungen: Abweichung {eur(e['abweichung'])}/Mo → {eur(e['jaehrlicheUeberschreitung'])}/Jahr, "
                              f"je Sonderzahlung {eur(e['beitragJeSz'])} · Rest 13. {eur(e['restSz13'])} · Rest 14. {eur(e['restSz14'])} · "
                              f"{'tragfähig' if e['tragfaehig'] else 'NICHT tragfähig'}") if e else
                             f"Erste Rate {dat(r['installmentDates'][0]['datum'])} · letzte {dat(r['installmentDates'][-1]['datum'])}"
                             if r["installmentDates"] else "")
        else:
            kp.lab.setText("Betrag je Rate")
            self.kpi_r.set("Betrag je Rate", eur(r["seizableMonthly"]))
            self.kpi_r.set("Anzahl Raten", str(r["monate"]))
            self.t_res.set_rows([[l["contact"]["name"], (eur(l["currentBalance"]), "red"), "", "", ""] for l in r["eligibleDebts"]],
                                hoehe_auto=True)
            self.ext.setText("")

    def speichern(self):
        if self.res:
            self.tu(self.db.konkurs_speichern, self.res, self.name.text().strip() or None, ok="Szenario gespeichert.")
            self.name.clear()

    def vergleich(self):
        ids = self.t_sc.sel_ids()
        if ids:
            self.pdf(pdf.szenario_vergleich, "szenario-vergleich", ids)

    def loeschen(self):
        i = self.t_sc.sel_id()
        if i and frage(self, "Löschen", "Szenario löschen?"):
            self.tu(self.db.konkurs_loeschen, i, ok="Gelöscht.")


# ── Abschöpfungsverfahren ─────────────────────────────────────────────────────
class AbschoepfungSeite(Seite):
    TITEL = "Abschöpfungsverfahren"

    def __init__(self, state):
        super().__init__(state)
        self.b_rsb = self.aktion("Restschuldbefreiung …", self.rsb)
        self.b_abort = self.aktion("Verfahren abbrechen", self.abbrechen, neg=True, flat=True)
        self.c_neu = Card("Verfahren auslösen")
        self.c_neu.lay.addWidget(label("Quoten werden aus den aktuellen Salden eingefroren (8 Stellen, Rest auf die größte "
                                       "Verbindlichkeit). Soll je Rate = aktuelle Pfändungsbasis aus dem SOLL-Lohn.", "sub"))
        self.t_el = Tabelle(["Gläubiger", "Bezeichnung", ">Restschuld"], [None, None, 140], mehrfach=True)
        self.t_el.setMinimumHeight(240)
        self.c_neu.lay.addWidget(self.t_el)
        self.start = QLineEdit(iso_to_de(add_months(date.today().replace(day=1), 1).isoformat()))
        self.dauer = QLineEdit("36")
        self.dauer.setMaximumWidth(80)
        self.c_neu.lay.addLayout(hbox(label("Beginn", "formlabel"), self.start, label("Dauer (Monate)", "formlabel"), self.dauer,
                                      button("Alle markieren", cb=self.t_el.selectAll), None,
                                      button("Verfahren auslösen", emph=True, cb=self.anlegen)))
        self.body.addWidget(self.c_neu)
        self.kpi = KpiReihe(["Beginn", "Gebuchte Raten", "Abgeführt gesamt", "Offene Raten"])
        self.body.addWidget(self.kpi)
        self.c_l = Card("Verbindlichkeiten im Verfahren (eingefrorene Quoten)")
        self.t_l = Tabelle(["Gläubiger", "Bezeichnung", ">Saldo bei Beginn", ">Quote", ">Aktueller Saldo"], [None, None, 140, 110, 140])
        self.c_l.lay.addWidget(self.t_l)
        self.body.addWidget(self.c_l)
        self.c_r = Card("Raten")
        self.t_r = Tabelle([">Nr.", "Monat", ">Soll", ">Abgeführt", "Gebucht am"], [60, 140, 130, 130, None])
        self.t_r.setMinimumHeight(380)
        self.t_r.aktiviert.connect(lambda _i: self.buchen())
        self.c_r.lay.addWidget(self.t_r)
        self.c_r.lay.addLayout(hbox(button("Rate buchen …", emph=True, cb=self.buchen),
                                    button("Rate zurücknehmen", flat=True, neg=True, cb=self.zuruecknehmen), None))
        self.body.addWidget(self.c_r)
        self.body.addStretch()

    def refresh(self):
        self.v = v = self.db.abschoepfung()
        aktiv = v is not None
        self.c_neu.setVisible(not aktiv)
        for w in (self.kpi, self.c_l, self.c_r, self.b_rsb, self.b_abort):
            w.setVisible(aktiv)
        if not aktiv:
            self.h_sub.setText("Kein aktives Verfahren")
            el = self.db.rows("SELECT l.*, c.name AS cn FROM liability l JOIN contact c ON c.id=l.contactId WHERE l.isBankruptcyEligible=1 "
                              "AND l.status NOT IN ('GELOESCHT','BEZAHLT') AND CAST(l.currentBalance AS REAL)>0 "
                              "ORDER BY CAST(l.currentBalance AS REAL) DESC")
            self.t_el.set_rows([[l["cn"], l["name"], (eur(l["currentBalance"]), "red")] for l in el], [l["id"] for l in el])
            return
        self.h_sub.setText(f"Aktiv seit {dat(v['startDate'])} · {v['durationMonths']} Monate")
        self.kpi.set("Beginn", dat(v["startDate"]))
        self.kpi.set("Gebuchte Raten", f"{v['paidCount']} / {v['durationMonths']}")
        self.kpi.set("Abgeführt gesamt", eur(v["totalPaid"]), "green")
        self.kpi.set("Offene Raten", str(v["openCount"]))
        self.t_l.set_rows([[l["contactName"], l["name"], eur(l["snapshotBalance"]), f"{D(l['quota']) * 100:.4f} %".replace(".", ","),
                            (eur(l["currentBalance"]), "red", True)] for l in v["liabilities"]], hoehe_auto=True)
        heute = date.today().isoformat()
        self.t_r.set_rows([[str(r["rateNo"]), f"{MONATE[int(r['month'][5:7]) - 1]} {r['month'][:4]}", eur(r["sollAmount"]),
                            (eur(r["paidAmount"]), "green", True) if r["paidAt"] else ("offen" if r["month"] <= heute else "", "amber"),
                            dat(r["paidAt"]) if r["paidAt"] else ""] for r in v["raten"]], [r["id"] for r in v["raten"]])

    def anlegen(self):
        ids = self.t_el.sel_ids()
        try:
            start = de_to_iso(self.start.text())
            dauer = int(self.dauer.text())
        except ValueError as e:
            self.meldung(str(e), "error")
            return
        if ids and frage(self, "Verfahren auslösen", f"Abschöpfungsverfahren mit {len(ids)} Verbindlichkeiten über {dauer} Monate auslösen?"):
            self.tu(self.db.abschoepfung_anlegen, start, dauer, ids, ok="Verfahren ausgelöst.")

    def buchen(self):
        i = self.t_r.sel_id()
        r = next((x for x in self.v["raten"] if x["id"] == i), None) if i else None
        if not r:
            return
        if r["paidAt"]:
            self.meldung("Rate ist bereits gebucht.", "warn")
            return
        w = dialog(self, f"Rate {r['rateNo']} als bezahlt markieren", [("paidAmount", "Abgeführter Betrag", "dec"),
                                                                        ("paidAt", "Datum", "date")],
                   {"paidAmount": r["sollAmount"], "paidAt": date.today().isoformat()})
        if w:
            self.tu(self.db.abschoepfung_rate_buchen, i, w["paidAmount"] or "0", w["paidAt"],
                    ok=lambda x: f"Rate gebucht: {len(x['allocations'])} Verbindlichkeiten aliquot vermindert"
                                 + (f", nicht verteilbar {eur(x['unallocated'])}" if x["unallocated"] > 0 else "") + ".")

    def zuruecknehmen(self):
        i = self.t_r.sel_id()
        if i and frage(self, "Rate zurücknehmen", "Gebuchte Rate per Gegenkorrektur (ABSCHOEPFUNG_STORNO) zurücknehmen?"):
            self.tu(self.db.abschoepfung_rate_zuruecknehmen, i, ok="Rate zurückgenommen.")

    def abbrechen(self):
        if self.v and frage(self, "Abbrechen", "Verfahren abbrechen? Gebuchte Raten bleiben stehen."):
            self.tu(self.db.abschoepfung_abbrechen, self.v["id"], ok="Verfahren abgebrochen.")

    def rsb(self):
        if self.v and frage(self, "Restschuldbefreiung", "Restsalden aller Verbindlichkeiten im Verfahren auf 0 buchen und Verfahren abschließen?"):
            self.tu(self.db.restschuldbefreiung, self.v["id"], ok=lambda n: f"Restschuldbefreiung gebucht ({n} Verbindlichkeiten).")


# ── Zahlungsplan (Sammel-Vereinbarung) ────────────────────────────────────────
class ZahlungsplanSeite(Seite):
    TITEL = "Zahlungsplan"
    UNTERTITEL = "Mehrere Verbindlichkeiten mit einheitlicher Quote umwandeln und Raten je Termin buchen"

    def __init__(self, state):
        super().__init__(state)
        c = Card("Neue Vereinbarung festsetzen")
        self.t_el = Tabelle(["Gläubiger", "Bezeichnung", ">Restschuld", ">Quotenbetrag · Rate"], [None, None, 130, 330], mehrfach=True)
        self.t_el.setMinimumHeight(200)
        self.t_el.itemSelectionChanged.connect(self.vorschau)
        c.lay.addWidget(self.t_el)
        self.quote, self.monate, self.start = QLineEdit(), QLineEdit("36"), QLineEdit(date.today().strftime("%d.%m.%Y"))
        self.quote.setPlaceholderText("z. B. 25")
        self.intervall = combo(INTERVALLE)
        combo_set(self.intervall, 6)
        for w in (self.quote, self.monate):
            w.setMaximumWidth(90)
            w.textChanged.connect(self.vorschau)
        self.intervall.currentIndexChanged.connect(self.vorschau)
        c.lay.addLayout(hbox(label("Quote %", "formlabel"), self.quote, label("Laufzeit (Mo.)", "formlabel"), self.monate,
                             label("Intervall", "formlabel"), self.intervall, label("Erste Rate", "formlabel"), self.start, None))
        self.info = label("", "sub")
        c.lay.addLayout(hbox(self.info, None, button("Festsetzen", emph=True, cb=self.festsetzen)))
        self.body.addWidget(c)
        c = Card("Offene Raten je Termin")
        self.t = Tabelle(["Termin", "Gläubiger", ">Rate Nr.", ">Betrag"], [110, None, 90, 130])
        self.t.setMinimumHeight(380)
        c.lay.addWidget(self.t)
        c.lay.addLayout(hbox(button("Markierte Rate buchen", cb=self.rate), button("Ganzen Termin buchen", emph=True, cb=self.termin),
                             None, label("Bezahlte Raten werden als Korrektur „Ratenzahlung“ an der Verbindlichkeit gespeichert.", "sub")))
        self.body.addWidget(c)

    def refresh(self):
        libs = self.db.verbindlichkeiten(False)
        self.el = [l for l in libs if l["isBankruptcyEligible"] and d(l["currentBalance"]) > 0 and not l["isPaymentPlan"]
                   and not l["isInAbschoepfung"]]
        self.vorschau()
        self.inst = self.db.offene_raten(False, plan_only=True)
        self.h_sub.setText(f"{sum(1 for l in libs if l['isPaymentPlan'])} Verbindlichkeiten im Zahlungsplan")
        self.t.set_rows([[(dat(i["dueDate"]), None, True), i["liabilityName"], str(i["monthNo"]), (eur(i["payment"]), "red")]
                         for i in self.inst], list(range(len(self.inst))))

    def vorschau(self):
        """Gleiche Rechenregel wie die Umwandlung (ratenplan_cent): Quotenbetrag je Gläubiger, Rate, letzte Rate."""
        q_h = rc.pct(parse_dec(self.quote.text()) or 0) if self._ok(self.quote.text()) else 0
        try:
            n = int(self.monate.text() or 0) // int(self.intervall.currentData())
        except (ValueError, ZeroDivisionError):
            n = 0
        sel = set(self.t_el.sel_ids())
        werte = {}
        for l in self.el:
            z = rc.quotenbetrag(rc.to_cents(l["currentBalance"]), q_h)
            werte[l["id"]] = (z, *rc.split_rates(z, n))
        c = rc.cents_to_dec

        def zelle(l):
            z, r, last = werte[l["id"]]
            if not q_h:
                return "–"
            if n <= 0:
                return eur(c(z))
            return f"{eur(c(z))} · Rate {eur(c(r))}" + (f" (letzte {eur(c(last))})" if last != r and n > 1 else "")

        self.t_el.blockSignals(True)
        rows = [[l["contactName"], l["name"], eur(l["currentBalance"]), zelle(l)] for l in self.el]
        self.t_el.set_rows(rows, [l["id"] for l in self.el])
        for r, l in enumerate(self.el):
            if l["id"] in sel:
                self.t_el.selectRow(r)
        self.t_el.blockSignals(False)
        chosen = [l for l in self.el if l["id"] in sel]
        s = sum((D(l["currentBalance"]) for l in chosen), Decimal(0))
        ges = sum(werte[l["id"]][0] for l in chosen)
        rate = sum((werte[l["id"]][1] if n > 1 else werte[l["id"]][2]) for l in chosen)
        last = sum(werte[l["id"]][2] for l in chosen)
        je = ("–" if not n else eur(c(rate)) + (f" · letzte {eur(c(last))}" if last != rate else ""))
        self.info.setText(f"{len(chosen)} gewählt · Summe {eur(s)} · Gesamt {eur(c(ges))} · {n} Raten · je Rate {je}")

    @staticmethod
    def _ok(t):
        try:
            parse_dec(t)
            return bool(t.strip())
        except FachFehler:
            return False

    def festsetzen(self):
        ids = self.t_el.sel_ids()
        if not ids:
            self.meldung("Keine Verbindlichkeit gewählt", "error")
            return
        try:
            q = parse_dec(self.quote.text(), True, "Quote")
            start = de_to_iso(self.start.text())
            if D(q) <= 0:
                raise FachFehler("Bitte eine gültige Quote eingeben")
        except (FachFehler, ValueError) as e:
            self.meldung(str(e), "error")
            return
        ok, fails = 0, []
        for i in ids:
            try:
                self.db.in_zahlungsplan_umwandeln(i, q, int(self.monate.text() or 36), self.intervall.currentData(), start)
                ok += 1
            except FachFehler as e:
                fails.append(f"{i}: {e}")
        self.meldung(f"{ok} von {len(ids)} Verbindlichkeiten umgewandelt." + (" Fehler: " + " · ".join(fails) if fails else ""),
                     "ok" if not fails else "warn")
        self.state.daten_geaendert.emit()

    def _buchen(self, items):
        ok, fails = 0, []
        for it in items:
            try:
                self.db.planrate_bezahlen(it["liabilityId"], it["rowId"])
                ok += 1
            except FachFehler as e:
                fails.append(f"{it['liabilityName']}: {e}")
        self.meldung(f"{ok} von {len(items)} Raten gebucht." + (" " + " · ".join(fails) if fails else ""), "ok" if not fails else "warn")
        self.state.daten_geaendert.emit()

    def rate(self):
        i = self.t.sel_id()
        if i is not None:
            self._buchen([self.inst[i]])

    def termin(self):
        i = self.t.sel_id()
        if i is None:
            return
        due = self.inst[i]["dueDate"]
        mk = (due.year, due.month)
        items = [x for x in self.inst if (x["dueDate"].year, x["dueDate"].month) == mk]
        if frage(self, "Termin buchen", f"Alle {len(items)} Raten im {MONATE[due.month - 1]} {due.year} als bezahlt buchen?"):
            self._buchen(items)


# ── Postbuch ──────────────────────────────────────────────────────────────────
class PostbuchSeite(Seite):
    TITEL = "Postbuch"

    def __init__(self, state):
        super().__init__(state)
        self.aktion("PDF Monat", self.pdf_)
        self.aktion("Löschen", self.loeschen, neg=True, flat=True)
        self.aktion("Erledigt / Wieder öffnen", self.erledigt)
        self.aktion("Antwort erfassen …", lambda: self.bearbeiten(antwort=True))
        self.aktion("Bearbeiten …", lambda: self.bearbeiten())
        self.aktion("+ Eintrag", lambda: self.bearbeiten(neu=True), emph=True)
        self.suche = QLineEdit()
        self.suche.setPlaceholderText("Absender/Empfänger suchen")
        self.typ = combo([("", "Alle"), ("EINGANG", "Eingang"), ("AUSGANG", "Ausgang")])
        self.done = combo([(None, "Alle"), (False, "Offen"), (True, "Erledigt")])
        self.pmonat = combo(monate_items())
        combo_set(self.pmonat, f"{date.today().year}-{date.today().month:02d}")
        for w in (self.typ, self.done):
            w.currentIndexChanged.connect(self.refresh)
        self.suche.textChanged.connect(self.refresh)
        self.body.addLayout(hbox(self.suche, label("Typ", "formlabel"), self.typ, label("Status", "formlabel"), self.done, None,
                                 label("PDF-Monat", "formlabel"), self.pmonat))
        self.info = label("", "sub")
        self.body.addWidget(self.info)
        c = Card()
        self.t = Tabelle(["Datum", "Typ", "Absender/Empfänger", "Betreff", "Referenz", "Wiedervorlage", "Status"],
                         [110, 90, None, None, 120, 110, 90])
        self.t.setMinimumHeight(480)
        self.t.aktiviert.connect(lambda _i: self.bearbeiten())
        c.lay.addWidget(self.t)
        self.body.addWidget(c)

    def refresh(self):
        es = self.db.postbuch(self.suche.text().strip(), self.typ.currentData(), self.done.currentData())
        self.info.setText(f"{len(es)} Einträge · {self.db.post_offene_wiedervorlagen()} offene Wiedervorlagen")
        heute = date.today().isoformat()
        rows, ids = [], []
        for e in es:
            for x, rep in [(e, False)] + [(r, True) for r in e["replies"]]:
                fu = (dat(x["followupDate"]), "red" if x["followupDate"] < heute and not x["isDone"] else "gray") if x["followupDate"] else "–"
                rows.append([("   ↳ " if rep else "") + dat(x["entryDate"]), (x["entryType"], "blue" if x["entryType"] == "EINGANG" else "green", True),
                             x["correspondent"], x["purpose"] or "–", x["reference"] or "–", fu,
                             ("Erledigt", "green", True) if x["isDone"] else ("Offen", "amber", True)])
                ids.append(x["id"])
        self.t.set_rows(rows, ids)

    def bearbeiten(self, neu=False, antwort=False):
        i = self.t.sel_id()
        if not neu and not i:
            self.meldung("Bitte einen Eintrag markieren.", "warn")
            return
        x = self.db.get("post_entry", i) if i and not neu else {}
        werte = {"entryType": "EINGANG", "entryDate": date.today().isoformat()} if neu or antwort else x
        if antwort:
            werte = {**werte, "correspondent": x["correspondent"], "reference": x["reference"],
                     "entryType": "AUSGANG" if x["entryType"] == "EINGANG" else "EINGANG"}
        felder = [("entryType", "Typ", "combo", [("EINGANG", "Eingang"), ("AUSGANG", "Ausgang")]), ("entryDate", "Datum", "date"),
                  ("correspondent", "Absender/Empfänger", "text"), ("purpose", "Betreff", "text"), ("reference", "Referenz/GZ", "text"),
                  ("trackingNumber", "Sendungsnummer", "text"), ("followupDate", "Wiedervorlage", "date"),
                  ("contactId", "Kontakt", "combo", kontakt_items(self.db, True)), ("notes", "Notizen", "multi")]
        w = dialog(self, "Antwort erfassen" if antwort else ("Neuer Eintrag" if neu else "Eintrag bearbeiten"), felder, werte)
        if w:
            if antwort:
                w["threadId"] = x["threadId"] or x["id"]
            elif not neu:
                w["id"], w["threadId"] = i, x["threadId"]
            self.tu(self.db.post_speichern, w, ok="Gespeichert.")

    def erledigt(self):
        i = self.t.sel_id()
        if i:
            x = self.db.get("post_entry", i)
            self.tu(self.db.post_erledigt, i, not x["isDone"], ok="Status geändert.")

    def loeschen(self):
        i = self.t.sel_id()
        if i and frage(self, "Löschen", "Eintrag samt Antworten löschen?"):
            self.tu(self.db.post_loeschen, i, ok="Gelöscht.")

    def pdf_(self):
        self.pdf(pdf.postbuch, "postbuch", self.pmonat.currentData(), self.typ.currentData() or "all")


# ── Reports ───────────────────────────────────────────────────────────────────
class ReportsSeite(Seite):
    TITEL = "Reports"
    UNTERTITEL = "PDF-Berichte – werden im Ordner „Berichte“ neben der Datenbank abgelegt und geöffnet"

    def __init__(self, state):
        super().__init__(state)
        self.aktion("Berichte-Ordner öffnen", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(berichte_ordner(self.db))))
        g = QGridLayout()
        g.setSpacing(16)
        c = Card("Verbindlichkeiten")
        c.lay.addWidget(button("Verbindlichkeitenübersicht", cb=lambda: self.pdf(pdf.verbindlichkeiten, "verbindlichkeiten")))
        self.gv = combo([("all", "Alle Gläubiger"), ("eligible", "Nur konkursfähige"), ("non-eligible", "Nur nicht konkursfähige")])
        c.lay.addLayout(hbox(self.gv, button("Gläubigerverzeichnis", cb=lambda: self.pdf(pdf.glaeubigerverzeichnis, "glaeubigerverzeichnis",
                                                                                         self.gv.currentData()))))
        c.lay.addWidget(button("Zahlungsplan-Übersicht", cb=lambda: self.pdf(pdf.zahlungsplan_uebersicht, "zahlungsplan-uebersicht")))
        c.lay.addWidget(button("Offene Raten", cb=lambda: self.pdf(pdf.offene_raten, "offene-raten")))
        c.lay.addWidget(button("12-Monats-Vorschau", cb=lambda: self.pdf(pdf.vorschau12, "vorschau-12-monate")))
        self.lib = combo([])
        c.lay.addLayout(hbox(self.lib, button("Tilgungsplan", cb=lambda: self.lib.currentData() and self.pdf(pdf.tilgungsplan, "tilgungsplan", self.lib.currentData())),
                             button("Buchungsmitteilung", cb=lambda: self.lib.currentData() and self.pdf(pdf.buchungsmitteilung, "buchungsmitteilung", self.lib.currentData()))))
        g.addWidget(c, 0, 0)
        c = Card("Forderungen, Haushalt & Post")
        c.lay.addWidget(button("Forderungsübersicht", cb=lambda: self.pdf(pdf.forderungen, "forderungen")))
        c.lay.addWidget(button("Haushaltsrechnung", cb=lambda: self.pdf(pdf.haushalt, "haushaltsrechnung")))
        self.pm = combo(monate_items())
        self.pt = combo([("all", "Alle"), ("EINGANG", "Nur Eingänge"), ("AUSGANG", "Nur Ausgänge")])
        c.lay.addLayout(hbox(self.pm, self.pt, button("Postbuch", cb=lambda: self.pdf(pdf.postbuch, "postbuch", self.pm.currentData(), self.pt.currentData()))))
        g.addWidget(c, 0, 1)
        c = Card("Lohn & Privatkonkurs")
        self.sal = combo([])
        c.lay.addLayout(hbox(self.sal, button("Lohnberechnung", cb=lambda: self.sal.currentData() and self.pdf(pdf.lohn, "lohnberechnung", self.sal.currentData()))))
        self.sc = combo([])
        c.lay.addLayout(hbox(self.sc, button("Privatkonkurs-Szenario", cb=lambda: self.sc.currentData() and self.pdf(pdf.konkurs, "privatkonkurs", self.sc.currentData()))))
        c.lay.addWidget(button("Szenario-Vergleich (alle Zahlungspläne)", cb=self.vergleich))
        g.addWidget(c, 1, 0)
        self.body.addLayout(g)
        self.body.addStretch()

    def refresh(self):
        def fill(w, items):
            w.clear()
            for k, t in items:
                w.addItem(t, k)
        fill(self.lib, [(l["id"], f"{l['contactName']} – {l['name']}") for l in self.db.verbindlichkeiten()])
        fill(self.sal, [(s["id"], f"{s['calcType']} · {s['name']}") for s in self.db.lohnberechnungen()])
        fill(self.sc, [(s["id"], f"{s['name'] or 'Szenario ' + str(s['id'])} ({s['scenarioType']})")
                       for s in self.db.rows("SELECT * FROM bankruptcy_scenario ORDER BY createdAt DESC")])

    def vergleich(self):
        ids = [r["id"] for r in self.db.rows("SELECT id FROM bankruptcy_scenario WHERE scenarioType='ZAHLUNGSPLAN'")]
        if ids:
            self.pdf(pdf.szenario_vergleich, "szenario-vergleich", ids)
        else:
            self.meldung("Keine Zahlungsplan-Szenarien gespeichert.", "warn")


# ── Kontakte ──────────────────────────────────────────────────────────────────
class KontakteSeite(ListeDetail):
    TITEL = "Kontakte"
    NEU_TEXT = "+ Kontakt"
    FILTER = [(None, "Alle Rollen"), ("KREDITOR", "Gläubiger"), ("DEBITOR", "Debitoren"), ("BEIDE", "Beide")]

    def aufbauen(self):
        self.aktion("Löschen", self.loeschen, neg=True, flat=True)
        self.aktion("Speichern", self.speichern, emph=True)
        v = self.tab("Allgemein")
        c = Card("Stammdaten")
        self.f = Felder([("name", "Name", "text"), ("role", "Rolle", "combo", [("KREDITOR", "Gläubiger (ich schulde Geld)"),
                                                                              ("DEBITOR", "Debitor (schuldet mir Geld)"),
                                                                              ("BEIDE", "Beide")]),
                         ("company", "Firma", "text"), ("address", "Adresse", "text"), ("zipCode", "PLZ", "text"),
                         ("city", "Ort", "text"), ("country", "Land", "text"), ("phone", "Telefon", "text"), ("email", "E-Mail", "text"),
                         ("iban", "IBAN", "text"), ("bic", "BIC", "text"), ("notes", "Notizen", "multi")])
        c.lay.addWidget(self.f)
        v.addWidget(c)
        c = Card("Verbindlichkeiten & Forderungen")
        self.t = Tabelle(["Art", "Bezeichnung", ">Saldo", "Status"], [130, None, 130, 120])
        c.lay.addWidget(self.t)
        v.addWidget(c)
        v.addStretch()

    def eintraege(self):
        r = self.filter.currentData()
        rows = [k for k in self.db.kontakte() if not r or k["role"] == r]
        self.summe.setText(f"{len(rows)} Kontakte")
        return [(k["id"], k["name"], " · ".join(x for x in (k["role"], k["city"], k["iban"]) if x)) for k in rows]

    def laden(self, oid):
        return self.db.must("contact", oid)

    def neu_obj(self):
        return {"role": "KREDITOR", "country": "Österreich"}     # Schuldenberatung: neue Kontakte sind meist Gläubiger

    def fuellen(self):
        o = self.obj
        self.f.set(o)
        self.h_name.setText(o.get("name") or "Neuer Kontakt")
        self.h_sub.setText(o.get("company") or "")
        if o.get("id"):
            ls = self.db.rows("SELECT * FROM liability WHERE contactId=? AND status!='GELOESCHT'", (o["id"],))
            cs = self.db.rows("SELECT * FROM claim WHERE contactId=? AND status!='GELOESCHT'", (o["id"],))
            self.t.set_rows([["Verbindlichkeit", l["name"], (eur(l["currentBalance"]), "red"), l["status"]] for l in ls]
                            + [["Forderung", c["name"], (eur(c["currentAmount"]), "green"), c["status"]] for c in cs], hoehe_auto=True)
        else:
            self.t.set_rows([])

    def speichern(self):
        try:
            b = {**self.f.get(), "id": (self.obj or {}).get("id")}
        except FachFehler as e:
            self.meldung(str(e), "error")
            return
        i = self.tu(self.db.kontakt_speichern, b, ok="Gespeichert.")
        if i:
            self.waehle(i)

    def loeschen(self):
        if self.obj and self.obj.get("id") and frage(self, "Löschen", f"Kontakt „{self.obj['name']}“ deaktivieren?"):
            if self.tu(self.db.kontakt_loeschen, self.obj["id"], ok="Kontakt deaktiviert."):
                self.obj = None
                self.tabs.setEnabled(False)


# ── Kategorien ────────────────────────────────────────────────────────────────
class KategorienSeite(Seite):
    TITEL = "Kategorien"

    def __init__(self, state):
        super().__init__(state)
        self.aktion("Löschen", self.loeschen, neg=True, flat=True)
        self.aktion("Bearbeiten …", lambda: self.bearbeiten(self.t.sel_id()))
        self.aktion("+ Kategorie", lambda: self.bearbeiten(None), emph=True)
        c = Card()
        self.t = Tabelle(["Name", "Übergeordnet", "Typ", "Farbe", ">Sortierung"], [None, 200, 120, 100, 100])
        self.t.setMinimumHeight(420)
        self.t.aktiviert.connect(self.bearbeiten)
        c.lay.addWidget(self.t)
        self.body.addWidget(c)

    def refresh(self):
        ks = self.db.kategorien()
        by = {k["id"]: k for k in ks}
        ordn = [k for k in ks if not k["parentId"]]
        rows, ids = [], []
        for p in ordn:
            for k in [p] + [c for c in ks if c["parentId"] == p["id"]]:
                rows.append([("   ↳ " if k["parentId"] else "") + k["name"], by.get(k["parentId"], {}).get("name", ""), k["catType"],
                             ("■ " + k["color"], k["color"]), str(k["sortOrder"])])
                ids.append(k["id"])
        self.t.set_rows(rows, ids)

    def bearbeiten(self, i):
        x = self.db.get("category", i) if i else {"catType": "FIX", "color": "#4F6BED", "sortOrder": 0}
        par = [(None, "– keine –")] + [(k["id"], k["name"]) for k in self.db.kategorien() if not k["parentId"] and k["id"] != i]
        w = dialog(self, "Kategorie", [("name", "Name", "text"), ("parentId", "Übergeordnet", "combo", par),
                                       ("catType", "Typ", "combo", [("FIX", "Fix"), ("VARIABLE", "Variabel"), ("SONSTIG", "Sonstig"),
                                                                    ("EINKOMMEN", "Einkommen")]),
                                       ("color", "Farbe (#RRGGBB)", "text"), ("sortOrder", "Sortierung", "int")], x)
        if w:
            self.tu(self.db.kategorie_speichern, {**w, "id": i}, ok="Gespeichert.")

    def loeschen(self):
        i = self.t.sel_id()
        if i and frage(self, "Löschen", "Kategorie löschen?"):
            self.tu(self.db.kategorie_loeschen, i, ok="Gelöscht.")


# ── Einstellungen ─────────────────────────────────────────────────────────────
GRUPPEN = [
    ("Pfändungsberechnung (§ 291a EO)", [("grundbetrag", "Grundbetrag (€)"), ("existenzminimum_stufe", "Rundungsintervall"),
                                          ("existenzminimum_pct", "Koeffizient (z. B. 0.30)")]),
    ("Lohnsteuer", [("verkehrsabsetzbetrag", "Verkehrsabsetzbetrag/Monat (€)"), ("sz_freibetrag", "Freibetrag Sonderzahlung (€)"),
                    ("lst_sz_satz", "LSt-Satz Sonderzahlungen (z. B. 0.06)")]),
    ("Sozialversicherung", [("sv_kv", "KV-Beitrag AN"), ("sv_pv", "PV-Beitrag AN"), ("sv_ak", "AK-Umlage"), ("sv_wbf", "WBF-Beitrag")]),
    ("AV-Staffel (Arbeitslosenversicherung)", [("av_grenze_1", "Grenze 1 (Brutto bis, €)"), ("av_grenze_2", "Grenze 2 (Brutto bis, €)"),
                                               ("av_grenze_3", "Grenze 3 (Brutto bis, €)"), ("av_satz_1", "Satz Stufe 1"),
                                               ("av_satz_2", "Satz Stufe 2"), ("av_satz_3", "Satz Stufe 3"), ("av_satz_4", "Satz Stufe 4")]),
    ("Privatkonkurs", [("tilgungsplan_jahre", "Laufzeit Abschöpfungsverfahren (Jahre)")]),
    ("Allgemein", [("app_name", "Anwendungsname"), ("owner_name", "Name des Inhabers (PDF-Kopf)"),
                   ("owner_street", "Straße und Hausnummer (PDF-Kopf)"), ("owner_city", "PLZ und Ort (PDF-Kopf)"),
                   ("currency", "Währung")]),
]


class EinstellungenSeite(Seite):
    TITEL = "Einstellungen"
    UNTERTITEL = "Rechenparameter (Dezimalwerte mit Punkt, z. B. 0.0387), Datenimport und Sicherung"

    def __init__(self, state):
        super().__init__(state)
        self.aktion("Alle Tilgungspläne neu berechnen", lambda: self.tu(self.db.alle_plaene_neu, ok=lambda n: f"{n} Pläne neu berechnet."))
        self.aktion("Speichern", self.speichern, emph=True)
        g = QGridLayout()
        g.setSpacing(16)
        self.w = {}
        for i, (titel, keys) in enumerate(GRUPPEN):
            c = Card(titel)
            from ..widgets import Form
            f = Form(2)
            for k, lab in keys:
                e = QLineEdit()
                f.add(k, lab, e)
                self.w[k] = e
            c.lay.addWidget(f)
            g.addWidget(c, i // 2, i % 2)
        self.body.addLayout(g)

        c = Card("Datensicherung")
        self.dbinfo = label("", "sub", wrap=True)
        c.lay.addWidget(self.dbinfo)
        c.lay.addLayout(hbox(button("Jetzt sichern", cb=self.sichern),
                             button("Sicherungsordner öffnen", cb=lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.db.backup_ordner()))),
                             None, button("Verschlüsselt importieren …", cb=self.importieren),
                             button("Verschlüsselt exportieren …", cb=self.exportieren)))
        c.lay.addWidget(label("Für die Schuldenberatung oder ein anderes Gerät: Der Export ist eine Abgleich-Datei "
                              "(*.ffsync, AES-256-GCM, Passwort mind. 12 Zeichen) mit dem gesamten Datenstand. Ohne Passwort ist "
                              "sie nicht lesbar; das Passwort wird nirgends gespeichert.", "sub", wrap=True))
        self.body.addWidget(c)
        self._konto_karten()
        c = Card("Änderungsprotokoll (Audit-Log, neueste 200)")
        self.audit = Tabelle(["Zeit", "Aktion", "Objekt", "ID", "Details"], [150, 160, 170, 80, None])
        self.audit.setMinimumHeight(300)
        c.lay.addWidget(self.audit)
        self.body.addWidget(c)

    def refresh(self):
        s = self.db.settings()
        for k, e in self.w.items():
            e.setText(s.get(k) or "")
        self.dbinfo.setText(f"Datenbank: {os.path.abspath(self.db.path)}\nSicherungen: {self.db.backup_ordner()} "
                            f"(automatisch täglich und vor jedem Update, 30 werden behalten)")
        a = self.db.rows("SELECT * FROM audit_log ORDER BY id DESC LIMIT 200")
        self.audit.set_rows([[(x["createdAt"] or "")[:19].replace("T", " "), x["action"], x["entityType"], x["entityId"] or "",
                              (x["newValue"] or x["oldValue"] or "")[:160]] for x in a])

    def speichern(self):
        werte = {k: e.text().strip() for k, e in self.w.items()}
        for k, v in werte.items():
            if k not in ("app_name", "owner_name", "owner_street", "owner_city", "currency"):
                try:
                    Decimal(v)
                except Exception:  # noqa: BLE001
                    self.meldung(f"„{k}“: „{v}“ ist keine Zahl (Dezimalpunkt verwenden).", "error")
                    return

        def save():
            with self.db.tx():
                for k, v in werte.items():
                    self.db.set_setting(k, v, "string" if k in ("app_name", "owner_name", "currency") else "number")
                self.db.audit("BULK_UPDATE", "Setting", None, None, {"keys": list(werte)})
        self.tu(save, ok="Einstellungen gespeichert. Neue Lohnberechnungen verwenden die neuen Werte.")

    def importieren(self):
        from .abgleich import datei_importieren
        if datei_importieren(self):
            self.refresh()

    def exportieren(self):
        from .abgleich import datei_exportieren
        datei_exportieren(self)

    def _konto_karten(self):
        u = getattr(self.db, "benutzer", None)
        konten = getattr(self.db, "benutzerverwaltung", None)
        if not u or not konten:
            return          # Mandant einer Schuldenberatung: Zugang/Benutzer in der Mandantenübersicht
        from ..zugang import ZugangKarten
        self.zugang = ZugangKarten(konten, u, self.meldung, mit_benutzern=not konten.ist_schuldner())
        self.body.addWidget(self.zugang)

    def sichern(self):
        p = self.db.auto_backup("manuell")
        self.meldung(f"Sicherung erstellt: {p}", "ok")
