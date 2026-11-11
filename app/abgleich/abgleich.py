"""Verschlüsselter Abgleich per Datei (*.ffsync) – Schuldenberatungs-Ausgabe.

Schuldner und Schuldenberatung tauschen den Datenstand als verschlüsselte Datei aus:
  Schuldner  → erstellt die Datei auf seinem Gerät und gibt sie der Beratung (USB-Stick, E-Mail …)
  Berater    → spielt sie beim Mandanten ein (ersetzt dessen Datenstand) und kann einen überarbeiteten
               Stand wieder als Datei an den Schuldner zurückgeben.

Format wie FinanceFlow 2.x (EXE, Android, iOS), siehe docs/ABGLEICH-FORMAT.md:
  {"schemaVersion": 1, "exportedAt": "...", "device": "...", "appVersion": "...", "edition": "...",
   "teile": {"finanzen": {"geaendertAm": ..., "daten": {Prisma-Modell: [Zeilen]}}}}
Diese Ausgabe kennt nur den Teil „finanzen“. Ein Teil „mobil“ (Mobile Erfassung / Kassabuch Devisen) aus der
Vollversion wird beim Import ignoriert, ebenso Modelle von HR, Aviation und Tankbuch.
Import: der Teil „finanzen“ ersetzt den lokalen Datenstand vollständig (eine Transaktion, vorher Sicherung).
"""
from __future__ import annotations

import json
import re
import socket
from datetime import datetime

from .. import APP_VERSION, EDITION
from . import krypto

SCHEMA_VERSION = 1
TEILE = ("finanzen",)
TEIL_NAMEN = {"finanzen": "Finanzen"}

STATUS_SCHEMA = """CREATE TABLE IF NOT EXISTS abgleich_status (teil TEXT PRIMARY KEY, geaendert INTEGER NOT NULL DEFAULT 0,
  geaendert_am TEXT, letzter_abgleich TEXT, letztes_geraet TEXT, letzte_richtung TEXT)"""


class Konflikt(krypto.AbgleichFehler):
    def __init__(self, teile: list[str]):
        self.teile = teile
        super().__init__(" ".join(warnung(t) for t in teile))


def warnung(teil: str = "finanzen") -> str:
    return "Auf diesem Gerät gibt es Änderungen seit dem letzten Abgleich – sie gehen beim Einspielen verloren."


def _jetzt() -> str:
    return datetime.now().isoformat(timespec="seconds")


def geraetename_standard() -> str:
    try:
        return socket.gethostname() or "Laptop"
    except OSError:
        return "Laptop"


def dateiname(geraet: str, zeit: datetime | None = None) -> str:
    g = re.sub(r"[^A-Za-z0-9\-]+", "-", geraet or "Geraet").strip("-")[:40] or "Geraet"
    return f"FinanceFlow-{(zeit or datetime.now()):%Y-%m-%d-%H%M}-{g}.ffsync"


# ── Änderungsmerker (daten.db: Trigger auf allen Finanztabellen) ──────────────
def finanz_merker_einrichten(db):
    """Trigger setzen „lokal geändert seit letztem Abgleich“ bei jeder Änderung einer Finanztabelle."""
    from ..schema import TABLES
    con = db.con
    con.execute(STATUS_SCHEMA)
    vorhanden = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'trg_abgl_%'")}
    tabellen = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in sorted(set(TABLES.values())):
        if t == "audit_log" or t not in tabellen:
            continue
        for art, op in (("i", "INSERT"), ("u", "UPDATE"), ("d", "DELETE")):
            name = f"trg_abgl_{t}_{art}"
            if name in vorhanden:
                continue
            con.execute(f"CREATE TRIGGER {name} AFTER {op} ON {t} BEGIN "
                        "INSERT INTO abgleich_status (teil, geaendert, geaendert_am) VALUES ('finanzen', 1, datetime('now','localtime')) "
                        "ON CONFLICT(teil) DO UPDATE SET geaendert=1, geaendert_am=excluded.geaendert_am; END")
    if con.in_transaction:
        con.commit()


def status(db) -> dict:
    out = {}
    for teil in TEILE:
        r = db.con.execute("SELECT * FROM abgleich_status WHERE teil=?", (teil,)).fetchone()
        out[teil] = dict(r) if r else {"teil": teil, "geaendert": 0}
    return out


def _status_setzen(db, teil, richtung, geraet):
    con = db.con
    con.execute("INSERT INTO abgleich_status (teil, geaendert, letzter_abgleich, letztes_geraet, letzte_richtung) VALUES (?,0,?,?,?) "
                "ON CONFLICT(teil) DO UPDATE SET geaendert=0, letzter_abgleich=excluded.letzter_abgleich, "
                "letztes_geraet=excluded.letztes_geraet, letzte_richtung=excluded.letzte_richtung",
                (teil, _jetzt(), geraet, richtung))
    if con.in_transaction:
        con.commit()


def status_text(s: dict) -> str:
    if not s.get("letzter_abgleich"):
        return "Letzter Abgleich: noch keiner"
    d = datetime.fromisoformat(s["letzter_abgleich"])
    t = f"Letzter Abgleich: {d:%d.%m.%Y %H:%M}, {s.get('letztes_geraet') or '–'}, {s.get('letzte_richtung') or ''}".rstrip(", ")
    if s.get("geaendert"):
        t += " · seither lokal geändert"
    return t


