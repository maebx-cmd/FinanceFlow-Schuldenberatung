import json
from datetime import date, timedelta
from decimal import Decimal as Dec

import pytest

from app.db_base import FachFehler


def _basis(db, saldo="1200", typ="FIX", rate="100"):
    cid = db.kontakt_speichern({"name": "Bank A"})
    lid = db.verbindlichkeit_speichern({"contactId": cid, "name": "Kredit", "currentBalance": saldo, "interestRate": "0",
                                        "repaymentType": typ, "repaymentValue": rate})
    return cid, lid


def test_verbindlichkeit_plan(db):
    _, lid = _basis(db)
    assert len(db.verbindlichkeit(lid)["plan"]) == 12


def test_planrate_bezahlen_und_storno(db):
    """Rate bezahlt → Korrektur RATENZAHLUNG + Planzeile bezahlt; Korrektur löschen → Saldo zurück, Planzeile offen."""
    _, lid = _basis(db)
    l = db.verbindlichkeit(lid)
    zeile = l["plan"][0]
    cid = db.planrate_bezahlen(lid, zeile["id"], datum="2026-11-05")
    l = db.verbindlichkeit(lid)
    k = l["corrections"][-1]
    assert k["id"] == cid and k["correctionType"] == "RATENZAHLUNG" and k["correctionDate"] == "2026-11-05"
    assert (k["amountBefore"], k["amountChange"], k["amountAfter"]) == ("1200.00", "-100.00", "1100.00")
    assert k["description"] == "Rate 1 bezahlt (100,00 €)"
    p = next(x for x in l["plan"] if x["id"] == zeile["id"])
    assert l["currentBalance"] == "1100.00" and p["paidAt"] and p["paidAmount"] == "100.00" and p["paidCorrectionId"] == cid
    assert len(l["plan"]) == 12
    db.korrektur_loeschen(cid)
    l = db.verbindlichkeit(lid)
    assert l["currentBalance"] == "1200.00" and not any(r["paidAt"] for r in l["plan"]) and not l["corrections"]
    assert not any(r["paidCorrectionId"] for r in l["plan"]) and len(l["plan"]) == 12


def test_planrate_hoechstens_saldo(db):
    _, lid = _basis(db, saldo="150")
    l = db.verbindlichkeit(lid)
    db.planrate_bezahlen(lid, l["plan"][0]["id"], betrag="400")
    l = db.verbindlichkeit(lid)
    assert l["currentBalance"] == "0.00" and l["corrections"][-1]["amountChange"] == "-150.00"
    assert next(p for p in l["plan"] if p["paidAt"])["paidAmount"] == "400.00"


def test_korrektur_nur_letzte_loeschbar(db):
    _, lid = _basis(db)
    db.korrektur_buchen(lid, "ZINSNACHTRAG", betrag="50")
    db.korrektur_buchen(lid, "ANPASSUNG_TAGSATZUNG", neuer_saldo="1000")
    l = db.verbindlichkeit(lid)
    assert l["currentBalance"] == "1000.00" and l["corrections"][1]["amountChange"] == "-250.00"
    with pytest.raises(FachFehler):
        db.korrektur_loeschen(l["corrections"][0]["id"])
    db.korrektur_loeschen(l["corrections"][1]["id"])
    assert db.verbindlichkeit(lid)["currentBalance"] == "1250.00"


def test_manuelle_korrektur_ratenzahlung(db):
    from app.services.finance import CORRECTION_TYPES
    assert "RATENZAHLUNG" in dict(CORRECTION_TYPES)
    _, lid = _basis(db)
    db.korrektur_buchen(lid, "RATENZAHLUNG", betrag="-30", beschreibung="Überweisung")
    assert db.verbindlichkeit(lid)["currentBalance"] == "1170.00"


