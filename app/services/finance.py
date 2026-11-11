"""Finanzkern: Kontakte, Kategorien, Verbindlichkeiten, Forderungen, Dashboard.

Port von routes/{contacts,categories,liabilities,liabilities-extra,claims,dashboard,settings}.ts.
Ab 1.6.0 ohne Konten/Buchungen (wie Web): Zahlungen sind Korrekturen (RATENZAHLUNG) bzw. Forderungszahlungen.
Jede schreibende Operation läuft in EINER Transaktion (db.tx) und schreibt einen Audit-Eintrag.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from ..calc import iban as ib
from ..calc import sepa
from ..calc import ratenplan_cent as rc
from ..calc.finanz import berechne_tilgungsplan, monatlicher_schuldendienst, zahlungsplan_rows
from ..dates import add_months, iso, to_date
from ..dec import D, D0, d, f2, f6, opt2
from ..db_base import FachFehler

OPEN_LIAB = "status NOT IN ('GELOESCHT','BEZAHLT') AND CAST(currentBalance AS REAL) > 0"
CORRECTION_TYPES = [
    ("SALDOANPASSUNG", "Saldoanpassung"), ("ZINSNACHTRAG", "Zinsnachtrag"),
    ("GERICHTSKOSTEN", "Gerichtskosten / Verfahrenskosten"), ("ERLASS", "Teilerlass / Verzicht"),
    ("ZAHLUNGSPLANUMWANDLUNG", "Umwandlung in Zahlungsplan"), ("INKASSOKOSTEN", "Inkassokosten"),
    ("ANPASSUNG_TAGSATZUNG", "Anpassung Tagsatzung (neuer Saldo)"), ("RATENZAHLUNG", "Ratenzahlung"),
    ("SONSTIG", "Sonstige Korrektur"),
]


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _b(v):
    return 1 if v else 0


class FinanceMixin:
    # ── Kontakte ──────────────────────────────────────────────────────────────
    CONTACT_FIELDS = ["name", "role", "company", "address", "zipCode", "city", "country", "phone", "email", "iban",
                      "bic", "notes"]

    def kontakte(self, nur_aktive=True):
        return self.rows("SELECT * FROM contact" + (" WHERE isActive=1" if nur_aktive else "") + " ORDER BY name COLLATE NOCASE")

    def kontakt_speichern(self, k: dict) -> int:
        if not (k.get("name") or "").strip():
            raise FachFehler("Name fehlt.")
        if k.get("email") and "@" not in k["email"]:
            raise FachFehler("E-Mail-Adresse ungültig.")
        data = {f: (k.get(f) or None) for f in self.CONTACT_FIELDS}
        data["role"] = data["role"] or "BEIDE"
        data["country"] = data["country"] or "Österreich"
        with self.tx():
            if k.get("id"):
                old = self.get("contact", k["id"])
                self.update("contact", k["id"], data)
                self.audit("UPDATE", "Contact", k["id"], {"name": old["name"]}, {"name": data["name"]})
                return k["id"]
            cid = self.insert("contact", {**data, "isActive": 1, "createdAt": _now()})
            self.audit("CREATE", "Contact", cid, None, {"name": data["name"]})
            return cid

    def kontakt_loeschen(self, cid):
        with self.tx():
            old = self.get("contact", cid)
            self.update("contact", cid, {"isActive": 0})
            self.audit("SOFT_DELETE", "Contact", cid, {"name": old and old["name"]})

    # ── Kategorien ────────────────────────────────────────────────────────────
    def kategorien(self):
        return self.rows("SELECT * FROM category WHERE isActive=1 ORDER BY sortOrder, name COLLATE NOCASE")

    def kategorie_speichern(self, c: dict) -> int:
        if not (c.get("name") or "").strip():
            raise FachFehler("Name fehlt.")
        data = {"name": c["name"].strip(), "parentId": c.get("parentId"), "catType": c.get("catType") or "FIX",
                "color": c.get("color") or "#4F6BED", "sortOrder": int(c.get("sortOrder") or 0)}
        with self.tx():
            if c.get("id"):
                self.update("category", c["id"], data)
                self.audit("UPDATE", "Category", c["id"], None, {"name": data["name"]})
                return c["id"]
            cid = self.insert("category", {**data, "isActive": 1})
            self.audit("CREATE", "Category", cid, None, {"name": data["name"], "catType": data["catType"]})
            return cid

    def kategorie_loeschen(self, cid):
        n = (self.val("SELECT COUNT(*) FROM fixed_cost WHERE categoryId=? AND isActive=1", (cid,))
             + self.val("SELECT COUNT(*) FROM variable_expense WHERE categoryId=? AND isActive=1", (cid,))
             + self.val("SELECT COUNT(*) FROM category WHERE parentId=? AND isActive=1", (cid,)))
        if n:
            raise FachFehler("Kategorie wird noch verwendet und kann nicht gelöscht werden")
        with self.tx():
            self.update("category", cid, {"isActive": 0})
            self.audit("SOFT_DELETE", "Category", cid)

    # ── Verbindlichkeiten ─────────────────────────────────────────────────────
    def verbindlichkeiten(self, inkl_bezahlt=True):
        sql = ("SELECT l.*, c.name AS contactName, c.iban AS contactIban, COALESCE(NULLIF(l.iban,''), c.iban) AS ibanEff "
               "FROM liability l JOIN contact c ON c.id=l.contactId "
               "WHERE l.status!='GELOESCHT'")
        if not inkl_bezahlt:
            sql += " AND l.status!='BEZAHLT'"
        return self.rows(sql + " ORDER BY CAST(l.currentBalance AS REAL) DESC")

    def verbindlichkeit(self, lid) -> dict:
        l = self.row("SELECT l.*, c.name AS contactName FROM liability l JOIN contact c ON c.id=l.contactId WHERE l.id=?", (lid,))
        if not l:
            raise FachFehler("Nicht gefunden")
        l["contact"] = self.get("contact", l["contactId"])
        l["corrections"] = self.rows("SELECT * FROM liability_correction WHERE liabilityId=? ORDER BY correctionDate, id", (lid,))
        l["plan"] = self.rows("SELECT * FROM debt_repayment_plan WHERE liabilityId=? ORDER BY monthNo", (lid,))
        l["contactIban"] = l["contact"]["iban"] if l["contact"] else None
        l["ibanEff"] = l["iban"] or l["contactIban"]   # für Zahlungen: eigene IBAN, sonst die des Kontakts
        return l

    def recalculate_plan(self, lid):
        """Bezahlte Planzeilen bewahren (Weg B), unbezahlte Zukunft neu rechnen."""
        l = self.get("liability", lid)
        if not l:
            return
        paid = self.rows("SELECT * FROM debt_repayment_plan WHERE liabilityId=? AND paidAt IS NOT NULL ORDER BY monthNo", (lid,))
        self.exec("DELETE FROM debt_repayment_plan WHERE liabilityId=? AND paidAt IS NULL", (lid,))
        last = paid[-1] if paid else None
        offset = last["monthNo"] if last else 0
        anchor = add_months(to_date(last["monthDate"]), 1) if last else None
        if d(l["currentBalance"]) <= 0:
            return
        now = _now()
        if l["isPaymentPlan"]:
            rate = d(l["repaymentValue"]) if l["repaymentValue"] else D0
            interval = l["paymentPlanInterval"] or 1
            start = anchor or to_date(l["paymentPlanStart"]) or date.today()
            # Rundungsrest in die letzte planmäßige Rate (ratenplan_cent.merge_rounding_tail)
            geplant = 0
            if l["paymentPlanMonths"]:
                pstart = to_date(l["paymentPlanStart"])
                bezahlt = sum(1 for p in paid if not pstart or to_date(p["monthDate"]) >= pstart)
                geplant = int(l["paymentPlanMonths"]) // interval - bezahlt
            saldo = rc.to_cents(l["currentBalance"])
            verschub = 0
            if rate <= 0:   # Quotenbetrag kleiner als 1 Cent je Rate → alles in der letzten planmäßigen Rate
                if geplant <= 0:
                    return
                zahlungen, verschub = [saldo], geplant - 1
            else:
                zahlungen = [rc.to_cents(r["payment"]) for r in zahlungsplan_rows(d(l["currentBalance"]), rate, interval, start)]
                zahlungen = rc.merge_rounding_tail(zahlungen, geplant)
            for i, z in enumerate(zahlungen, 1):
                saldo -= z
                self.insert("debt_repayment_plan", {"liabilityId": lid, "monthNo": offset + i,
                                                    "monthDate": iso(add_months(start, (i - 1 + verschub) * interval)),
                                                    "payment": f2(rc.cents_to_dec(z)), "interest": "0.00",
                                                    "principal": f2(rc.cents_to_dec(z)), "endBalance": f2(rc.cents_to_dec(saldo)),
                                                    "calculatedAt": now})
            return
        for r in berechne_tilgungsplan(l, anchor or date.today()):
            self.insert("debt_repayment_plan", {"liabilityId": lid, "monthNo": offset + r["monthNo"], "monthDate": iso(r["monthDate"]),
                                                "payment": f2(r["payment"]), "interest": f2(r["interest"]),
                                                "principal": f2(r["principal"]), "endBalance": f2(r["endBalance"]),
                                                "calculatedAt": now})

    def create_correction(self, lid, typ, change: Decimal, beschreibung, datum, rate_id=None) -> int:
        l = self.get("liability", lid)
        if not l:
            raise FachFehler("Verbindlichkeit nicht gefunden")
        before = d(l["currentBalance"])
        after = d(before + change)
        cid = self.insert("liability_correction", {
            "liabilityId": lid, "correctionType": typ, "amountBefore": f2(before), "amountChange": f2(change),
            "amountAfter": f2(after), "description": beschreibung, "correctionDate": iso(datum), "createdAt": _now(),
            "abschoepfungsRateId": rate_id})
        self.update("liability", lid, {"currentBalance": f2(after), "updatedAt": _now()})
        return cid

    LIAB_FIELDS = ["contactId", "name", "interestType", "repaymentType", "dueDay", "allowAvalanche", "isBankruptcyEligible", "notes"]

    @staticmethod
    def iban_pruefen(wert) -> str | None:
        """Normalisieren (ohne Leerzeichen/Bindestriche, Großbuchstaben, leer → None) und prüfen (Aufbau + mod 97)."""
        n = ib.normalisieren(wert)
        if n and (len(n) > 34 or not ib.gueltig(n)):
            raise FachFehler(ib.FEHLER)
        return n

    def verbindlichkeit_speichern(self, b: dict) -> int:
        """b: Eingaben wie im Web-Formular (Zinssatz/Prozent in %, Beträge als Text)."""
        if not b.get("contactId"):
            raise FachFehler("Gläubiger fehlt.")
        if not (b.get("name") or "").strip():
            raise FachFehler("Bezeichnung fehlt.")
        if b.get("repaymentType") not in ("FIX", "PERCENT", "OPEN", "PLAN"):
            raise FachFehler("Rückzahlungstyp ungültig.")
        if b.get("dueDay") not in (None, "") and not 1 <= int(b["dueDay"]) <= 28:
            raise FachFehler("Fälligkeitstag muss zwischen 1 und 28 liegen.")
        data = {k: b.get(k) for k in self.LIAB_FIELDS}
        data["name"] = data["name"].strip()
        data["interestType"] = data["interestType"] or "FIX"
        data["dueDay"] = int(b["dueDay"]) if b.get("dueDay") not in (None, "") else None
        data["allowAvalanche"] = _b(b.get("allowAvalanche"))
        data["isBankruptcyEligible"] = _b(b.get("isBankruptcyEligible", True))
        data["interestRate"] = f6(d(b.get("interestRate") or "0") / 100)
        data["repaymentValue"] = opt2(b.get("repaymentValue") or None)
        data["repaymentPercentage"] = f6(d(b["repaymentPercentage"]) / 100) if b.get("repaymentPercentage") else None
        data["repaymentMinimum"] = opt2(b.get("repaymentMinimum") or None)
        data["notes"] = b.get("notes") or None
        data["iban"] = self.iban_pruefen(b.get("iban"))
        data["zahlungsreferenz"] = sepa.referenz_normalisieren(b.get("zahlungsreferenz"))
        if data["zahlungsreferenz"] and not sepa.referenz_gueltig(data["zahlungsreferenz"]):
            raise FachFehler("Zahlungsreferenz ungültig – höchstens 35 Zeichen, erlaubt sind A–Z, a–z, 0–9 und + ? / - : ( ) . , '")
        data["verwendungszweck"] = (b.get("verwendungszweck") or "").strip() or None
        if data["verwendungszweck"] and len(data["verwendungszweck"]) > 140:
            raise FachFehler("Verwendungszweck: höchstens 140 Zeichen.")
        with self.tx():
            if b.get("id"):
                lid = b["id"]
                old = self.must("liability", lid)
                self.update("liability", lid, {**data, "updatedAt": _now()})
                self.recalculate_plan(lid)
                self.audit("UPDATE", "Liability", lid, {"name": old["name"]}, {"name": data["name"]})
                return lid
            bal = d(b.get("currentBalance") or "0")
            lid = self.insert("liability", {**data, "originalBalance": f2(bal), "currentBalance": f2(bal), "status": "OFFEN",
                                            "createdAt": _now(), "updatedAt": _now()})
            self.recalculate_plan(lid)
            self.audit("CREATE", "Liability", lid, None, {"name": data["name"], "balance": f2(bal)})
            return lid

    def korrektur_buchen(self, lid, typ, betrag=None, neuer_saldo=None, beschreibung="", datum=None):
        with self.tx():
            if typ == "ANPASSUNG_TAGSATZUNG":
                l = self.must("liability", lid, "Verbindlichkeit nicht gefunden")
                if neuer_saldo in (None, ""):
                    raise FachFehler("Neuer Saldo erforderlich")
                nb = d(neuer_saldo)
                if nb < 0:
                    raise FachFehler("Neuer Saldo darf nicht negativ sein")
                change = d(nb - d(l["currentBalance"]))
                if change == 0:
                    raise FachFehler("Saldo unverändert — keine Korrektur nötig")
            else:
                if betrag in (None, ""):
                    raise FachFehler("Betrag fehlt.")
                change = d(betrag)
            cid = self.create_correction(lid, typ or "SONSTIG", change, beschreibung or "", to_date(datum) or date.today())
            self.recalculate_plan(lid)
            self.audit("CORRECT", "Liability", lid, None, {"correctionType": typ, "change": f2(change), "correctionId": cid})

    def _korrektur_zurueck(self, corr):
        self.update("liability", corr["liabilityId"], {"currentBalance": corr["amountBefore"], "updatedAt": _now()})
        # Ratenzahlung zurück → Planzeile wieder offen
        self.exec("UPDATE debt_repayment_plan SET paidAt=NULL, paidAmount=NULL, paidCorrectionId=NULL WHERE paidCorrectionId=?",
                  (corr["id"],))
        self.exec("DELETE FROM liability_correction WHERE id=?", (corr["id"],))
        # Kontoblatt-Import: gelöschte Buchung gilt wieder als neu (Id kann sonst neu vergeben werden)
        self.exec("DELETE FROM kontoblatt_zeile WHERE correctionId=? AND status='GEBUCHT'", (corr["id"],))

    def letzte_korrektur(self, lid):
        return self.row("SELECT * FROM liability_correction WHERE liabilityId=? ORDER BY correctionDate DESC, id DESC LIMIT 1", (lid,))

    def korrektur_loeschen(self, cid):
        corr = self.must("liability_correction", cid)
        latest = self.letzte_korrektur(corr["liabilityId"])
        if not latest or latest["id"] != cid:
            raise FachFehler("Nur die letzte Korrektur kann gelöscht werden")
        with self.tx():
            self._korrektur_zurueck(corr)
            self.recalculate_plan(corr["liabilityId"])
            self.audit("DELETE_CORRECTION", "LiabilityCorrection", cid, {"liabilityId": corr["liabilityId"],
                                                                         "correctionType": corr["correctionType"]})

    def als_bezahlt_markieren(self, lid):
        with self.tx():
            self.update("liability", lid, {"status": "BEZAHLT", "updatedAt": _now()})
            self.audit("MARK_DONE", "Liability", lid)

    def reaktivieren(self, lid):
        with self.tx():
            self.update("liability", lid, {"status": "OFFEN", "updatedAt": _now()})
            self.recalculate_plan(lid)
            self.audit("REACTIVATE", "Liability", lid)

    def verbindlichkeit_loeschen(self, lid) -> str:
        l = self.must("liability", lid)
        if d(l["currentBalance"]) > 0:
            raise FachFehler("Verbindlichkeit hat noch einen offenen Saldo")
        hist = self.val("SELECT COUNT(*) FROM liability_correction WHERE liabilityId=?", (lid,))
        bezahlt = self.val("SELECT COUNT(*) FROM debt_repayment_plan WHERE liabilityId=? AND paidAt IS NOT NULL", (lid,))
        with self.tx():
            if not hist and not bezahlt:
                self.exec("DELETE FROM debt_repayment_plan WHERE liabilityId=?", (lid,))
                self.exec("DELETE FROM liability WHERE id=?", (lid,))
                self.audit("DELETE", "Liability", lid, {"name": l["name"]})
                return "Verbindlichkeit gelöscht."
            self.update("liability", lid, {"status": "GELOESCHT", "updatedAt": _now()})
            self.audit("SOFT_DELETE", "Liability", lid, {"name": l["name"]})
            return "Verbindlichkeit ausgeblendet (Historie vorhanden)."

    def in_zahlungsplan_umwandeln(self, lid, quote_pct, monate=36, intervall=1, start=None):
        """Quotenbetrag centgenau (ratenplan_cent): z = gerundet(Saldo × Quote), Erlass = Saldo − z,
        gespeicherte Rate = split_rates(z, n).rate – die letzte planmäßige Rate nimmt die Differenz auf."""
        q_h = rc.pct(quote_pct)
        months, interval = int(monate), int(intervall)
        if q_h <= 0:
            raise FachFehler("Bitte eine gültige Quote eingeben")
        if interval <= 0 or months // interval <= 0:
            raise FachFehler("Laufzeit und Intervall ergeben keine Rate")
        start = to_date(start) or date.today()
        with self.tx():
            l = self.must("liability", lid)
            saldo = rc.to_cents(l["currentBalance"])
            z = rc.quotenbetrag(saldo, q_h)
            n = months // interval
            rate, _ = rc.split_rates(z, n)
            erlass = rc.cents_to_dec(saldo - z)
            if erlass > 0:
                self.create_correction(lid, "ZAHLUNGSPLANUMWANDLUNG", -erlass,
                                       f"Zahlungsplan: {q_h / 100:.2f}% in {n} Raten (Intervall: {interval} Monate)".replace(".", ","),
                                       start)
            self.update("liability", lid, {"isPaymentPlan": 1, "paymentPlanRate": f6(Decimal(q_h) / 10000),
                                           "paymentPlanMonths": months, "paymentPlanInterval": interval,
                                           "paymentPlanStart": iso(start), "repaymentType": "PLAN",
                                           "repaymentValue": f2(rc.cents_to_dec(rate)), "status": "ZAHLUNGSPLAN",
                                           "updatedAt": _now()})
            self.recalculate_plan(lid)
            self.audit("TO_PAYMENT_PLAN", "Liability", lid, None, {"ratePct": str((Decimal(q_h) / 100).quantize(Decimal('0.01'))),
                                                                   "months": months, "interval": interval,
                                                                   "quotenbetrag": f2(rc.cents_to_dec(z))})

    def zahlungsplan_rueckgaengig(self, lid):
        l = self.must("liability", lid)
        if not l["isPaymentPlan"]:
            raise FachFehler("Verbindlichkeit ist kein Zahlungsplan")
        last = self.letzte_korrektur(lid)
        if not last or last["correctionType"] != "ZAHLUNGSPLANUMWANDLUNG":
            raise FachFehler("Letzte Korrekturbuchung ist keine Zahlungsplanumwandlung – manuelles Eingreifen erforderlich")
        with self.tx():
            self._korrektur_zurueck(last)
            self.update("liability", lid, {"isPaymentPlan": 0, "status": "OFFEN", "repaymentType": "OPEN", "repaymentValue": None,
                                           "paymentPlanRate": None, "paymentPlanMonths": None, "paymentPlanInterval": None,
                                           "paymentPlanStart": None, "updatedAt": _now()})
            self.recalculate_plan(lid)
            self.audit("UNDO_PAYMENT_PLAN", "Liability", lid)

    def alle_plaene_neu(self) -> int:
        ids = [r["id"] for r in self.rows(f"SELECT id FROM liability WHERE {OPEN_LIAB}")]
        with self.tx():
            for i in ids:
                self.recalculate_plan(i)
        return len(ids)

    def planrate_bezahlen(self, lid, row_id, betrag=None, datum=None) -> int:
        """Rate bezahlt → Korrektur RATENZAHLUNG (Änderung = −min(Betrag, Saldo)); Planzeile zeigt auf die Korrektur.
        Funktioniert bei jeder Verbindlichkeit (kein Konto nötig)."""
        pr = self.get("debt_repayment_plan", row_id)
        if not pr or pr["liabilityId"] != lid:
            raise FachFehler("Planzeile nicht gefunden")
        if pr["paidAt"]:
            raise FachFehler("Rate ist bereits als bezahlt gebucht")
        pay = abs(d(betrag) if betrag not in (None, "") else d(pr["payment"] or 0))
        if pay <= 0:
            raise FachFehler("Betrag muss größer als 0 sein")
        with self.tx():
            l = self.must("liability", lid)
            change = -min(pay, d(l["currentBalance"]))
            betrag_text = f"{pay:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            cid = self.create_correction(lid, "RATENZAHLUNG", change, f"Rate {pr['monthNo']} bezahlt ({betrag_text} €)",
                                         to_date(datum) or date.today())
            self.update("debt_repayment_plan", row_id, {"paidAt": _now(), "paidAmount": f2(pay), "paidCorrectionId": cid})
            self.recalculate_plan(lid)
            self.audit("PAY", "DebtRepaymentPlan", row_id, None, {"paidAmount": f2(pay), "correctionId": cid})
            return cid

    def offene_raten(self, nur_erste=True, monat: str | None = None, plan_only=False):
        """nur_erste: erste offene Planrate je Verbindlichkeit (upcoming-installments), sonst alle (installments)."""
        where = OPEN_LIAB.replace("status", "l.status").replace("currentBalance", "l.currentBalance")
        if plan_only:
            where += " AND l.isPaymentPlan=1"
        libs = {r["id"]: r for r in self.rows(
            f"SELECT l.*, c.name AS contactName FROM liability l JOIN contact c ON c.id=l.contactId WHERE {where}")}
        if not libs:
            return []
        q = (f"SELECT * FROM debt_repayment_plan WHERE paidAt IS NULL AND liabilityId IN ({','.join(map(str, libs))})")
        args = []
        if monat:
            y, m = map(int, monat.split("-"))
            q += " AND monthDate>=? AND monthDate<?"
            args += [date(y, m, 1).isoformat(), add_months(date(y, m, 1), 1).isoformat()]
        rows = self.rows(q + (" ORDER BY monthNo" if nur_erste else " ORDER BY monthDate, liabilityId"), args)
        seen, items = set(), []
        for r in rows:
            if nur_erste:
                if r["liabilityId"] in seen:
                    continue
                seen.add(r["liabilityId"])
            l = libs[r["liabilityId"]]
            if d(r["payment"] or 0) <= 0:
                continue
            md = to_date(r["monthDate"])
            due = md.replace(day=l["dueDay"]) if l["dueDay"] else md
            items.append({"liabilityId": l["id"], "liabilityName": l["contactName"] or l["name"], "rowId": r["id"],
                          "monthNo": r["monthNo"], "monthDate": md, "dueDate": due, "payment": d(r["payment"] or 0),
                          "repaymentType": l["repaymentType"], "isPaymentPlan": bool(l["isPaymentPlan"])})
        if nur_erste:
            items.sort(key=lambda x: x["dueDate"])
        return items

    def first_unpaid_map(self, ids) -> dict:
        if not ids:
            return {}
        res = {}
        for r in self.rows(f"SELECT liabilityId, payment FROM debt_repayment_plan WHERE paidAt IS NULL AND liabilityId IN "
                           f"({','.join(map(str, ids))}) ORDER BY monthNo"):
            res.setdefault(r["liabilityId"], d(r["payment"] or 0))
        return res

    def schuldendienst(self) -> tuple[Decimal, list]:
        libs = self.rows(f"SELECT * FROM liability WHERE {OPEN_LIAB}")
        fu = self.first_unpaid_map([l["id"] for l in libs])
        rates = [(l, monatlicher_schuldendienst(l, fu.get(l["id"]))) for l in libs]
        return sum((r for _, r in rates), D0), rates

    # ── Forderungen ───────────────────────────────────────────────────────────
    def forderungen(self):
        return self.rows("SELECT cl.*, c.name AS contactName FROM claim cl JOIN contact c ON c.id=cl.contactId "
                         "WHERE cl.status!='GELOESCHT' ORDER BY CAST(cl.currentAmount AS REAL)<=0, cl.dueDate IS NULL, cl.dueDate")

    def forderung_speichern(self, b: dict) -> int:
        if not b.get("contactId"):
            raise FachFehler("Schuldner fehlt.")
        if not (b.get("name") or "").strip():
            raise FachFehler("Bezeichnung fehlt.")
        data = {"contactId": b["contactId"], "name": b["name"].strip(), "interestType": b.get("interestType") or "FIX",
                "interestRate": f6(d(b.get("interestRate") or "0") / 100), "dueDate": iso(b.get("dueDate")),
                "paymentTerms": b.get("paymentTerms") or None, "notes": b.get("notes") or None, "updatedAt": _now()}
        with self.tx():
            if b.get("id"):
                old = self.must("claim", b["id"])
                self.update("claim", b["id"], data)
                self.audit("UPDATE", "Claim", b["id"], {"name": old["name"]}, {"name": data["name"]})
                return b["id"]
            amt = d(b.get("originalAmount") or "0")
            cid = self.insert("claim", {**data, "originalAmount": f2(amt), "currentAmount": f2(amt), "status": "OFFEN",
                                        "createdAt": _now()})
            self.audit("CREATE", "Claim", cid, None, {"name": data["name"], "amount": f2(amt)})
            return cid

    def forderung_zahlung(self, cid, betrag, beschreibung=None, datum=None) -> int:
        cl = self.must("claim", cid)
        amount = d(betrag)
        if amount <= 0:
            raise FachFehler("Betrag muss größer als 0 sein")
        new = max(d(cl["currentAmount"]) - amount, D0)
        status = "BEZAHLT" if new <= 0 else ("TEILBEZAHLT" if new < d(cl["originalAmount"]) else "OFFEN")
        with self.tx():
            pid = self.insert("claim_payment", {"claimId": cid, "amount": f2(amount),
                                                "description": beschreibung or f"Zahlung auf Forderung: {cl['name']}",
                                                "paymentDate": iso(datum) or date.today().isoformat(), "createdAt": _now()})
            self.update("claim", cid, {"currentAmount": f2(new), "status": status, "updatedAt": _now()})
            self.audit("PAYMENT", "Claim", cid, None, {"amount": f2(amount), "newStatus": status, "claimPaymentId": pid})
            return pid

    def forderung_zahlungen(self, cid):
        return self.rows("SELECT * FROM claim_payment WHERE claimId=? ORDER BY paymentDate DESC, id DESC", (cid,))

    def forderung_loeschen(self, cid) -> str:
        cl = self.must("claim", cid)
        with self.tx():
            if not self.val("SELECT COUNT(*) FROM claim_payment WHERE claimId=?", (cid,)):
                self.exec("DELETE FROM claim WHERE id=?", (cid,))
                self.audit("DELETE", "Claim", cid, {"name": cl["name"]})
                return "Forderung gelöscht."
            self.update("claim", cid, {"status": "GELOESCHT", "updatedAt": _now()})
            self.audit("SOFT_DELETE", "Claim", cid, {"name": cl["name"]})
            return "Forderung ausgeblendet (Zahlungen vorhanden)."

    # ── Dashboard ─────────────────────────────────────────────────────────────
    def soll_lohn(self):
        return self.row("SELECT * FROM salary_calculation WHERE calcType='SOLL' AND isActive=1 ORDER BY id DESC LIMIT 1")

    def dashboard(self) -> dict:
        today = date.today()
        libs = self.rows(f"SELECT l.*, c.name AS contactName FROM liability l JOIN contact c ON c.id=l.contactId "
                         f"WHERE l.status NOT IN ('GELOESCHT','BEZAHLT') AND CAST(l.currentBalance AS REAL)>0 "
                         f"ORDER BY CAST(l.currentBalance AS REAL) DESC")
        claims = self.rows("SELECT * FROM claim WHERE CAST(currentAmount AS REAL)>0")
        fu_rows = {}
        ids = [l["id"] for l in libs if l["dueDay"]]
        if ids:
            for r in self.rows(f"SELECT * FROM debt_repayment_plan WHERE paidAt IS NULL AND liabilityId IN "
                               f"({','.join(map(str, ids))}) ORDER BY monthNo"):
                fu_rows.setdefault(r["liabilityId"], r)
        upcoming = []
        for l in libs:
            if not l["dueDay"]:
                continue
            r = fu_rows.get(l["id"])
            if r:
                md = to_date(r["monthDate"])
                due, amount = md.replace(day=l["dueDay"]), d(r["payment"] or 0)
            else:
                due = today.replace(day=l["dueDay"])
                if due < today:
                    due = add_months(today.replace(day=1), 1).replace(day=l["dueDay"])
                amount = d(l["repaymentValue"] or 0)
            if amount > 0:
                upcoming.append({"id": l["id"], "name": l["name"], "dueDate": due, "amount": amount,
                                 "repaymentType": l["repaymentType"]})
        upcoming.sort(key=lambda x: x["dueDate"])
        return {
            "liabilities": libs[:5], "totalDebt": sum((d(l["currentBalance"]) for l in libs), D0), "liabilityCount": len(libs),
            "totalClaims": sum((d(c["currentAmount"]) for c in claims), D0), "sollLohn": self.soll_lohn(),
            "upcoming": upcoming, "vorschau": self.vorschau(3),
        }

    def vorschau(self, monate: int) -> list[dict]:
        """n-Monats-Vorschau unbezahlter Planraten, getrennt Fix (FIX/PLAN) / Revolving."""
        today = date.today().replace(day=1)
        libs = self.rows(f"SELECT * FROM liability WHERE {OPEN_LIAB}")
        out = []
        for i in range(monate):
            ms, me = add_months(today, i), add_months(today, i + 1)
            fix = rev = D0
            for l in libs:
                p = self.row("SELECT payment FROM debt_repayment_plan WHERE liabilityId=? AND paidAt IS NULL AND monthDate>=? "
                             "AND monthDate<? ORDER BY monthNo LIMIT 1", (l["id"], ms.isoformat(), me.isoformat()))
                if p:
                    if l["repaymentType"] in ("FIX", "PLAN"):
                        fix += d(p["payment"])
                    else:
                        rev += d(p["payment"])
            out.append({"monat": ms, "fix": fix, "revolving": rev, "gesamt": fix + rev})
        return out
