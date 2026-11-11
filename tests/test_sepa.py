"""SEPA-Zahlungsdatei (pain.001.001.09 / .03) – Erwartungswerte aus der Web-Version, XSD-Prüfung mit lxml."""
import os
from datetime import date, datetime

import pytest

from app.calc import sepa
from app.db_base import FachFehler

SCHEMAS = os.path.join(os.path.dirname(__file__), "schemas")
HEUTE = date(2026, 11, 7)


def _xsd_pruefen(xml: str, version: str):
    etree = pytest.importorskip("lxml.etree")
    schema = etree.XMLSchema(etree.parse(os.path.join(SCHEMAS, f"pain.001.001.{version}.xsd")))
    doc = etree.fromstring(xml.encode("utf-8"))
    assert schema.validate(doc), schema.error_log
    return doc


def _x(doc, pfad, version="09"):
    ns = {"p": f"urn:iso:std:iso:20022:tech:xsd:pain.001.001.{version}"}
    return [e.text for e in doc.xpath(pfad, namespaces=ns)]


# ── Zeichensatz, BIC, Vorlage ─────────────────────────────────────────────────
def test_zeichensatz():
    assert sepa.text("Grüße & Füße – §1 € 5") == "Gruesse + Fuesse - Par.1 EUR 5"
    assert sepa.text("Café Élan ñ") == "Cafe Elan n"
    assert sepa.kennung("/FF  12//3/") == "FF12/3"
    assert sepa.text('a#b;c!d@e*f=g"h') == "aNr.b,c.d(at)e.f-g'h"
    assert len(sepa.name("x" * 100)) == 70 and len(sepa.zweck("y" * 200)) == 140
    assert sepa.text("  viel   \t Leerraum ") == "viel Leerraum"


def test_bic():
    assert sepa.bic_gueltig("BKAUATWW") and sepa.bic_gueltig("GIBAATWWXXX")
    assert not sepa.bic_gueltig("BKAU")


def test_vorlage():
    t = sepa.vorlage_fuellen("{bezeichnung} Rate {rate} {monat} fällig {faellig} an {glaeubiger}", "Kredit", "Bank", 7,
                             date(2026, 1, 5))
    assert t == "Kredit Rate 7 01/2026 fällig 05.01.2026 an Bank"


# ── XML ───────────────────────────────────────────────────────────────────────
AUFTRAGGEBER = {"name": "Noah Müller", "iban": "AT611904300234573201", "bic": None}
ZAHLUNGEN = [
    {"endToEndId": "FF-L1-R3-261107", "betrag": 24194, "empfaenger": "Bank Austria – Inkasso & Co",
     "iban": "DE89370400440532013000", "zweck": "Kredit 4711 Rate 3 11/2026 · Zahlungsplan §194 IO"},
    {"endToEndId": "FF-L2-R1-261107", "betrag": 5, "empfaenger": "Gläubiger Ö", "iban": "AT611904300234573201",
     "bic": "BKAUATWW", "referenz": "123456789012"},
]


def test_xml_09_beispiel():
    xml = sepa.erstelle_xml(AUFTRAGGEBER, ZAHLUNGEN, "2026-11-10", "09", False, "FF-261107-1200-ABCDEF12",
                            datetime(2026, 11, 7, 12, 0, 5), HEUTE)
    doc = _xsd_pruefen(xml, "09")
    assert _x(doc, "//p:GrpHdr/p:NbOfTxs") == ["2"] and _x(doc, "//p:GrpHdr/p:CtrlSum") == ["241.99"]
    assert _x(doc, "//p:GrpHdr/p:CreDtTm") == ["2026-11-07T12:00:05"]
    assert _x(doc, "//p:PmtInf/p:PmtInfId") == ["FF-261107-1200-ABCDEF12-1"]
    assert _x(doc, "//p:PmtInf/p:BtchBookg") == ["false"]
    assert _x(doc, "//p:ReqdExctnDt/p:Dt") == ["2026-11-10"]
    assert _x(doc, "//p:DbtrAgt/p:FinInstnId/p:Othr/p:Id") == ["NOTPROVIDED"]
    assert _x(doc, "//p:Dbtr/p:Nm") == ["Noah Mueller"]
    assert _x(doc, "//p:CdtrAgt/p:FinInstnId/p:BICFI") == ["BKAUATWW"]
    assert _x(doc, "//p:RmtInf/p:Ustrd") == ["Kredit 4711 Rate 3 11/2026 Zahlungsplan Par.194 IO"]
    assert _x(doc, "//p:CdtrRefInf/p:Tp/p:CdOrPrtry/p:Cd") == ["SCOR"]
    assert _x(doc, "//p:CdtrRefInf/p:Ref") == ["123456789012"]
    assert _x(doc, "//p:Cdtr/p:Nm") == ["Bank Austria - Inkasso + Co", "Glaeubiger Oe"]
    assert _x(doc, "//p:InstdAmt") == ["241.94", "0.05"]
    assert 'Ccy="EUR"' in xml