def test_zahlungsplan_umwandeln_und_zurueck(db):
    _, lid = _basis(db, saldo="1000", typ="OPEN", rate="")
    db.in_zahlungsplan_umwandeln(lid, "30", 36, 6, "2026-01-31")
    l = db.verbindlichkeit(lid)
    assert l["currentBalance"] == "300.00" and l["repaymentValue"] == "50.00" and l["status"] == "ZAHLUNGSPLAN"
    assert [r["monthDate"] for r in l["plan"][:2]] == ["2026-01-31", "2026-07-31"]
    db.zahlungsplan_rueckgaengig(lid)
    l = db.verbindlichkeit(lid)
    assert l["currentBalance"] == "1000.00" and not l["isPaymentPlan"] and not l["corrections"]


def test_forderung_zahlung(db):
    cid = db.kontakt_speichern({"name": "Max"})
    f = db.forderung_speichern({"contactId": cid, "name": "Darlehen", "originalAmount": "500"})
    db.forderung_zahlung(f, "200", "Überweisung", "2026-10-03")
    cl = db.get("claim", f)
    assert cl["currentAmount"] == "300.00" and cl["status"] == "TEILBEZAHLT"
    z = db.forderung_zahlungen(f)
    assert len(z) == 1 and (z[0]["amount"], z[0]["description"], z[0]["paymentDate"]) == ("200.00", "Überweisung", "2026-10-03")
    assert "ausgeblendet" in db.forderung_loeschen(f)
    f2 = db.forderung_speichern({"contactId": cid, "name": "Ohne Zahlung", "originalAmount": "50"})
    assert "gelöscht" in db.forderung_loeschen(f2)


def test_fixkosten_monat_zahlung(db):
    db.ausgabe_speichern("fixed_cost", {"name": "Miete", "plannedAmount": "700", "dueDay": 1})
    m = db.fixkosten_monat(2026, 10)
    pid = m["items"][0]["id"]
    db.fixkosten_bezahlen(pid, "690")
    assert db.get("fixed_cost_payment", pid)["paidAmount"] == "690.00"
    db.fixkosten_zuruecknehmen(pid)
    assert db.fixkosten_monat(2026, 10)["openCount"] == 1


def test_haushalt_szenario_kopiert_ausgaben(db):
    db.ausgabe_speichern("fixed_cost", {"name": "Miete", "plannedAmount": "700"})
    db.ausgabe_speichern("variable_expense", {"name": "Essen", "plannedAmount": "300"})
    sid = db.szenario_speichern({"name": "Umzug", "manualNetMonthly": "2000"})
    h = db.haushalt(sid)
    assert h["surplus"] == Dec("1000.00") and h["lohnQuelle"] == "MANUELL"
    db.szenario_loeschen(sid)
    assert db.haushalt()["totalPlanned"] == Dec("1000.00")


def test_abschoepfung_buchen_und_storno(db):
    cid = db.kontakt_speichern({"name": "G"})
    l1 = db.verbindlichkeit_speichern({"contactId": cid, "name": "A", "currentBalance": "3000", "repaymentType": "OPEN"})
    l2 = db.verbindlichkeit_speichern({"contactId": cid, "name": "B", "currentBalance": "1000", "repaymentType": "OPEN"})
    vid = db.abschoepfung_anlegen("2026-01-15", 36, [l1, l2])
    v = db.abschoepfung()
    assert len(v["raten"]) == 36 and v["raten"][0]["month"] == "2026-01-01"
    res = db.abschoepfung_rate_buchen(v["raten"][0]["id"], "400")
    assert {a["liabilityId"]: a["amount"] for a in res["allocations"]} == {l1: Dec("300.00"), l2: Dec("100.00")}
    assert db.get("liability", l1)["currentBalance"] == "2700.00"
    db.abschoepfung_rate_zuruecknehmen(v["raten"][0]["id"])
    assert db.get("liability", l1)["currentBalance"] == "3000.00"
    assert db.restschuldbefreiung(vid) == 2
    assert db.get("liability", l2)["status"] == "BEZAHLT"


