"""Seiten: Startseite, Dashboard, Verbindlichkeiten, Offene Raten, Forderungen (ab 1.6.0 ohne Konten/Buchungen)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from PySide6.QtWidgets import QGridLayout, QVBoxLayout, QWidget

from ... import pdf
from ...dec import D, d
from ...calc import iban as ib
from ...services.finance import CORRECTION_TYPES
from ..common import (Card, Felder, KpiReihe, ListeDetail, Seite, Tabelle, dat, dialog, eur, frage, hbox,
                      kontakt_items, label, pct, set_badge, tone_of)
from ..widgets import Tile, button, combo

REP_TYPEN = [("FIX", "Fixe Rate"), ("PERCENT", "Prozent vom Saldo"), ("OPEN", "Offen / revolvierend"), ("PLAN", "Ratenplan")]
STATUS_ART = {"OFFEN": "none", "ZAHLUNGSPLAN": "draft", "BEZAHLT": "ok", "GELOESCHT": "none"}


# ── Startseite ────────────────────────────────────────────────────────────────
class StartSeite(QWidget):
    WANTS_NAVIGATE = True

    def __init__(self, state, navigate):
        super().__init__()
        self.setObjectName("page")
        self.state, self.db = state, state.db
        # Inhalt in einem Scrollbereich: bei kleinem Fenster oder Windows-Skalierung (125 %/150 %)
        # werden die Kacheln nicht zusammengedrückt (sonst überlappen die Reihen), sondern es wird gescrollt.
        from PySide6.QtWidgets import QFrame, QLayout, QScrollArea
        aussen = QVBoxLayout(self)
        aussen.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        inhalt = QWidget()
        inhalt.setObjectName("page")
        sc.setWidget(inhalt)
        aussen.addWidget(sc)
        v = QVBoxLayout(inhalt)
        v.setSizeConstraint(QLayout.SetMinimumSize)
        v.setContentsMargins(32, 24, 32, 24)
        self.h = label("Guten Tag", "h1")
        v.addWidget(self.h)
        v.addWidget(label("Wähle eine App, um zu beginnen.", "sub"))
        self.abgl = label("", "sub")
        self.abgl.setWordWrap(True)
        v.addWidget(self.abgl)
        self.t = {}
        gruppen = [
            ("FinanceFlow", [("dashboard", "Dashboard", "Finanzübersicht"), ("verbindlichkeiten", "Verbindlichkeiten", "offen"),
                             ("forderungen", "Forderungen", "offen"),
                             ("offene_raten", "Offene Raten", "nächste Raten"), ("haushalt", "Haushaltsrechnung", "Überschuss"),
                             ("privatkonkurs", "Privatkonkurs", "Pfändungsbasis/Mo"), ("postbuch", "Postbuch", "offene Wiedervorlagen"),
                             ("reports", "Reports", "PDF-Berichte")]),
            ("Abgleich", [("abgleich", "Abgleich", "verschlüsselte Datei")]),
        ]
        for gname, tiles in gruppen:
            v.addSpacing(8)
            v.addWidget(label(gname, "h2"))
            g = QGridLayout()
            g.setSpacing(16)
            for i, (key, titel, sub) in enumerate(tiles):
                t = Tile(titel, sub)
                t.clicked.connect(lambda k=key: navigate(k))
                g.addWidget(t, i // 6, i % 6)
                self.t[key] = t
            g.setColumnStretch(6, 1)
            v.addLayout(g)
        v.addStretch()
        state.daten_geaendert.connect(self.refresh)
        self.refresh()

    def refresh(self):
        db = self.db
        dash = db.dashboard()
        h = db.haushalt()
        name = (db.setting("owner_name", "") or "").split(" ")[0]
        self.h.setText(f"Guten Tag, {name}." if name else "Guten Tag.")
        kurz = lambda x: f"{Decimal(str(x)).quantize(Decimal('1')):,} €".replace(",", ".").replace("-", "−")
        self.t["dashboard"].set(kpi=kurz(dash["totalDebt"]), sub="Gesamtverbindlichkeiten")
        self.t["verbindlichkeiten"].set(kpi=str(dash["liabilityCount"]), sub=f"offen · {eur(dash['totalDebt'])}")
        self.t["forderungen"].set(kpi=kurz(dash["totalClaims"]), sub="offene Forderungen")
        n = len(db.offene_raten(True))
        self.t["offene_raten"].set(kpi=str(n), sub="nächste Raten offen")
        self.t["haushalt"].set(kpi=kurz(h["surplus"]), sub="Überschuss/Monat")
        s = dash["sollLohn"]
        self.t["privatkonkurs"].set(kpi=kurz(s["seizableMonthlyBasis"]) if s else "–", sub="Pfändungsbasis/Mo")
        self.t["postbuch"].set(kpi=str(db.post_offene_wiedervorlagen()), sub="offene Wiedervorlagen")
        self.t["reports"].set(kpi="", sub="PDF-Berichte erstellen")
        from ...abgleich import abgleich as ab
        stat = ab.status(db)
        self.abgl.setText(ab.status_text(stat["finanzen"]))
        self.t["abgleich"].set(kpi="", sub="Datei für Schuldenberatung / Schuldner (*.ffsync)")

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()


# ── Dashboard ─────────────────────────────────────────────────────────────────
class DashboardSeite(Seite):
    TITEL = "Dashboard"
    WANTS_NAVIGATE = True

    def __init__(self, state, navigate):
        super().__init__(state)
        self.nav = navigate
        self.kpi = KpiReihe(["Gesamtverbindlichkeiten", "Offene Forderungen", "Netto lfd."])
        self.body.addWidget(self.kpi)
        self.pfaend = label("", "sub")
        self.body.addWidget(self.pfaend)
        g = QGridLayout()
        g.setSpacing(16)
        c1 = Card("Verbindlichkeiten (Top 5 nach Restschuld)")
        self.t_top = Tabelle(["Gläubiger", "Typ", ">Restschuld", ">Zinssatz"], [None, 80, 120, 80])
        self.t_top.aktiviert.connect(lambda i: i and self._open_liab(i))
        c1.lay.addWidget(self.t_top)
        c2 = Card("Bevorstehende Fälligkeiten")
        self.t_up = Tabelle(["Fällig", "Verbindlichkeit", "Typ", ">Betrag"], [90, None, 70, 110])
        self.t_up.aktiviert.connect(lambda i: i and self._open_liab(i))
        c2.lay.addWidget(self.t_up)
        c3 = Card("3-Monats-Vorschau")
        self.t_vs = Tabelle(["Monat", ">Fix", ">Revolving", ">Gesamt"])
        c3.lay.addWidget(self.t_vs)
        for i, c in enumerate([c1, c2, c3]):
            g.addWidget(c, i // 2, i % 2)
        self.body.addLayout(g)
        self.body.addStretch()
        self.h_sub.setText("Finanzübersicht · " + date.today().strftime("%d.%m.%Y"))

    def _open_liab(self, lid):
        self.nav("verbindlichkeiten")
        self.window().pages["verbindlichkeiten"].waehle(lid)

    def refresh(self):
        x = self.db.dashboard()
        self.kpi.set("Gesamtverbindlichkeiten", eur(x["totalDebt"]), "red")
        self.kpi.set("Offene Forderungen", eur(x["totalClaims"]))
        s = x["sollLohn"]
        self.kpi.set("Netto lfd.", eur(s["netMonthly"]) if s else "kein SOLL-Lohn")
        self.pfaend.setText(f"{x['liabilityCount']} offene Verbindlichkeiten · Pfändungsbasis/Mo: "
                            f"{eur(s['seizableMonthlyBasis']) if s else '–'}")
        self.t_top.set_rows([[l["name"], l["repaymentType"], (eur(l["currentBalance"]), "red", True), pct(l["interestRate"])]
                             for l in x["liabilities"]], [l["id"] for l in x["liabilities"]], hoehe_auto=True)
        up = x["upcoming"][:8]
        self.t_up.set_rows([[dat(u["dueDate"]), u["name"], u["repaymentType"], (eur(u["amount"]), "red", True)] for u in up],
                           [u["id"] for u in up], hoehe_auto=True)
        from ...dates import MONATE
        self.t_vs.set_rows([[f"{MONATE[m['monat'].month - 1]} {m['monat'].year}", eur(m["fix"]), eur(m["revolving"]),
                             (eur(m["gesamt"]), "red", True)] for m in x["vorschau"]], hoehe_auto=True)


# ── Verbindlichkeiten ─────────────────────────────────────────────────────────
class VerbindlichkeitenSeite(ListeDetail):
    TITEL = "Verbindlichkeiten"
    NEU_TEXT = "+ Neu"
    FILTER = [("OFFEN", "Offene"), ("ALLE", "Alle"), ("ZAHLUNGSPLAN", "Zahlungsplan"), ("BEZAHLT", "Bezahlt")]

    def _filterzeile(self):
        """Filter wie in der Web-Version: Konkursfähigkeit (Alle/KF/NKF) und kombinierbare Merkmale (UND)."""
        from PySide6.QtWidgets import QCheckBox
        self.f_kf = combo([("ALLE", "Konkurs: alle"), ("KF", "Konkursfähig"), ("NKF", "Nicht konkursfähig")])
        self.f_avl, self.f_zp, self.f_av = QCheckBox("AVL"), QCheckBox("ZP"), QCheckBox("AV")
        self.f_avl.setToolTip("In Avalanche einbezogen")
        self.f_zp.setToolTip("Zahlungsplan")
        self.f_av.setToolTip("Im Abschöpfungsverfahren")
        self.f_kf.currentIndexChanged.connect(self.refresh_liste)
        for cb in (self.f_avl, self.f_zp, self.f_av):
            cb.toggled.connect(self.refresh_liste)
        self.b_reset = button("Zurücksetzen", flat=True, cb=self._filter_reset)
        lay = self.liste.parentWidget().layout()
        lay.insertLayout(lay.indexOf(self.liste), hbox(self.f_kf, self.f_avl, self.f_zp, self.f_av, None, self.b_reset))

    def _filter_reset(self):
        for w in (self.f_kf, self.f_avl, self.f_zp, self.f_av, self.filter):
            w.blockSignals(True)
        self.f_kf.setCurrentIndex(0)
        self.filter.setCurrentIndex(1)  # Alle
        for cb in (self.f_avl, self.f_zp, self.f_av):
            cb.setChecked(False)
        for w in (self.f_kf, self.f_avl, self.f_zp, self.f_av, self.filter):
            w.blockSignals(False)
        self.suche.clear()
        self.refresh_liste()

    @staticmethod
    def _flags(l):
        f = []
        if not l["isBankruptcyEligible"]:
            f.append("NK")
        if l["allowAvalanche"]:
            f.append("AVL")
        if l["isPaymentPlan"]:
            f.append("ZP")
        if l["isInAbschoepfung"]:
            f.append("AV")
        return f

    def aufbauen(self):
        from PySide6.QtWidgets import QMenu, QPushButton
        self._filterzeile()
        self.b_mehr = QPushButton("Aktionen ▾")
        m = QMenu(self.b_mehr)
        m.addAction("Korrektur buchen …", self.korrektur)
        m.addAction("In Zahlungsplan umwandeln …", self.zahlungsplan)
        m.addAction("Zahlungsplan rückgängig", lambda: self._q("Zahlungsplan rückgängig machen?", self.db.zahlungsplan_rueckgaengig,
                                                               "Zahlungsplan rückgängig gemacht."))
        m.addAction("Tilgungsplan neu berechnen", lambda: self.tu(self._recalc, ok="Plan neu berechnet."))
        m.addSeparator()
        m.addAction("Als bezahlt markieren", lambda: self._q("Als bezahlt markieren?", self.db.als_bezahlt_markieren, "Als bezahlt markiert."))
        m.addAction("Reaktivieren", lambda: self._q("Verbindlichkeit reaktivieren?", self.db.reaktivieren, "Reaktiviert."))
        m.addSeparator()
        m.addAction("PDF Tilgungsplan", lambda: self.pdf(pdf.tilgungsplan, f"tilgungsplan-{self.obj['id']}", self.obj["id"]))
        m.addAction("PDF Buchungsmitteilung", lambda: self.pdf(pdf.buchungsmitteilung, f"buchungsmitteilung-{self.obj['id']}", self.obj["id"]))
        m.addSeparator()
        m.addAction("Löschen …", self.loeschen)
        self.b_mehr.setMenu(m)
        self.aktionen.addWidget(self.b_mehr)
        self.b_speichern = self.aktion("Speichern", self.speichern, emph=True)

        v = self.tab("Übersicht")
        self.kpi = KpiReihe(["Ursprungssaldo", "Aktueller Saldo", "Zinssatz", "Nächste Rate"])
        v.addWidget(self.kpi)
        c = Card("Stammdaten")
        self.f = Felder([("contactId", "Gläubiger", "combo", []), ("name", "Bezeichnung", "text"),
                         ("currentBalance", "Saldo (nur bei Neuanlage)", "dec"),
                         ("interestRate", "Zinssatz (% p.a.)", "dec", 4), ("interestType", "Zinstyp", "combo",
                                                                          [("FIX", "Fix"), ("VARIABEL", "Variabel")]),
                         ("repaymentType", "Rückzahlungstyp", "combo", REP_TYPEN), ("repaymentValue", "Rate (€/Monat)", "dec"),
                         ("repaymentPercentage", "Rate in % vom Saldo", "dec", 4), ("repaymentMinimum", "Mindestrate (€)", "dec"),
                         ("dueDay", "Fälligkeitstag (1–28)", "int"), ("isBankruptcyEligible", "Privatkonkurs", "bool", "konkursfähig"),
                         ("allowAvalanche", "Avalanche", "bool", "in Avalanche einbeziehen"),
                         ("notes", "Notizen", "multi")])
        c.lay.addWidget(self.f)
        # IBAN unter den übrigen Feldern, volle Breite
        from PySide6.QtWidgets import QLineEdit
        self.iban = QLineEdit()
        self.iban.setMaxLength(42)   # mit Leerzeichen/Bindestrichen; gespeichert max. 34 Zeichen
        self.iban.textChanged.connect(self._iban_pruefen)
        self.iban_fehler = label("", "sub")
        self.iban_fehler.setStyleSheet("color:#BB0000;")
        c.lay.addWidget(label("IBAN (für Zahlungen an den Gläubiger)", "formlabel"))
        c.lay.addWidget(self.iban)
        c.lay.addWidget(self.iban_fehler)
        self.f_sepa = Felder([("zahlungsreferenz", "Zahlungsreferenz (optional)", "text", "z. B. RF18 5390 0754 7034"),
                              ("verwendungszweck", "Verwendungszweck (optional)", "text", "leer = Standardvorlage")], spalten=2)
        self.f_sepa.felder["zahlungsreferenz"].setMaxLength(40)
        self.f_sepa.felder["verwendungszweck"].setMaxLength(140)
        c.lay.addWidget(self.f_sepa)
        hinweis = label("Für die SEPA-Zahlungsdatei: Die Zahlungsreferenz hat Vorrang. Im Verwendungszweck sind Platzhalter "
                        "erlaubt ({bezeichnung} {glaeubiger} {rate} {faellig} {monat}); leer = Standardvorlage.", "sub")
        hinweis.setWordWrap(True)
        c.lay.addWidget(hinweis)
        self.f.felder["contactId"].currentIndexChanged.connect(lambda _i: self._iban_platzhalter())
        v.addWidget(c)
        self.iban_info = label("", "sub")
        v.addWidget(self.iban_info)
        self.zp_info = label("", "sub")
        v.addWidget(self.zp_info)
        v.addStretch()

        v = self.tab("Tilgungsplan")
        from ..widgets import button
        v.addLayout(hbox(button("Markierte Rate bezahlen …", emph=True, cb=self.rate_bezahlen), None,
                         label("Bezahlte Raten bleiben erhalten; offene Raten werden bei jeder Änderung neu berechnet.", "sub")))
        self.t_plan = Tabelle([">#", "Datum", ">Rate", ">Zinsen", ">Tilgung", ">Restsaldo", "Bezahlt"], [50, 100, 110, 100, 110, 120, None])
        self.t_plan.setMinimumHeight(460)
        v.addWidget(self.t_plan)

        v = self.tab("Korrekturen")
        v.addLayout(hbox(button("Korrektur buchen …", emph=True, cb=self.korrektur), None,
                         button("Letzte Korrektur löschen", flat=True, neg=True, cb=self.korr_loeschen)))
        self.t_korr = Tabelle(["Datum", "Typ", "Beschreibung", ">Vorher", ">Änderung", ">Nachher"], [95, 190, None, 110, 110, 110])
        self.t_korr.setMinimumHeight(360)
        v.addWidget(self.t_korr)

    def eintraege(self):
        f = self.filter.currentData()
        rows = self.db.verbindlichkeiten()
        if f == "OFFEN":
            rows = [l for l in rows if l["status"] != "BEZAHLT"]
        elif f in ("ZAHLUNGSPLAN", "BEZAHLT"):
            rows = [l for l in rows if l["status"] == f]
        alle = len(rows)
        kf = self.f_kf.currentData()
        if kf == "KF":
            rows = [l for l in rows if l["isBankruptcyEligible"]]
        elif kf == "NKF":
            rows = [l for l in rows if not l["isBankruptcyEligible"]]
        if self.f_avl.isChecked():
            rows = [l for l in rows if l["allowAvalanche"]]
        if self.f_zp.isChecked():
            rows = [l for l in rows if l["isPaymentPlan"]]
        if self.f_av.isChecked():
            rows = [l for l in rows if l["isInAbschoepfung"]]
        q = self.suche.text().lower().strip()
        if q:
            rows = [l for l in rows if q in f"{l['contactName']} {l['name']}".lower()]
        tot = sum((d(l["currentBalance"]) for l in rows if l["status"] != "BEZAHLT"), Decimal(0))
        self.summe.setText(f"{len(rows)} von {alle} · offen {eur(tot)}")
        return [(l["id"], f"{l['contactName']} – {l['name']}",
                 " · ".join([eur(l["currentBalance"]), l["repaymentType"], l["status"]] + self._flags(l))) for l in rows]

    def laden(self, oid):
        l = self.db.verbindlichkeit(oid)
        l["interestRate"] = D(l["interestRate"]) * 100
        l["repaymentPercentage"] = D(l["repaymentPercentage"]) * 100 if l["repaymentPercentage"] else None
        return l

    def neu_obj(self):
        return {"repaymentType": "FIX", "interestType": "FIX", "isBankruptcyEligible": True, "interestRate": "0"}

    def neu(self):
        super().neu()
        if not self.db.kontakte():
            self.meldung("Zuerst den Gläubiger anlegen: links „Kontakte“ → „+ Kontakt“. Danach hier die Schuld erfassen und "
                         "den Gläubiger auswählen.", "warn")

    def _recalc(self):
        with self.db.tx():
            self.db.recalculate_plan(self.obj["id"])

    def _q(self, text, fn, ok):
        if self.obj and self.obj.get("id") and frage(self, self.obj["name"], text):
            self.tu(fn, self.obj["id"], ok=ok)

    def fuellen(self):
        o = self.obj
        w = self.f.felder["contactId"]
        w.clear()
        for k, t in kontakt_items(self.db, True):
            w.addItem(t, k)
        self.f.set(o)
        self.f_sepa.set(o)
        neu = not o.get("id")
        self.f.enable("currentBalance", neu)
        self.iban.blockSignals(True)
        self.iban.setText(ib.formatieren(o.get("iban")))
        self.iban.blockSignals(False)
        self._iban_pruefen()
        self._iban_platzhalter()
        self.b_mehr.setEnabled(not neu)
        self.h_name.setText(o.get("name") or "Neue Verbindlichkeit")
        self.h_badge.setVisible(not neu)
        set_badge(self.h_badge, o.get("status", ""), STATUS_ART.get(o.get("status"), "none"))
        if neu:
            self.h_sub.setText("")
            for t in (self.t_plan, self.t_korr):
                t.set_rows([])
            self.iban_info.setText("")
            return
        if o["iban"]:
            iban_txt = f"IBAN {ib.formatieren(o['iban'])}"
            self.iban_info.setText(f"IBAN für Zahlungen: {ib.formatieren(o['iban'])}")
            self.iban_info.setStyleSheet("")
        elif o["contactIban"]:
            iban_txt = f"IBAN {ib.formatieren(o['contactIban'])} (Kontakt)"
            self.iban_info.setText(f"IBAN für Zahlungen: {ib.formatieren(o['contactIban'])} – vom Kontakt, keine eigene hinterlegt")
            self.iban_info.setStyleSheet("color:#6A6D70;")
        else:
            iban_txt = "keine IBAN"
            self.iban_info.setText("Keine IBAN hinterlegt (weder an der Verbindlichkeit noch beim Kontakt).")
            self.iban_info.setStyleSheet("color:#6A6D70;")
        self.h_sub.setText(f"Gläubiger: {o['contactName']} · {iban_txt}"
                           + (" · im Abschöpfungsverfahren" if o["isInAbschoepfung"] else "")
                           + ("" if o["isBankruptcyEligible"] else " · nicht konkursfähig"))
        nxt = next((p for p in o["plan"] if not p["paidAt"]), None)
        self.kpi.set("Ursprungssaldo", eur(o["originalBalance"]))
        self.kpi.set("Aktueller Saldo", eur(o["currentBalance"]), "red")
        self.kpi.set("Zinssatz", f"{num(o['interestRate'], 3)} %")
        self.kpi.set("Nächste Rate", f"{eur(nxt['payment'])} ({dat(nxt['monthDate'])[:6]})" if nxt else "–")
        self.zp_info.setText(f"Zahlungsplan: Quote {pct(o['paymentPlanRate'])}, {o['paymentPlanMonths']} Monate, Intervall "
                             f"{o['paymentPlanInterval']} Monate, Start {dat(o['paymentPlanStart'])}" if o["isPaymentPlan"] else "")
        self.t_plan.set_rows([[str(p["monthNo"]), dat(p["monthDate"]), eur(p["payment"]), (eur(p["interest"]), "red"),
                               (eur(p["principal"]), "green"), (eur(p["endBalance"]), None, True),
                               (f"✓ {dat(p['paidAt'])} · {eur(p['paidAmount'])}", "green") if p["paidAt"] else ""]
                              for p in o["plan"]], [p["id"] for p in o["plan"]])
        k = o["corrections"]
        self.t_korr.set_rows([[dat(c["correctionDate"]), c["correctionType"], c["description"] or "–", eur(c["amountBefore"]),
                               (eur(c["amountChange"], True), tone_of(c["amountChange"])), (eur(c["amountAfter"]), None, True)]
                              for c in k], [c["id"] for c in k])

    def _iban_platzhalter(self):
        cid = self.f.felder["contactId"].currentData()
        k = self.db.get("contact", cid) if cid else None
        self.iban.setPlaceholderText(f"leer = IBAN des Kontakts ({ib.formatieren(k['iban'])})" if k and k["iban"] else "")

    def _iban_pruefen(self) -> bool:
        t = self.iban.text()
        n = ib.normalisieren(t)
        ok = not n or (len(n) <= 34 and ib.gueltig(n))
        self.iban_fehler.setText("" if ok else ib.FEHLER)
        self.iban_fehler.setVisible(not ok)
        self.iban.setStyleSheet("" if ok else "border:1px solid #BB0000;")
        if hasattr(self, "b_speichern"):
            self.b_speichern.setEnabled(ok)
        return ok

    def speichern(self):
        if not self._iban_pruefen():
            self.meldung(ib.FEHLER, "error")
            return
        try:
            b = self.f.get()
        except Exception as e:  # noqa: BLE001
            self.meldung(str(e), "error")
            return
        b["id"] = (self.obj or {}).get("id")
        b["iban"] = ib.normalisieren(self.iban.text())
        b.update(self.f_sepa.get())
        for k in ("interestRate", "repaymentPercentage"):
            b[k] = b[k] or ("0" if k == "interestRate" else None)
        i = self.tu(self.db.verbindlichkeit_speichern, b, ok="Gespeichert, Tilgungsplan neu berechnet.")
        if i:
            self.waehle(i)

    def korrektur(self):
        if not self.obj or not self.obj.get("id"):
            return
        o = self.obj
        w = dialog(self, f"Korrektur – {o['name']}", [
            ("correction_type", "Korrekturtyp", "combo", CORRECTION_TYPES),
            ("correction_date", "Datum", "date"),
            ("amount_change", "Änderungsbetrag (+ erhöht / − senkt Saldo)", "dec"),
            ("new_balance", "Neuer Saldo (nur bei Tagsatzung)", "dec"),
            ("description", "Beschreibung", "multi")],
            {"correction_type": "SONSTIG", "correction_date": date.today().isoformat()})
        if w:
            self.tu(self.db.korrektur_buchen, o["id"], w["correction_type"], w["amount_change"], w["new_balance"],
                    w["description"], w["correction_date"], ok="Korrektur gebucht.")

    def korr_loeschen(self):
        last = self.db.letzte_korrektur(self.obj["id"]) if self.obj and self.obj.get("id") else None
        if last and frage(self, "Korrektur löschen", f"Letzte Korrektur ({last['correctionType']}, {eur(last['amountChange'])}) "
                                                     "rückgängig machen?"):
            self.tu(self.db.korrektur_loeschen, last["id"], ok="Korrektur gelöscht.")

    def zahlungsplan(self):
        o = self.obj
        w = dialog(self, f"Zahlungsplan – {o['name']}", [
            ("rate", "Quote in % des Saldos", "dec"), ("months", "Laufzeit (Monate)", "int"),
            ("interval", "Intervall", "combo", [(1, "Monatlich"), (3, "Quartalsweise"), (6, "Halbjährlich"), (12, "Jährlich")]),
            ("start", "Erste Rate am", "date")],
            {"months": 36, "interval": 1, "start": date.today().isoformat()})
        if w:
            if not w["rate"] or D(w["rate"]) <= 0:
                self.meldung("Bitte eine gültige Quote eingeben.", "error")
                return
            self.tu(self.db.in_zahlungsplan_umwandeln, o["id"], w["rate"], w["months"] or 36, w["interval"], w["start"],
                    ok="In Zahlungsplan umgewandelt (Erlass als Korrektur gebucht).")

    def rate_bezahlen(self):
        rid = self.t_plan.sel_id()
        p = next((x for x in self.obj["plan"] if x["id"] == rid), None) if self.obj and rid else None
        if not p:
            self.meldung("Bitte zuerst eine Planzeile markieren.", "warn")
            return
        bezahle_rate(self, self.obj["id"], p["id"], p["payment"], f"Rate {p['monthNo']} – {self.obj['name']}")

    def loeschen(self):
        if frage(self, "Löschen", f"„{self.obj['name']}“ löschen? Mit Historie wird sie nur ausgeblendet."):
            if self.tu(self.db.verbindlichkeit_loeschen, self.obj["id"], ok=lambda m: m):
                self.obj = None
                self.tabs.setEnabled(False)


def num(x, nk=2):
    from ..common import num_de
    return num_de(x, nk)


def bezahle_rate(seite, lid, row_id, betrag, titel):
    """Rate bezahlt → Korrektur „Ratenzahlung“ an der Verbindlichkeit (kein Konto nötig)."""
    w = dialog(seite, titel, [("amount", "Betrag", "dec"), ("date", "Datum", "date")],
               {"amount": betrag, "date": date.today().isoformat()})
    if w:
        seite.tu(seite.db.planrate_bezahlen, lid, row_id, w["amount"], w["date"],
                 ok="Rate bezahlt – Korrektur „Ratenzahlung“ gebucht.")


# ── Offene Raten ──────────────────────────────────────────────────────────────
class OffeneRatenSeite(Seite):
    TITEL = "Offene Raten"
    UNTERTITEL = "Erste offene Planrate je Verbindlichkeit, nach Fälligkeit"

    def __init__(self, state):
        super().__init__(state)
        self.aktion("PDF", lambda: self.pdf(pdf.offene_raten, "offene-raten"))
        self.aktion("Zahlungsdatei (SEPA) …", lambda: self.window().navigate("zahlungsdatei"))
        self.aktion("Rate bezahlen …", self.zahlen, emph=True)
        self.kpi = KpiReihe(["Offene Raten", "Summe nächste Raten", "Davon überfällig"])
        self.body.addWidget(self.kpi)
        c = Card()
        self.t = Tabelle(["Fällig", "Verbindlichkeit", ">Rate Nr.", "Typ", ">Betrag"], [110, None, 90, 110, 130])
        self.t.setMinimumHeight(480)
        self.t.aktiviert.connect(lambda _i: self.zahlen())
        c.lay.addWidget(self.t)
        self.body.addWidget(c)

    def refresh(self):
        self.items = self.db.offene_raten(True)
        heute = date.today()
        self.kpi.set("Offene Raten", str(len(self.items)))
        self.kpi.set("Summe nächste Raten", eur(sum((i["payment"] for i in self.items), Decimal(0))), "red")
        self.kpi.set("Davon überfällig", str(sum(1 for i in self.items if i["dueDate"] < heute)), "red")
        self.t.set_rows([[(dat(i["dueDate"]), "red" if i["dueDate"] < heute else None), i["liabilityName"], str(i["monthNo"]),
                          i["repaymentType"], (eur(i["payment"]), "red", True)] for i in self.items],
                        list(range(len(self.items))))

    def zahlen(self):
        i = self.t.sel_id()
        if i is None:
            self.meldung("Bitte eine Rate markieren.", "warn")
            return
        it = self.items[i]
        bezahle_rate(self, it["liabilityId"], it["rowId"], it["payment"], f"Rate {it['monthNo']} – {it['liabilityName']}")


# ── Forderungen ───────────────────────────────────────────────────────────────
class ForderungenSeite(ListeDetail):
    TITEL = "Forderungen"
    NEU_TEXT = "+ Forderung"
    FILTER = [("OFFEN", "Offene"), ("ALLE", "Alle"), ("BEZAHLT", "Erledigte")]

    def aufbauen(self):
        self.aktion("Löschen", self.loeschen, neg=True, flat=True)
        self.aktion("PDF", lambda: self.obj and self.obj.get("id") and self.pdf(pdf.forderung, f"forderung-{self.obj['id']}", self.obj["id"]))
        self.b_pay = self.aktion("Zahlung erfassen …", self.zahlung)
        self.aktion("Speichern", self.speichern, emph=True)
        v = self.tab("Übersicht")
        self.kpi = KpiReihe(["Ursprungsbetrag", "Offener Betrag", "Bereits bezahlt", "Tilgungsgrad"])
        v.addWidget(self.kpi)
        c = Card("Details")
        self.f = Felder([("contactId", "Schuldner", "combo", []), ("name", "Bezeichnung", "text"),
                         ("originalAmount", "Forderungsbetrag (nur Neuanlage)", "dec"), ("interestRate", "Zinssatz (%)", "dec", 4),
                         ("interestType", "Zinstyp", "combo", [("FIX", "Fix"), ("VARIABEL", "Variabel")]),
                         ("dueDate", "Fälligkeit", "date"), ("paymentTerms", "Zahlungsmodalitäten", "text"),
                         ("notes", "Notizen", "multi")])
        c.lay.addWidget(self.f)
        v.addWidget(c)
        c = Card("Zahlungshistorie")
        self.t = Tabelle(["Datum", "Beschreibung", ">Betrag"], [100, None, 120])
        c.lay.addWidget(self.t)
        v.addWidget(c)
        v.addStretch()

    def eintraege(self):
        f = self.filter.currentData()
        rows = self.db.forderungen()
        if f == "OFFEN":
            rows = [c for c in rows if d(c["currentAmount"]) > 0]
        elif f == "BEZAHLT":
            rows = [c for c in rows if d(c["currentAmount"]) <= 0]
        tot = sum((d(c["currentAmount"]) for c in rows if d(c["currentAmount"]) > 0), Decimal(0))
        self.summe.setText(f"Offen gesamt: {eur(tot)}")
        heute = date.today().isoformat()
        return [(c["id"], f"{c['contactName']} – {c['name']}",
                 f"{eur(c['currentAmount'])} · {c['status']}" + (" · ⚠ überfällig" if c["dueDate"] and c["dueDate"] < heute and
                                                                 c["status"] != "BEZAHLT" else "")) for c in rows]

    def laden(self, oid):
        c = self.db.must("claim", oid)
        c["interestRate"] = D(c["interestRate"]) * 100
        return c

    def neu_obj(self):
        return {"interestType": "FIX"}

    def fuellen(self):
        o = self.obj
        w = self.f.felder["contactId"]
        w.clear()
        for k, t in kontakt_items(self.db, True):
            w.addItem(t, k)
        self.f.set(o)
        self.f.enable("originalAmount", not o.get("id"))
        self.h_name.setText(o.get("name") or "Neue Forderung")
        self.h_badge.setVisible(bool(o.get("id")))
        set_badge(self.h_badge, o.get("status", ""), {"BEZAHLT": "ok", "TEILBEZAHLT": "draft"}.get(o.get("status"), "none"))
        self.b_pay.setEnabled(bool(o.get("id")) and d(o.get("currentAmount") or 0) > 0)
        if not o.get("id"):
            self.t.set_rows([])
            return
        paid = d(o["originalAmount"]) - d(o["currentAmount"])
        self.kpi.set("Ursprungsbetrag", eur(o["originalAmount"]))
        self.kpi.set("Offener Betrag", eur(o["currentAmount"]), "green")
        self.kpi.set("Bereits bezahlt", eur(paid))
        self.kpi.set("Tilgungsgrad", f"{paid / d(o['originalAmount']) * 100:.1f} %".replace(".", ",") if d(o["originalAmount"]) else "–")
        p = self.db.forderung_zahlungen(o["id"])
        self.t.set_rows([[dat(x["paymentDate"]), x["description"] or "–", (eur(x["amount"]), "green", True)]
                         for x in p], hoehe_auto=True)

    def speichern(self):
        try:
            b = {**self.f.get(), "id": (self.obj or {}).get("id")}
        except Exception as e:  # noqa: BLE001
            self.meldung(str(e), "error")
            return
        i = self.tu(self.db.forderung_speichern, b, ok="Gespeichert.")
        if i:
            self.waehle(i)

    def zahlung(self):
        w = dialog(self, "Zahlung erfassen", [("amount", "Betrag", "dec"), ("date", "Datum", "date"),
                                              ("description", "Beschreibung", "text")], {"date": date.today().isoformat()})
        if w:
            self.tu(self.db.forderung_zahlung, self.obj["id"], w["amount"], w["description"], w["date"],
                    ok="Zahlung erfasst.")

    def loeschen(self):
        if self.obj and self.obj.get("id") and frage(self, "Löschen", f"Forderung „{self.obj['name']}“ löschen?"):
            if self.tu(self.db.forderung_loeschen, self.obj["id"], ok=lambda m: m):
                self.obj = None
                self.tabs.setEnabled(False)
