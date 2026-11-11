"""1.6.0: Konten/Buchungen entfernt, IBAN an der Verbindlichkeit, einmalige Datenübernahme (wie Web-Version)."""
import json

from app.calc import iban as ib
from app.services import kontenmigration as km


# ── IBAN ──────────────────────────────────────────────────────────────────────
def test_iban():
    assert ib.normalisieren(" at61 1904-3002 3457 3201 ") == "AT611904300234573201"
    assert ib.gueltig(" at61 1904-3002 3457 3201 ")
    assert ib.gueltig("DE89370400440532013000")
    assert not ib.gueltig("AT611904300234573202")
    assert not ib.gueltig("AT61")
    assert ib.formatieren("AT611904300234573201") == "AT61 1904 3002 3457 3201"
    assert ib.normalisieren("  ") is None and ib.formatieren(None) == ""


# ── Altbestand (bis 1.5.0) nachbauen ──────────────────────────────────────────
def _altbestand(db):
    """Beispiel aus der Vorgabe: Saldo aktuell 800 mit ERLASS 1000 → 900 am 01.01., Tilgungen 50 € am 01.02. und 01.03.,
    eine gelöschte Tilgung über 99 €, Konto mit IBAN, ein GZ-Konto, ein Forderungseingang 120 €."""
    con = db.con
    with db.tx():
        km.alt_struktur_anlegen(con)
        k = db.insert("contact", {"name": "Bank", "iban": "DE89370400440532013000"})
        lid = db.insert("liability", {"contactId": k, "name": "Kredit", "originalBalance": "1000.00", "currentBalance": "800.00",
                                      "repaymentType": "FIX", "repaymentValue": "50.00", "status": "OFFEN"})
        lid2 = db.insert("liability", {"contactId": k, "name": "Gericht", "originalBalance": "300.00", "currentBalance": "300.00",
                                       "repaymentType": "OPEN", "status": "OFFEN"})
        db.insert("liability_correction", {"liabilityId": lid, "correctionType": "ERLASS", "amountBefore": "1000.00",
                                           "amountChange": "-100.00", "amountAfter": "900.00", "description": "Teilerlass",
                                           "correctionDate": "2026-01-01", "createdAt": "2026-01-01T10:00:00"})
        a1 = db.insert("account", {"name": "Kreditkonto", "accountType": "KREDIT", "identifierType": "IBAN",
                                   "iban": "at61 1904 3002 3457 3201"})
        a2 = db.insert("account", {"name": "Gerichtskonto", "accountType": "KREDIT", "identifierType": "GZ",
                                   "iban": "AT611904300234573201", "gz": "12 S 34/26"})
        giro = db.insert("account", {"name": "Giro", "accountType": "GIRO"})
        db.insert("account_liability_link", {"accountId": a1, "liabilityId": lid})
        db.insert("account_liability_link", {"accountId": a2, "liabilityId": lid2})
        t1 = db.insert("tx", {"accountId": a1, "transactionType": "SCHULDENTILGUNG", "amount": "50.00", "description": "Tilgungsrate 1",
                              "referenceType": "LIABILITY", "referenceId": lid, "transactionDate": "2026-02-01",
                              "createdAt": "2026-02-01T09:00:00"})
        t2 = db.insert("tx", {"accountId": a1, "transactionType": "SCHULDENTILGUNG", "amount": "50.00", "description": "Tilgungsrate 2",
                              "referenceType": "LIABILITY", "referenceId": lid, "transactionDate": "2026-03-01",
                              "createdAt": "2026-03-01T09:00:00"})
        db.insert("tx", {"accountId": a1, "transactionType": "SCHULDENTILGUNG", "amount": "99.00", "description": "storniert",
                         "referenceType": "LIABILITY", "referenceId": lid, "transactionDate": "2026-02-15",
                         "deletedAt": "2026-02-16T08:00:00"})
        db.insert("tx", {"accountId": giro, "transactionType": "ZAHLUNG", "amount": "-89.90", "description": "Billa",
                         "transactionDate": "2026-02-02"})
        cl = db.insert("claim", {"contactId": k, "name": "Darlehen", "originalAmount": "500.00", "currentAmount": "380.00",
                                 "status": "TEILBEZAHLT"})
        db.insert("tx", {"accountId": giro, "transactionType": "FORDERUNGSEINGANG", "amount": "120.00", "description": "Rate Max",
                         "referenceType": "CLAIM", "referenceId": cl, "transactionDate": "2026-04-10"})
        p1 = db.insert("debt_repayment_plan", {"liabilityId": lid, "monthNo": 1, "monthDate": "2026-02-01", "payment": "50.00",
                                               "paidAt": "2026-02-01T09:00:00", "paidAmount": "50.00", "paidTransactionId": t1})
        p2 = db.insert("debt_repayment_plan", {"liabilityId": lid, "monthNo": 2, "monthDate": "2026-03-01", "payment": "50.00",
                                               "paidAt": "2026-03-01T09:00:00", "paidAmount": "50.00", "paidTransactionId": t2})
        db.insert("fixed_cost", {"name": "Miete", "plannedAmount": "700"})
    return {"lid": lid, "lid2": lid2, "claim": cl, "p1": p1, "p2": p2}