def test_konkurs_berechnen_speichern(db):
    cid = db.kontakt_speichern({"name": "G"})
    db.verbindlichkeit_speichern({"contactId": cid, "name": "A", "currentBalance": "10000", "repaymentType": "OPEN"})
    db.lohn_speichern({"calcType": "SOLL", "name": "Soll", "monthlyBase": "2500"})
    r = db.konkurs_berechnen({"scenarioType": "ZAHLUNGSPLAN", "monthlyAmount": "200", "durationMonths": 36,
                              "intervalMonths": 1, "startDatum": "2026-11-01"})
    assert str(r["totalPayment"]) == "7200.00"
    sid = db.konkurs_speichern(r, "Test")
    s = db.get("bankruptcy_scenario", sid)
    assert json.loads(s["creditorSnapshot"])[0]["zahlungGesamt"] == "7200.00"
    assert s["seizableMonthlyBasis"] == "498.38" and s["tilgungsplanTotal"] == "17941.68"


def test_import_umwandlung(db):
    """Teil „finanzen“: Dezimalzahlen exakt als Text, Ja/Nein als 0/1, fehlende Einstellungen werden ergänzt."""
    from decimal import Decimal
    exp = {"Contact": [{"id": 7, "name": "Bank", "role": "KREDITOR", "isActive": True, "correctionMinutes": 0,
                        "createdAt": "2026-06-24T03:26:28.123"}],
           "Liability": [{"id": 3, "contactId": 7, "name": "K", "originalBalance": Decimal("1000.00"),
                          "currentBalance": Decimal("950.50"), "interestRate": Decimal("0.0899"), "repaymentType": "FIX",
                          "repaymentValue": Decimal("50.00"), "status": "OFFEN", "isBankruptcyEligible": True,
                          "allowAvalanche": False, "isPaymentPlan": False, "isInAbschoepfung": False, "correctionMinutes": 0,
                          "version": 1, "interestType": "FIX", "startDate": "2026-01-01", "smartField": "ignorieren"}],
           "Setting": [{"id": 1, "key": "grundbetrag", "value": "1308.00", "valueType": "number"}]}
    from app.importer import importieren_daten
    c = importieren_daten(db, exp)
    assert c["Liability"] == 1
    l = db.get("liability", 3)
    assert l["currentBalance"] == "950.50" and l["interestRate"] == "0.0899" and l["isBankruptcyEligible"] == 1
    assert db.val("SELECT 1 FROM setting WHERE key='owner_name'") == 1   # fehlende Keys werden ergänzt


def test_verbindlichkeit_loeschen_nur_ohne_historie(db):
    _, lid = _basis(db, saldo="100")
    l = db.verbindlichkeit(lid)
    db.planrate_bezahlen(lid, l["plan"][0]["id"])
    assert "ausgeblendet" in db.verbindlichkeit_loeschen(lid)
    _, lid2 = _basis(db, saldo="0")
    assert "gelöscht" in db.verbindlichkeit_loeschen(lid2)


def test_iban_an_verbindlichkeit(db):
    cid = db.kontakt_speichern({"name": "Bank", "iban": "DE89370400440532013000"})
    lid = db.verbindlichkeit_speichern({"contactId": cid, "name": "K", "currentBalance": "10", "repaymentType": "OPEN",
                                        "iban": " at61 1904-3002 3457 3201 "})
    assert db.get("liability", lid)["iban"] == "AT611904300234573201"
    with pytest.raises(FachFehler, match="IBAN ungültig"):
        db.verbindlichkeit_speichern({"id": lid, "contactId": cid, "name": "K", "repaymentType": "OPEN",
                                      "iban": "AT611904300234573202"})
    db.verbindlichkeit_speichern({"id": lid, "contactId": cid, "name": "K", "repaymentType": "OPEN", "iban": "  "})
    l = db.verbindlichkeit(lid)
    assert l["iban"] is None and l["ibanEff"] == "DE89370400440532013000"
