"""Mandantenverwaltung der Schuldenberatung (nur Modus BERATER).

Jeder Mandant (= ein:e Schuldner:in) hat einen eigenen, eigens verschlüsselten FinanceFlow-Datenstand – genau so,
wie ihn der Schuldner auf seinem eigenen Gerät führt. Ablage im Profilordner des angemeldeten Beraters:

    mandanten.db                      Verzeichnis der Mandanten (SQLCipher, Schlüssel = Profilschlüssel)
    mandanten\\<zufällige ID>\\daten.db  Datenstand des Mandanten samt Sicherungen und Berichte
    Gelöschte Mandanten\\…             gelöschte Mandanten werden verschoben, nicht vernichtet

Schlüssel je Mandant = HMAC-SHA256(Profilschlüssel, „financeflow-mandant/1|<ID>“): ohne Anmeldung des Beraters ist
kein Mandant lesbar, und eine Mandanten-Datenbank lässt sich nicht mit dem Schlüssel einer anderen öffnen.

Datenstand des Schuldners übernehmen: Abgleich-Datei (*.ffsync) des Schuldners einspielen – sie ersetzt den Stand
des Mandanten vollständig (vorher automatische Sicherung). Zurück an den Schuldner geht es auf demselben Weg.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import shutil
from datetime import datetime

from . import sqldb

SCHEMA = """
CREATE TABLE IF NOT EXISTS mandant (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, aktenzeichen TEXT, geburtsdatum TEXT, telefon TEXT, email TEXT, notiz TEXT,
  status TEXT NOT NULL DEFAULT 'AKTIV' CHECK (status IN ('AKTIV','ARCHIV')), erstellt TEXT NOT NULL, geaendert TEXT,
  letzter_import TEXT, import_geraet TEXT, import_stand TEXT, letzter_export TEXT);
CREATE TABLE IF NOT EXISTS mandant_protokoll (id INTEGER PRIMARY KEY, mandant_id TEXT NOT NULL, zeit TEXT NOT NULL,
  aktion TEXT NOT NULL, details TEXT, benutzer TEXT);
