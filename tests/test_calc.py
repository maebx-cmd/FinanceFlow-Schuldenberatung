from datetime import date
from decimal import Decimal as Dec

from app.calc import finanz
from app.calc.lohn import FALLBACK_JAHRESTARIF, berechne_lohn, berechne_pfaendung, leite_monatstarif_ab
from app.dates import add_months
from app.dec import d


def test_d_rundet_half_up():
    assert str(d("2.345")) == "2.35"
    assert str(d("-2.345")) == "-2.35"
    assert str(d("1.234,56")) == "1234.56"
    assert str(d("12,5")) == "12.50"


def test_add_months_klemmt():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 1, 31), 2) == date(2026, 3, 31)
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)


def test_lohn_2500_brutto_handrechnung():
    r = berechne_lohn(Dec("2500"), S={})
    assert str(r["svLfd"]) == "428.00"
    assert str(r["lstLfd"]) == "168.05"
    assert str(r["nettoLfd"]) == "1903.95"
    assert str(r["nettoSz13"]) == "2008.38"
    assert str(r["nettoSz14"]) == "1971.18"
    assert str(r["existenzminimumLfd"]) == "1485.60"
    assert str(r["seizableLfd"]) == "418.35"
    assert str(r["seizableAnnual"]) == "5980.56"
    assert str(r["seizableMonthlyBasis"]) == "498.38"


def test_pfaendung_unter_grundbetrag():
    r = berechne_pfaendung(Dec("1200.00"), {})
    assert r["pfaendbarer_betrag"] == 0
    assert str(r["existenzminimum"]) == "1308.00"


def test_monatstarif_aus_jahresstufen():
    t = leite_monatstarif_ab(FALLBACK_JAHRESTARIF, 132)
    assert t[0]["bmg_bis"] == 1139.25          # 13539/12 = 1128.25 + 11
    assert t[1]["allg_abzug"] == 227.85        # 0.2 * 1139.25
    assert abs(t[1]["bmg_bis"] - 1843.67) < 1e-9


def test_tilgungsplan_fix():
    plan = finanz.berechne_tilgungsplan({"currentBalance": "1000", "interestRate": "0.12", "repaymentType": "FIX",
                                         "repaymentValue": "100"}, date(2026, 10, 16))
    assert plan[0]["monthDate"] == date(2026, 10, 1)
    assert str(plan[0]["interest"]) == "10.00" and str(plan[0]["endBalance"]) == "910.00"
    assert plan[-1]["endBalance"] == 0
    assert sum(r["principal"] for r in plan) == Dec("1000.00")


def test_tilgungsplan_nicht_tilgbar_bricht_ab():
    plan = finanz.berechne_tilgungsplan({"currentBalance": "1000", "interestRate": "0.24", "repaymentType": "FIX",
                                         "repaymentValue": "10"}, date(2026, 1, 1))
    assert len(plan) == 1


def test_zahlungsplan_privatkonkurs():
    el = [{"id": 1, "name": "A", "currentBalance": "3000"}, {"id": 2, "name": "B", "currentBalance": "1000"}]
    r = finanz.zahlungsplan_privatkonkurs("MONTHLY", Dec("100"), 36, 6, el, date(2026, 1, 31))
    assert r["numInstallments"] == 6 and str(r["amountPerInstallment"]) == "600.00"
    assert str(r["totalPayment"]) == "3600.00" and str(r["quote"]) == "0.900000"
    assert r["installmentDates"][1]["datum"] == date(2026, 7, 31)
    assert str(r["creditorShares"][0]["zahlungGesamt"]) == "2700.00"


def test_schuldendienst_intervall():
    assert finanz.monatlicher_schuldendienst({"isPaymentPlan": 1, "paymentPlanInterval": 6}, Dec("600")) == Dec("100")
    assert finanz.monatlicher_schuldendienst({"repaymentValue": "55.5"}, None) == Dec("55.50")


def test_avalanche_volle_zinspraezision():
    libs = [{"id": 1, "currentBalance": "1000", "interestRate": "0.0899", "repaymentValue": "50"}]
    r = finanz.avalanche(libs, Dec("100"), date(2026, 1, 1))
    assert str(r["results"][0]["interest"]) == "7.49"   # 1000*0.0899/12; Web-Version rechnete fälschlich 7.50


def test_aliquot_verteilung_mit_clamp():
    items = [{"liabilityId": 1, "balance": Dec("10.00"), "quota": Dec("0.5")},
             {"liabilityId": 2, "balance": Dec("500.00"), "quota": Dec("0.5")}]
    allocs, rest = finanz.verteile_aliquot(Dec("100.00"), items)
    m = {a["liabilityId"]: a["amount"] for a in allocs}
    assert m[1] == Dec("10.00") and m[2] == Dec("90.00") and rest == 0


def test_quoten_summe_eins():
    q = finanz.abschoepfung_quoten([{"id": 1, "currentBalance": "1"}, {"id": 2, "currentBalance": "2"}])
    assert sum(q.values()) == 1
