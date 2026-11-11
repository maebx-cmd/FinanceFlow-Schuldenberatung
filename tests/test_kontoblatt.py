"""Kontoblatt-Import (nur EXE): Beispiel-Kontoblatt 3121 inkl. Subkonten (tests/daten/kontoblatt_3121_beispiel.csv)."""
import os
from decimal import Decimal

import pytest

from app.db_base import FachFehler
from app.services import kontoblatt as kb

DATEI = os.path.join(os.path.dirname(__file__), "daten", "kontoblatt_3121_beispiel.csv")
KOPF = "Datum;Beleg;Belegkreis;Fremdbeleg;Konto;Text;Gegenkonto;Soll;Haben;Saldo;S/H;Storno\r\n"
EB = {"3121.01": "1887.81", "3121.02": "1800.00", "3121.03": "240.81", "3121.04": "201.34", "3121.05": "1700.00"}


def roh():
    return open(DATEI, "rb").read()


def _einrichten(db):
    k = db.kontakt_speichern({"name": "Privat"})
    lids = {}
    for konto, saldo in EB.items():
        lids[konto] = db.verbindlichkeit_speichern({"contactId": k, "name": f"Darlehen {konto}", "currentBalance": saldo,
                                                    "repaymentType": "OPEN"})
        db.kb_zuordnen(konto, lids[konto])
    return lids


def _vorschlag(vorschau):
    """Entscheidungen wie in der Vorschau vorgeschlagen (nur neue / ignorierte Zeilen mit Zuordnung)."""
    e = {}
    for v in vorschau:
        if v["status"] in (kb.NEU, kb.FEHLT, kb.IGNORIERT) and v["liabilityId"]:
            e[v["zeile"].schluessel] = {"aktion": "IGNORIEREN" if v["ignorieren"] else "BUCHEN", "typ": v["typ"]}
    return e


def _saldo(db, lid):
    return Decimal(db.get("liability", lid)["currentBalance"])


def test_lesen_beispiel():
    z = kb.lesen(roh())
    assert len(z) == 18 and len({x.schluessel for x in z}) == 18
    assert sum(x.aenderung for x in z) == Decimal("7002.21")           # = Saldo der letzten Zeile (−7002,21 H)
    je = {}
    for x in z:
        je[x.konto] = je.get(x.konto, 0) + x.aenderung
    assert je == {"3121.01": Decimal("2415.02"), "3121.02": Decimal("1800.00"), "3121.03": Decimal("372.99"),
                  "3121.04": Decimal("202.01"), "3121.05": Decimal("2212.19")}
    ba = [x for x in z if x.beleg == "BA 2026/0001"]
    assert [x.haben for x in ba] == [Decimal("6.29"), Decimal("131.79"), Decimal("250.00")]
    assert ba[0].gegenkonten == ["8315", "7325", "2800.03"]


def test_vorschlaege():
    z = {x.nr: x for x in kb.lesen(roh())}
    assert z[13].vorschlag_typ() == "ZINSNACHTRAG"        # Zinsen 8327
    assert z[10].vorschlag_typ() == "ZINSNACHTRAG"        # 8315
    assert z[7].vorschlag_typ() == "SALDOANPASSUNG"       # Sammelbeleg mit 7325/2800.03
    assert z[17].vorschlag_typ() == "SALDOANPASSUNG"      # JET Imst
    assert z[17].beschreibung() == "JET Imst (Kontoblatt 3121.03, SO 2026/0010)"
    assert z[7].beschreibung() == "Gegenkonto 8315, 7325, 2800.03 (Kontoblatt 3121.01, BA 2026/0001)"


def test_buchen_und_nicht_doppelt(db):
    lids = _einrichten(db)
    z = kb.lesen(roh())
    v = db.kb_vorschau(z)
    assert [x["ignorieren"] for x in v[:5]] == [True] * 5              # EB vorgeschlagen: ignorieren
    assert not any(x["ignorieren"] for x in v[5:])
    erg = db.kb_buchen(z, _vorschlag(v), "kontoblatt.csv")
    assert erg["gebucht"] == 13 and erg["ignoriert"] == 5 and erg["summe"] == Decimal("1172.25")   # 7002,21 − EB 5829,96
    assert os.path.exists(erg["sicherung"])
    # Saldo FinanceFlow = Saldo Kontoblatt je Subkonto
    for a in db.kb_abstimmung(z):
        assert a["differenz"] == 0, a
    assert _saldo(db, lids["3121.01"]) == Decimal("2415.02")
    k = db.rows("SELECT * FROM liability_correction WHERE liabilityId=? ORDER BY id", (lids["3121.03"],))
    assert [(c["correctionType"], c["amountBefore"], c["amountChange"], c["amountAfter"], c["correctionDate"]) for c in k] == [
        ("ZINSNACHTRAG", "240.81", "2.01", "242.82", "2026-10-17"), ("ZINSNACHTRAG", "242.82", "2.09", "244.91", "2026-10-29"),
        ("SALDOANPASSUNG", "244.91", "109.38", "354.29", "2026-11-01"), ("SALDOANPASSUNG", "354.29", "18.70", "372.99", "2026-11-01")]
    # zweiter Import derselben Datei: nichts Neues, Ignoriertes bleibt ignoriert
    v2 = db.kb_vorschau(kb.lesen(roh()))
    assert {x["status"] for x in v2[:5]} == {kb.IGNORIERT} and {x["status"] for x in v2[5:]} == {kb.GEBUCHT}
    with pytest.raises(FachFehler, match="kann nicht gebucht werden"):
        db.kb_buchen(z, {v2[6]["zeile"].schluessel: {"aktion": "BUCHEN", "typ": "SONSTIG"}})
    assert _saldo(db, lids["3121.01"]) == Decimal("2415.02")