def test_xml_03_mit_bic_und_sammelbuchung():
    a = {**AUFTRAGGEBER, "bic": "GIBAATWWXXX"}
    xml = sepa.erstelle_xml(a, ZAHLUNGEN, "2026-11-10", "03", True, None, datetime(2026, 11, 7, 12, 0), HEUTE)
    doc = _xsd_pruefen(xml, "03")
    assert _x(doc, "//p:DbtrAgt/p:FinInstnId/p:BIC", "03") == ["GIBAATWWXXX"]
    assert _x(doc, "//p:CdtrAgt/p:FinInstnId/p:BIC", "03") == ["BKAUATWW"]
    assert _x(doc, "//p:BtchBookg", "03") == ["true"]
    assert _x(doc, "//p:PmtInf/p:ReqdExctnDt", "03") == ["2026-11-10"]
    assert _x(doc, "//p:GrpHdr/p:MsgId", "03")[0].startswith("FF-261107-1200-")


@pytest.mark.parametrize("version", ["09", "03"])
def test_xml_57_zahlungen(version):
    z = [{"endToEndId": f"FF-L{i}-R1-261107", "betrag": 1 + i * 997, "empfaenger": f"Empfänger {i}",
          "iban": "DE89370400440532013000", "zweck": ""} for i in range(57)]
    xml = sepa.erstelle_xml(AUFTRAGGEBER, z, "2026-11-10", version, False, "FF-TEST-57", heute=HEUTE)
    doc = _xsd_pruefen(xml, version)
    summe = sum(1 + i * 997 for i in range(57))
    assert _x(doc, "//p:GrpHdr/p:CtrlSum", version) == [f"{summe // 100}.{summe % 100:02d}"]
    assert _x(doc, "//p:GrpHdr/p:NbOfTxs", version) == ["57"]
    assert "RmtInf" not in xml


@pytest.mark.parametrize("aenderung, meldung", [
    (lambda a, z: a.update(iban="AT611904300234573202"), "Auftraggeber: IBAN ungültig"),
    (lambda a, z: a.update(name=""), r"Kontoinhaber \(Name\) fehlt"),
    (lambda a, z: z[0].update(iban="XX00"), "IBAN ungültig"),
    (lambda a, z: z[0].update(betrag=0), "Betrag muss größer als 0"),
    (lambda a, z: z[1].update(endToEndId=z[0]["endToEndId"]), "doppelt"),
    (lambda a, z: z.clear(), "Keine Zahlung"),
])
def test_xml_pruefungen(aenderung, meldung):
    a, z = dict(AUFTRAGGEBER), [dict(x) for x in ZAHLUNGEN]
    aenderung(a, z)
    with pytest.raises(sepa.SepaFehler, match=meldung):
        sepa.erstelle_xml(a, z, "2026-11-10", "09", heute=HEUTE)


def test_xml_ausfuehrung_vergangen():
    with pytest.raises(sepa.SepaFehler, match="Vergangenheit"):
        sepa.erstelle_xml(AUFTRAGGEBER, ZAHLUNGEN, "2026-11-06", "09", heute=HEUTE)


