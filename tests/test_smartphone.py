"""Smartphone-Version (web/FinanceFlow-Schuldner.html): eigenständig, gleiches Dateiformat, Datei der Seite einspielbar.

Der vollständige Browser-Durchlauf (Einrichten, Gläubiger, Schuld, Korrektur, Datei → Beratung → zurück) läuft mit
Playwright außerhalb der Testsuite; hier wird geprüft, was die Desktop-Seite davon braucht."""
import os
import re

from app.abgleich import abgleich as ab
from app.db import DB

BASIS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(BASIS, "web", "FinanceFlow-Schuldner.html")


def test_eine_datei_ohne_externe_quellen():
    t = open(HTML, encoding="utf-8").read()
    assert not re.search(r"""(src|href)\s*=\s*["']?(https?:)?//""", t)          # kein CDN, keine Schriften von außen
    assert "fetch(" not in t and "XMLHttpRequest" not in t                       # nichts wird gesendet
    for konst in ('ITER: 600000', 'AAD: "financeflow-sync/1"', 'FORMAT: "financeflow-sync"', "MIN_PW: 12",
                  'name: "PBKDF2-HMAC-SHA256"', 'name: "AES-256-GCM"'):
        assert konst in t, konst
    assert len(t) < 80_000


def _wie_vom_handy():
    """Datenstand genau so, wie ihn die Seite erzeugt (Beträge als Text, Zins als Anteil, keine leeren Felder)."""
    return {
        "Contact": [{"id": 1, "name": "Bank Austria", "address": "Rothschildplatz 1", "zipCode": "1020", "city": "Wien",
                     "iban": "AT611904300234573201", "role": "KREDITOR", "country": "Österreich", "correctionMinutes": 0,
                     "isActive": 1, "createdAt": "2026-11-11T01:30:00"}],
        "Liability": [{"id": 1, "contactId": 1, "name": "Kredit Auto", "interestRate": "0.069000", "interestType": "FIX",
                       "repaymentType": "FIX", "repaymentValue": "320.00", "dueDay": 5, "isBankruptcyEligible": 1,
                       "updatedAt": "2026-11-11T01:31:00", "originalBalance": "12450.00", "currentBalance": "12450.00",
                       "allowAvalanche": 0, "isPaymentPlan": 0, "paymentPlanInterval": 1, "status": "OFFEN",
                       "correctionMinutes": 0, "version": 1, "isInAbschoepfung": 0, "createdAt": "2026-11-11T01:31:00"}],
        "Setting": [{"id": 1, "key": "owner_name", "value": "Maria Muster", "valueType": "string",
                     "updatedAt": "2026-11-11T01:30:00"}],
    }


def test_datei_vom_handy_einspielen_rechnet_plaene(tmp_path):
    from tests.schluessel import TEST_KEY
    db = DB(str(tmp_path / "daten.db"), key=TEST_KEY)
    nutz = {"schemaVersion": 1, "device": "Smartphone", "edition": "Schuldner-Web", "exportedAt": "2026-11-11T01:32:00",
            "teile": {"finanzen": {"geaendertAm": None, "daten": _wie_vom_handy()}}}
    erg = ab.importieren(db, nutz)
    assert erg["plaene_neu"] == 1
    l = db.verbindlichkeit(1)
    assert l["plan"] and l["plan"][0]["payment"] == "320.00" and l["contactName"] == "Bank Austria"
    assert db.setting("grundbetrag")                       # Standardwerte trotz Setting nur mit owner_name
    assert len(db.offene_raten(True)) == 1
    # zweites Einspielen: vorhandener Plan bleibt unangetastet
    db2 = ab.teil_finanzen(db)
    assert ab.plaene_ergaenzen(db) == 0 and ab.teil_finanzen(db) == db2
