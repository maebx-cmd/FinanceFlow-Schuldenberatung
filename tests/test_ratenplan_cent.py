"""Centgenaue Rechenregel für Privatkonkurs-Szenario, Zahlungsplan-Umwandlung und Planaufbau (wie Web-Version)."""
import json
import random
import sqlite3
from datetime import date
from decimal import Decimal as Dec

from app.calc import ratenplan_cent as rc
from app.calc import finanz

SALDEN = ["12.345,67", "8.901,23", "4.567,89", "23.456,78", "987,65"]


def test_parsen_und_runden():
    assert rc.to_cents("1.234,56") == 123456
    assert rc.to_cents("1234,565") == 123457
    assert rc.to_cents("1234.56") == 123456
    assert rc.to_cents(1.005) == 101
    assert rc.to_cents(Dec("0.005")) == 1
    assert rc.pct("12,345") == 1235
    assert rc.round_div(5, 2) == 3 and rc.round_div(4, 3) == 1


def test_split_rates():
    assert rc.split_rates(100000, 7) == (14286, 14284)
    assert rc.split_rates(100001, 7) == (14286, 14285)
    assert rc.split_rates(4, 7) == (0, 4)
    assert rc.split_rates(500, 1) == (500, 500)
    assert rc.split_rates(0, 7) == (0, 0) and rc.split_rates(10, 0) == (0, 10)


def test_split_rates_viele_faelle():
    for z in list(range(0, 400)) + [999, 1000, 1001, 123457, 870992, 9999999]:
        for n in (1, 2, 3, 6, 7, 12, 36, 72):
            r, last = rc.split_rates(z, n)
            raten = [r] * (n - 1) + [last]
            assert len(raten) == n and sum(raten) == z and min(raten) >= 0, (z, n)


def test_allocate():
    assert rc.allocate(100, [1, 1, 1]) == [34, 33, 33]
    rnd = random.Random(1)
    for _ in range(300):
        w = [rnd.randint(0, 10 ** 9) for _ in range(rnd.randint(1, 9))]
        t = rnd.randint(0, 10 ** 8)
        assert sum(rc.allocate(t, w)) == t