def test_typ_aus_vorschau_wird_gebucht(db):
    lids = _einrichten(db)
    z = kb.lesen(roh())
    v = db.kb_vorschau(z)
    e = _vorschlag(v)
    jet = next(x for x in z if x.text == "JET Imst")
    e[jet.schluessel]["typ"] = "SONSTIG"
    db.kb_buchen(z, e)
    assert db.val("SELECT correctionType FROM liability_correction WHERE description LIKE 'JET Imst%'") == "SONSTIG"
    assert lids


def test_neue_zeilen_spaeter_und_gleiche_zeilen(db):
    lids = _einrichten(db)
    z = kb.lesen(roh())
    db.kb_buchen(z, _vorschlag(db.kb_vorschau(z)))
    neu = roh() + ("01.11.2026;SO 2026/0015;SO;;3121.01;KFZ-Versicherung November 2026;7325;0,00;131,79;-7134,00;H;nein\r\n"
                   "05.11.2026;BA 2026/0009;BA;;3121.02;Rate;2800.03;300,00;0,00;-6834,00;S;nein\r\n").encode()
    z2 = kb.lesen(neu)
    v = [x for x in db.kb_vorschau(z2) if x["status"] == kb.NEU]
    assert [(x["zeile"].nr, x["typ"]) for x in v] == [(20, "SALDOANPASSUNG"), (21, "RATENZAHLUNG")]
    assert v[0]["zeile"].schluessel.endswith("#2")                    # zweite identische KFZ-Zeile
    db.kb_buchen(z2, _vorschlag(db.kb_vorschau(z2)))
    assert _saldo(db, lids["3121.01"]) == Decimal("2546.81")
    assert _saldo(db, lids["3121.02"]) == Decimal("1500.00")


def test_ignoriert_spaeter_doch_buchen(db):
    lids = _einrichten(db)
    z = kb.lesen(roh())
    v = db.kb_vorschau(z)
    jet = next(x for x in v if x["zeile"].text == "JET Imst")
    e = _vorschlag(v)
    e[jet["zeile"].schluessel]["aktion"] = "IGNORIEREN"
    db.kb_buchen(z, e)
    assert _saldo(db, lids["3121.03"]) == Decimal("263.61")
    v2 = db.kb_vorschau(z)
    j2 = next(x for x in v2 if x["zeile"].text == "JET Imst")
    assert j2["status"] == kb.IGNORIERT and j2["ignorieren"]
    db.kb_buchen(z, {j2["zeile"].schluessel: {"aktion": "BUCHEN", "typ": "SALDOANPASSUNG"}})
    assert _saldo(db, lids["3121.03"]) == Decimal("372.99")
    assert next(x for x in db.kb_vorschau(z) if x["zeile"].text == "JET Imst")["status"] == kb.GEBUCHT


def test_ohne_zuordnung_und_alles_oder_nichts(db):
    k = db.kontakt_speichern({"name": "P"})
    lid = db.verbindlichkeit_speichern({"contactId": k, "name": "A", "currentBalance": "100", "repaymentType": "OPEN"})
    db.kb_zuordnen("3121.01", lid)
    z = kb.lesen((KOPF + "01.11.2026;X 1;SO;;3121.01;Zins;8327;0,00;5,00;;H;nein\r\n"
                         "02.11.2026;X 2;SO;;3121.01;Zahlung;2800;200,00;0,00;;S;nein\r\n"
                         "02.11.2026;X 3;SO;;3121.02;Fremd;2800;0,00;9,00;;H;nein\r\n").encode())
    v = db.kb_vorschau(z)
    assert v[2]["liabilityId"] is None
    with pytest.raises(FachFehler, match="keiner Verbindlichkeit zugeordnet"):
        db.kb_buchen(z, {v[2]["zeile"].schluessel: {"aktion": "BUCHEN", "typ": "SONSTIG"}})
    vor = db.val("SELECT count(*) FROM liability_correction")
    with pytest.raises(FachFehler, match="Zeile 3 .*würde negativ"):
        db.kb_buchen(z, _vorschlag(v))
    assert db.val("SELECT count(*) FROM liability_correction") == vor and _saldo(db, lid) == Decimal("100.00")
    assert db.val("SELECT count(*) FROM kontoblatt_zeile") == 0
    # Zuordnung wird gemerkt und kann geändert werden
    assert db.kb_zuordnungen() == {"3121.01": lid}
    db.kb_zuordnen("3121.01", None)
    assert db.kb_zuordnungen() == {}


