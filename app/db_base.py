"""SQLite-Basis: Schema-Versionierung, Migrationen in einer Transaktion, automatische Sicherungen.

Datenmodell: relationale 1:1-Abbildung des Prisma-Schemas von FinanceFlow-TS (Spaltennamen identisch),
damit der Import aus PostgreSQL verlustfrei ist. Geldbeträge als TEXT (exakte Dezimalzahl).
"""
from __future__ import annotations

import json
import os
from . import sqldb as sqlite3
from datetime import date, datetime

from . import APP_VERSION, SCHEMA_VERSION

from .schema import SCHEMA


# (Schema-Version, Funktion(con)) – nur additiv (Tabellen/Spalten ergänzen), niemals Daten löschen
MIGRATIONEN = [
    # (2, lambda con: con.execute("CREATE INDEX IF NOT EXISTS ix_kunde_name ON kunde(name)")),
    (2, lambda con: _spalte(con, "bankruptcy_scenario", "lastInstallment", "TEXT")),
    # 1.6.0: IBAN an der Verbindlichkeit, Planzeile → bezahlende Korrektur (claim_payment legt SCHEMA an).
    # Übernahme und Entfernen der Konten/Buchungen: services/kontenmigration.py (nach Bestätigung beim Start).
    (3, lambda con: (_spalte(con, "liability", "iban", "TEXT"), _spalte(con, "debt_repayment_plan", "paidCorrectionId", "INTEGER"))),
    # 1.7.0: SEPA-Zahlungsdatei (Tabellen legt SCHEMA an)
    (4, lambda con: (_spalte(con, "liability", "zahlungsreferenz", "TEXT"), _spalte(con, "liability", "verwendungszweck", "TEXT"))),
    # 1.9.0: Kontoblatt-Import (Tabellen legt SCHEMA an)
    (5, lambda con: None),
]


def _spalte(con, tabelle, spalte, typ):
    if spalte not in {r[1] for r in con.execute(f"PRAGMA table_info({tabelle})")}:
        con.execute(f"ALTER TABLE {tabelle} ADD COLUMN {spalte} {typ}")


class VersionsFehler(Exception):
    pass


class DBBase:
    def __init__(self, path: str, backup_behalten: int = 30, key: bytes | None = None):
        self.path = path
        self.key = key
        neu = not os.path.exists(path) or os.path.getsize(path) == 0
        if key is not None and not neu and sqlite3.ist_klartext(path):
            raise sqlite3.SchluesselFehler("Die Datenbank ist noch nicht verschlüsselt.")
        if key is None and not neu and not sqlite3.ist_klartext(path):
            raise sqlite3.SchluesselFehler("Die Datenbank ist verschlüsselt – Öffnen nur nach Anmeldung möglich.")
        self.con = sqlite3.connect(path, key)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=DELETE")
        self.con.execute("PRAGMA foreign_keys=ON")
        self.con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        db_schema = int(self._meta("schema_version") or (SCHEMA_VERSION if neu else 0))
        if db_schema > SCHEMA_VERSION:
            self.con.close()
            raise VersionsFehler(f"Datenbank stammt von einer neueren Programmversion (Schema {db_schema} > "
                                 f"{SCHEMA_VERSION}). Bitte die aktuelle EXE verwenden.")
        self.letzte_sicherung = None
        if not neu:
            if self._meta("app_version") != APP_VERSION or db_schema < SCHEMA_VERSION:
                self.letzte_sicherung = self.auto_backup(f"vor_v{APP_VERSION}", backup_behalten)
            else:
                self.letzte_sicherung = self.auto_backup_taeglich(backup_behalten)
        with self.con:
            self.con.executescript("BEGIN;" + SCHEMA)
            for version, migration in MIGRATIONEN:
                if db_schema < version <= SCHEMA_VERSION:
                    migration(self.con)
            self._set_meta("schema_version", str(SCHEMA_VERSION))
            self._set_meta("app_version", APP_VERSION)

    def _meta(self, key):
        r = self.con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else None

    def _set_meta(self, key, value):
        self.con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))

    def backup_ordner(self) -> str:
        d = os.path.join(os.path.dirname(os.path.abspath(self.path)), "Sicherungen")
        os.makedirs(d, exist_ok=True)
        return d

    def backup(self, ziel: str):
        self.con.commit()
        b = sqlite3.connect(ziel, self.key)      # Sicherung mit demselben Schlüssel verschlüsselt
        self.con.backup(b)
        b.close()

    def auto_backup(self, grund: str, behalten: int = 30) -> str:
        ziel = os.path.join(self.backup_ordner(), f"daten_{datetime.now():%Y-%m-%d_%H%M%S}_{grund}.db")
        self.backup(ziel)
        dateien = sorted(f for f in os.listdir(self.backup_ordner()) if f.endswith(".db"))
        for alt in dateien[:-behalten] if behalten else []:
            try:
                os.remove(os.path.join(self.backup_ordner(), alt))
            except OSError:
                pass
        return ziel

    def auto_backup_taeglich(self, behalten: int = 30):
        heute = date.today().isoformat()
        if self._meta("letzte_tagessicherung") == heute:
            return None
        ziel = self.auto_backup("taeglich", behalten)
        with self.con:
            self._set_meta("letzte_tagessicherung", heute)
        return ziel

    def integritaet(self) -> str:
        return self.con.execute("PRAGMA integrity_check").fetchone()[0]


