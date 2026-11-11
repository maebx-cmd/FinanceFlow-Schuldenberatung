"""Einmalige Übernahme aus dem früheren Konten-/Buchungs-Modul (bis 1.5.0) – wie die Web-Version.

a) IBAN je Verbindlichkeit aus dem ersten verknüpften Konto mit Kennungstyp IBAN
b) Forderungseingänge (FORDERUNGSEINGANG/CLAIM) → claim_payment
c) Tilgungen (SCHULDENTILGUNG/LIABILITY) → Korrektur RATENZAHLUNG, Saldo vorher/nachher rückwärts rekonstruiert;
   Planzeilen, die damit bezahlt wurden, zeigen danach auf die neue Korrektur
d) Verweisspalten und die Tabellen Konto-Verknüpfung, Buchung, Konto löschen – alle übrigen Buchungen entfallen.

Alles in EINER Transaktion. Die Funktionen arbeiten direkt auf der SQLite-Verbindung, damit auch der Import
eines alten JSON-Exports (mit „Account“/„Transaction“) denselben Weg nimmt.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from ..calc import iban as ib

ALT_TABELLEN = ("account_liability_link", "tx", "account")
ALT_SPALTEN = [("fixed_cost_payment", "paidTransactionId"), ("debt_repayment_plan", "paidTransactionId"),
               ("abschoepfungs_rate", "paidTransactionId"), ("liability_correction", "transactionId"),
               ("liability_correction", "accountId")]

# Struktur bis 1.5.0 – nur für den Import alter JSON-Exporte (danach wird alles wieder entfernt)
ALT_SCHEMA = """
CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY, name TEXT NOT NULL, accountType TEXT NOT NULL,
  bankName TEXT, identifierType TEXT DEFAULT 'IBAN', iban TEXT, bic TEXT, gz TEXT,
  startBalance TEXT NOT NULL DEFAULT '0.00', currentBalance TEXT NOT NULL DEFAULT '0.00', currency TEXT NOT NULL DEFAULT 'EUR',
  isActive INTEGER NOT NULL DEFAULT 1, isDormant INTEGER NOT NULL DEFAULT 0, notes TEXT,
  correctionMinutes INTEGER NOT NULL DEFAULT 0, createdAt TEXT);
CREATE TABLE IF NOT EXISTS tx (id INTEGER PRIMARY KEY, uuid TEXT, accountId INTEGER,
  transactionType TEXT NOT NULL, amount TEXT NOT NULL, description TEXT, referenceType TEXT, referenceId INTEGER,
  categoryId INTEGER, counterAccountId INTEGER, transactionDate TEXT NOT NULL, valueDate TEXT,
  isCorrection INTEGER NOT NULL DEFAULT 0, notes TEXT, correctionMinutes INTEGER NOT NULL DEFAULT 0, integrityHash TEXT,
  deletedAt TEXT, createdAt TEXT);
