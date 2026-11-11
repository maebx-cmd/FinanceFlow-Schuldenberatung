"""Alle PDF-Reports (Port von routes/reports.ts, routes/hr-pdf.ts + Postbuch-Report aus dem Juni-Stand).

Jede Funktion: (db, pfad, …) -> pfad. Inhalte/Kennzahlen 1:1 wie in der Web-Version.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

from .calc import iban as ib
from .calc import ratenplan_cent as rc
from .dates import MONATE, month_end
from .dec import D, D0, d
from .pdf_base import GRUEN, HELL, C, N, Report, datum, esc, eur, eurw, pct

INTERVAL = {1: "monatlich", 3: "quartalsweise", 6: "halbjährlich", 12: "jährlich"}


def ilabel(m):
    return INTERVAL.get(int(m), f"alle {m} Monate")


def _rep(db, titel, quer=False, sub=""):
    adresse = [x for x in (db.setting("owner_street", ""), db.setting("owner_city", "")) if x]
    return Report(titel, db.setting("owner_name", "") or "", sub, quer, adresse=adresse)


def _red_if_neg(v):
    return "red" if d(v) < 0 else "green"


# ── Finanz-Reports ────────────────────────────────────────────────────────────
def verbindlichkeiten(db, pfad):
    libs = db.rows("SELECT l.*, c.name AS cn FROM liability l JOIN contact c ON c.id=l.contactId WHERE l.status!='GELOESCHT' "
                   "ORDER BY CAST(l.currentBalance AS REAL) DESC")
    offen = [l for l in libs if l["status"] != "BEZAHLT"]
    tot = sum((d(l["currentBalance"]) for l in offen), D0)
    r = _rep(db, "Verbindlichkeitenübersicht")
    r.kpis([("Gesamtschulden (offen)", eurw(tot), "red"), ("Anzahl Verbindlichkeiten", str(len(offen)))])
    r.tabelle(["Gläubiger", "Bezeichnung", ">Zinssatz", "Typ", ">Rate/Mo", ">Restschuld", "Status"],
              [[l["cn"], l["name"], pct(l["interestRate"]), l["repaymentType"],
                eur(l["repaymentValue"]) if l["repaymentValue"] else "–",
                N(eur(l["currentBalance"]), "gray" if l["status"] == "BEZAHLT" else "red", l["status"] != "BEZAHLT"),
                l["status"]] for l in libs],
              [22, 22, 9, 8, 11, 13, 13], fuss=["Gesamt offen", "", "", "", "", N(eur(tot), "red"), ""])
    return r.speichern(pfad)


def tilgungsplan(db, pfad, lid):
    l = db.verbindlichkeit(lid)
    plan = l["plan"][:120]
    ti = sum((d(p["interest"]) for p in plan), D0)
    tp = sum((d(p["payment"]) for p in plan), D0)
    r = _rep(db, f"Tilgungsplan – {l['name']}")
    r.kpis([("Gläubiger", l["contactName"]), ("Aktuelle Restschuld", eurw(l["currentBalance"]), "red"),
            ("Zinssatz", pct(l["interestRate"])), ("Gesamtzinsbelastung", eurw(ti), "red"), ("Gesamtzahlung", eurw(tp))])
    r.tabelle([">#", "Datum", ">Rate", ">Zinsen", ">Tilgung", ">Restsaldo", "Bezahlt"],
              [[str(p["monthNo"]), datum(p["monthDate"]), eur(p["payment"]), N(eur(p["interest"]), "red"),
                N(eur(p["principal"]), "green"), N(eur(p["endBalance"]), bold=True),
                datum(p["paidAt"]) if p["paidAt"] else ""] for p in plan], [6, 14, 15, 14, 15, 17, 12])
    if len(l["plan"]) >= 120:
        r.text("* Anzeige auf 120 Raten begrenzt")
    return r.speichern(pfad)


def lohn(db, pfad, sid):
    c = db.must("salary_calculation", sid)
    r = _rep(db, f"Lohnberechnung – {c['name']}", sub=c["calcType"])
    r.kpis([("Brutto monatlich", eurw(c["grossMonthly"])), ("Netto laufend", eurw(c["netMonthly"]), "green"),
            ("Pfändungsbasis/Mo", eurw(c["seizableMonthlyBasis"]), "red")])
    r.abschnitt("Laufender Bezug")
    r.tabelle(["Position", ">Betrag"], [["Brutto", eur(c["grossMonthly"])], ["SV-Satz gesamt", pct(c["svTotalRate"])],
                                         ["SV-Betrag", N(eur(c["svAmount"]), "red")], ["BMG Lohnsteuer", eur(c["bmgLst"])],
                                         ["LSt-Satz", pct(c["lstRate"])], ["Lohnsteuer", N(eur(c["lstAmount"]), "red")]],
              [70, 30], gesamt=["Netto laufend", N(eur(c["netMonthly"]), "green")])
    r.abschnitt("Sonderzahlungen")
    r.tabelle(["", ">13. Gehalt", ">14. Gehalt"],
              [["Brutto", eur(c["grossSz13"]), eur(c["grossSz14"])],
               ["SV", N(eur(c["svSz13"]), "red"), N(eur(c["svSz14"]), "red")],
               ["BMG LSt", eur(c["bmgLstSz13"]), eur(c["bmgLstSz14"])],
               ["Lohnsteuer", N(eur(c["lstSz13"]), "red"), N(eur(c["lstSz14"]), "red")]], [40, 30, 30],
              gesamt=["Netto", N(eur(c["netSz13"]), "green"), N(eur(c["netSz14"]), "green")])
    r.abschnitt("Pfändung § 291a EO")
    r.tabelle(["Position", ">Betrag"], [["Existenzminimum lfd.", eur(c["existenzminimumLfd"])],
                                         ["Pfändbar lfd.", N(eur(c["seizableLfd"]), "red")],
                                         ["Pfändbar SZ13", N(eur(c["seizableSz13"]), "red")],
                                         ["Pfändbar SZ14", N(eur(c["seizableSz14"]), "red")],
                                         ["Pfändbar/Jahr", N(eur(c["seizableAnnual"]), "red", True)]], [70, 30],
              fuss=["Pfändungsbasis/Monat", N(eur(c["seizableMonthlyBasis"]), "red")])
    r.abschnitt("SV-Tarife")
    r.tabelle(["Beitrag", ">Satz"], [["KV", pct(c["svRateKv"])], ["PV", pct(c["svRatePv"])], ["AV", pct(c["svRateAv"])],
                                     ["AK", pct(c["svRateAk"])], ["WBF", pct(c["svRateWbf"])]], [70, 30])
    return r.speichern(pfad)


def lohn_vorschau(db, pfad, res: dict, name="Szenario"):
    """salary-preview: PDF einer nicht gespeicherten Berechnung."""
    r = _rep(db, f"Lohnberechnung – {name}", sub="Vorschau (nicht gespeichert)")
    r.kpis([("Brutto monatlich", eurw(res["brutto"])), ("Netto laufend", eurw(res["nettoLfd"]), "green"),
            ("Pfändungsbasis/Mo", eurw(res["seizableMonthlyBasis"]), "red")])
    r.tabelle(["Position", ">Betrag"], [["Brutto", eur(res["brutto"])], ["SV-Satz", pct(res["svTarifLfd"])],
                                         ["SV-Betrag", N(eur(res["svLfd"]), "red")], ["BMG Lohnsteuer", eur(res["bmgLstLfd"])],
                                         ["LSt-Satz", pct(res["lstSatzLfd"])], ["Lohnsteuer", N(eur(res["lstLfd"]), "red")]],
              [70, 30], gesamt=["Netto laufend", N(eur(res["nettoLfd"]), "green")])
    r.tabelle(["", ">13. Gehalt", ">14. Gehalt"],
              [["Brutto", eur(res["brutto"]), eur(res["brutto"])], ["SV", eur(res["svSz13"]), eur(res["svSz14"])],
               ["Lohnsteuer", eur(res["lstSz13"]), eur(res["lstSz14"])]], [40, 30, 30],
              gesamt=["Netto", eur(res["nettoSz13"]), eur(res["nettoSz14"])])
    r.tabelle(["Pfändung § 291a EO", ">Betrag"], [["Existenzminimum lfd.", eur(res["existenzminimumLfd"])],
                                                 ["Pfändbar lfd.", eur(res["seizableLfd"])],
                                                 ["Pfändbar SZ13", eur(res["seizableSz13"])],
                                                 ["Pfändbar SZ14", eur(res["seizableSz14"])],
                                                 ["Pfändbar/Jahr", eur(res["seizableAnnual"])]], [70, 30],
              fuss=["Pfändungsbasis/Monat", eur(res["seizableMonthlyBasis"])])
    return r.speichern(pfad)


def konkurs(db, pfad, sid):
    s = db.must("bankruptcy_scenario", sid)
    snap = json.loads(s["creditorSnapshot"]) if s["creditorSnapshot"] else None
    calc = json.loads(s["calculationSnapshot"]) if s["calculationSnapshot"] else None
    n = (s["durationMonths"] // s["intervalMonths"]) if s["durationMonths"] and s["intervalMonths"] else 0
    q = lambda v: f"{D(v) * 100:.2f} %".replace(".", ",") if v else "–"
    modus = (calc or {}).get("inputMode")
    r = _rep(db, f"Privatkonkurs – {s['scenarioType']}", sub=s["name"] or "")
    r.kpis([("Szenariotyp", s["scenarioType"]), ("Pfändungsbasis/Mo", eurw(s["seizableMonthlyBasis"]), "red"),
            ("Gesamtzahlung", eurw(s["totalPayment"])), ("Quote", q(s["quote"]))])
    rate_s = (calc or {}).get("amountPerInstallment")
    letzte_s = s.get("lastInstallment") or (calc or {}).get("lastInstallment")
    if calc:
        abw = letzte_s is not None and rate_s is not None and D(letzte_s) != D(rate_s)
        r.kpis([("Betrag je Rate / letzte" if abw else "Betrag je Rate",
                 f"{eurw(rate_s)} / {eurw(letzte_s)}" if abw else eurw(rate_s)),
                ("Intervall", ilabel(calc["intervalMonths"]) if calc.get("intervalMonths") else "–"),
                ("Anzahl Raten", str(calc.get("numInstallments", n))),
                ("Laufzeit", f"{calc.get('durationMonths', s['durationMonths'])} Monate")])
    r.abschnitt("Gläubigerverteilung" + (f" – {n} Raten" if n else ""))

    def je_rate(rate, letzte, mn=None, mx=None):
        if modus == "MONTHLY" and mn is not None and D(mn) != D(mx):
            return N(f"{eur(mn)} – {eur(mx)}")
        if letzte is not None and D(letzte) != D(rate):
            return N(eur(rate), klein=f"letzte {eur(letzte)}")
        return N(eur(rate))

    if snap:
        rows = [[C(cs["name"], klein=ib.formatieren(cs.get("iban")) or None), N(eur(cs["balance"]), "red", True), f"{D(cs['anteilPct']):.2f} %".replace(".", ","),
                 N(eur(cs["zahlungGesamt"]), bold=True),
                 je_rate(cs["zahlungJeRate"], cs.get("zahlungLetzteRate"), cs.get("zahlungMin"), cs.get("zahlungMax"))]
                for cs in snap]
        hint = None
    else:
        libs = db.rows("SELECT l.*, c.name AS cn FROM liability l JOIN contact c ON c.id=l.contactId WHERE l.isBankruptcyEligible=1 "
                       "AND l.status NOT IN ('GELOESCHT','BEZAHLT') AND CAST(l.currentBalance AS REAL)>0 "
                       "ORDER BY CAST(l.currentBalance AS REAL) DESC")
        salden = [rc.to_cents(l["currentBalance"]) for l in libs]
        te = sum(salden)
        anteile = rc.allocate(rc.to_cents(s["totalPayment"] or 0), salden)
        rows = []
        for l, sal, g in zip(libs, salden, anteile):
            jr, jl = rc.split_rates(g, n)
            rows.append([l["cn"], N(eur(l["currentBalance"]), "red", True),
                         f"{d(Decimal(sal) * 100 / te) if te else D0:.2f} %".replace(".", ","),
                         N(eur(rc.cents_to_dec(g)), bold=True),
                         je_rate(rc.cents_to_dec(jr if n > 1 else jl), rc.cents_to_dec(jl)) if n else "–"])
        hint = ("Hinweis: Für dieses Szenario wurde keine Gläubigerverteilung gespeichert. Die Aufteilung wurde aus den "
                "aktuellen Salden berechnet und kann vom ursprünglichen Angebot abweichen.")
    if rate_s is not None:
        fuss_rate = je_rate(rate_s, letzte_s)
    elif n:
        fr, fl = rc.split_rates(rc.to_cents(s["totalPayment"] or 0), n)
        fuss_rate = je_rate(rc.cents_to_dec(fr if n > 1 else fl), rc.cents_to_dec(fl))
    else:
        fuss_rate = "–"
    r.tabelle(["Gläubiger", ">Forderung", ">Anteil", ">Quotierter Betrag", ">Je Rate"], rows, [34, 18, 12, 18, 18],
              fuss=["Gesamtschuld", N(eur(s["totalEligibleDebt"]), "red"), "100,00 %", eur(s["totalPayment"]), fuss_rate])
    if hint:
        r.text(hint)
    if calc and calc.get("installmentDates"):
        dts = calc["installmentDates"]
        r.abschnitt("Fälligkeitskalender")
        r.text(f"Erste Rate: <b>{datum(dts[0]['datum'])}</b> · Letzte Rate: <b>{datum(dts[-1]['datum'])}</b> · {len(dts)} Raten")
        r.tabelle([">Nr.", "Fällig am", ">Betrag"], [[str(x["nr"]), datum(x["datum"]), eur(x["betrag"])] for x in dts], [15, 45, 40])
    if calc and calc.get("extended"):
        e = calc["extended"]
        r.abschnitt("Überschuss-Aufteilung auf Sonderzahlungen")
        r.text("Die monatliche Rate übersteigt den pfändbaren Überschuss. Der Mehrbetrag wird jährlich aus den "
               "Sonderzahlungen (13./14. Gehalt) aufgebracht.")
        r.tabelle(["Position", ">Betrag"], [["Monatliche Rate", eur(calc["monthlyAmount"])],
                                             ["Überschuss aus Haushaltsrechnung", eur(D(calc["monthlyAmount"]) - D(e["abweichung"]))],
                                             ["Monatliche Abweichung", N(eur(e["abweichung"]), "red")],
                                             ["Jährliche Überschreitung", N(eur(e["jaehrlicheUeberschreitung"]), "red")],
                                             ["Beitrag je Sonderzahlung", eur(e["beitragJeSz"])],
                                             ["Rest 13. Gehalt", eur(e["restSz13"])], ["Rest 14. Gehalt", eur(e["restSz14"])],
                                             ["Effektiv monatlich tragbar", N(eur(e["effektivMonatlich"]), bold=True)]],
                  [70, 30], gesamt=["Tragfähig", N("Ja" if e["tragfaehig"] else "Nein — Sonderzahlungen reichen nicht",
                                                    "green" if e["tragfaehig"] else "red")])
    if s["scenarioType"] == "ZAHLUNGSPLAN" and s["tilgungsplanTotal"]:
        r.abschnitt("Gegenüberstellung: Zahlungsplan vs. Abschöpfungsverfahren")
        r.tabelle(["", ">Zahlungsplan", ">Abschöpfungsverfahren"],
                  [["Gesamtzahlung an Gläubiger", N(eur(s["totalPayment"]), bold=True), eur(s["tilgungsplanTotal"])],
                   ["Quote", N(q(s["quote"]), bold=True), q(s["tilgungsplanQuote"])]], [40, 30, 30],
                  fuss=["Mehrbetrag Zahlungsplan", eur(D(s["totalPayment"] or 0) - D(s["tilgungsplanTotal"] or 0)), ""])
    if s["netMonthly"]:
        r.abschnitt("Lohndetails")
        r.tabelle(["Position", ">Betrag"], [["Netto monatlich", eur(s["netMonthly"])], ["Netto 13. Gehalt", eur(s["netSz13"])],
                                             ["Netto 14. Gehalt", eur(s["netSz14"])],
                                             ["Pfändbar/Jahr", N(eur(s["seizableAnnual"]), "red")]], [70, 30],
                  fuss=["Pfändungsbasis/Mo", N(eur(s["seizableMonthlyBasis"]), "red")])
    return r.speichern(pfad)


def _rate_letzte(rate, letzte):
    if letzte is not None and rate is not None and D(letzte) != D(rate):
        return N(eur(rate), klein=f"letzte {eur(letzte)}")
    return eur(rate)


def szenario_vergleich(db, pfad, ids):
    sc = db.rows(f"SELECT * FROM bankruptcy_scenario WHERE scenarioType='ZAHLUNGSPLAN' AND id IN ({','.join(str(int(i)) for i in ids)})")
    if not sc:
        raise ValueError("Keine passenden Zahlungsplan-Szenarien gefunden")
    sc.sort(key=lambda s: D(s["totalPayment"] or 0))
    h = db.haushalt()
    surplus = h["netMonthly"] - h["allTotalFixed"] - h["allTotalVariable"]
    av = next((s for s in sc if s["tilgungsplanTotal"]), None)
    av_t, av_q, av_l = (av["tilgungsplanTotal"], av["tilgungsplanQuote"], av["seizableLfd"]) if av else (None, None, None)
    snap = lambda s: json.loads(s["calculationSnapshot"]) if s["calculationSnapshot"] else {}
    q = lambda v: f"{D(v) * 100:.2f} %".replace(".", ",") if v else "–"

    def mehr(s):
        if not av_t:
            return "–"
        m = D(s["totalPayment"] or 0) - D(av_t)
        pp = (D(s["quote"] or 0) - D(av_q or 0)) * 100
        return f"{'+' if m > 0 else ''}{eur(m)} ({'+' if pp > 0 else ''}{f'{pp:.2f}'.replace('.', ',')} %-Pkt.)"

    def abw(s):
        a = D(s["monthlyAmount"] or 0) - surplus
        return N(("+" if a > 0 else "") + eur(a), "red" if a > 0 else "green")

    zeilen = [("Monatliche Rate", lambda s: eur(s["monthlyAmount"]), eur(av_l) if av_l else "–"),
              ("Betrag pro Rate", lambda s: _rate_letzte(snap(s).get("amountPerInstallment")
                                                         or d(D(s["monthlyAmount"] or 0) * (s["intervalMonths"] or 1)),
                                                         s.get("lastInstallment") or snap(s).get("lastInstallment")), "–"),
              ("Anteil pro Sonderzahlung", lambda s: eur((snap(s).get("extended") or {}).get("beitragJeSz")) if (snap(s).get("extended") or {}).get("beitragJeSz") else "–", "–"),
              ("Intervall", lambda s: ilabel(s["intervalMonths"]) if s["intervalMonths"] else "–", "monatlich"),
              ("Laufzeit", lambda s: f"{s['durationMonths']} Mon." if s["durationMonths"] else "–", "36 Mon."),
              ("Gesamtzahlung", lambda s: eur(s["totalPayment"]), eur(av_t) if av_t else "–"),
              ("Mehrbetrag ggü. Abschöpfung", mehr, "–"), ("Quote", lambda s: q(s["quote"]), q(av_q)),
              ("Abweichung z. Überschuss", abw, "–")]
    r = _rep(db, "Szenario-Vergleich", quer=len(sc) > 2)
    r.text(f"Monatlich verfügbarer Überschuss (netto − Haushalt): <b>{eurw(surplus)}</b> · Verglichene Szenarien: <b>{len(sc)}</b>")
    for ci in range(0, len(sc), 3):
        block = sc[ci:ci + 3]
        if len(sc) > 3:
            r.abschnitt(f"Szenarien {ci + 1}–{ci + len(block)} von {len(sc)}")
        r.tabelle(["Kennzahl"] + [">" + (s["name"] or f"Szenario {s['id']}") for s in block] + [">Abschöpfung"],
                  [[lab] + [fn(s) for s in block] + [C(avc, "gray")] for lab, fn, avc in zeilen],
                  [24] + [22] * len(block) + [16], keep=True)
    r.text("Die Abweichung zum Überschuss zeigt, ob die monatliche Rate aus dem laufenden Überschuss tragbar ist (positiv) oder "
           "ihn übersteigt (negativ); ein übersteigender Betrag ist über die Sonderzahlungen aufzubringen. Die Spalte "
           "„Abschöpfung“ führt das gesetzliche Abschöpfungsverfahren als Vergleichsmaßstab an.")
    return r.speichern(pfad)


def buchungsmitteilung(db, pfad, lid):
    l = db.verbindlichkeit(lid)
    c = l["contact"]
    r = _rep(db, f"Buchungsmitteilung – {l['name']}")
    # Adressblock des Gläubigers immer (früher nur mit verknüpftem Konto); IBAN der Verbindlichkeit, sonst des Kontakts
    z = [f"<b>{esc(c['name'])}</b>"] + [esc(x) for x in (c["company"], c["address"]) if x]
    if c["zipCode"] or c["city"]:
        z.append(esc(" ".join(x for x in (c["zipCode"], c["city"]) if x)))
    if c["country"] and c["country"] != "Österreich":
        z.append(esc(c["country"]))
    if l["ibanEff"]:
        z.append(f"IBAN: {esc(ib.formatieren(l['ibanEff']))}")
    if c["email"]:
        z.append(f"E-Mail: {esc(c['email'])}")
    if c["phone"]:
        z.append(f"Tel: {esc(c['phone'])}")
    r.box("Gläubiger / Vertragspartner", z)
    r.text(f"<b>Verbindlichkeit: {esc(l['name'])}</b>" + (f" ({esc(l['status'])})" if l["status"] != "OFFEN" else ""), klein=False)
    r.kpis([("Gläubiger", c["name"]), ("Ursprungssaldo", eurw(l["originalBalance"])),
            ("Aktueller Saldo", eurw(l["currentBalance"]), "red"), ("Zinssatz", pct(l["interestRate"]))])
    if l["corrections"]:
        r.abschnitt(f"Korrekturbuchungen ({len(l['corrections'])})")
        r.tabelle(["Datum", "Typ", "Beschreibung", ">Saldo vorher", ">Änderung", ">Saldo nachher"],
                  [[datum(k["correctionDate"]), k["correctionType"], k["description"] or "–", eur(k["amountBefore"]),
                    N(eur(k["amountChange"]), _red_if_neg(k["amountChange"])), N(eur(k["amountAfter"]), bold=True)]
                   for k in l["corrections"]], [11, 18, 31, 13, 13, 14])
    else:
        r.leer("Keine Korrekturbuchungen vorhanden.")
    return r.speichern(pfad)


def haushalt(db, pfad, scenario_id=None, category_ids=None):
    h = db.haushalt(scenario_id, category_ids)
    filt = bool(category_ids)
    fl, vl = ("Fixkosten (gefiltert)", "Variable (gefiltert)") if filt else ("Fixkosten", "Variable")
    titel = f"Haushaltsrechnung – Szenario: {h['scenario']['name']}" if h["scenario"] else "Haushaltsrechnung"
    s = h["surplus"]
    r = _rep(db, titel)
    if h["scenario"]:
        r.text("Szenario-Haushaltsrechnung – nicht die Ist-Rechnung")
    if filt:
        names = [k["name"] for k in db.kategorien() if k["id"] in category_ids]
        r.text("Gefiltert nach: <b>" + esc(", ".join(names)) + "</b>")
    r.kpis([("Netto laufend", eurw(h["netMonthly"]), "green"), (fl, eurw(h["totalFixed"]), "red"),
            (vl, eurw(h["totalVariable"]), "red"), ("Schuldendienst", eurw(h["totalDebtService"]), "red"),
            ("Überschuss" if s >= 0 else "Defizit", eurw(s), "green" if s >= 0 else "red")])
    r.abschnitt(f"{fl} ({eur(h['totalFixed'])})")
    r.tabelle(["Bezeichnung", "Kategorie", "Fällig", ">Betrag"],
              [[f["name"], C(f["categoryName"] or "–", "gray"), f"{f['dueDay']}. d. M." if f["dueDay"] else "–",
                N(eur(f["plannedAmount"]), "red")] for f in h["fixed"]], [45, 25, 12, 18],
              fuss=["Gesamt", "", "", N(eur(h["totalFixed"]), "red")])
    r.abschnitt(f"{vl} ({eur(h['totalVariable'])})")
    r.tabelle(["Bezeichnung", "Kategorie", ">Betrag"], [[v["name"], C(v["categoryName"] or "–", "gray"), N(eur(v["plannedAmount"]), "red")]
                                                        for v in h["variable"]], [55, 27, 18],
              fuss=["Gesamt", "", N(eur(h["totalVariable"]), "red")])
    r.abschnitt("Zusammenfassung")
    r.tabelle(["Position", ">Betrag"], [["Netto laufend", N(eur(h["netMonthly"]), "green")],
                                         ["− Fixkosten (gesamt)", N(eur(h["allTotalFixed"]), "red")],
                                         ["− Variable (gesamt)", N(eur(h["allTotalVariable"]), "red")],
                                         ["− Schuldendienst", N(eur(h["totalDebtService"]), "red")]], [70, 30],
              gesamt=["= Verfügbarer Überschuss" if s >= 0 else "= Defizit", N(eur(s), "green" if s >= 0 else "red")])
    return r.speichern(pfad)


def forderungen(db, pfad):
    cl = db.forderungen()
    today = date.today().isoformat()
    tot = sum((d(c["currentAmount"]) for c in cl if d(c["currentAmount"]) > 0), D0)
    over = lambda c: c["dueDate"] and c["dueDate"] < today and c["status"] != "BEZAHLT"
    r = _rep(db, "Forderungsübersicht")
    r.kpis([("Offene Forderungen gesamt", eurw(tot), "green"), ("Anzahl Forderungen", str(sum(1 for c in cl if c["status"] != "BEZAHLT"))),
            ("Davon überfällig", str(sum(1 for c in cl if over(c))), "red")])
    rows = []
    for c in cl:
        o = d(c["originalAmount"])
        pp = f"{(o - d(c['currentAmount'])) / o * 100:.1f}".replace(".", ",") if o > 0 else "0,0"
        rows.append([c["contactName"], c["name"], eur(o), N(eur(c["currentAmount"]), "green"), f"{pp} %",
                     datum(c["dueDate"]) + (" ⚠" if over(c) else ""), c["status"]])
    r.tabelle(["Schuldner", "Bezeichnung", ">Ursprung", ">Offen", ">Tilgung", "Fälligkeit", "Status"], rows,
              [18, 22, 13, 13, 9, 12, 13], fuss=["Gesamt offen", "", "", N(eur(tot), "green"), "", "", ""])
    return r.speichern(pfad)


def forderung(db, pfad, cid):
    c = db.must("claim", cid)
    k = db.get("contact", c["contactId"])
    pays = list(reversed(db.forderung_zahlungen(cid)))
    paid = d(c["originalAmount"]) - d(c["currentAmount"])
    o = d(c["originalAmount"])
    pp = f"{paid / o * 100:.1f}".replace(".", ",") if o > 0 else "0,0"
    over = c["dueDate"] and c["dueDate"] < date.today().isoformat() and c["status"] != "BEZAHLT"
    r = _rep(db, f"Forderung – {c['name']}")
    z = [f"<b>{esc(k['name'])}</b>"] + [esc(x) for x in (k["company"], k["address"]) if x]
    if k["zipCode"] or k["city"]:
        z.append(esc(" ".join(x for x in (k["zipCode"], k["city"]) if x)))
    z += [f"E-Mail: {esc(k['email'])}"] if k["email"] else []
    z += [f"Tel: {esc(k['phone'])}"] if k["phone"] else []
    z += [f"IBAN: {esc(ib.formatieren(k['iban']))}"] if k["iban"] else []
    r.box("Schuldner", z)
    r.text(f"<b>Forderung: {esc(c['name'])}</b> ({esc(c['status'])})", klein=False)
    r.kpis([("Ursprungsbetrag", eurw(o)), ("Offener Betrag", eurw(c["currentAmount"]), "green"), ("Bereits bezahlt", eurw(paid)),
            ("Tilgungsgrad", f"{pp} %")])
    r.abschnitt("Details")
    det = [["Zinssatz", pct(c["interestRate"])], ["Zinstyp", c["interestType"]],
           ["Fälligkeit", C(datum(c["dueDate"]) + (" (Überfällig)" if over else ""), "red" if over else None, bool(over))]]
    if c["paymentTerms"]:
        det.append(["Zahlungsmodalitäten", c["paymentTerms"]])
    if c["notes"]:
        det.append(["Notizen", c["notes"]])
    r.tabelle(["Feld", "Wert"], det, [30, 70])
    r.abschnitt(f"Zahlungshistorie ({len(pays)} Einträge)")
    if pays:
        r.tabelle(["Datum", "Beschreibung", ">Betrag"], [[datum(p["paymentDate"]), p["description"] or "–",
                                                          N(eur(p["amount"]), "green", True)] for p in pays],
                  [15, 65, 20], fuss=["Gesamt bezahlt", "", N(eur(paid), "green")])
    else:
        r.leer("Noch keine Zahlungen erfasst.")
    return r.speichern(pfad)


def glaeubigerverzeichnis(db, pfad, filt="all"):
    where = "l.status!='GELOESCHT'" + (" AND l.isBankruptcyEligible=1" if filt == "eligible" else
                                       " AND l.isBankruptcyEligible=0" if filt == "non-eligible" else "")
    libs = db.rows(f"SELECT l.*, c.name AS cn, c.address, c.zipCode, c.city, COALESCE(NULLIF(l.iban,''), c.iban) AS ibanEff "
                   f"FROM liability l JOIN contact c ON "
                   f"c.id=l.contactId WHERE {where} ORDER BY CAST(l.currentBalance AS REAL) DESC")
    tot = sum((d(l["currentBalance"]) for l in libs), D0)
    lab = {"all": "Alle Gläubiger", "eligible": "Konkursfähig", "non-eligible": "Nicht konkursfähig"}[filt]
    r = _rep(db, "Gläubigerverzeichnis", quer=True)
    r.text(f"Filter: <b>{lab}</b> · {len(libs)} Gläubiger · Gesamtschuld: <b>{eurw(tot)}</b>")
    r.kpis([("Gesamtschuld", eurw(tot), "red"), ("Anzahl Gläubiger", str(len(libs))), ("Filter", lab)])
    rows = []
    for l in libs:
        adr = l["address"] + (", " + " ".join(x for x in (l["zipCode"], l["city"]) if x) if (l["zipCode"] or l["city"]) else "") \
            if l["address"] else "–"
        an = f"{d(l['currentBalance']) / tot * 100:.2f}".replace(".", ",") if tot > 0 else "0,00"
        rows.append([l["cn"], l["name"], adr, C(ib.formatieren(l["ibanEff"]) or "–"), N(eur(l["currentBalance"]), "red"), f"{an} %",
                     pct(l["interestRate"]), eur(l["repaymentValue"]) if l["repaymentValue"] else "–", l["status"]])
    r.tabelle(["Gläubiger", "Verbindlichkeit", "Adresse", "IBAN", ">Restschuld", ">Anteil", ">Zinssatz", ">Rate/Mo", "Status"],
              rows, [14, 14, 18, 15, 10, 7, 7, 8, 9],
              fuss=["Gesamt", "", "", "", N(eur(tot), "red"), "100,00 %", "", "", ""])
    return r.speichern(pfad)


def zahlungsplan_uebersicht(db, pfad):
    libs = db.rows("SELECT l.*, c.name AS cn FROM liability l JOIN contact c ON c.id=l.contactId WHERE l.isPaymentPlan=1 AND "
                   "l.status!='GELOESCHT' AND CAST(l.currentBalance AS REAL)>0 ORDER BY CAST(l.currentBalance AS REAL) DESC")
    if not libs:
        raise ValueError("Keine Zahlungsplan-Verbindlichkeiten vorhanden")
    plans = db.rows(f"SELECT * FROM debt_repayment_plan WHERE liabilityId IN ({','.join(str(l['id']) for l in libs)}) ORDER BY monthNo")
    tot = sum((d(l["currentBalance"]) for l in libs), D0)
    trate = sum((d(l["repaymentValue"]) for l in libs if l["repaymentValue"]), D0)
    dates = sorted({p["monthDate"] for p in plans})
    r = _rep(db, "Zahlungsplan-Übersicht", quer=True)
    r.kpis([("Gesamtschuld (ZP)", eurw(tot), "red"), ("Gesamtrate/Intervall", eurw(trate), "red"),
            ("Anzahl Gläubiger", str(len(libs))), ("Fälligkeitstermine", str(len(dates)))])
    pmap = {(p["liabilityId"], p["monthDate"]): d(p["payment"]) for p in plans}
    for ci in range(0, len(libs), 6):
        ch = libs[ci:ci + 6]
        r.abschnitt("Fälligkeitskalender" + (f" – Gläubiger {ci + 1}–{ci + len(ch)} von {len(libs)}" if len(libs) > 6 else ""))
        rows = []
        for ds in dates[:60]:
            vals = [pmap.get((l["id"], ds)) for l in ch]
            rows.append([datum(ds)] + [eur(v) if v else "–" for v in vals] + [N(eur(sum((v for v in vals if v), D0)), bold=True)])
        r.tabelle(["Fällig am"] + [f">{l['cn']} ({eur(l['repaymentValue'] or 0)}/Rate)" for l in ch] + [">Block-Summe"], rows,
                  [12] + [14] * len(ch) + [12],
                  fuss=["Restschuld"] + [eur(l["currentBalance"]) for l in ch] + [N(eur(sum((d(l["currentBalance"]) for l in ch), D0)), "red")])
    r.abschnitt("Gesamt je Fälligkeitstermin")
    rows = []
    for ds in dates[:60]:
        dp_ = [p for p in plans if p["monthDate"] == ds]
        rows.append([datum(ds), str(len(dp_)), N(eur(sum((d(p["payment"]) for p in dp_), D0)), "red", True)])
    r.tabelle(["Fällig am", ">Gläubiger", ">Gesamt"], rows, [40, 20, 40], fuss=["Restschuld gesamt", str(len(libs)), N(eur(tot), "red")])
    r.abschnitt("Detailpläne je Gläubiger")
    for l in libs:
        an = f"{d(l['currentBalance']) / tot * 100:.2f}".replace(".", ",") if tot > 0 else "0,00"
        r.text(f"<b>{esc(l['cn'])}</b> · {esc(l['name'])} ({ilabel(l['paymentPlanInterval'] or 1)}) · "
               f"<font color='#AA0808'><b>{eurw(l['currentBalance'])}</b></font> · {an} % · Rate: {eurw(l['repaymentValue'])}", klein=False)
        r.tabelle([">#", "Fällig am", ">Betrag", ">Restsaldo"],
                  [[f"{p['monthNo']}.", datum(p["monthDate"]), eur(p["payment"]), C(eur(p["endBalance"]), "gray")]
                   for p in plans if p["liabilityId"] == l["id"]], [10, 30, 30, 30], keep=True)
    return r.speichern(pfad)


def vorschau12(db, pfad):
    ms = db.vorschau(12)
    tf = sum((m["fix"] for m in ms), D0)
    tr = sum((m["revolving"] for m in ms), D0)
    r = _rep(db, "12-Monats-Vorschau")
    r.kpis([("Summe Fix (12 Mon.)", eurw(tf)), ("Summe Revolving (12 Mon.)", eurw(tr)), ("Gesamt (12 Mon.)", eurw(tf + tr), "red")])
    r.tabelle(["Monat", ">Fix", ">Revolving", ">Gesamt"],
              [[C(f"{MONATE[m['monat'].month - 1]} {m['monat'].year}", bold=True), eur(m["fix"]), eur(m["revolving"]),
                N(eur(m["gesamt"]), "red", True)] for m in ms], [34, 22, 22, 22],
              fuss=["Gesamt", eur(tf), eur(tr), N(eur(tf + tr), "red")])
    return r.speichern(pfad)


def offene_raten(db, pfad):
    items = db.offene_raten(True)
    tot = sum((i["payment"] for i in items), D0)
    r = _rep(db, "Offene Raten")
    r.kpis([("Offene Raten", str(len(items))), ("Summe nächste Raten", eurw(tot), "red")])
    r.tabelle(["Verbindlichkeit", "Fällig", ">Rate Nr.", "Typ", ">Betrag"],
              [[i["liabilityName"], datum(i["dueDate"]), str(i["monthNo"]), i["repaymentType"], N(eur(i["payment"]), "red", True)]
               for i in items], [38, 15, 12, 15, 20], fuss=["Gesamt", "", "", "", N(eur(tot), "red")])
    return r.speichern(pfad)


def postbuch(db, pfad, monat: str, typ="all"):
    y, m = map(int, monat.split("-"))
    frm, to = date(y, m, 1), month_end(y, m)
    sql = "SELECT * FROM post_entry WHERE entryDate>=? AND entryDate<=? AND threadId IS NULL"
    args = [frm.isoformat(), to.isoformat()]
    if typ != "all":
        sql += " AND entryType=?"
        args.append(typ)
    es = db.rows(sql + " ORDER BY entryDate, id", args)
    for e in es:
        e["replies"] = db.rows("SELECT * FROM post_entry WHERE threadId=? ORDER BY entryDate, id", (e["id"],))
    tl = {"EINGANG": "Nur Eingänge", "AUSGANG": "Nur Ausgänge"}.get(typ, "Alle")
    r = _rep(db, f"Postbuch – {MONATE[m - 1]} {y} ({tl})", quer=True)
    r.kpis([("Eingang", str(sum(1 for e in es if e["entryType"] == "EINGANG"))),
            ("Ausgang", str(sum(1 for e in es if e["entryType"] == "AUSGANG"))), ("Gesamt", str(len(es))),
            ("Offen", str(sum(1 for e in es if not e["isDone"])), "amber")])
    today = date.today().isoformat()
    rows = []
    for e in es:
        for x, rep in [(e, False)] + [(rp, True) for rp in e["replies"]]:
            fu = C(datum(x["followupDate"]), "red" if x["followupDate"] and x["followupDate"] < today and not x["isDone"] else "gray") \
                if x["followupDate"] else "–"
            rows.append([("↳ " if rep else "") + datum(x["entryDate"]), C(x["entryType"], None, True), x["correspondent"],
                         x["purpose"] or "–", x["reference"] or "–", fu,
                         C("Erledigt" if x["isDone"] else "Offen", "green" if x["isDone"] else "amber", True)])
    r.tabelle(["Datum", "Typ", "Absender/Empfänger", "Betreff", "Referenz", "Wiedervorlage", "Status"], rows,
              [11, 9, 20, 25, 13, 11, 9])
    return r.speichern(pfad)