def test_bezahlt_markiert(db):
    k = db.kontakt_speichern({"name": "P"})
    lid = db.verbindlichkeit_speichern({"contactId": k, "name": "A", "currentBalance": "100", "repaymentType": "OPEN"})
    db.kb_zuordnen("3121.01", lid)
    db.als_bezahlt_markieren(lid)
    z = kb.lesen((KOPF + "01.11.2026;X 1;SO;;3121.01;Zins;8327;0,00;5,00;;H;nein\r\n").encode())
    with pytest.raises(FachFehler, match="bezahlt markiert"):
        db.kb_buchen(z, _vorschlag(db.kb_vorschau(z)))


def test_korrektur_geloescht_wieder_neu(db):
    lids = _einrichten(db)
    z = kb.lesen(roh())
    db.kb_buchen(z, _vorschlag(db.kb_vorschau(z)))
    letzte = db.letzte_korrektur(lids["3121.01"])
    db.korrektur_loeschen(letzte["id"])
    v = db.kb_vorschau(z)
    kfz = [x for x in v if x["zeile"].text == "KFZ-Versicherung November 2026"][0]
    assert kfz["status"] == kb.NEU
    # neue Korrektur mit derselben Id darf nicht als „gebucht“ gelten
    db.korrektur_buchen(lids["3121.01"], "SONSTIG", "1.00", "manuell", "2026-11-02")
    assert [x for x in db.kb_vorschau(z) if x["zeile"].text.startswith("KFZ")][0]["status"] == kb.NEU


def test_daten_ersetzt_fruehere_buchung_fehlt(db):
    lids = _einrichten(db)
    z = kb.lesen(roh())
    db.kb_buchen(z, _vorschlag(db.kb_vorschau(z)))
    db.con.execute("DELETE FROM liability_correction WHERE description LIKE 'JET%'")   # wie nach Datenimport
    j = [x for x in db.kb_vorschau(z) if x["zeile"].text == "JET Imst"][0]
    assert j["status"] == kb.FEHLT and not j["ignorieren"] and lids


def test_schluessel_ohne_saldo_und_storno():
    a = kb.lesen((KOPF + "01.11.2026;X 1;SO;;3121.01;Zins;8327;0,00;5,00;-5,00;H;nein\r\n").encode())
    b = kb.lesen((KOPF + "01.11.2026;X 1;SO;;3121.01;Zins;8327;0,00;5,00;-99,00;H;ja\r\n").encode())
    assert a[0].schluessel == b[0].schluessel and b[0].storno


@pytest.mark.parametrize("zeile,meldung", [
    ("1.11.2026;X;SO;;3121.01;T;1;0,00;5,00;;H;nein", "Datum"),
    ("31.02.2026;X;SO;;3121.01;T;1;0,00;5,00;;H;nein", "gibt es nicht"),
    ("01.11.2026;X;SO;;3121.01;T;1;0,00;5.5;;H;nein", "Betrag"),
    ("01.11.2026;X;SO;;3121.01;T;1;0,00;-5,00;;H;nein", "Betrag"),
    ("01.11.2026;X;SO;;;T;1;0,00;5,00;;H;nein", "Konto fehlt"),
    ("01.11.2026;X;SO", "zu wenige Spalten"),
])
def test_fehlerhafte_zeilen(zeile, meldung):
    with pytest.raises(FachFehler, match=meldung):
        kb.lesen((KOPF + zeile + "\r\n").encode())


def test_kein_kontoblatt_und_kodierung():
    with pytest.raises(FachFehler, match="Kein Kontoblatt"):
        kb.lesen(b"a;b;c\r\n1;2;3\r\n")
    z = kb.lesen((KOPF + "01.11.2026;X;SO;;3121.01;Gebühr Überweisung;1;0,00;1.234,50;;H;nein\r\n").encode("cp1252"))
    assert z[0].text == "Gebühr Überweisung" and z[0].haben == Decimal("1234.50")