CREATE TABLE IF NOT EXISTS account_liability_link (id INTEGER PRIMARY KEY, accountId INTEGER, liabilityId INTEGER, createdAt TEXT);
"""
ALT_MODELLE = {"Account": "account", "Transaction": "tx", "AccountLiabilityLink": "account_liability_link"}


def _tabellen(con) -> set:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _spalten(con, t) -> set:
    return {r[1] for r in con.execute(f"PRAGMA table_info({t})")}


def noetig(con) -> bool:
    return bool(_tabellen(con) & set(ALT_TABELLEN)) or any(s in _spalten(con, t) for t, s in ALT_SPALTEN)


def alt_struktur_anlegen(con):
    """Für den Import eines alten Exports: alte Tabellen und Verweisspalten vorübergehend anlegen."""
    for befehl in ALT_SCHEMA.split(";"):
        if befehl.strip():
            con.execute(befehl)
    for t, s in ALT_SPALTEN:
        if s not in _spalten(con, t):
            con.execute(f"ALTER TABLE {t} ADD COLUMN {s} INTEGER")


def _dec(x) -> Decimal:
    return Decimal(str(x or "0"))


def _f2(x: Decimal) -> str:
    return str(x.quantize(Decimal("0.01")))


def _q(con, sql, args=()):
    cur = con.execute(sql, args)
    namen = [c[0] for c in cur.description]
    return [dict(zip(namen, r)) for r in cur.fetchall()]


def _plan(con) -> dict:
    """Was übernommen wird (ohne etwas zu ändern)."""
    tab = _tabellen(con)
    p = {"iban": [], "forderung": [], "tilgung": [], "konten": 0, "buchungen": 0, "verknuepfungen": 0}
    if "account" in tab and "account_liability_link" in tab:
        libs = {r["id"]: r for r in _q(con, "SELECT id, iban FROM liability")}
        for r in _q(con, "SELECT k.liabilityId, a.iban, a.identifierType FROM account_liability_link k "
                         "JOIN account a ON a.id=k.accountId ORDER BY k.liabilityId, k.id"):
            lid = r["liabilityId"]
            if lid not in libs or libs[lid]["iban"] or any(x[0] == lid for x in p["iban"]):
                continue
            if (r["identifierType"] or "IBAN") != "IBAN":
                continue
            n = ib.normalisieren(r["iban"])
            if n and 15 <= len(n) <= 34:
                p["iban"].append((lid, n))
    if "tx" in tab:
        p["forderung"] = _q(con, "SELECT t.* FROM tx t JOIN claim c ON c.id=t.referenceId WHERE t.transactionType='FORDERUNGSEINGANG' "
                                 "AND t.referenceType='CLAIM' AND t.deletedAt IS NULL ORDER BY t.transactionDate, t.id")
        p["tilgung"] = _q(con, "SELECT t.* FROM tx t JOIN liability l ON l.id=t.referenceId WHERE t.transactionType='SCHULDENTILGUNG' "
                               "AND t.referenceType='LIABILITY' AND t.deletedAt IS NULL ORDER BY t.transactionDate, t.id")
        p["buchungen"] = con.execute("SELECT COUNT(*) FROM tx").fetchone()[0]
    if "account" in tab:
        p["konten"] = con.execute("SELECT COUNT(*) FROM account").fetchone()[0]
    if "account_liability_link" in tab:
        p["verknuepfungen"] = con.execute("SELECT COUNT(*) FROM account_liability_link").fetchone()[0]
    return p


def vorschau(con) -> dict:
    p = _plan(con)
    uebernommen = len(p["forderung"]) + len(p["tilgung"])
    return {"iban": len(p["iban"]), "forderungszahlungen": len(p["forderung"]), "tilgungen": len(p["tilgung"]),
            "konten": p["konten"], "buchungen": p["buchungen"], "verknuepfungen": p["verknuepfungen"],
            "buchungen_entfallen": p["buchungen"] - uebernommen}


def vorschau_text(v: dict) -> str:
    return (f"Übernommen werden:\n"
            f"  • {v['iban']} IBAN aus verknüpften Konten in die Verbindlichkeiten\n"
            f"  • {v['tilgungen']} Tilgungsbuchungen als Korrektur „Ratenzahlung“\n"
            f"  • {v['forderungszahlungen']} Forderungseingänge als Forderungszahlung\n\n"
            f"Gelöscht werden:\n"
            f"  • {v['konten']} Konten und {v['verknuepfungen']} Konto-Verknüpfungen\n"
            f"  • {v['buchungen']} Buchungen – davon entfallen {v['buchungen_entfallen']} ersatzlos "
            f"(Giro, Fixkosten, Umbuchungen, gelöschte …)")


def ausfuehren(con) -> dict:
    """Übernahme + Entfernen. Muss innerhalb einer offenen Transaktion laufen (Aufrufer: db.tx())."""
    p = _plan(con)
    jetzt = datetime.now().isoformat(timespec="seconds")
    # a) IBAN
    for lid, n in p["iban"]:
        con.execute("UPDATE liability SET iban=? WHERE id=? AND (iban IS NULL OR iban='')", (n, lid))
    # b) Forderungseingänge
    for t in p["forderung"]:
        con.execute("INSERT INTO claim_payment (claimId, amount, description, paymentDate, createdAt) VALUES (?,?,?,?,?)",
                    (t["referenceId"], _f2(abs(_dec(t["amount"]))), t["description"], (t["transactionDate"] or "")[:10],
                     t["createdAt"] or jetzt))
    # c) Tilgungen → RATENZAHLUNG mit rekonstruiertem Saldo
    plan_spalte = "paidTransactionId" in _spalten(con, "debt_repayment_plan")
    nach_lib: dict[int, list] = {}
    for t in p["tilgung"]:
        nach_lib.setdefault(t["referenceId"], []).append(t)
    neue = 0
    for lid, tilg in nach_lib.items():
        aktuell = _dec(con.execute("SELECT currentBalance FROM liability WHERE id=?", (lid,)).fetchone()[0])
        ereignisse = [{"art": 0, "datum": k["correctionDate"][:10], "erfasst": k["createdAt"] or "", "id": k["id"],
                       "aenderung": _dec(k["amountChange"]), "korr": True}
                      for k in _q(con, "SELECT * FROM liability_correction WHERE liabilityId=?", (lid,))]
        ereignisse += [{"art": 1, "datum": (t["transactionDate"] or "")[:10], "erfasst": t["createdAt"] or "", "id": t["id"],
                        "aenderung": -_dec(t["amount"]), "korr": False, "tx": t} for t in tilg]
        ereignisse.sort(key=lambda e: (e["datum"], e["erfasst"], e["art"], e["id"]))
        spaeter = Decimal(0)
        for e in reversed(ereignisse):
            nachher = aktuell - spaeter
            e["nachher"], e["vorher"] = nachher, nachher - e["aenderung"]
            spaeter += e["aenderung"]
        for e in ereignisse:
            if e["korr"]:
                continue
            t = e["tx"]
            text = f"{t['description'] or 'Tilgung'} (aus Buchung übernommen)"
            cur = con.execute("INSERT INTO liability_correction (liabilityId, correctionType, amountBefore, amountChange, amountAfter, "
                              "description, correctionDate, createdAt) VALUES (?,?,?,?,?,?,?,?)",
                              (lid, "RATENZAHLUNG", _f2(e["vorher"]), _f2(e["aenderung"]), _f2(e["nachher"]), text, e["datum"],
                               t["createdAt"] or jetzt))
            neue += 1
            if plan_spalte:
                con.execute("UPDATE debt_repayment_plan SET paidCorrectionId=? WHERE paidTransactionId=?", (cur.lastrowid, t["id"]))
    # d) Verweisspalten und alte Tabellen entfernen
    for t, s in ALT_SPALTEN:
        if s in _spalten(con, t):
            con.execute(f"ALTER TABLE {t} DROP COLUMN {s}")
    for t in ALT_TABELLEN:
        con.execute(f"DROP TABLE IF EXISTS {t}")
    return {"iban": len(p["iban"]), "forderungszahlungen": len(p["forderung"]), "tilgungen": neue,
            "konten": p["konten"], "buchungen": p["buchungen"], "verknuepfungen": p["verknuepfungen"]}


def migrieren(db) -> dict:
    """Mit Sicherung und in einer Transaktion; schreibt einen Audit-Eintrag."""
    db.auto_backup("vor_kontenmigration")
    with db.tx():
        ergebnis = ausfuehren(db.con)
        db.audit("MIGRATE_ACCOUNTS", "Database", None, None, ergebnis)
    return ergebnis