# ── Auswahl (reine Funktion) ──────────────────────────────────────────────────
def test_auswahl():
    libs = [
        {"id": 1, "name": "Kredit 1", "status": "OFFEN", "currentBalance": "5000", "dueDay": 15,
         "iban": "AT61 1904 3002 3457 3201", "contactName": "Bank A", "contactIban": "DE89370400440532013000",
         "contactBic": "COBADEFFXXX"},
        {"id": 2, "name": "Kredit 2", "status": "OFFEN", "currentBalance": "900", "dueDay": 15, "iban": None,
         "contactName": "Commerzbank", "contactIban": "de89 3704 0044 0532 0130 00", "contactBic": "COBADEFFXXX",
         "zahlungsreferenz": "987654321"},
        {"id": 3, "name": "Inkasso", "status": "OFFEN", "currentBalance": "300", "dueDay": 15, "iban": None,
         "contactName": "Inkasso Graz", "contactIban": None, "verwendungszweck": "AZ 4711 / {rate}. Rate {faellig}"},
        {"id": 4, "name": "Handy", "status": "OFFEN", "currentBalance": "100", "dueDay": 1, "iban": "AT611904300234573201",
         "contactName": "A1"},
    ]
    zeilen = [
        {"liabilityId": 1, "monthNo": 5, "monthDate": "2027-01-01", "payment": "241.94"},
        {"liabilityId": 1, "monthNo": 4, "monthDate": "2026-12-01", "payment": "241.94"},
        {"liabilityId": 2, "monthNo": 2, "monthDate": "2026-12-01", "payment": "100.00"},
        {"liabilityId": 3, "monthNo": 7, "monthDate": "2026-11-01", "payment": "50.005"},
        {"liabilityId": 4, "monthNo": 3, "monthDate": "2027-02-01", "payment": "40.00"},
    ]
    a = sepa.auswahl(libs, zeilen, {(2, 2): "2026-11-01T10:00:00"}, None, "2026-12-31")
    assert [x["liabilityId"] for x in a] == [3, 1, 2]
    v3, v1, v2 = a
    assert (v1["monthNo"], v1["faellig"], v1["betrag"]) == (4, date(2026, 12, 15), 24194)
    assert (v1["iban"], v1["ibanQuelle"], v1["bic"], v1["zweck"], v1["problem"]) == (
        "AT611904300234573201", "verbindlichkeit", None, "Kredit 1 Rate 4 12/2026", None)
    assert v1["endToEndBasis"] == "FF-L1-R4" and not v1["exportiertAm"]
    assert (v2["iban"], v2["ibanQuelle"], v2["bic"], v2["referenz"]) == ("DE89370400440532013000", "kontakt", "COBADEFFXXX",
                                                                         "987654321")
    assert v2["exportiertAm"] and v2["problem"] is None
    assert (v3["betrag"], v3["monthNo"], v3["zweck"]) == (5001, 7, "AZ 4711 / 7. Rate 15.11.2026")
    assert v3["problem"] == sepa.PROBLEM_KEINE_IBAN
    alle = sepa.auswahl(libs, zeilen)
    assert 4 in [x["liabilityId"] for x in alle]


def test_auswahl_probleme_und_nullraten():
    libs = [{"id": 1, "name": "", "status": "OFFEN", "currentBalance": "10", "iban": "AT611904300234573202",
             "contactName": "", "verwendungszweck": "§§§"},
            {"id": 2, "name": "X", "status": "OFFEN", "currentBalance": "10", "iban": "AT611904300234573201", "contactName": "Y"},
            {"id": 3, "name": "Z", "status": "BEZAHLT", "currentBalance": "10", "iban": "AT611904300234573201"}]
    zeilen = [{"liabilityId": 1, "monthNo": 1, "monthDate": "2026-12-01", "payment": "5"},
              {"liabilityId": 2, "monthNo": 1, "monthDate": "2026-12-01", "payment": "0.00"},
              {"liabilityId": 3, "monthNo": 1, "monthDate": "2026-12-01", "payment": "5"}]
    a = sepa.auswahl(libs, zeilen)
    assert len(a) == 1 and a[0]["probleme"] == [sepa.PROBLEM_IBAN, sepa.PROBLEM_NAME]
    libs[0]["name"] = "N"
    libs[0]["verwendungszweck"] = "€€"   # wird zu „EUREUR“ – nicht leer
    assert sepa.auswahl(libs, zeilen)[0]["probleme"] == [sepa.PROBLEM_IBAN]


# ── Mit Datenbank: erstellen, bereits exportiert, bezahlt erfassen, verwerfen ─
def _setup(db):
    db.sepa_einstellungen_speichern({"name": "Noah Müller", "iban": "AT61 1904 3002 3457 3201", "version": "09"})
    k = db.kontakt_speichern({"name": "Bank Austria", "iban": "DE89370400440532013000", "bic": "BKAUATWW"})
    lid = db.verbindlichkeit_speichern({"contactId": k, "name": "Kredit", "currentBalance": "1000", "repaymentType": "FIX",
                                        "repaymentValue": "241.94", "dueDay": 15, "zahlungsreferenz": "RF18 5390 0754 7034"})
    k2 = db.kontakt_speichern({"name": "Ohne IBAN"})
    db.verbindlichkeit_speichern({"contactId": k2, "name": "Rest", "currentBalance": "50", "repaymentType": "FIX",
                                  "repaymentValue": "50"})
    return lid


