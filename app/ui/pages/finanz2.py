"""Seiten: Haushaltsrechnung, Fixkosten, Lohnberechnung, Steuertarif, Avalanche."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QGridLayout, QLineEdit, QListWidget, QListWidgetItem, QSplitter, QVBoxLayout, QWidget
from PySide6.QtCore import Qt

from ... import pdf
from ...dates import MONATE
from ...calc.lohn import leite_monatstarif_ab
from ...dec import D, d
from ...db_base import FachFehler
from .. import diskret
from ..common import (Card, Felder, KpiReihe, Seite, Tabelle, dat, dialog, eur, frage, hbox, label, num_de,
                      parse_dec, pct, set_badge, badge, tone_of)
from ..widgets import TabelleEditor, button, combo, combo_set, set_strip, strip


# ── Haushaltsrechnung ─────────────────────────────────────────────────────────
class HaushaltSeite(Seite):
    TITEL = "Haushaltsrechnung"

    def __init__(self, state):
        super().__init__(state)
        self.aktion("PDF", self.pdf_)
        self.aktion("Szenario löschen", self.sz_loeschen, neg=True, flat=True)
        self.aktion("Szenario bearbeiten …", self.sz_bearbeiten)
        self.aktion("+ Szenario", self.sz_neu)
        self.szenario = combo([])
        self.kat = combo([])
        self.szenario.currentIndexChanged.connect(self.refresh)
        self.kat.currentIndexChanged.connect(self.refresh)
        self.body.addLayout(hbox(label("Rechnung", "formlabel"), self.szenario, label("Kategorie", "formlabel"), self.kat, None))
        self.hinweis = strip("")
        self.hinweis.setVisible(False)
        self.body.addWidget(self.hinweis)
        self.kpi = KpiReihe(["Netto laufend", "Fixkosten", "Variable", "Schuldendienst", "Überschuss"])
        self.body.addWidget(self.kpi)
        g = QGridLayout()
        g.setSpacing(16)
        self.c_fix = Card("Fixkosten")
        self.t_fix = Tabelle(["Bezeichnung", "Kategorie", "Fällig", ">Betrag"], [None, 140, 80, 110])
        self.t_fix.aktiviert.connect(lambda i: self.bearbeiten("fixed_cost", i))
        self.c_fix.lay.addWidget(self.t_fix)
        self.c_fix.lay.addLayout(hbox(button("+ Fixkosten", cb=lambda: self.bearbeiten("fixed_cost")),
                                      button("Bearbeiten", flat=True, cb=lambda: self.bearbeiten("fixed_cost", self.t_fix.sel_id())),
                                      button("Entfernen", flat=True, neg=True, cb=lambda: self.entfernen("fixed_cost", self.t_fix)),
                                      None))
        self.c_var = Card("Variable Ausgaben")
        self.t_var = Tabelle(["Bezeichnung", "Kategorie", ">Betrag"], [None, 140, 110])
        self.t_var.aktiviert.connect(lambda i: self.bearbeiten("variable_expense", i))
        self.c_var.lay.addWidget(self.t_var)
        self.c_var.lay.addLayout(hbox(button("+ Variable", cb=lambda: self.bearbeiten("variable_expense")),
                                      button("Bearbeiten", flat=True, cb=lambda: self.bearbeiten("variable_expense", self.t_var.sel_id())),
                                      button("Entfernen", flat=True, neg=True, cb=lambda: self.entfernen("variable_expense", self.t_var)),
                                      None))
        g.addWidget(self.c_fix, 0, 0)
        g.addWidget(self.c_var, 0, 1)
        self.body.addLayout(g)
        c = Card("Schuldendienst (erste offene Planrate je Verbindlichkeit, Intervall auf Monat umgerechnet)")
        self.t_debt = Tabelle(["Verbindlichkeit", ">Restschuld", ">Monatsrate"], [None, 140, 140])
        c.lay.addWidget(self.t_debt)
        self.body.addWidget(c)
        self.body.addStretch()

    def refresh(self):
        for w, items in ((self.szenario, [(None, "Ist-Haushaltsrechnung")] + [(s["id"], f"Szenario: {s['name']}") for s in self.db.szenarien()]),
                         (self.kat, [(None, "Alle Kategorien")] + [(k["id"], k["name"]) for k in self.db.kategorien()])):
            cur = w.currentData()
            w.blockSignals(True)
            w.clear()
            for k, t in items:
                w.addItem(t, k)
            combo_set(w, cur)
            w.blockSignals(False)
        sid, kid = self.szenario.currentData(), self.kat.currentData()
        h = self.db.haushalt(sid, [kid] if kid else None)
        quelle = {"SOLL_LOHN": "aus SOLL-Lohn", "SZENARIO_LOHN": "aus Szenario-Lohnberechnung", "MANUELL": "manuell erfasst",
                  "KEIN_LOHN": "kein Lohn hinterlegt"}[h["lohnQuelle"]]
        set_strip(self.hinweis, ("Szenario-Haushaltsrechnung – nicht die Ist-Rechnung. " if sid else "")
                  + ("Gefiltert: Überschuss rechnet trotzdem mit allen Ausgaben." if kid else ""), "info")
        self.h_sub.setText(f"Netto {quelle}")
        s = h["surplus"]
        self.kpi.set("Netto laufend", eur(h["netMonthly"]), "green")
        self.kpi.set("Fixkosten", eur(h["totalFixed"]), "red")
        self.kpi.set("Variable", eur(h["totalVariable"]), "red")
        self.kpi.set("Schuldendienst", eur(h["totalDebtService"]), "red")
        self.kpi.k["Überschuss"].lab.setText("ÜBERSCHUSS" if s >= 0 else "DEFIZIT")
        self.kpi.set("Überschuss", eur(s), tone_of(s))
        self.t_fix.set_rows([[f["name"], (f["categoryName"] or "–", "gray"), f"{f['dueDay']}." if f["dueDay"] else "–",
                              (eur(f["plannedAmount"]), "red")] for f in h["fixed"]], [f["id"] for f in h["fixed"]],
                            hoehe_auto=True)
        self.t_var.set_rows([[v["name"], (v["categoryName"] or "–", "gray"), (eur(v["plannedAmount"]), "red")] for v in h["variable"]],
                            [v["id"] for v in h["variable"]], hoehe_auto=True)
        self.t_debt.set_rows([[l["name"], eur(l["currentBalance"]), (eur(r), None, True)] for l, r in h["debtRates"]],
                             hoehe_auto=True)
        self.c_fix.findChild(type(label(""))).setText(f"Fixkosten · {eur(h['totalFixed'])}")
        self.c_var.findChild(type(label(""))).setText(f"Variable Ausgaben · {eur(h['totalVariable'])}")

    def bearbeiten(self, table, i=None):
        x = self.db.get(table, i) if i else {"householdScenarioId": self.szenario.currentData()}
        kats = [(None, "– keine –")] + [(k["id"], k["name"]) for k in self.db.kategorien()]
        felder = [("name", "Bezeichnung", "text"), ("plannedAmount", "Betrag/Monat", "dec"), ("categoryId", "Kategorie", "combo", kats)]
        if table == "fixed_cost":
            felder += [("dueDay", "Fällig am (Tag 1–28)", "int"), ("actualAmount", "Ist-Betrag", "dec")]
        felder.append(("notes", "Notizen", "multi"))
        w = dialog(self, ("Fixkosten" if table == "fixed_cost" else "Variable Ausgabe") + (" bearbeiten" if i else " anlegen"), felder, x)
        if w:
            self.tu(self.db.ausgabe_speichern, table, {**w, "id": i, "householdScenarioId": x.get("householdScenarioId")},
                    ok="Gespeichert.")

    def entfernen(self, table, t):
        i = t.sel_id()
        if i and frage(self, "Entfernen", "Eintrag entfernen?"):
            self.tu(self.db.ausgabe_loeschen, table, i, ok="Entfernt.")

    def _sz_felder(self):
        sal = [(None, "– manuell –")] + [(s["id"], f"{s['calcType']}: {s['name']} ({eur(s['netMonthly'])})") for s in self.db.lohnberechnungen()]
        return [("name", "Name", "text"), ("salaryScenarioId", "Lohn aus Lohnberechnung", "combo", sal),
                ("manualNetMonthly", "Netto/Monat (manuell)", "dec"), ("manualNetSz13", "Netto 13. (manuell)", "dec"),
                ("manualNetSz14", "Netto 14. (manuell)", "dec")]

    def sz_neu(self):
        w = dialog(self, "Neues Szenario (kopiert die aktuellen Ist-Ausgaben)", self._sz_felder())
        if w:
            i = self.tu(self.db.szenario_speichern, w, ok="Szenario angelegt.")
            if i:
                self.refresh()
                combo_set(self.szenario, i)

    def sz_bearbeiten(self):
        sid = self.szenario.currentData()
        if not sid:
            self.meldung("Bitte zuerst ein Szenario wählen.", "warn")
            return
        w = dialog(self, "Szenario bearbeiten", self._sz_felder(), self.db.get("household_scenario", sid))
        if w:
            self.tu(self.db.szenario_speichern, {**w, "id": sid}, ok="Gespeichert.")

    def sz_loeschen(self):
        sid = self.szenario.currentData()
        if sid and frage(self, "Szenario löschen", "Szenario samt seinen Ausgaben löschen?"):
            self.tu(self.db.szenario_loeschen, sid, ok="Szenario gelöscht.")

    def pdf_(self):
        kid = self.kat.currentData()
        self.pdf(pdf.haushalt, "haushaltsrechnung", self.szenario.currentData(), [kid] if kid else None)


# ── Fixkosten (Monatszahlungen) ───────────────────────────────────────────────
class FixkostenSeite(Seite):
    TITEL = "Fixkosten"
    UNTERTITEL = "Monatliche Fixkosten als bezahlt markieren"

    def __init__(self, state):
        super().__init__(state)
        self.aktion("Zurücknehmen", self.zurueck, neg=True, flat=True)
        self.aktion("Als bezahlt markieren …", self.zahlen, emph=True)
        self.monat = combo([])
        heute = date.today().replace(day=1)
        from ...dates import add_months
        for i in range(-12, 4):
            m = add_months(heute, i)
            self.monat.addItem(f"{MONATE[m.month - 1]} {m.year}", (m.year, m.month))
        self.monat.setCurrentIndex(12)
        self.monat.currentIndexChanged.connect(self.refresh)
        self.body.addLayout(hbox(label("Monat", "formlabel"), self.monat, None))
        self.kpi = KpiReihe(["Geplant", "Bezahlt", "Offen", "Status"])
        self.body.addWidget(self.kpi)
        c = Card()
        self.t = Tabelle(["Fällig", "Bezeichnung", ">Geplant", "Status", ">Bezahlt"], [70, None, 120, 160, 120])
        self.t.setMinimumHeight(420)
        self.t.aktiviert.connect(lambda _i: self.zahlen())
        c.lay.addWidget(self.t)
        self.body.addWidget(c)

    def refresh(self):
        y, m = self.monat.currentData()
        x = self.db.fixkosten_monat(y, m)
        self.items = {i["id"]: i for i in x["items"]}
        self.kpi.set("Geplant", eur(x["totalPlanned"]))
        self.kpi.set("Bezahlt", eur(x["totalPaid"]), "green")
        self.kpi.set("Offen", eur(x["totalOpen"]), "red")
        self.kpi.set("Status", f"{x['paidCount']} bezahlt · {x['openCount']} offen")
        self.t.set_rows([[f"{i['dueDay']}." if i["dueDay"] else "–", i["name"], eur(i["plannedAmount"]),
                          (f"✓ bezahlt {dat(i['paidAt'])}", "green") if i["paidAt"] else ("offen", "amber"),
                          eur(i["paidAmount"]) if i["paidAt"] else ""] for i in x["items"]],
                        [i["id"] for i in x["items"]])

    def zahlen(self):
        i = self.t.sel_id()
        if not i:
            return
        it = self.items[i]
        w = dialog(self, f"{it['name']} bezahlt", [("amount", "Betrag", "dec")], {"amount": it["plannedAmount"]})
        if w:
            self.tu(self.db.fixkosten_bezahlen, i, w["amount"], ok="Als bezahlt markiert.")

    def zurueck(self):
        i = self.t.sel_id()
        if i and frage(self, "Zurücknehmen", "Als bezahlt markierte Zahlung zurücknehmen?"):
            self.tu(self.db.fixkosten_zuruecknehmen, i, ok="Zurückgenommen.")


# ── Lohnberechnung (Arbeitsseite) ─────────────────────────────────────────────
class LohnSeite(QWidget):
    def __init__(self, state):
        super().__init__()
        self.setObjectName("page")
        self.state, self.db = state, state.db
        self.sel = None
        from PySide6.QtWidgets import QFrame, QHBoxLayout
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        split = QSplitter()
        root.addWidget(split)
        left = QWidget()
        left.setObjectName("page")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(16, 16, 8, 16)
        lv.addWidget(label("Lohnberechnung", "h1"))
        lv.addLayout(hbox(None, button("+ Neue Berechnung", emph=True, cb=self.neu)))
        self.liste = QListWidget()
        self.liste.setObjectName("masterlist")
        self.liste.currentItemChanged.connect(self._auswahl)
        lv.addWidget(self.liste, 1)
        split.addWidget(left)
        right = QWidget()
        right.setObjectName("page")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        head = QFrame()
        head.setObjectName("objheader")
        hv = QVBoxLayout(head)
        hv.setContentsMargins(24, 16, 24, 10)
        self.h = label("Neue Berechnung", "h1")
        self.badge = badge("Entwurf", "draft")
        self.b_del = button("Entfernen", flat=True, neg=True, cb=self.loeschen)
        self.b_pdf = button("PDF", cb=self.pdf_)
        self.b_save = button("Speichern", emph=True, cb=self.speichern)
        hv.addLayout(hbox(self.h, self.badge, None, self.b_del, self.b_pdf, self.b_save))
        self.msg = strip("")
        self.msg.setVisible(False)
        hv.addWidget(self.msg)
        rv.addWidget(head)
        inner = QWidget()
        inner.setObjectName("page")
        iv = QVBoxLayout(inner)
        iv.setContentsMargins(24, 16, 24, 24)
        iv.setSpacing(16)
        c = Card("Eingabe")
        self.f = Felder([("calcType", "Typ", "combo", [("SOLL", "SOLL"), ("IST", "IST"), ("SZENARIO", "SZENARIO")]),
                         ("name", "Bezeichnung", "text"), ("periodMonth", "Monat (1–14)", "int"), ("periodYear", "Jahr", "int"),
                         ("kvName", "Kollektivvertrag", "text"), ("lohnGruppe", "Lohngruppe", "text"), ("stufe", "Stufe", "text"),
                         ("monthlyBase", "Monatsbrutto (€)", "dec"), ("hourlyRate", "oder Stundensatz (€)", "dec", 4),
                         ("hoursTarget", "Soll-Stunden", "dec"), ("hoursActual", "Ist-Stunden", "dec"),
                         ("allowance", "Zulagen (€)", "dec"), ("notes", "Notizen", "multi")])
        for w in self.f.felder.values():
            if isinstance(w, QLineEdit):
                w.textChanged.connect(self._trigger)
        c.lay.addWidget(self.f)
        c.lay.addWidget(label("Stundensatz × Ist-Stunden hat Vorrang vor dem Monatsbrutto. Werte aus Einstellungen (SV, LSt, § 291a EO).", "sub"))
        iv.addWidget(c)
        c = Card("Ergebnis")
        self.kpi = KpiReihe(["Brutto", "Netto laufend", "Netto 13.", "Netto 14.", "Pfändungsbasis/Mo"])
        c.lay.addWidget(self.kpi)
        self.t = Tabelle(["Position", ">Bemessungsgrundlage", ">Betrag"], [None, 180, 160])
        c.lay.addWidget(self.t)
        iv.addWidget(c)
        iv.addStretch()
        from ..common import scroll
        rv.addWidget(scroll(inner), 1)
        split.addWidget(right)
        split.setSizes([300, 1000])
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.rechnen)
        state.daten_geaendert.connect(self.refresh)
        self.refresh()
        self.neu()

    def refresh(self):
        self.liste.blockSignals(True)
        self.liste.clear()
        for c in self.db.lohnberechnungen():
            it = QListWidgetItem(f"{c['calcType']} · {c['name']}\nNetto {eur(c['netMonthly'])} · Pfändbar {eur(c['seizableMonthlyBasis'])}")
            it.setData(Qt.UserRole, c["id"])
            self.liste.addItem(diskret.listen_text(it))
            if c["id"] == self.sel:
                self.liste.setCurrentItem(it)
        self.liste.blockSignals(False)

    def _trigger(self):
        if not self.sel:
            self.timer.start()

    def neu(self):
        self.sel = None
        self.liste.clearSelection()
        self.f.set({"calcType": "SOLL", "periodYear": date.today().year, "allowance": "0"})
        self._modus(False)
        self.rechnen()

    def _modus(self, gespeichert):
        self.h.setText("Neue Berechnung" if not gespeichert else self.h.text())
        set_badge(self.badge, "Gespeichert" if gespeichert else "Entwurf", "ok" if gespeichert else "draft")
        self.f.setEnabled(not gespeichert)
        self.b_save.setEnabled(not gespeichert)
        self.b_del.setEnabled(gespeichert)
        set_strip(self.msg, "Gespeicherte Berechnungen sind unveränderlich (Ergebnis eingefroren). Für Änderungen neue Berechnung anlegen."
                  if gespeichert else "", "ok")

    def _auswahl(self, it, _p=None):
        if not it:
            return
        c = self.db.get("salary_calculation", it.data(Qt.UserRole))
        self.sel = c["id"]
        self.f.set(c)
        self.h.setText(f"{c['calcType']} · {c['name']}")
        self._modus(True)
        self._zeigen({"brutto": c["grossMonthly"], "nettoLfd": c["netMonthly"], "nettoSz13": c["netSz13"], "nettoSz14": c["netSz14"],
                      "seizableMonthlyBasis": c["seizableMonthlyBasis"], "svTarifLfd": c["svTotalRate"], "svLfd": c["svAmount"],
                      "bmgLstLfd": c["bmgLst"], "lstSatzLfd": c["lstRate"], "lstLfd": c["lstAmount"], "svSz13": c["svSz13"],
                      "bmgLstSz13": c["bmgLstSz13"], "lstSz13": c["lstSz13"], "svSz14": c["svSz14"], "bmgLstSz14": c["bmgLstSz14"],
                      "lstSz14": c["lstSz14"], "existenzminimumLfd": c["existenzminimumLfd"], "seizableLfd": c["seizableLfd"],
                      "existenzminimumSz13": c["existenzminimumSz13"], "seizableSz13": c["seizableSz13"],
                      "existenzminimumSz14": c["existenzminimumSz14"], "seizableSz14": c["seizableSz14"],
                      "seizableAnnual": c["seizableAnnual"], "svTarifSz": c["svRateSz"]})

    def _eingabe(self):
        return self.f.get()

    def rechnen(self):
        try:
            b = self._eingabe()
            r = self.db.lohn_vorschau(b)
        except FachFehler as e:
            set_strip(self.msg, str(e), "error")
            return
        set_strip(self.msg, "", "info")
        self.res = r
        self._zeigen(r)

    def _zeigen(self, r):
        self.kpi.set("Brutto", eur(r["brutto"]))
        self.kpi.set("Netto laufend", eur(r["nettoLfd"]), "green")
        self.kpi.set("Netto 13.", eur(r["nettoSz13"]), "green")
        self.kpi.set("Netto 14.", eur(r["nettoSz14"]), "green")
        self.kpi.set("Pfändungsbasis/Mo", eur(r["seizableMonthlyBasis"]), "red")
        rows = [
            ("Laufender Bezug – Brutto", "", eur(r["brutto"])),
            (f"− Sozialversicherung ({pct(r['svTarifLfd'])})", eur(r["brutto"]), (eur(r["svLfd"]), "red")),
            (f"− Lohnsteuer ({pct(r['lstSatzLfd'])} Grenzsteuersatz)", eur(r["bmgLstLfd"]), (eur(r["lstLfd"]), "red")),
            (("= Netto laufend", None, True), "", (eur(r["nettoLfd"]), "green", True)),
            (f"13. Gehalt – SV ({pct(r['svTarifSz'])})", eur(r["brutto"]), (eur(r["svSz13"]), "red")),
            ("13. Gehalt – LSt 6 % (nach Freibetrag)", eur(r["bmgLstSz13"]), (eur(r["lstSz13"]), "red")),
            (("= Netto 13. Gehalt", None, True), "", (eur(r["nettoSz13"]), "green", True)),
            ("14. Gehalt – SV", eur(r["brutto"]), (eur(r["svSz14"]), "red")),
            ("14. Gehalt – LSt 6 %", eur(r["bmgLstSz14"]), (eur(r["lstSz14"]), "red")),
            (("= Netto 14. Gehalt", None, True), "", (eur(r["nettoSz14"]), "green", True)),
            ("Existenzminimum lfd. (§ 291a EO)", eur(r["nettoLfd"]), eur(r["existenzminimumLfd"])),
            ("Pfändbar laufend", "", (eur(r["seizableLfd"]), "red")),
            ("Pfändbar 13. / 14.", f"EM {eur(r['existenzminimumSz13'])} / {eur(r['existenzminimumSz14'])}",
             (f"{eur(r['seizableSz13'])} / {eur(r['seizableSz14'])}", "red")),
            ("Pfändbar/Jahr (lfd. × 12 + SZ)", "", (eur(r["seizableAnnual"]), "red")),
            (("Pfändungsbasis/Monat (÷ 12)", None, True), "", (eur(r["seizableMonthlyBasis"]), "red", True)),
        ]
        self.t.set_rows([list(x) for x in rows], hoehe_auto=True)

    def speichern(self):
        try:
            b = self._eingabe()
            i = self.db.lohn_speichern(b)
        except FachFehler as e:
            set_strip(self.msg, str(e), "error")
            return
        self.sel = i
        self.state.daten_geaendert.emit()
        self.refresh()
        it = self.liste.currentItem()
        if it:
            self._auswahl(it)
        set_strip(self.msg, "Gespeichert.", "ok")

    def loeschen(self):
        if self.sel and frage(self, "Entfernen", "Berechnung entfernen (deaktivieren)?"):
            self.db.lohn_loeschen(self.sel)
            self.state.daten_geaendert.emit()
            self.neu()

    def pdf_(self):
        from ..common import pdf_oeffnen
        if self.sel:
            pdf_oeffnen(self, pdf.lohn, f"lohnberechnung-{self.sel}", self.sel)
        else:
            try:
                name = self.f.get().get("name") or "Szenario"
            except FachFehler:
                name = "Szenario"
            pdf_oeffnen(self, pdf.lohn_vorschau, "lohn-vorschau", self.res, name)

    def meldung(self, text, art="info"):
        set_strip(self.msg, text, art)


# ── Steuertarif ───────────────────────────────────────────────────────────────
class SteuertarifSeite(Seite):
    TITEL = "Steuertarif"
    UNTERTITEL = "Jahresstufen § 33 EStG → monatliche LSt-Tabelle (§ 66 EStG), Abzug ungerundet weitergeführt"

    def __init__(self, state):
        super().__init__(state)
        self.aktion("Speichern", self.speichern, emph=True)
        c = Card("Jahresstufen")
        self.ed = TabelleEditor([("stufe", "Stufe", "num"), ("satz", "Satz (z. B. 0,20)", "num"), ("jahresgrenze", "Jahresgrenze (€)", "num")])
        self.ed.t.itemChanged.connect(lambda _i: self.vorschau())
        c.lay.addWidget(self.ed)
        self.wk = QLineEdit()
        self.wk.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.wk.setMaximumWidth(160)
        self.wk.textChanged.connect(lambda _t: self.vorschau())
        c.lay.addLayout(hbox(label("Werbungskostenpauschale/Jahr (§ 16 Abs. 3 EStG)", "formlabel"), self.wk, None))
        self.body.addWidget(c)
        c = Card("Hergeleitete Monatstabelle (wird bei der Lohnberechnung verwendet)")
        self.t = Tabelle([">Stufe", ">Satz", ">BMG von", ">BMG bis", ">allg. Abzug"])
        c.lay.addWidget(self.t)
        self.body.addWidget(c)
        self.body.addStretch()

    def refresh(self):
        x = self.db.steuertarif()
        self.ed.t.blockSignals(True)
        self.ed.set_data([{"stufe": s["stufe"], "satz": s["satz"], "jahresgrenze": s["jahresgrenze"]} for s in x["jahrestarif"]])
        self.ed.t.blockSignals(False)
        self.wk.setText(num_de(x["werbungskostenJahr"]))
        self._zeige(x["monatstarif"])

    def _daten(self):
        rows = [r for r in self.ed.data() if r.get("satz") is not None and r.get("jahresgrenze") is not None]
        return [{"stufe": int(r.get("stufe") or i + 1), "satz": float(r["satz"]), "jahresgrenze": float(r["jahresgrenze"])}
                for i, r in enumerate(rows)], float(parse_dec(self.wk.text(), True, "Werbungskosten"))

    def vorschau(self):
        try:
            jt, wk = self._daten()
            self._zeige(leite_monatstarif_ab(jt, wk))
        except Exception:  # noqa: BLE001
            pass

    def _zeige(self, mt):
        self.t.set_rows([[str(s["stufe"]), f"{s['satz'] * 100:.0f} %", num_de(Decimal(str(s["bmg_von"]))),
                          num_de(Decimal(str(s["bmg_bis"]))) if s["bmg_bis"] < 9000000 else "∞", num_de(Decimal(str(s["allg_abzug"])))]
                         for s in mt], hoehe_auto=True)

    def speichern(self):
        try:
            jt, wk = self._daten()
        except (FachFehler, ValueError) as e:
            self.meldung(str(e), "error")
            return
        self.tu(self.db.steuertarif_speichern, jt, wk, ok="Steuertarif gespeichert, Monatstabelle abgeleitet.")


# ── Avalanche ─────────────────────────────────────────────────────────────────
class AvalancheSeite(Seite):
    TITEL = "Avalanche"
    UNTERTITEL = "Schuldenabbau: Überschuss jeweils auf die höchstverzinste offene Schuld"

    def __init__(self, state):
        super().__init__(state)
        self.b_save = self.aktion("Plan speichern", self.speichern)
        self.b_save.setEnabled(False)
        c = Card("Einbezogene Verbindlichkeiten (Avalanche aktiviert)")
        self.t_l = Tabelle(["Gläubiger", "Bezeichnung", ">Zinssatz", ">Restschuld", ">Mindestrate"], [None, None, 90, 130, 120])
        c.lay.addWidget(self.t_l)
        self.budget = QLineEdit()
        self.budget.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.budget.setMaximumWidth(160)
        self.minrate = label("", "sub")
        c.lay.addLayout(hbox(label("Monatsbudget (€)", "formlabel"), self.budget, button("Berechnen", emph=True, cb=self.rechnen),
                             self.minrate, None))
        self.body.addWidget(c)
        self.kpi = KpiReihe(["Laufzeit Avalanche", "Zinsen Avalanche", "Laufzeit nur Mindestraten", "Zinsersparnis"])
        self.body.addWidget(self.kpi)
        c = Card("Monatsplan")
        self.t = Tabelle([">Monat", "Datum", "Verbindlichkeit", ">Zahlung", ">Zinsen", ">Tilgung", ">Restsaldo", "Ziel"],
                         [60, 90, None, 110, 100, 110, 120, 50])
        self.t.setMinimumHeight(420)
        c.lay.addWidget(self.t)
        self.body.addWidget(c)
        self.gespeichert = label("", "sub")
        self.body.addWidget(self.gespeichert)

    def refresh(self):
        self.libs = self.db.avalanche_libs()
        self.names = {l["id"]: l["name"] for l in self.libs}
        mn = sum((d(l["repaymentValue"] or 0) for l in self.libs), Decimal(0))
        self.minrate.setText(f"Summe Mindestraten: {eur(mn)}")
        self.t_l.set_rows([[l["contactName"], l["name"], pct(l["interestRate"]), (eur(l["currentBalance"]), "red"),
                            eur(l["repaymentValue"] or 0)] for l in self.libs], hoehe_auto=True)
        run = self.db.avalanche_aktuell()
        self.gespeichert.setText(f"Gespeicherter Plan: Budget {eur(run['planBudget'])} · {run['totalMonths']} Monate · "
                                 f"Ersparnis {eur(run['interestSaved'])} · {dat(run['calculatedAt'])}" if run else "Noch kein Plan gespeichert.")

    def rechnen(self):
        try:
            b = parse_dec(self.budget.text(), True, "Budget")
            self.res = self.db.avalanche_berechnen(b)
        except FachFehler as e:
            self.meldung(str(e), "error")
            return
        r = self.res
        self.meldung("Hinweis: Zinsen werden mit voller Zinssatz-Präzision gerechnet (Web-Version rundete den Satz auf 2 Stellen).", "info")
        self.kpi.set("Laufzeit Avalanche", f"{r['totalMonths']} Monate")
        self.kpi.set("Zinsen Avalanche", eur(r["totalInterest"]), "red")
        self.kpi.set("Laufzeit nur Mindestraten", f"{r['baseMonths']} Monate" + (" (≥ 600)" if r["baseMonths"] >= 600 else ""))
        self.kpi.set("Zinsersparnis", eur(r["interestSaved"]), "green")
        rows = r["results"][:1500]
        self.t.set_rows([[str(x["monthNo"]), dat(x["monthDate"]), self.names.get(x["liabilityId"], ""), eur(x["payment"]),
                          (eur(x["interest"]), "red"), (eur(x["principal"]), "green"), eur(x["endBalance"]),
                          ("●", "blue") if x["isTarget"] else ""] for x in rows])
        self.b_save.setEnabled(True)

    def speichern(self):
        self.tu(self.db.avalanche_speichern, self.res, ok="Avalanche-Plan gespeichert.")