# ── Teil lesen ────────────────────────────────────────────────────────────────
def teil_finanzen(db) -> dict:
    from ..importer import ORDER
    from ..schema import TABLES
    return {model: db.rows(f"SELECT * FROM {TABLES[model]} ORDER BY rowid") for model in ORDER}


def klartext(db, geraet: str) -> bytes:
    st = status(db)
    nutz = {"schemaVersion": SCHEMA_VERSION, "exportedAt": _jetzt(), "device": geraet, "appVersion": APP_VERSION,
            "edition": EDITION,
            "teile": {"finanzen": {"geaendertAm": st["finanzen"].get("geaendert_am"), "daten": teil_finanzen(db)}}}
    return json.dumps(nutz, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


# ── Export / Import ───────────────────────────────────────────────────────────
def pruefe_passwort(pw: str, wiederholung: str | None = None):
    if len(pw or "") < krypto.MIN_PASSWORT:
        raise krypto.AbgleichFehler(f"Das Passwort muss mindestens {krypto.MIN_PASSWORT} Zeichen lang sein.")
    if wiederholung is not None and pw != wiederholung:
        raise krypto.AbgleichFehler("Die Passwörter stimmen nicht überein.")


def exportieren(db, pfad: str, passwort: str, geraet: str) -> dict:
    pruefe_passwort(passwort)
    krypto.datei_schreiben(pfad, klartext(db, geraet), passwort)
    _status_setzen(db, "finanzen", "Export", geraet)
    if hasattr(db, "set_geraet_einstellung"):
        db.set_geraet_einstellung("export_erstellt", "1")
    return {"datei": pfad}


def lesen(pfad: str, passwort: str) -> dict:
    roh = krypto.datei_lesen(pfad, passwort)
    try:
        nutz = json.loads(roh.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise krypto.AbgleichFehler(krypto.FEHLER_PASSWORT) from e
    sv = nutz.get("schemaVersion")
    if not isinstance(sv, int):
        raise krypto.AbgleichFehler("Keine gültige Abgleich-Datei (schemaVersion fehlt).")
    if sv > SCHEMA_VERSION:
        raise krypto.AbgleichFehler("Die Datei stammt aus einer neueren App-Version. Bitte App aktualisieren.")
    if not isinstance(nutz.get("teile"), dict):
        raise krypto.AbgleichFehler("Keine gültige Abgleich-Datei (Teile fehlen).")
    if not isinstance((nutz["teile"].get("finanzen") or {}).get("daten"), dict):
        raise krypto.AbgleichFehler("Die Datei enthält keine Finanzdaten.")
    return nutz


def info(nutz: dict) -> dict:
    """Kurzinfo zu einer gelesenen Datei (für die Mandantenverwaltung): Name aus dem PDF-Kopf, Anzahlen."""
    daten = nutz["teile"]["finanzen"]["daten"]
    name = next((s.get("value") for s in daten.get("Setting") or [] if s.get("key") == "owner_name"), "") or ""
    offen = [l for l in daten.get("Liability") or [] if l.get("status") not in ("GELOESCHT", "BEZAHLT") and not l.get("deletedAt")]
    return {"name": name.strip(), "geraet": nutz.get("device") or "?", "exportiert": nutz.get("exportedAt") or "",
            "glaeubiger": len(daten.get("Contact") or []), "verbindlichkeiten": len(offen),
            "edition": nutz.get("edition") or "Vollversion"}


def konflikte(db, teile=TEILE) -> list[str]:
    st = status(db)
    return [t for t in teile if t in st and st[t].get("geaendert")]


def importieren(db, nutz: dict, teile=TEILE, trotz_aenderungen: bool = False) -> dict:
    teile = [t for t in TEILE if t in teile and t in nutz["teile"]]
    if not teile:
        raise krypto.AbgleichFehler("Die Datei enthält keine Finanzdaten.")
    k = konflikte(db, teile)
    if k and not trotz_aenderungen:
        raise Konflikt(k)
    if not isinstance(nutz["teile"]["finanzen"].get("daten"), dict):
        raise krypto.AbgleichFehler("Teil Finanzen ist in der Datei beschädigt.")
    geraet = nutz.get("device") or "?"
    db.auto_backup("vor_abgleich")
    from ..importer import importieren_daten
    ergebnis = {"finanzen": importieren_daten(db, nutz["teile"]["finanzen"]["daten"])}
    ergebnis["plaene_neu"] = plaene_ergaenzen(db)
    _status_setzen(db, "finanzen", "Import", geraet)
    return ergebnis


def plaene_ergaenzen(db) -> int:
    """Tilgungspläne für offene Verbindlichkeiten ohne offene Planzeilen neu rechnen. Die Smartphone-Version
    (web/FinanceFlow-Schuldner.html) rechnet keine Pläne: Sie legt Schulden ohne Plan an und verwirft bei jeder
    Änderung die unbezahlten Planzeilen der Schuld – bezahlte Zeilen bleiben. Für alle übrigen Schulden ändert sich
    nichts (der Plan ist vorhanden)."""
    ids = [r["id"] for r in db.rows(
        "SELECT id FROM liability l WHERE status IN ('OFFEN','ZAHLUNGSPLAN') AND deletedAt IS NULL AND NOT EXISTS "
        "(SELECT 1 FROM debt_repayment_plan p WHERE p.liabilityId=l.id AND p.paidAt IS NULL)")]
    if ids:
        with db.tx():
            for i in ids:
                db.recalculate_plan(i)
    return len(ids)