# ── Zugriffshelfer (generisch, von allen Fach-Services genutzt) ────────────────
from contextlib import contextmanager  # noqa: E402


class FachFehler(Exception):
    """Fachliche Ablehnung (wird in der UI als Strip/Hinweis angezeigt)."""


class DBHelfer(DBBase):
    _depth = 0

    @contextmanager
    def tx(self):
        """Atomarer Block (verschachtelbar über SAVEPOINT)."""
        self._depth += 1
        name = f"sp{self._depth}"
        self.con.execute(f"SAVEPOINT {name}")
        try:
            yield
            self.con.execute(f"RELEASE {name}")
        except BaseException:
            self.con.execute(f"ROLLBACK TO {name}")
            self.con.execute(f"RELEASE {name}")
            raise
        finally:
            self._depth -= 1
        if self._depth == 0 and self.con.in_transaction:
            self.con.commit()

    def _autocommit(self):
        if self._depth == 0 and self.con.in_transaction:
            self.con.commit()

    def rows(self, sql, args=()) -> list[dict]:
        return [dict(r) for r in self.con.execute(sql, args)]

    def row(self, sql, args=()) -> dict | None:
        r = self.con.execute(sql, args).fetchone()
        return dict(r) if r else None

    def val(self, sql, args=()):
        r = self.con.execute(sql, args).fetchone()
        return r[0] if r else None

    def get(self, table, id_) -> dict | None:
        return self.row(f"SELECT * FROM {table} WHERE id=?", (id_,))

    def must(self, table, id_, text="Nicht gefunden") -> dict:
        r = self.get(table, id_)
        if not r:
            raise FachFehler(text)
        return r

    @staticmethod
    def _v(v):
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, (dict, list)):
            return json.dumps(v, ensure_ascii=False, default=str)
        if isinstance(v, (date, datetime)):
            return v.isoformat()
        if v is not None and type(v).__name__ == "Decimal":
            return str(v)
        return v

    def insert(self, table, data: dict) -> int:
        cols = list(data)
        cur = self.con.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                               [self._v(data[c]) for c in cols])
        self._autocommit()
        return cur.lastrowid

    def update(self, table, id_, data: dict):
        if not data:
            return
        sets = ",".join(f"{c}=?" for c in data)
        self.con.execute(f"UPDATE {table} SET {sets} WHERE id=?", [self._v(v) for v in data.values()] + [id_])
        self._autocommit()

    def exec(self, sql, args=()):
        cur = self.con.execute(sql, args)
        self._autocommit()
        return cur

    def audit(self, action, entity, entity_id=None, old=None, new=None):
        self.insert("audit_log", {"userId": "desktop", "action": action, "entityType": entity,
                                  "entityId": None if entity_id is None else str(entity_id),
                                  "oldValue": old, "newValue": new, "createdAt": datetime.now().isoformat(timespec="seconds")})

    # Einstellungen
    def settings(self) -> dict:
        return {r["key"]: r["value"] for r in self.con.execute("SELECT key, value FROM setting")}

    def setting(self, key, default=""):
        v = self.val("SELECT value FROM setting WHERE key=?", (key,))
        return default if v is None else v

    def set_setting(self, key, value, value_type="string", description=None):
        now = datetime.now().isoformat(timespec="seconds")
        if self.val("SELECT 1 FROM setting WHERE key=?", (key,)):
            self.exec("UPDATE setting SET value=?, updatedAt=? WHERE key=?", (str(value), now, key))
        else:
            self.insert("setting", {"key": key, "value": str(value), "valueType": value_type,
                                    "description": description, "updatedAt": now})
