"""Module: Haushalt (+Szenarien, Fixkosten-Zahlungen), Lohn, Steuertarif, Privatkonkurs, Abschöpfung,
Avalanche, Postbuch, Tankbuch.

Port von routes/{household,household-scenarios,salary,steuertarif,bankruptcy,abschoepfung,avalanche,postbook}.ts.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal

from ..calc import finanz
from ..calc.lohn import berechne_lohn, jahrestarif, leite_monatstarif_ab, lohn_to_record, snum
from ..dates import add_months, iso, to_date
from ..dec import D, D0, ceil_to_multiple, d, f2, opt2
from ..db_base import FachFehler

ELIGIBLE = ("isBankruptcyEligible=1 AND status NOT IN ('GELOESCHT','BEZAHLT') AND CAST(currentBalance AS REAL)>0")


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _js(x):
    """Decimal/Datum für JSON-Snapshots als String."""
    if isinstance(x, dict):
        return {k: _js(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_js(v) for v in x]
    if isinstance(x, Decimal):
        return str(x)
    if isinstance(x, date):
        return x.isoformat()
    return x


class ModuleMixin:
    # ── Haushalt ──────────────────────────────────────────────────────────────
    def szenarien(self):
        return self.rows("SELECT * FROM household_scenario ORDER BY createdAt DESC, id DESC")

    def haushalt(self, scenario_id=None, category_ids=None) -> dict:
        sc = "householdScenarioId IS NULL" if not scenario_id else f"householdScenarioId={int(scenario_id)}"
        cat = ""
        if category_ids:
            cat = f" AND categoryId IN ({','.join(str(int(c)) for c in category_ids)})"
        q = lambda t: self.rows(f"SELECT x.*, k.name AS categoryName FROM {t} x LEFT JOIN category k ON k.id=x.categoryId "
                                f"WHERE x.isActive=1 AND x.{sc}{cat.replace('categoryId', 'x.categoryId')} ORDER BY x.name COLLATE NOCASE")
        fixed, variable = q("fixed_cost"), q("variable_expense")
        all_f = self.rows(f"SELECT plannedAmount FROM fixed_cost WHERE isActive=1 AND {sc}")
        all_v = self.rows(f"SELECT plannedAmount FROM variable_expense WHERE isActive=1 AND {sc}")
        tf = sum((d(x["plannedAmount"]) for x in fixed), D0)
        tv = sum((d(x["plannedAmount"]) for x in variable), D0)
        atf = sum((d(x["plannedAmount"]) for x in all_f), D0)
        atv = sum((d(x["plannedAmount"]) for x in all_v), D0)
        debt, rates = self.schuldendienst()
        soll = self.soll_lohn()
        meta = self.get("household_scenario", scenario_id) if scenario_id else None
        if scenario_id:
            sal = self.get("salary_calculation", meta["salaryScenarioId"]) if meta and meta["salaryScenarioId"] else None
            if sal and sal["netMonthly"]:
                net, quelle = D(sal["netMonthly"]), "SZENARIO_LOHN"
            elif meta and meta["manualNetMonthly"]:
                net, quelle = D(meta["manualNetMonthly"]), "MANUELL"
            else:
                net, quelle = D0, "KEIN_LOHN"
        else:
            net = D(soll["netMonthly"]) if soll and soll["netMonthly"] else D0
            quelle = "SOLL_LOHN" if soll else "KEIN_LOHN"
        return {"fixed": fixed, "variable": variable, "totalFixed": tf, "totalVariable": tv, "totalPlanned": tf + tv,
                "allTotalFixed": atf, "allTotalVariable": atv, "totalDebtService": debt, "debtRates": rates,
                "netMonthly": net, "surplus": net - atf - atv - debt, "lohnQuelle": quelle, "scenario": meta,
                "filtered": bool(category_ids)}

    def ausgabe_speichern(self, table: str, b: dict) -> int:
        """table: fixed_cost | variable_expense."""
        if not (b.get("name") or "").strip():
            raise FachFehler("Bezeichnung fehlt.")
        if b.get("plannedAmount") in (None, ""):
            raise FachFehler("Betrag fehlt.")
        data = {"name": b["name"].strip(), "categoryId": b.get("categoryId"), "plannedAmount": f2(d(b["plannedAmount"])),
                "notes": b.get("notes") or None, "householdScenarioId": b.get("householdScenarioId"),
                "isActive": 1 if b.get("isActive", True) else 0}
        if table == "fixed_cost":
            dd = b.get("dueDay")
            if dd not in (None, "") and not 1 <= int(dd) <= 28:
                raise FachFehler("Fälligkeitstag 1–28.")
            data["dueDay"] = int(dd) if dd not in (None, "") else None
            data["actualAmount"] = opt2(b.get("actualAmount") or None)
        ent = "FixedCost" if table == "fixed_cost" else "VariableExpense"
        with self.tx():
            if b.get("id"):
                self.update(table, b["id"], data)
                self.audit("UPDATE", ent, b["id"], None, {"name": data["name"]})
                return b["id"]
            i = self.insert(table, {**data, "createdAt": _now()})
            self.audit("CREATE", ent, i, None, {"name": data["name"], "plannedAmount": data["plannedAmount"]})
            return i

    def ausgabe_loeschen(self, table, i):
        with self.tx():
            self.update(table, i, {"isActive": 0})
            self.audit("SOFT_DELETE", "FixedCost" if table == "fixed_cost" else "VariableExpense", i)

    def szenario_speichern(self, b: dict) -> int:
        if not (b.get("name") or "").strip():
            raise FachFehler("Name fehlt.")
        data = {"name": b["name"].strip(), "salaryScenarioId": b.get("salaryScenarioId"),
                "manualNetMonthly": opt2(b.get("manualNetMonthly") or None), "manualNetSz13": opt2(b.get("manualNetSz13") or None),
                "manualNetSz14": opt2(b.get("manualNetSz14") or None)}
        with self.tx():
            if b.get("id"):
                self.update("household_scenario", b["id"], data)
                return b["id"]
            sid = self.insert("household_scenario", {**data, "createdAt": _now()})
            for f in self.rows("SELECT * FROM fixed_cost WHERE isActive=1 AND householdScenarioId IS NULL"):
                self.insert("fixed_cost", {"name": f["name"], "categoryId": f["categoryId"], "plannedAmount": f["plannedAmount"],
                                           "actualAmount": f["actualAmount"], "dueDay": f["dueDay"], "notes": f["notes"],
                                           "householdScenarioId": sid, "isActive": 1, "createdAt": _now()})
            for v in self.rows("SELECT * FROM variable_expense WHERE isActive=1 AND householdScenarioId IS NULL"):
                self.insert("variable_expense", {"name": v["name"], "categoryId": v["categoryId"],
                                                 "plannedAmount": v["plannedAmount"], "notes": v["notes"],
                                                 "householdScenarioId": sid, "isActive": 1, "createdAt": _now()})
            self.audit("CREATE", "HouseholdScenario", sid, None, {"name": data["name"]})
            return sid

    def szenario_loeschen(self, sid):
        with self.tx():
            self.exec("DELETE FROM fixed_cost_payment WHERE fixedCostId IN (SELECT id FROM fixed_cost WHERE householdScenarioId=?)", (sid,))
            self.exec("DELETE FROM fixed_cost WHERE householdScenarioId=?", (sid,))
            self.exec("DELETE FROM variable_expense WHERE householdScenarioId=?", (sid,))
            self.exec("DELETE FROM household_scenario WHERE id=?", (sid,))
            self.audit("DELETE", "HouseholdScenario", sid)

    def fixkosten_monat(self, jahr: int, monat: int) -> dict:
        ms = date(jahr, monat, 1).isoformat()
        with self.tx():
            for fc in self.rows("SELECT * FROM fixed_cost WHERE isActive=1 AND householdScenarioId IS NULL"):
                if not self.val("SELECT id FROM fixed_cost_payment WHERE fixedCostId=? AND month=?", (fc["id"], ms)):
                    self.insert("fixed_cost_payment", {"fixedCostId": fc["id"], "month": ms,
                                                       "plannedAmount": f2(fc["plannedAmount"]), "createdAt": _now()})
        items = self.rows("SELECT p.*, f.name, f.dueDay FROM fixed_cost_payment p JOIN fixed_cost f ON f.id=p.fixedCostId "
                          "WHERE p.month=? AND f.isActive=1", (ms,))
        items.sort(key=lambda x: x["dueDay"] or 99)
        return {"month": ms, "items": items,
                "totalPlanned": sum((d(i["plannedAmount"]) for i in items), D0),
                "totalPaid": sum((d(i["paidAmount"] or 0) for i in items if i["paidAt"]), D0),
                "totalOpen": sum((d(i["plannedAmount"]) for i in items if not i["paidAt"]), D0),
                "openCount": sum(1 for i in items if not i["paidAt"]), "paidCount": sum(1 for i in items if i["paidAt"])}

    def fixkosten_bezahlen(self, pid, betrag=None):
        """Nur als bezahlt markieren (ab 1.6.0 ohne Buchung/Konto)."""
        p = self.row("SELECT p.*, f.name FROM fixed_cost_payment p JOIN fixed_cost f ON f.id=p.fixedCostId WHERE p.id=?", (pid,))
        if not p:
            raise FachFehler("Fixkosten-Zahlung nicht gefunden")
        if p["paidAt"]:
            raise FachFehler("Bereits als bezahlt markiert")
        pay = abs(d(betrag) if betrag not in (None, "") else d(p["plannedAmount"]))
        if pay <= 0:
            raise FachFehler("Betrag muss größer als 0 sein")
        with self.tx():
            self.update("fixed_cost_payment", pid, {"paidAt": _now(), "paidAmount": f2(pay)})
            self.audit("PAY", "FixedCostPayment", pid, None, {"paidAmount": f2(pay)})

    def fixkosten_zuruecknehmen(self, pid):
        p = self.must("fixed_cost_payment", pid, "Fixkosten-Zahlung nicht gefunden")
        if not p["paidAt"]:
            raise FachFehler("Nicht als bezahlt markiert")
        with self.tx():
            self.update("fixed_cost_payment", pid, {"paidAt": None, "paidAmount": None})
            self.audit("UNPAY", "FixedCostPayment", pid, {"paidAmount": p["paidAmount"]})

    # ── Lohn ──────────────────────────────────────────────────────────────────
    def lohnberechnungen(self):
        return self.rows("SELECT * FROM salary_calculation WHERE isActive=1 ORDER BY calcType, id DESC")

    def lohn_vorschau(self, b: dict) -> dict:
        nz = lambda k: d(b[k]) if b.get(k) not in (None, "") else None
        return berechne_lohn(nz("monthlyBase"), nz("hoursActual"), nz("hourlyRate"), d(b.get("allowance") or "0"),
                             self.settings())

    def lohn_speichern(self, b: dict) -> int:
        if b.get("calcType") not in ("SOLL", "IST", "SZENARIO"):
            raise FachFehler("Typ ungültig.")
        if not (b.get("name") or "").strip():
            raise FachFehler("Bezeichnung fehlt.")
        r = self.lohn_vorschau(b)
        nz = lambda k, q="0.01": str(d(b[k]).quantize(Decimal(q))) if b.get(k) not in (None, "") else None
        rec = {"calcType": b["calcType"], "name": b["name"].strip(),
               "periodMonth": int(b["periodMonth"]) if b.get("periodMonth") else None,
               "periodYear": int(b["periodYear"]) if b.get("periodYear") else None,
               "kvName": b.get("kvName") or None, "lohnGruppe": b.get("lohnGruppe") or None, "stufe": b.get("stufe") or None,
               "hoursTarget": nz("hoursTarget"), "hoursActual": nz("hoursActual"),
               "hourlyRate": str(D(b["hourlyRate"]).quantize(Decimal("0.0001"))) if b.get("hourlyRate") else None,
               "monthlyBase": nz("monthlyBase"), "allowance": f2(d(b.get("allowance") or "0")), "notes": b.get("notes") or None,
               "isActive": 1, "createdAt": _now(), **lohn_to_record(r)}
        with self.tx():
            i = self.insert("salary_calculation", rec)
            self.audit("CREATE", "SalaryCalculation", i, None, {"calcType": rec["calcType"], "name": rec["name"]})
            return i

    def lohn_loeschen(self, i):
        with self.tx():
            self.update("salary_calculation", i, {"isActive": 0})
            self.audit("SOFT_DELETE", "SalaryCalculation", i)

    # ── Steuertarif ───────────────────────────────────────────────────────────
    def steuertarif(self) -> dict:
        S = self.settings()
        jt = jahrestarif(S)
        wk = float(snum(S, "werbungskosten_jahr", 132))
        return {"jahrestarif": jt, "werbungskostenJahr": wk, "monatstarif": leite_monatstarif_ab(jt, wk)}

    def steuertarif_speichern(self, jahrestarif_: list, wk: float):
        if not 2 <= len(jahrestarif_) <= 20:
            raise FachFehler("2 bis 20 Stufen erforderlich.")
        for s in jahrestarif_:
            if not 0 <= float(s["satz"]) <= 1:
                raise FachFehler("Satz muss zwischen 0 und 1 liegen (z. B. 0.20).")
        mt = leite_monatstarif_ab(jahrestarif_, wk)
        with self.tx():
            self.set_setting("lst_jahrestarif", json.dumps(jahrestarif_), "json", "LSt-Jahresstufen § 33 EStG (Grenze + Satz)")
            self.set_setting("werbungskosten_jahr", str(wk), "number", "Werbungskostenpauschale § 16 Abs. 3 EStG (Jahr)")
            self.set_setting("lst_tarif", json.dumps(mt), "json", "LSt-Monatstabelle (aus Jahresstufen hergeleitet)")
            self.audit("UPDATE", "Steuertarif", "lst_tarif", None, {"stufen": len(jahrestarif_), "werbungskostenJahr": wk})
        return mt

    # ── Privatkonkurs ─────────────────────────────────────────────────────────
    def konkurs_basis(self) -> dict:
        libs = self.rows(f"SELECT l.*, c.name AS contactName, COALESCE(NULLIF(l.iban,''), c.iban) AS contactIban FROM liability l JOIN contact c "
                         f"ON c.id=l.contactId WHERE l.isBankruptcyEligible=1 AND l.status NOT IN ('GELOESCHT','BEZAHLT') "
                         f"AND CAST(l.currentBalance AS REAL)>0 ORDER BY CAST(l.currentBalance AS REAL) DESC")
        soll = self.soll_lohn()
        g = lambda k: D(soll[k]) if soll and soll[k] else D0
        tf = sum((d(x["plannedAmount"]) for x in self.rows(
            "SELECT plannedAmount FROM fixed_cost WHERE isActive=1 AND householdScenarioId IS NULL")), D0)
        tv = sum((d(x["plannedAmount"]) for x in self.rows(
            "SELECT plannedAmount FROM variable_expense WHERE isActive=1 AND householdScenarioId IS NULL")), D0)
        total = sum((d(l["currentBalance"]) for l in libs), D0)
        basis = g("seizableMonthlyBasis")
        t_total = basis * 36
        return {"liabilities": libs, "totalEligible": total, "seizableMonthlyBasis": basis,
                "suggestedBase": ceil_to_multiple(basis, Decimal(50)) if basis > 0 else D0,
                "netMonthly": g("netMonthly"), "netSz13": g("netSz13"), "netSz14": g("netSz14"),
                "totalHousehold": tf + tv, "surplusBeforeDebt": g("netMonthly") - (tf + tv),
                "tilgungTotal": t_total, "tilgungQuote": (t_total / total) if total > 0 else D0,
                "hasSollLohn": bool(soll), "scenarios": self.rows("SELECT * FROM bankruptcy_scenario ORDER BY createdAt DESC, id DESC")}

    def konkurs_berechnen(self, b: dict, basis: dict | None = None) -> dict:
        basis = basis or self.konkurs_basis()
        eligible = [{"id": l["id"], "name": l["name"], "currentBalance": l["currentBalance"],
                     "contact": {"name": l["contactName"], "iban": l["contactIban"]}} for l in basis["liabilities"]]
        typ = b.get("scenarioType") or "TILGUNGSPLAN"
        dur, intv = int(b.get("durationMonths") or 36), int(b.get("intervalMonths") or 1)
        modus = "PERCENT" if b.get("inputMode") == "PERCENT" else "MONTHLY"
        wert = b.get("percentOfDebt") if modus == "PERCENT" else b.get("monthlyAmount")
        if typ == "TILGUNGSPLAN":
            jahre = int(self.setting("tilgungsplan_jahre", "3") or 3)
            res = finanz.tilgungsplan_privatkonkurs(basis["seizableMonthlyBasis"], eligible, jahre)
            return {"scenarioType": typ, "monthlyAmount": d(b.get("monthlyAmount") or 0), **res}
        res = finanz.zahlungsplan_privatkonkurs(modus, wert, dur, intv, eligible, to_date(b.get("startDatum")) or date.today())
        if modus == "PERCENT":
            res["percentOfDebt"] = str(D(wert or 0))
        ext = None
        if b.get("useExtended"):
            ext = finanz.erweitertes_angebot(res["monthlyAmount"], basis["surplusBeforeDebt"], basis["netSz13"], basis["netSz14"])
        return {"scenarioType": typ, **res, "extended": ext}

    def konkurs_speichern(self, result: dict, name=None, notes=None) -> int:
        basis = self.konkurs_basis()
        soll = self.soll_lohn()
        sv = lambda k: soll[k] if soll else None
        snap = None
        if result.get("creditorShares"):
            snap = [{"name": (cs["liability"].get("contact") or {}).get("name") or cs["liability"]["name"],
                     "bezeichnung": cs["liability"]["name"], "balance": str(cs["balance"]),
                     "iban": (cs["liability"].get("contact") or {}).get("iban"),
                     "anteilPct": str(cs["anteilPct"]), "zahlungGesamt": str(cs["zahlungGesamt"]),
                     "zahlungJeRate": str(cs["zahlungJeRate"]),
                     "zahlungLetzteRate": str(cs.get("zahlungLetzteRate", cs["zahlungJeRate"])),
                     **({"zahlungMin": str(cs["zahlungMin"]), "zahlungMax": str(cs["zahlungMax"])} if "zahlungMin" in cs else {})}
                    for cs in result["creditorShares"]]
        calc = _js({k: v for k, v in result.items() if k not in ("eligibleDebts",)})
        if "creditorShares" in calc:
            for cs in calc["creditorShares"]:
                cs["liability"] = {"id": cs["liability"]["id"], "name": cs["liability"]["name"],
                                   "contact": cs["liability"].get("contact")}
        rec = {"scenarioType": result["scenarioType"], "name": name or None, "salaryCalcId": soll and soll["id"],
               "grossMonthly": sv("grossMonthly"), "netMonthly": sv("netMonthly"), "netSz13": sv("netSz13"),
               "netSz14": sv("netSz14"), "seizableLfd": sv("seizableLfd"), "seizableSz13": sv("seizableSz13"),
               "seizableSz14": sv("seizableSz14"), "seizableAnnual": sv("seizableAnnual"),
               "seizableMonthlyBasis": f2(basis["seizableMonthlyBasis"]), "totalEligibleDebt": f2(basis["totalEligible"]),
               "monthlyAmount": f2(result.get("monthlyAmount") or 0),
               "durationMonths": result.get("durationMonths") or result.get("monate"),
               "intervalMonths": result.get("intervalMonths") or 1, "totalPayment": f2(result["totalPayment"]),
               "lastInstallment": f2(result["lastInstallment"]) if result.get("lastInstallment") is not None else None,
               "quote": str(result["quote"]), "tilgungsplanMonths": result.get("monate") or 36,
               "tilgungsplanTotal": f2(basis["tilgungTotal"]), "tilgungsplanQuote": str(basis["tilgungQuote"].quantize(Decimal("0.000001"))),
               "creditorSnapshot": snap, "calculationSnapshot": calc, "notes": notes, "createdAt": _now()}
        with self.tx():
            i = self.insert("bankruptcy_scenario", rec)
            self.audit("CREATE", "BankruptcyScenario", i, None, {"scenarioType": rec["scenarioType"], "name": rec["name"]})
            return i

    def konkurs_loeschen(self, i):
        with self.tx():
            self.exec("DELETE FROM bankruptcy_scenario WHERE id=?", (i,))
            self.audit("DELETE", "BankruptcyScenario", i)

    # ── Abschöpfung ───────────────────────────────────────────────────────────
    def abschoepfung(self) -> dict | None:
        v = self.row("SELECT * FROM abschoepfungs_verfahren WHERE status='AKTIV' ORDER BY id DESC LIMIT 1")
        if not v:
            return None
        v["liabilities"] = self.rows("SELECT al.*, l.name, l.currentBalance, c.name AS contactName FROM abschoepfungs_liability al "
                                     "JOIN liability l ON l.id=al.liabilityId JOIN contact c ON c.id=l.contactId "
                                     "WHERE al.verfahrenId=? ORDER BY CAST(al.snapshotBalance AS REAL) DESC", (v["id"],))
        v["raten"] = self.rows("SELECT * FROM abschoepfungs_rate WHERE verfahrenId=? ORDER BY rateNo", (v["id"],))
        v["paidCount"] = sum(1 for r in v["raten"] if r["paidAt"])
        v["openCount"] = v["durationMonths"] - v["paidCount"]
        v["totalPaid"] = sum((d(r["paidAmount"]) for r in v["raten"] if r["paidAmount"]), D0)
        return v

    def abschoepfung_anlegen(self, start, dauer: int, liability_ids: list[int]) -> int:
        if self.val("SELECT id FROM abschoepfungs_verfahren WHERE status='AKTIV'"):
            raise FachFehler("Es existiert bereits ein aktives Abschöpfungsverfahren.")
        if not liability_ids:
            raise FachFehler("Keine Verbindlichkeit gewählt.")
        libs = self.rows(f"SELECT * FROM liability WHERE id IN ({','.join(str(int(i)) for i in liability_ids)}) AND {ELIGIBLE}")
        if not libs:
            raise FachFehler("Keine gültige (offene, eligible) Verbindlichkeit in der Auswahl.")
        quoten = finanz.abschoepfung_quoten(libs)
        soll = self.soll_lohn()
        soll_amt = f2(soll["seizableMonthlyBasis"]) if soll and soll["seizableMonthlyBasis"] else None
        start = to_date(start)
        with self.tx():
            vid = self.insert("abschoepfungs_verfahren", {"startDate": iso(start), "durationMonths": int(dauer), "status": "AKTIV",
                                                          "createdAt": _now(), "updatedAt": _now()})
            for l in libs:
                self.insert("abschoepfungs_liability", {"verfahrenId": vid, "liabilityId": l["id"],
                                                        "snapshotBalance": f2(l["currentBalance"]),
                                                        "quota": str(quoten[l["id"]].quantize(Decimal("0.00000001")))})
            for n in range(int(dauer)):
                self.insert("abschoepfungs_rate", {"verfahrenId": vid, "rateNo": n + 1,
                                                   "month": add_months(start.replace(day=1), n).isoformat(),
                                                   "sollAmount": soll_amt, "createdAt": _now()})
            self.exec(f"UPDATE liability SET isInAbschoepfung=1 WHERE id IN ({','.join(str(l['id']) for l in libs)})")
            self.audit("CREATE", "AbschoepfungsVerfahren", vid, None,
                       {"durationMonths": int(dauer), "liabilityCount": len(libs),
                        "totalBalance": f2(sum((d(l["currentBalance"]) for l in libs), D0))})
            return vid

    def abschoepfung_rate_buchen(self, rate_id, betrag, datum=None) -> dict:
        paid = d(betrag)
        if paid <= 0:
            raise FachFehler("Betrag muss größer als 0 sein")
        rate = self.must("abschoepfungs_rate", rate_id, "Rate nicht gefunden")
        v = self.get("abschoepfungs_verfahren", rate["verfahrenId"])
        if v["status"] != "AKTIV":
            raise FachFehler("Verfahren ist nicht aktiv")
        if rate["paidAt"]:
            raise FachFehler("Rate ist bereits gebucht")
        als = self.rows("SELECT * FROM abschoepfungs_liability WHERE verfahrenId=?", (v["id"],))
        quota = {a["liabilityId"]: D(a["quota"]) for a in als}
        items = []
        for a in als:
            l = self.get("liability", a["liabilityId"])
            if l and d(l["currentBalance"]) > 0:
                items.append({"liabilityId": l["id"], "balance": d(l["currentBalance"]), "quota": quota.get(l["id"], D0)})
        allocs, unalloc = finanz.verteile_aliquot(paid, items)
        pay_date = to_date(datum) or date.today()
        with self.tx():
            for a in allocs:
                self.create_correction(a["liabilityId"], "ABSCHOEPFUNG", -a["amount"], f"Abschöpfung Rate {rate['rateNo']}",
                                       pay_date, rate_id)
            self.update("abschoepfungs_rate", rate_id, {"paidAt": iso(pay_date), "paidAmount": f2(paid)})
            for a in allocs:
                self.recalculate_plan(a["liabilityId"])
            self.audit("PAY", "AbschoepfungsRate", rate_id, None, {"rateNo": rate["rateNo"], "paidAmount": f2(paid),
                                                                   "allocations": len(allocs), "unallocated": f2(unalloc)})
        return {"allocations": allocs, "unallocated": unalloc}

    def abschoepfung_rate_zuruecknehmen(self, rate_id):
        rate = self.must("abschoepfungs_rate", rate_id, "Rate nicht gefunden")
        if not rate["paidAt"]:
            raise FachFehler("Rate ist nicht gebucht")
        if self.get("abschoepfungs_verfahren", rate["verfahrenId"])["status"] != "AKTIV":
            raise FachFehler("Verfahren ist nicht aktiv — Rate kann nicht zurückgenommen werden")
        corrs = self.rows("SELECT * FROM liability_correction WHERE abschoepfungsRateId=? AND correctionType='ABSCHOEPFUNG'", (rate_id,))
        with self.tx():
            aff = set()
            for c in corrs:
                self.create_correction(c["liabilityId"], "ABSCHOEPFUNG_STORNO", -d(c["amountChange"]),
                                       f"Storno Abschöpfung Rate {rate['rateNo']}", date.today())
                aff.add(c["liabilityId"])
            self.update("abschoepfungs_rate", rate_id, {"paidAt": None, "paidAmount": None})
            for lid in aff:
                self.recalculate_plan(lid)
            self.audit("UNPAY", "AbschoepfungsRate", rate_id, None, {"rateNo": rate["rateNo"], "reversedCorrections": len(corrs)})

    def abschoepfung_abbrechen(self, vid):
        v = self.must("abschoepfungs_verfahren", vid, "Verfahren nicht gefunden")
        if v["status"] != "AKTIV":
            raise FachFehler("Nur aktive Verfahren können abgebrochen werden")
        with self.tx():
            self.update("abschoepfungs_verfahren", vid, {"status": "ABGEBROCHEN", "updatedAt": _now()})
            self.exec("UPDATE liability SET isInAbschoepfung=0 WHERE id IN (SELECT liabilityId FROM abschoepfungs_liability "
                      "WHERE verfahrenId=?)", (vid,))
            self.audit("ABORT", "AbschoepfungsVerfahren", vid)

    def restschuldbefreiung(self, vid) -> int:
        v = self.must("abschoepfungs_verfahren", vid, "Verfahren nicht gefunden")
        if v["status"] != "AKTIV":
            raise FachFehler("Nur aktive Verfahren können abgeschlossen werden")
        libs = self.rows("SELECT l.* FROM liability l JOIN abschoepfungs_liability a ON a.liabilityId=l.id WHERE a.verfahrenId=?", (vid,))
        n = 0
        with self.tx():
            for l in libs:
                rest = d(l["currentBalance"])
                if rest > 0:
                    self.create_correction(l["id"], "RESTSCHULDBEFREIUNG", -rest, f"Restschuldbefreiung Verfahren {vid}", date.today())
                    n += 1
            for l in libs:
                self.update("liability", l["id"], {"isInAbschoepfung": 0, "status": "BEZAHLT", "updatedAt": _now()})
                self.recalculate_plan(l["id"])
            self.update("abschoepfungs_verfahren", vid, {"status": "ABGESCHLOSSEN", "restschuldbefreiungAt": _now(),
                                                         "updatedAt": _now()})
            self.audit("RESTSCHULDBEFREIUNG", "AbschoepfungsVerfahren", vid, None, {"liabilityCount": len(libs), "erlassen": n})
        return n

    # ── Avalanche ─────────────────────────────────────────────────────────────
    def avalanche_libs(self):
        return self.rows("SELECT l.*, c.name AS contactName FROM liability l JOIN contact c ON c.id=l.contactId WHERE "
                         "l.allowAvalanche=1 AND l.status NOT IN ('GELOESCHT','BEZAHLT') AND CAST(l.currentBalance AS REAL)>0 "
                         "ORDER BY CAST(l.interestRate AS REAL) DESC")

    def avalanche_berechnen(self, budget) -> dict:
        libs = self.avalanche_libs()
        if not libs:
            raise FachFehler("Keine Verbindlichkeiten für Avalanche aktiviert")
        b = d(budget)
        mint = sum((d(l["repaymentValue"] or 0) for l in libs), D0)
        if b < mint:
            raise FachFehler(f"Budget ({f2(b)}) ist kleiner als Mindestrate ({f2(mint)})")
        return finanz.avalanche(libs, b, date.today())

    def avalanche_speichern(self, res: dict) -> int:
        run = str(uuid.uuid4())
        with self.tx():
            self.exec("UPDATE avalanche_run SET isCurrent=0 WHERE isCurrent=1")
            i = self.insert("avalanche_run", {"runId": run, "planBudget": f2(res["budget"]), "totalInterest": f2(res["totalInterest"]),
                                              "totalMonths": res["totalMonths"], "interestSaved": f2(res["interestSaved"]),
                                              "isCurrent": 1, "calculatedAt": _now()})
            for r in res["results"]:
                self.insert("avalanche_result", {"runId": run, "liabilityId": r["liabilityId"], "monthNo": r["monthNo"],
                                                 "monthDate": iso(r["monthDate"]), "payment": f2(r["payment"]),
                                                 "interest": f2(r["interest"]), "principal": f2(r["principal"]),
                                                 "endBalance": f2(r["endBalance"]), "isTarget": int(r["isTarget"]),
                                                 "calculatedAt": _now()})
            self.audit("SAVE", "AvalancheRun", i, None, {"budget": f2(res["budget"]), "totalMonths": res["totalMonths"]})
            return i

    def avalanche_aktuell(self):
        run = self.row("SELECT * FROM avalanche_run WHERE isCurrent=1 ORDER BY calculatedAt DESC LIMIT 1")
        if run:
            run["results"] = self.rows("SELECT r.*, l.name FROM avalanche_result r JOIN liability l ON l.id=r.liabilityId "
                                       "WHERE runId=? ORDER BY monthNo, r.id", (run["runId"],))
        return run

    # ── Postbuch ──────────────────────────────────────────────────────────────
    def postbuch(self, suche="", typ="", erledigt=None):
        sql, args = "SELECT * FROM post_entry WHERE threadId IS NULL", []
        if typ:
            sql += " AND entryType=?"
            args.append(typ)
        if suche:
            sql += " AND correspondent LIKE ?"
            args.append(f"%{suche}%")
        if erledigt is not None:
            sql += " AND isDone=?"
            args.append(1 if erledigt else 0)
        rows = self.rows(sql + " ORDER BY entryDate DESC, id DESC", args)
        for r in rows:
            r["replies"] = self.rows("SELECT * FROM post_entry WHERE threadId=? ORDER BY entryDate, id", (r["id"],))
        return rows

    def post_offene_wiedervorlagen(self) -> int:
        return self.val("SELECT COUNT(*) FROM post_entry WHERE isDone=0 AND followupDate IS NOT NULL")

    def post_speichern(self, b: dict) -> int:
        if b.get("entryType") not in ("EINGANG", "AUSGANG"):
            raise FachFehler("Typ ungültig.")
        if not (b.get("correspondent") or "").strip():
            raise FachFehler("Absender/Empfänger fehlt.")
        if not b.get("entryDate"):
            raise FachFehler("Datum fehlt.")
        data = {"entryType": b["entryType"], "entryDate": iso(b["entryDate"]), "correspondent": b["correspondent"].strip(),
                "purpose": b.get("purpose") or None, "reference": b.get("reference") or None,
                "trackingNumber": b.get("trackingNumber") or None, "notes": b.get("notes") or None,
                "followupDate": iso(b.get("followupDate")), "contactId": b.get("contactId"), "threadId": b.get("threadId"),
                "updatedAt": _now()}
        with self.tx():
            if b.get("id"):
                self.update("post_entry", b["id"], data)
                self.audit("UPDATE", "PostEntry", b["id"], None, {"correspondent": data["correspondent"]})
                return b["id"]
            i = self.insert("post_entry", {**data, "createdAt": _now()})
            self.audit("CREATE", "PostEntry", i, None, {"entryType": data["entryType"], "correspondent": data["correspondent"]})
            return i

    def post_erledigt(self, i, erledigt=True):
        with self.tx():
            self.update("post_entry", i, {"isDone": 1, "isProcessed": 1} if erledigt else {"isDone": 0})
            self.audit("MARK_DONE" if erledigt else "REOPEN", "PostEntry", i)

    def post_loeschen(self, i):
        with self.tx():
            self.exec("DELETE FROM post_entry WHERE threadId=?", (i,))
            self.exec("DELETE FROM post_entry WHERE id=?", (i,))
            self.audit("DELETE", "PostEntry", i)

