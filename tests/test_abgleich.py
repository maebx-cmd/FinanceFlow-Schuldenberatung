"""Verschlüsselter Abgleich *.ffsync (nur Teil „finanzen“): Rundreise, Konfliktschutz, Fehlerfälle, Vollversion-Dateien."""
import json

import pytest

from app.abgleich import abgleich as ab
from app.abgleich import krypto
from app.db import DB
from tests.demo_data import befuellen

PW = "Sehr-geheimes-PW 42"


def _installation(tmp_path, name):
    d = tmp_path / name
    d.mkdir()
    from tests.schluessel import TEST_KEY
    return DB(str(d / "daten.db"), key=TEST_KEY)


def _ohne_meta(nutz):
    return {t: v["daten"] for t, v in nutz["teile"].items()}


def test_rundreise_export_import_export(tmp_path):
    a = _installation(tmp_path, "schuldner")
    befuellen(a)
    datei = str(tmp_path / ab.dateiname("Laptop"))
    ab.exportieren(a, datei, PW, "Laptop")
    roh = json.load(open(datei, encoding="utf-8"))
    assert roh["format"] == "financeflow-sync" and roh["kdf"]["iterations"] == 600000
    n1 = ab.lesen(datei, PW)
    assert n1["schemaVersion"] == 1 and n1["device"] == "Laptop" and set(n1["teile"]) == {"finanzen"}
    assert n1["edition"] == "Schuldenberatung"
    assert "WorkEntry" not in n1["teile"]["finanzen"]["daten"] and "BoardingPass" not in n1["teile"]["finanzen"]["daten"]

    b = _installation(tmp_path, "beratung")                      # leerer Mandant
    ab.importieren(b, n1)
    datei2 = str(tmp_path / "zurueck.ffsync")
    ab.exportieren(b, datei2, PW, "Beratung")
    n2 = ab.lesen(datei2, PW)
    assert _ohne_meta(n1) == _ohne_meta(n2)
    st = ab.status(b)
    assert st["finanzen"]["letzte_richtung"] == "Export" and st["finanzen"]["letztes_geraet"] == "Beratung"
    i = ab.info(n1)
    assert i["glaeubiger"] == 6 and i["verbindlichkeiten"] == 5 and i["geraet"] == "Laptop"


def test_datei_der_vollversion_mit_mobil_und_hr(tmp_path):
    """Dateien aus FinanceFlow Desktop 2.x (mit Teil „mobil“ und HR/Aviation-Modellen) lassen sich einspielen –
    nur die Finanzdaten werden übernommen."""
    a = _installation(tmp_path, "a")
    befuellen(a)
    nutz = json.loads(ab.klartext(a, "Vollversion"))
    nutz.pop("edition")
    nutz["teile"]["finanzen"]["daten"]["WorkEntry"] = [{"id": 1, "date": "2026-10-01", "startTime": "08:00"}]
    nutz["teile"]["finanzen"]["daten"]["FuelEntry"] = [{"id": 1, "date": "2026-10-01", "odometer": 1, "liters": "1"}]
    nutz["teile"]["mobil"] = {"geaendertAm": None, "daten": {"mobile_beleg": [{"id": 1, "nr": 1}]}}
    datei = str(tmp_path / "voll.ffsync")
    krypto.datei_schreiben(datei, json.dumps(nutz).encode(), PW)
    b = _installation(tmp_path, "b")
    erg = ab.importieren(b, ab.lesen(datei, PW))
    assert set(erg) == {"finanzen", "plaene_neu"} and erg["finanzen"]["Contact"] == 6
    assert ab.info(ab.lesen(datei, PW))["edition"] == "Vollversion"
    assert not b.val("SELECT count(*) FROM sqlite_master WHERE name IN ('work_entry','fuel_entry','boarding_pass')")


def test_konfliktschutz_merker(tmp_path):
    a = _installation(tmp_path, "a")
    befuellen(a)
    assert ab.status(a)["finanzen"]["geaendert"]                         # Änderungen setzen den Merker
    datei = str(tmp_path / "a.ffsync")
    ab.exportieren(a, datei, PW, "A")
    st = ab.status(a)
    assert not st["finanzen"]["geaendert"]                               # nach Export gelöscht
    assert "Letzter Abgleich:" in ab.status_text(st["finanzen"]) and "Export" in ab.status_text(st["finanzen"])
    a.kontakt_speichern({"name": "Neu nach Export"})
    assert ab.konflikte(a) == ["finanzen"]
    with pytest.raises(ab.Konflikt) as e:
        ab.importieren(a, ab.lesen(datei, PW))
    assert e.value.teile == ["finanzen"]
    assert "Änderungen seit dem letzten Abgleich" in str(e.value)
    assert a.val("SELECT count(*) FROM contact WHERE name='Neu nach Export'") == 1   # nichts geändert
    ab.importieren(a, ab.lesen(datei, PW), trotz_aenderungen=True)
    assert a.val("SELECT count(*) FROM contact WHERE name='Neu nach Export'") == 0
    assert not ab.status(a)["finanzen"]["geaendert"]


def test_falsches_passwort_aendert_nichts(tmp_path):
    a = _installation(tmp_path, "a")
    befuellen(a)
    datei = str(tmp_path / "a.ffsync")
    ab.exportieren(a, datei, PW, "A")
    with pytest.raises(krypto.AbgleichFehler, match="Passwort falsch oder Datei beschädigt"):
        ab.lesen(datei, PW + "x")
    roh = json.load(open(datei, encoding="utf-8"))
    daten = bytearray(__import__("base64").b64decode(roh["data"]))
    daten[10] ^= 0xFF
    roh["data"] = __import__("base64").b64encode(bytes(daten)).decode()
    json.dump(roh, open(datei, "w", encoding="utf-8"))
    with pytest.raises(krypto.AbgleichFehler, match="Passwort falsch oder Datei beschädigt"):
        ab.lesen(datei, PW)


def test_neuere_schema_version_und_ohne_finanzen(tmp_path):
    datei = str(tmp_path / "neu.ffsync")
    krypto.datei_schreiben(datei, json.dumps({"schemaVersion": 2, "teile": {}}).encode(), PW)
    with pytest.raises(krypto.AbgleichFehler, match="Bitte App aktualisieren"):
        ab.lesen(datei, PW)
    krypto.datei_schreiben(datei, json.dumps({"schemaVersion": 1, "teile": {"mobil": {"daten": {}}}}).encode(), PW)
    with pytest.raises(krypto.AbgleichFehler, match="keine Finanzdaten"):
        ab.lesen(datei, PW)


def test_passwortregeln(tmp_path):
    with pytest.raises(krypto.AbgleichFehler, match="mindestens 12"):
        ab.pruefe_passwort("kurz1234567")
    with pytest.raises(krypto.AbgleichFehler, match="stimmen nicht"):
        ab.pruefe_passwort("123456789012", "123456789013")
    a = _installation(tmp_path, "a")
    with pytest.raises(krypto.AbgleichFehler, match="mindestens 12"):
        ab.exportieren(a, str(tmp_path / "x.ffsync"), "kurz", "A")


def test_dateiname():
    from datetime import datetime
    assert ab.dateiname("Noahs Laptop", datetime(2026, 11, 7, 22, 15)) == "FinanceFlow-2026-11-07-2215-Noahs-Laptop.ffsync"