def _tabellen(db):
    return {r["name"] for r in db.rows("SELECT name FROM sqlite_master WHERE type='table'")}


def test_migration_beispiel(db):
    ids = _altbestand(db)
    assert km.noetig(db.con)
    v = km.vorschau(db.con)
    assert v == {"iban": 1, "forderungszahlungen": 1, "tilgungen": 2, "konten": 3, "buchungen": 5, "verknuepfungen": 2,
                 "buchungen_entfallen": 2}
    km.migrieren(db)
    k = db.rows("SELECT * FROM liability_correction WHERE liabilityId=? ORDER BY correctionDate, id", (ids["lid"],))
    assert [(x["correctionType"], x["amountBefore"], x["amountChange"], x["amountAfter"], x["correctionDate"]) for x in k] == [
        ("ERLASS", "1000.00", "-100.00", "900.00", "2026-01-01"),
        ("RATENZAHLUNG", "900.00", "-50.00", "850.00", "2026-02-01"),
        ("RATENZAHLUNG", "850.00", "-50.00", "800.00", "2026-03-01")]
    assert k[1]["description"] == "Tilgungsrate 1 (aus Buchung übernommen)"
    assert db.get("debt_repayment_plan", ids["p1"])["paidCorrectionId"] == k[1]["id"]
    assert db.get("debt_repayment_plan", ids["p2"])["paidCorrectionId"] == k[2]["id"]
    assert db.get("liability", ids["lid"])["iban"] == "AT611904300234573201"
    assert db.get("liability", ids["lid2"])["iban"] is None          # GZ-Konto ignoriert
    cp = db.rows("SELECT * FROM claim_payment")
    assert [(x["claimId"], x["amount"], x["paymentDate"]) for x in cp] == [(ids["claim"], "120.00", "2026-04-10")]
    assert not _tabellen(db) & {"account", "tx", "account_liability_link"}
    for t, s in km.ALT_SPALTEN:
        assert s not in {r[1] for r in db.con.execute(f"PRAGMA table_info({t})")}
    assert not km.noetig(db.con)
    assert db.val("SELECT COUNT(*) FROM audit_log WHERE action='MIGRATE_ACCOUNTS'") == 1
    # Danach läuft der normale Betrieb: Korrektur löschen öffnet die Planzeile wieder
    db.korrektur_loeschen(k[2]["id"])
    assert db.get("liability", ids["lid"])["currentBalance"] == "850.00"


def test_migration_rollback_bei_fehler(db, monkeypatch):
    ids = _altbestand(db)

    def kaputt(con):
        con.execute("UPDATE liability SET iban='X' WHERE id=?", (ids["lid"],))
        raise RuntimeError("Abbruch")
    monkeypatch.setattr(km, "ausfuehren", kaputt)
    import pytest
    with pytest.raises(RuntimeError):
        km.migrieren(db)
    assert db.get("liability", ids["lid"])["iban"] is None
    assert {"account", "tx", "account_liability_link"} <= _tabellen(db)