def test_sepa_ablauf(db):
    lid = _setup(db)
    a = db.sepa_auswahl()
    bereit = [x for x in a if not x["problem"]]
    assert len(a) == 2 and len(bereit) == 1 and bereit[0]["referenz"] == "RF18539007547034"
    ausf = date.today().isoformat()
    with pytest.raises(FachFehler, match="keine IBAN"):
        db.sepa_erstellen([(x["liabilityId"], x["monthNo"]) for x in a], ausf)
    e = db.sepa_erstellen([(lid, bereit[0]["monthNo"])], ausf)
    _xsd_pruefen(e["xml"], "09")
    assert e["anzahl"] == 1 and e["summe"] == 24194 and "RF18539007547034" in e["xml"]
    assert db.sepa_exporte()[0]["status"] == "offen"
    assert next(x for x in db.sepa_auswahl() if x["liabilityId"] == lid)["exportiertAm"]
    with pytest.raises(FachFehler, match="bereits exportiert"):
        db.sepa_erstellen([(lid, bereit[0]["monthNo"])], ausf)
    r = db.sepa_als_bezahlt(e["id"], "2026-11-20")
    assert r["erfasst"] == 1 and r["vollstaendig"]
    l = db.verbindlichkeit(lid)
    k = l["corrections"][-1]
    assert k["correctionType"] == "RATENZAHLUNG" and k["amountChange"] == "-241.94" and k["correctionDate"] == "2026-11-20"
    assert l["currentBalance"] == "758.06"
    ex = db.sepa_exporte()[0]
    assert ex["status"] == "bezahlt erfasst" and ex["bezahltAm"] == "2026-11-20"
    with pytest.raises(FachFehler, match="Verwerfen nicht möglich"):
        db.sepa_verwerfen(e["id"])
    # nächste Rate wird angeboten
    assert next(x for x in db.sepa_auswahl() if x["liabilityId"] == lid)["monthNo"] == bereit[0]["monthNo"] + 1


def test_sepa_verwerfen_und_nicht_mehr_offen(db):
    lid = _setup(db)
    x = next(a for a in db.sepa_auswahl() if a["liabilityId"] == lid)
    e = db.sepa_erstellen([(lid, x["monthNo"])], date.today())
    db.sepa_verwerfen(e["id"])
    assert db.sepa_exporte()[0]["status"] == "verworfen"
    assert not next(a for a in db.sepa_auswahl() if a["liabilityId"] == lid)["exportiertAm"]
    # Rate inzwischen bezahlt → Fehler beim Erstellen
    z = db.verbindlichkeit(lid)["plan"][0]
    db.planrate_bezahlen(lid, z["id"])
    with pytest.raises(FachFehler, match="nicht mehr offen – Liste neu laden"):
        db.sepa_erstellen([(lid, x["monthNo"])], date.today())


def test_sepa_bezahlt_ueberspringt_nicht_mehr_offene(db):
    lid = _setup(db)
    x = next(a for a in db.sepa_auswahl() if a["liabilityId"] == lid)
    e = db.sepa_erstellen([(lid, x["monthNo"])], date.today())
    db.planrate_bezahlen(lid, db.verbindlichkeit(lid)["plan"][0]["id"])
    r = db.sepa_als_bezahlt(e["id"])
    assert r["erfasst"] == 0 and len(r["uebersprungen"]) == 1 and not r["vollstaendig"]


def test_verbindlichkeit_referenz_und_zweck(db):
    k = db.kontakt_speichern({"name": "B"})
    with pytest.raises(FachFehler, match="Zahlungsreferenz ungültig"):
        db.verbindlichkeit_speichern({"contactId": k, "name": "K", "repaymentType": "OPEN", "zahlungsreferenz": "ÄÖÜ"})
    with pytest.raises(FachFehler, match="140"):
        db.verbindlichkeit_speichern({"contactId": k, "name": "K", "repaymentType": "OPEN", "verwendungszweck": "x" * 141})
    lid = db.verbindlichkeit_speichern({"contactId": k, "name": "K", "repaymentType": "OPEN", "zahlungsreferenz": " 12 34 ",
                                        "verwendungszweck": "  AZ {rate} "})
    l = db.get("liability", lid)
    assert (l["zahlungsreferenz"], l["verwendungszweck"]) == ("1234", "AZ {rate}")


def test_sepa_einstellungen_pruefen(db):
    with pytest.raises(FachFehler, match="IBAN"):
        db.sepa_einstellungen_speichern({"name": "N", "iban": "AT611904300234573202"})
    with pytest.raises(FachFehler, match="BIC"):
        db.sepa_einstellungen_speichern({"name": "N", "iban": "AT611904300234573201", "bic": "BKAU"})
