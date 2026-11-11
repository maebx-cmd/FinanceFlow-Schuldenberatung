"""SQLite mit Verschlüsselung (SQLCipher 4, AES-256 je Seite, HMAC-SHA512 gegen Manipulation).

Alle Datenbanken des Programms (daten.db, mobil.db und ihre Sicherungen) werden hierüber geöffnet.
Schlüssel: 32 zufällige Bytes je Profil, roh übergeben (PRAGMA key = "x'…'"), daher kein zusätzlicher Rechenaufwand beim
Öffnen – das Passwort wird in konten.py mit scrypt zu einem Schlüssel verarbeitet, der diesen Profil-Schlüssel umhüllt.
Ohne Schlüssel (key=None) verhält sich alles wie normales SQLite (nur für benutzer.db und Tests).
"""
from __future__ import annotations

import os

from sqlcipher3 import dbapi2 as _s
from sqlcipher3.dbapi2 import (Connection, DatabaseError, Error, IntegrityError, OperationalError, Row,  # noqa: F401
                               sqlite_version)

SQLITE_KOPF = b"SQLite format 3\x00"


class SchluesselFehler(DatabaseError):
    pass


def _key_pragma(key: bytes) -> str:
    if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
        raise ValueError("Datenbank-Schlüssel muss 32 Bytes haben.")
    return f"\"x'{bytes(key).hex()}'\""


def connect(pfad: str, key: bytes | None = None, **kw) -> Connection:
    """Öffnet die Datenbank. Mit Schlüssel: erster Befehl ist PRAGMA key; falscher Schlüssel → SchluesselFehler."""
    c = _s.connect(pfad, **kw)
    c.execute("PRAGMA cipher_log_level = NONE")
    if key is not None:
        c.execute(f"PRAGMA key = {_key_pragma(key)}")
        try:
            c.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except DatabaseError:
            c.close()
            raise SchluesselFehler("Datenbank lässt sich mit diesem Schlüssel nicht öffnen "
                                   "(falscher Schlüssel oder unverschlüsselte/beschädigte Datei).") from None
    return c


def ist_klartext(pfad: str) -> bool:
    """True, wenn die Datei eine unverschlüsselte SQLite-Datenbank ist (Kopf „SQLite format 3“)."""
    try:
        with open(pfad, "rb") as f:
            return f.read(16) == SQLITE_KOPF
    except OSError:
        return False


def _zaehlen(c) -> dict:
    tabellen = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    z = {t: c.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tabellen}
    z["#objekte"] = c.execute("SELECT count(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchone()[0]
    return z


def verschluesseln(pfad: str, key: bytes) -> bool:
    """Wandelt eine unverschlüsselte Datenbank in eine verschlüsselte um (gleicher Pfad). Gibt False zurück, wenn sie
    schon verschlüsselt ist. Ablauf: WAL einarbeiten → verschlüsselte Kopie (sqlcipher_export) → Inhalt vergleichen
    (alle Tabellen, Zeilenzahl, Trigger/Indizes, integrity_check) → Kopie ersetzt das Original atomar.
    Bei jedem Fehler bleibt das Original unverändert."""
    if not ist_klartext(pfad):
        return False
    tmp = pfad + ".verschluesselt.tmp"
    for x in (tmp, tmp + "-journal"):
        if os.path.exists(x):
            os.remove(x)
    c = connect(pfad, isolation_level=None)
    try:
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        c.execute("PRAGMA journal_mode=DELETE")
        vorher = _zaehlen(c)
        uv = c.execute("PRAGMA user_version").fetchone()[0]
        c.execute(f"ATTACH DATABASE ? AS enc KEY {_key_pragma(key)}", (tmp,))
        c.execute("SELECT sqlcipher_export('enc')")
        c.execute(f"PRAGMA enc.user_version = {int(uv)}")
        c.execute("DETACH DATABASE enc")
    finally:
        c.close()
    e = connect(tmp, key)
    try:
        if e.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or _zaehlen(e) != vorher:
            raise DatabaseError(f"Verschlüsselte Kopie von {os.path.basename(pfad)} weicht ab – Original unverändert.")
    finally:
        e.close()
    os.replace(tmp, pfad)
    for rest in (pfad + "-wal", pfad + "-shm"):
        if os.path.exists(rest):
            os.remove(rest)
    return True