def test_neue_datenbank_braucht_keine_migration(db):
    assert not km.noetig(db.con)
    assert not _tabellen(db) & {"account", "tx", "account_liability_link"}


def test_neuer_export_import_rundlauf(db, tmp_path):
    from app.abgleich import abgleich as ab
    from app.db import DB
    from tests.demo_data import befuellen
    befuellen(db)
    p = str(tmp_path / "e.ffsync")
    ab.exportieren(db, p, "ein langes Passwort", "Test")
    daten = ab.lesen(p, "ein langes Passwort")["teile"]["finanzen"]["daten"]
    assert "ClaimPayment" in daten and "Account" not in daten and "Transaction" not in daten
    (tmp_path / "b").mkdir()
    b = DB(str(tmp_path / "b" / "b.db"))
    ab.importieren(b, ab.lesen(p, "ein langes Passwort"))
    for t in ("liability", "liability_correction", "debt_repayment_plan", "claim_payment"):
        assert db.rows(f"SELECT * FROM {t} ORDER BY id") == b.rows(f"SELECT * FROM {t} ORDER BY id"), t


# ── Gläubigerverzeichnis / Buchungsmitteilung ─────────────────────────────────
def _pdf_inhalt(monkeypatch, fn, *args) -> str:
    """Text, der in Tabellen und Adressblöcke des PDFs geschrieben wird (ohne Zusatzpaket zum PDF-Lesen)."""
    from app import pdf_base
    texte = []
    tabelle, box = pdf_base.Report.tabelle, pdf_base.Report.box

    def t(self, kopf, zeilen, *a, **k):
        texte.extend(str(getattr(c, "text", c)) for z in zeilen for c in z)
        return tabelle(self, kopf, zeilen, *a, **k)

    def b(self, titel, zeilen):
        texte.extend(str(z) for z in zeilen)
        return box(self, titel, zeilen)
    monkeypatch.setattr(pdf_base.Report, "tabelle", t)
    monkeypatch.setattr(pdf_base.Report, "box", b)
    fn(*args)
    monkeypatch.undo()
    return " | ".join(texte)


def test_glaeubigerverzeichnis_iban(db, tmp_path, monkeypatch):
    import os
    from app import pdf
    k1 = db.kontakt_speichern({"name": "Bank Eins", "iban": "DE89370400440532013000"})
    k2 = db.kontakt_speichern({"name": "Bank Zwei", "iban": "DE89370400440532013000"})
    db.verbindlichkeit_speichern({"contactId": k1, "name": "Eigene IBAN", "currentBalance": "100", "repaymentType": "OPEN",
                                  "iban": "AT611904300234573201"})
    lid = db.verbindlichkeit_speichern({"contactId": k2, "name": "Kontakt-IBAN", "currentBalance": "50", "repaymentType": "OPEN"})
    p = str(tmp_path / "gv.pdf")
    t = _pdf_inhalt(monkeypatch, pdf.glaeubigerverzeichnis, db, p, "all")
    assert os.path.getsize(p) > 0
    zeilen = t.split(" | ")
    i1, i2 = zeilen.index("Eigene IBAN"), zeilen.index("Kontakt-IBAN")
    assert "AT61 1904 3002 3457 3201" in zeilen[i1:i1 + 4]          # IBAN der Verbindlichkeit
    assert "DE89 3704 0044 0532 0130 00" in zeilen[i2:i2 + 4]       # sonst die des Kontakts
    p = str(tmp_path / "bm.pdf")
    t = _pdf_inhalt(monkeypatch, pdf.buchungsmitteilung, db, p, lid)
    assert "Bank Zwei" in t and "IBAN: DE89 3704 0044 0532 0130 00" in t     # Adressblock immer
