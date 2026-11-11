"""Reine Finanz-Rechenlogik (Port von calculations/*.ts und den Rechenteilen der Routen).

Alle Funktionen sind seiteneffektfrei: dict/Decimal rein -> dict/list raus.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from ..dates import add_months
from ..dec import D, D0, d, d6, dp

CENT = Decimal("0.01")


# ── Tilgungsplan (calculations/tilgungsplan.ts) ───────────────────────────────
def berechne_tilgungsplan(l: dict, start: date) -> list[dict]:
    start = start.replace(day=1)
    balance = d(l.get("currentBalance"))
    rate = D(l.get("interestRate") or 0)
    typ = l.get("repaymentType")
    rep_val = d(l.get("repaymentValue") or 0)
    rep_pct = D(l.get("repaymentPercentage") or 0)
    rep_min = D(l.get("repaymentMinimum") or 0)
    plan, n = [], 1
    while balance > CENT and n <= 1200:
        interest = d(balance * (rate / 12))
        if typ in ("FIX", "PLAN"):
            payment = min(rep_val, balance + interest)
        elif typ == "PERCENT":
            payment = d(balance * rep_pct)
            payment = max(payment, interest + CENT)
            if rep_min > 0:
                payment = max(payment, rep_min)
        elif typ == "OPEN":
            payment = max(interest, rep_val)
        else:
            payment = rep_val
        payment = min(payment, balance + interest)
        principal = d(payment - interest)
        new_bal = d(balance - principal)
        if principal <= 0 and n > 1:
            break
        plan.append({"monthNo": n, "monthDate": add_months(start, n - 1), "payment": payment,
                     "interest": interest, "principal": principal, "endBalance": new_bal})
        balance = new_bal
        n += 1
        if balance <= 0:
            break
    return plan


def zahlungsplan_rows(balance: Decimal, rate: Decimal, interval: int, start: date) -> list[dict]:
    """Ratenplan ohne Zinsen für Zahlungsplan-Verbindlichkeiten (recalculatePlan, isPaymentPlan)."""
    rows, i = [], 0
    balance = d(balance)
    while balance > 0 and len(rows) < 1200:
        i += 1
        pay = min(rate, balance)
        balance = balance - pay
        rows.append({"i": i, "monthDate": add_months(start, (i - 1) * interval), "payment": pay,
                     "interest": D0, "principal": pay, "endBalance": balance})
    return rows


# ── Schuldendienst (calculations/schuldendienst.ts) ───────────────────────────
def monatlicher_schuldendienst(l: dict, first_unpaid: Decimal | None) -> Decimal:
    if first_unpaid is None:
        return d(l["repaymentValue"]) if l.get("repaymentValue") else D0
    interval = (l.get("paymentPlanInterval") or 1) if l.get("isPaymentPlan") else 1
    if interval > 1:
        return first_unpaid / interval
    return first_unpaid


# ── Privatkonkurs (calculations/privatkonkurs.ts) ─────────────────────────────
def tilgungsplan_privatkonkurs(seizable_basis: Decimal, eligible: list[dict], jahre: int = 3) -> dict:
    monate = 12 * jahre
    total = sum((d(l["currentBalance"]) for l in eligible), D0)
    total_pay = d(seizable_basis * monate)
    quote = d6(total_pay / total) if total > 0 else D0
    return {"monate": monate, "seizableMonthly": seizable_basis, "totalEligibleDebt": d(total),
            "totalPayment": total_pay, "quote": quote, "quotePct": d(quote * 100), "eligibleDebts": eligible}


def zahlungsplan_privatkonkurs(eingabe: str, wert, duration: int, interval: int, eligible: list[dict],
                               start: date) -> dict:
    """Szenario „Zahlungsplan“ centgenau (ratenplan_cent) – identisch mit Web-Version und Zahlungsplan-Umwandlung.

    eingabe: "PERCENT" (wert = % der Schuld) oder "MONTHLY" (wert = freier Monatsbetrag).
    """
    from . import ratenplan_cent as rc
    n = duration // interval if interval > 0 else 0
    salden = [rc.to_cents(l["currentBalance"]) for l in eligible]
    schuld = sum(salden)
    if eingabe == "PERCENT":
        p = rc.plan_by_quote(salden, rc.pct(wert or 0), n)
        monat = rc.round_div(p["termine"][0], interval) if p["termine"] else 0   # nur informativ
    else:
        monat = rc.to_cents(wert or 0)
        p = rc.plan_by_installment(salden, monat, interval, n)
    c = rc.cents_to_dec
    shares = []
    for l, g in zip(eligible, p["glaeubiger"]):
        shares.append({"liability": l, "balance": c(g["saldo"]),
                       "anteilPct": d(Decimal(g["saldo"]) * 100 / schuld) if schuld else D0,
                       "zahlungGesamt": c(g["gesamt"]), "zahlungJeRate": c(g["rate"]), "zahlungLetzteRate": c(g["letzte"]),
                       "zahlungMin": c(g["min"]), "zahlungMax": c(g["max"])})
    dates = [{"nr": i + 1, "datum": add_months(start, i * interval), "betrag": c(b)} for i, b in enumerate(p["termine"])]
    return {"inputMode": eingabe, "monthlyAmount": c(monat), "durationMonths": duration, "intervalMonths": interval,
            "numInstallments": n, "amountPerInstallment": c(p["termine"][0] if p["termine"] else 0),
            "lastInstallment": c(p["termine"][-1] if p["termine"] else 0), "totalPayment": c(p["gesamt"]),
            "totalEligibleDebt": c(schuld), "quote": p["quote"], "quotePct": d(p["quote"] * 100),
            "installmentDates": dates, "creditorShares": shares}


def erweitertes_angebot(monthly: Decimal, surplus: Decimal, net13: Decimal, net14: Decimal) -> dict | None:
    """Überschuss-Aufteilung auf Sonderzahlungen (routes/bankruptcy.ts, useExtended)."""
    abw = monthly - surplus
    if abw <= 0:
        return None
    jahr = abw * 12
    je = jahr / 2
    r13, r14 = net13 - je, net14 - je
    return {"abweichung": abw, "jaehrlicheUeberschreitung": jahr, "beitragJeSz": je, "restSz13": r13,
            "restSz14": r14, "effektivMonatlich": surplus + jahr / 12, "tragfaehig": r13 >= 0 and r14 >= 0}


# ── Avalanche (routes/avalanche.ts) ───────────────────────────────────────────
def avalanche(liabs: list[dict], budget: Decimal, today: date) -> dict:
    """liabs: sortiert nach interestRate absteigend.

    KORREKTUR ggü. Web-Version: Der Zinssatz wird mit voller Präzision verwendet. Die Web-Version
    rundete ihn mit d() auf 2 Stellen (0,0899 -> 0,09), was die Zinsen verfälschte.
    """
    MAX = 600
    bals = [{"id": l["id"], "balance": d(l["currentBalance"]), "rate": D(l["interestRate"] or 0),
             "minPayment": d(l.get("repaymentValue") or 0)} for l in liabs]
    month, total_int, results = 0, D0, []
    start = today.replace(day=1)
    while any(b["balance"] > 0 for b in bals) and month < MAX:
        month += 1
        md = add_months(start, month - 1)
        remaining = budget
        mres = []
        for b in bals:
            if b["balance"] <= 0:
                continue
            interest = d(b["balance"] * (b["rate"] / 12))
            total_int += interest
            pay = min(b["minPayment"], b["balance"] + interest)
            principal = d(pay - interest)
            b["balance"] = max(d(b["balance"] - principal), D0)
            remaining -= pay
            mres.append({"liabilityId": b["id"], "monthNo": month, "monthDate": md, "payment": d(pay),
                         "interest": interest, "principal": principal, "endBalance": b["balance"], "isTarget": False})
        if remaining > 0:
            target = next((b for b in bals if b["balance"] > 0), None)
            if target:
                extra = min(remaining, target["balance"])
                target["balance"] = max(d(target["balance"] - extra), D0)
                for r in mres:
                    if r["liabilityId"] == target["id"]:
                        r["payment"] = d(r["payment"] + d(extra))
                        r["principal"] = d(r["principal"] + d(extra))
                        r["endBalance"] = target["balance"]
                        r["isTarget"] = True
                        break
        results += mres
        bals = [b for b in bals if b["balance"] > 0]
    base = [{"balance": d(l["currentBalance"]), "rate": D(l["interestRate"] or 0),
             "minPayment": d(l.get("repaymentValue") or 0)} for l in liabs]
    bm, bint = 0, D0
    while any(b["balance"] > 0 for b in base) and bm < MAX:
        bm += 1
        for b in base:
            if b["balance"] <= 0:
                continue
            interest = d(b["balance"] * (b["rate"] / 12))
            bint += interest
            pay = min(b["minPayment"], b["balance"] + interest)
            b["balance"] = max(d(b["balance"] - d(pay - interest)), D0)
    return {"budget": d(budget), "totalMonths": month, "totalInterest": d(total_int),
            "interestSaved": d(bint - total_int), "baseMonths": bm, "baseInterest": d(bint), "results": results}


# ── Abschöpfung (routes/abschoepfung.ts) ──────────────────────────────────────
def abschoepfung_quoten(liabs: list[dict]) -> dict[int, Decimal]:
    """Eingefrorener Aliquot-Schlüssel, 8 Stellen; Rundungsrest auf die größte Verbindlichkeit."""
    total = sum((d(l["currentBalance"]) for l in liabs), D0)
    srt = sorted(liabs, key=lambda l: d(l["currentBalance"]), reverse=True)
    q, s = {}, D0
    for l in srt:
        x = dp(d(l["currentBalance"]) / total, 8)
        q[l["id"]] = x
        s += x
    rest = Decimal(1) - s
    if rest != 0:
        q[srt[0]["id"]] += rest
    return q


def verteile_aliquot(paid: Decimal, items: list[dict]) -> tuple[list[dict], Decimal]:
    """items: {liabilityId, balance, quota}. Liefert (allocations, unallocated)."""
    result: dict[int, Decimal] = {}
    remaining = paid
    open_ = [{"id": it["liabilityId"], "cap": it["balance"], "quota": it["quota"]} for it in items if it["balance"] > 0]
    while remaining > 0 and open_:
        qsum = sum((it["quota"] for it in open_), D0)
        if qsum <= 0:
            break
        dist, still = D0, []
        for it in open_:
            share = remaining * it["quota"] / qsum
            applied = dp(min(share, it["cap"]), 2)
            if applied > 0:
                result[it["id"]] = result.get(it["id"], D0) + applied
                dist += applied
                cap = it["cap"] - applied
                if cap > 0:
                    still.append({**it, "cap": cap})
            else:
                still.append(it)
        remaining -= dist
        if dist <= 0:
            break
        open_ = still
    allocs = [{"liabilityId": k, "amount": v} for k, v in result.items() if v > 0]
    return allocs, (remaining if remaining > 0 else D0)