def test_beispiel_quote_17_33():
    s = [rc.to_cents(x) for x in SALDEN]
    assert sum(s) == 5025922
    p = rc.plan_by_quote(s, rc.pct("17,33"), 36)
    assert [g["gesamt"] for g in p["glaeubiger"]] == [213950, 154258, 79162, 406506, 17116]
    assert p["gesamt"] == 870992 and str(p["quote"]) == "0.173300"
    assert (p["rate"], p["letzte"]) == (24194, 24202) and 35 * 24194 + 24202 == 870992
    assert [(g["rate"], g["letzte"]) for g in p["glaeubiger"]] == [(5943, 5945), (4285, 4283), (2199, 2197),
                                                                    (11292, 11286), (475, 491)]
    p7 = rc.plan_by_quote(s, rc.pct("17,33"), 42 // 6)
    assert len(p7["termine"]) == 7 and (p7["rate"], p7["letzte"]) == (124427, 124430) and sum(p7["termine"]) == 870992


def test_szenario_prozent_ueber_finanz():
    el = [{"id": i, "name": f"G{i}", "currentBalance": str(Dec(rc.to_cents(x)) / 100)} for i, x in enumerate(SALDEN)]
    r = finanz.zahlungsplan_privatkonkurs("PERCENT", "17,33", 36, 1, el, date(2026, 1, 1))
    assert str(r["totalPayment"]) == "8709.92" and str(r["quote"]) == "0.173300"
    assert str(r["amountPerInstallment"]) == "241.94" and str(r["lastInstallment"]) == "242.02"
    assert str(r["monthlyAmount"]) == "241.94"
    assert sum(x["betrag"] for x in r["installmentDates"]) == r["totalPayment"]
    assert str(r["creditorShares"][4]["zahlungLetzteRate"]) == "4.91"
    r6 = finanz.zahlungsplan_privatkonkurs("PERCENT", "17,33", 42, 6, el, date(2026, 1, 1))
    assert r6["numInstallments"] == 7 and str(r6["lastInstallment"]) == "1244.30"
    assert str(r6["monthlyAmount"]) == "207.38"   # round_div(124427, 6), nur informativ


def test_freier_monatsbetrag():
    s = [rc.to_cents(x) for x in SALDEN]
    for iv in (1, 3, 6):
        n = 36 // iv
        p = rc.plan_by_installment(s, 12345, iv, n)
        assert p["termine"] == [12345 * iv] * n
        for k in range(n):
            assert sum(g["zahlungen"][k] for g in p["glaeubiger"]) == 12345 * iv
        assert sum(g["gesamt"] for g in p["glaeubiger"]) == p["gesamt"] == 12345 * iv * n


def test_zufall_summen_stimmen():
    rnd = random.Random(42)
    for _ in range(500):
        salden = [rnd.randint(1, 5_000_000) for _ in range(rnd.randint(1, 8))]
        n = rnd.randint(1, 72)
        p = rc.plan_by_quote(salden, rnd.randint(1, 10000), n)
        assert len(p["termine"]) == n
        assert sum(p["termine"]) == p["gesamt"] == sum(g["gesamt"] for g in p["glaeubiger"])
        for g in p["glaeubiger"]:
            assert g["rate"] * (n - 1) + g["letzte"] == g["gesamt"] and g["letzte"] >= 0
        iv = rnd.choice((1, 3, 6, 12))
        m = rnd.randint(1, 500_000)
        p = rc.plan_by_installment(salden, m, iv, n)
        assert sum(p["termine"]) == p["gesamt"] == sum(g["gesamt"] for g in p["glaeubiger"]) == m * iv * n


def test_merge_rounding_tail():
    assert rc.merge_rounding_tail([14286] * 7 + [2], 7) == [14286] * 6 + [14288]
    assert rc.merge_rounding_tail([14286] * 7 + [5000], 7) == [14286] * 7 + [5000]
    assert rc.merge_rounding_tail([100] * 3, 7) == [100] * 3


# ── mit Datenbank ─────────────────────────────────────────────────────────────
def _lib(db, saldo, eligible=True):
    cid = db.kontakt_speichern({"name": f"Gläubiger {saldo}"})
    return db.verbindlichkeit_speichern({"contactId": cid, "name": f"F {saldo}", "currentBalance": saldo, "interestRate": "0",
                                         "repaymentType": "OPEN", "repaymentValue": "0",
                                         "isBankruptcyEligible": eligible})


def _plan(db, lid):
    return [r for r in db.verbindlichkeit(lid)["plan"]]


def test_planaufbau_immer_genau_7_raten(db):
    cent = 100000
    while cent <= 101000:
        saldo = f"{cent // 100}.{cent % 100:02d}"
        lid = _lib(db, saldo, False)
        db.in_zahlungsplan_umwandeln(lid, "23,45", 42, 6, "2026-01-01")
        z = rc.quotenbetrag(cent, 2345)
        plan = _plan(db, lid)
        assert len(plan) == 7, saldo
        assert sum(rc.to_cents(r["payment"]) for r in plan) == z, saldo
        assert plan[-1]["endBalance"] == "0.00"
        assert db.verbindlichkeit(lid)["currentBalance"] == str(rc.cents_to_dec(z))
        cent += 7


def test_planaufbau_nach_bezahlter_rate_und_neuberechnung(db):
    lid = _lib(db, "1000.00", False)
    db.in_zahlungsplan_umwandeln(lid, "100", 7, 1, "2026-01-01")   # 100.000 Cent / 7 → 14286 … letzte 14284
    plan = _plan(db, lid)
    assert [rc.to_cents(r["payment"]) for r in plan] == [14286] * 6 + [14284]
    db.planrate_bezahlen(lid, plan[0]["id"])
    db.alle_plaene_neu()
    plan = _plan(db, lid)
    assert len(plan) == 7 and sum(rc.to_cents(r["payment"]) for r in plan) == 100000


def test_alter_plan_mit_restrate_wird_bereinigt(db):
    lid = _lib(db, "1000.01", False)
    # Zustand wie aus Version 1.4: Rate abgerundet → 8. Rate mit wenigen Cent
    db.update("liability", lid, {"isPaymentPlan": 1, "paymentPlanMonths": 7, "paymentPlanInterval": 1,
                                 "paymentPlanStart": "2026-01-01", "repaymentType": "PLAN", "repaymentValue": "142.85",
                                 "status": "ZAHLUNGSPLAN"})
    db.alle_plaene_neu()
    plan = _plan(db, lid)
    assert len(plan) == 7 and plan[-1]["payment"] == "142.91" and plan[-1]["endBalance"] == "0.00"


def test_echte_mehrschuld_bleibt_als_weitere_rate(db):
    lid = _lib(db, "1000.00", False)
    db.in_zahlungsplan_umwandeln(lid, "100", 7, 1, "2026-01-01")
    db.korrektur_buchen(lid, "ZINSNACHTRAG", betrag="50")
    plan = _plan(db, lid)
    assert len(plan) == 8 and sum(rc.to_cents(r["payment"]) for r in plan) == 105000


def test_szenario_speichern_und_pdf(db, tmp_path):
    for x in SALDEN:
        _lib(db, str(Dec(rc.to_cents(x)) / 100))
    w = {"scenarioType": "ZAHLUNGSPLAN", "inputMode": "PERCENT", "percentOfDebt": "17,33", "durationMonths": 36,
         "intervalMonths": 1, "startDatum": "2026-01-01"}
    r = db.konkurs_berechnen(w)
    assert str(r["totalPayment"]) == "8709.92" and str(r["lastInstallment"]) == "242.02"
    sid = db.konkurs_speichern(r, "Test")
    s = db.get("bankruptcy_scenario", sid)
    assert s["totalPayment"] == "8709.92" and s["lastInstallment"] == "242.02" and s["quote"] == "0.173300"
    snap = json.loads(s["creditorSnapshot"])
    assert sum(rc.to_cents(c["zahlungGesamt"]) for c in snap) == 870992
    assert {c["zahlungLetzteRate"] for c in snap} == {"59.45", "42.83", "21.97", "112.86", "4.91"}
    from app import pdf
    pdf.konkurs(db, str(tmp_path / "s.pdf"), sid)
    pdf.szenario_vergleich(db, str(tmp_path / "v.pdf"), [sid])
    # Umwandlung mit derselben Quote ergibt dieselben Beträge je Gläubiger
    for l in db.konkurs_basis()["liabilities"]:
        db.in_zahlungsplan_umwandeln(l["id"], "17,33", 36, 1, "2026-01-01")
    raten = {}
    for l in db.rows("SELECT id FROM liability"):
        for p in _plan(db, l["id"]):
            raten[p["monthNo"]] = raten.get(p["monthNo"], 0) + rc.to_cents(p["payment"])
    assert len(raten) == 36 and raten[1] == 24194 and raten[36] == 24202 and sum(raten.values()) == 870992


def test_altes_szenario_ohne_verteilung_pdf(db, tmp_path):
    for x in SALDEN:
        _lib(db, str(Dec(rc.to_cents(x)) / 100))
    sid = db.insert("bankruptcy_scenario", {"scenarioType": "ZAHLUNGSPLAN", "durationMonths": 36, "intervalMonths": 1,
                                            "totalPayment": "8709.92", "totalEligibleDebt": "50259.22", "quote": "0.173300"})
    from app import pdf
    pdf.konkurs(db, str(tmp_path / "alt.pdf"), sid)


def test_migration_ergaenzt_spalte(tmp_path):
    from app.db import DB
    p = str(tmp_path / "m.db")
    DB(p).con.close()
    con = sqlite3.connect(p)
    con.execute("ALTER TABLE bankruptcy_scenario DROP COLUMN lastInstallment")
    con.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
    con.commit()
    con.close()
    db = DB(p)
    assert "lastInstallment" in {r[1] for r in db.con.execute("PRAGMA table_info(bankruptcy_scenario)")}