"""

FELDER = ("name", "aktenzeichen", "geburtsdatum", "telefon", "email", "notiz")


class MandantFehler(ValueError):
    pass


def _jetzt() -> str:
    return datetime.now().isoformat(timespec="seconds")


def mandant_schluessel(profil_key: bytes, mid: str) -> bytes:
    return hmac.new(profil_key, f"financeflow-mandant/1|{mid}".encode(), hashlib.sha256).digest()


class Mandanten:
    def __init__(self, profil_ordner: str, profil_key: bytes, benutzer: str = ""):
        self.ordner = profil_ordner
        self.key = profil_key
        self.benutzer = benutzer
        os.makedirs(os.path.join(profil_ordner, "mandanten"), exist_ok=True)
        self.path = os.path.join(profil_ordner, "mandanten.db")
        self.con = sqldb.connect(self.path, profil_key)
        self.con.row_factory = sqldb.Row
        with self.con:
            self.con.executescript(SCHEMA)

    def close(self):
        self.con.close()

    # ── Abfragen ─────────────────────────────────────────────────────────────
    def liste(self, archiv: bool = False, suche: str = "") -> list[dict]:
        rows = [dict(r) for r in self.con.execute(
            "SELECT * FROM mandant WHERE status=? ORDER BY name COLLATE NOCASE, erstellt", ("ARCHIV" if archiv else "AKTIV",))]
        q = (suche or "").strip().casefold()
        if q:
            rows = [r for r in rows if q in " ".join(str(r.get(k) or "") for k in ("name", "aktenzeichen", "notiz")).casefold()]
        return rows

    def anzahl(self) -> dict:
        return {s: n for s, n in self.con.execute("SELECT status, count(*) FROM mandant GROUP BY status")}

    def get(self, mid) -> dict:
        r = self.con.execute("SELECT * FROM mandant WHERE id=?", (mid,)).fetchone()
        if not r:
            raise MandantFehler("Mandant nicht gefunden.")
        return dict(r)

    def ordner_von(self, mid) -> str:
        if not mid or any(c not in "0123456789abcdef" for c in mid):
            raise MandantFehler("Ungültige Mandanten-ID.")
        d = os.path.join(self.ordner, "mandanten", mid)
        os.makedirs(d, exist_ok=True)
        return d

    def db_pfad(self, mid) -> str:
        return os.path.join(self.ordner_von(mid), "daten.db")

    def schluessel(self, mid) -> bytes:
        return mandant_schluessel(self.key, mid)

    def protokoll(self, mid, limit=100) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT * FROM mandant_protokoll WHERE mandant_id=? ORDER BY id DESC LIMIT ?", (mid, limit))]

    # ── Ändern ──────────────────────────────────────────────────────────────
    def _log(self, mid, aktion, details=""):
        self.con.execute("INSERT INTO mandant_protokoll (mandant_id, zeit, aktion, details, benutzer) VALUES (?,?,?,?,?)",
                         (mid, _jetzt(), aktion, details, self.benutzer))

    @staticmethod
    def _werte(daten: dict) -> dict:
        w = {k: (str(daten.get(k) or "").strip() or None) for k in FELDER}
        if not w["name"]:
            raise MandantFehler("Name des Mandanten fehlt.")
        if len(w["name"]) > 120:
            raise MandantFehler("Name ist zu lang (höchstens 120 Zeichen).")
        return w

    def anlegen(self, daten: dict) -> dict:
        w = self._werte(daten)
        mid = secrets.token_hex(8)
        with self.con:
            self.con.execute("INSERT INTO mandant (id, name, aktenzeichen, geburtsdatum, telefon, email, notiz, status, erstellt, "
                             "geaendert) VALUES (?,?,?,?,?,?,?,'AKTIV',?,?)",
                             (mid, w["name"], w["aktenzeichen"], w["geburtsdatum"], w["telefon"], w["email"], w["notiz"],
                              _jetzt(), _jetzt()))
            self._log(mid, "ANGELEGT", w["name"])
        self.ordner_von(mid)
        return self.get(mid)

    def aendern(self, mid, daten: dict) -> dict:
        self.get(mid)
        w = self._werte(daten)
        with self.con:
            self.con.execute("UPDATE mandant SET name=?, aktenzeichen=?, geburtsdatum=?, telefon=?, email=?, notiz=?, geaendert=? "
                             "WHERE id=?", (w["name"], w["aktenzeichen"], w["geburtsdatum"], w["telefon"], w["email"], w["notiz"],
                                            _jetzt(), mid))
            self._log(mid, "GEAENDERT")
        return self.get(mid)

    def archivieren(self, mid, archiv: bool = True):
        self.get(mid)
        with self.con:
            self.con.execute("UPDATE mandant SET status=?, geaendert=? WHERE id=?", ("ARCHIV" if archiv else "AKTIV", _jetzt(), mid))
            self._log(mid, "ARCHIVIERT" if archiv else "REAKTIVIERT")

    def vermerken(self, mid, richtung: str, geraet: str = "", stand: str = "", datei: str = ""):
        """Nach Import/Export einer Abgleich-Datei: letzter Stand im Verzeichnis und Protokoll."""
        with self.con:
            if richtung == "Import":
                self.con.execute("UPDATE mandant SET letzter_import=?, import_geraet=?, import_stand=? WHERE id=?",
                                 (_jetzt(), geraet, stand, mid))
            else:
                self.con.execute("UPDATE mandant SET letzter_export=? WHERE id=?", (_jetzt(), mid))
            self._log(mid, "IMPORT" if richtung == "Import" else "EXPORT",
                      " · ".join(x for x in (geraet, stand[:16].replace("T", " ") if stand else "", os.path.basename(datei)) if x))

    def loeschen(self, mid) -> str:
        """Entfernt den Mandanten aus der Liste. Der Datenordner wird nach „Gelöschte Mandanten“ verschoben."""
        m = self.get(mid)
        quelle = os.path.join(self.ordner, "mandanten", mid)
        ziel = ""
        if os.path.isdir(quelle):
            d = os.path.join(self.ordner, "Gelöschte Mandanten")
            os.makedirs(d, exist_ok=True)
            ziel = os.path.join(d, f"{datetime.now():%Y-%m-%d_%H%M%S}_{mid}")
            shutil.move(quelle, ziel)
        with self.con:
            self.con.execute("DELETE FROM mandant WHERE id=?", (mid,))
            self._log(mid, "GELOESCHT", f"{m['name']} → {os.path.basename(ziel) or '–'}")
        return ziel

    # ── Datenstand ──────────────────────────────────────────────────────────
    def oeffnen(self, mid):
        """Datenstand des Mandanten als DB öffnen (legt ihn beim ersten Mal an, Name als PDF-Kopf)."""
        from .db import DB
        m = self.get(mid)
        pfad = self.db_pfad(mid)
        neu = not os.path.exists(pfad)
        db = DB(pfad, key=self.schluessel(mid))
        if neu or not db.setting("owner_name", ""):
            db.set_setting("owner_name", m["name"])
            # neuer Mandant gilt nicht als „lokal geändert“ – das erste Einspielen soll ohne Warnung gehen
            db.con.execute("UPDATE abgleich_status SET geaendert=0")
            db.con.commit()
        db.mandant = m
        return db
