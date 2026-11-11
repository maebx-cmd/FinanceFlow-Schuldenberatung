"""Benutzerprofile: Anmeldung mit Passwort, je Benutzer ein eigener, getrennter Datenbestand.

Ablage (Basisordner = %APPDATA%\\FinanceFlow\\FinanceFlow):
    benutzer.db                       Konten (Name, Passwort-Hash, Rolle, Profilordner)
    daten.db, Sicherungen, Berichte   Profil des Administrators (bisheriger Datenbestand bleibt unverändert)
    profile\\<zufällige ID>\\daten.db   Profil jedes weiteren Benutzers, samt eigener Sicherungen und Berichte

Ordnernamen sind zufällige IDs, damit aus dem Dateisystem keine Benutzernamen ablesbar sind.
Die Anmeldemaske verrät nicht, ob ein Benutzername existiert: gleiche Fehlermeldung, gleicher Rechenaufwand,
wachsende Wartezeit nach Fehlversuchen.

Passwörter: scrypt (n=2^15, r=8, p=1, 16 Byte Salz), Vergleich in konstanter Zeit. Gespeichert wird nur der Hash.

Verschlüsselung (ab 2.0.0): Jedes Profil hat einen zufälligen 256-Bit-Datenbankschlüssel (SQLCipher, siehe sqldb.py).
Er wird nie im Klartext gespeichert, sondern zweimal umhüllt (AES-256-GCM, Schlüssel per scrypt, je eigenes Salz):
  key_pw  – mit dem Passwort des Benutzers       key_rk – mit seinem Wiederherstellungsschlüssel (160 Bit, einmal angezeigt)
Beides steht in benutzer.db und zusätzlich in <Profilordner>/schluessel.json (falls benutzer.db verloren geht).
Passwort ändern = neu umhüllen (Daten bleiben). Der Administrator kann ein Passwort nur mit dem Wiederherstellungsschlüssel
des Benutzers zurücksetzen – ohne Passwort oder Wiederherstellungsschlüssel sind die Daten nicht lesbar.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import shutil
import sqlite3
import time
import unicodedata
from datetime import datetime

MIN_PW = 8
_N, _R, _P = 2 ** 15, 8, 1


class KontoFehler(ValueError):
    pass


def _norm(name: str) -> str:
    return unicodedata.normalize("NFKC", (name or "").strip()).casefold()


def hash_pw(pw: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, maxmem=64 * 1024 * 1024, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(h).decode()}"


def pruefe_pw(pw: str, gespeichert: str) -> bool:
    try:
        _alg, n, r, p, salt, h = gespeichert.split("$")
        neu = hashlib.scrypt(pw.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                             maxmem=64 * 1024 * 1024, dklen=32)
        return hmac.compare_digest(neu, base64.b64decode(h))
    except Exception:  # noqa: BLE001
        return False


# Für unbekannte Benutzernamen wird gegen diesen Hash geprüft → gleiche Rechenzeit wie bei echten Konten
_DUMMY = hash_pw(secrets.token_hex(16))


def pw_regel(pw: str):
    if len(pw or "") < MIN_PW:
        raise KontoFehler(f"Das Passwort muss mindestens {MIN_PW} Zeichen haben.")


# Wer nutzt das Programm? Wird bei der Ersteinrichtung festgelegt (Tabelle einrichtung in benutzer.db).
MODUS_SCHULDNER = "SCHULDNER"     # ein einziger Zugang, keine Benutzer- und keine Mandantenverwaltung
MODUS_BERATER = "BERATER"         # Schuldenberatung: Benutzer (Kolleg:innen) und Mandanten
MODI = (MODUS_SCHULDNER, MODUS_BERATER)
SCHULDNER_KONTO = "Schuldner"     # interner Benutzername im Schuldner-Modus (Anmeldung nur mit Passwort)

SCHEMA = """
CREATE TABLE IF NOT EXISTS einrichtung (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS benutzer (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, name_norm TEXT NOT NULL UNIQUE, pw_hash TEXT NOT NULL,
  rolle TEXT NOT NULL DEFAULT 'USER', aktiv INTEGER NOT NULL DEFAULT 1, ordner TEXT NOT NULL,
  erstellt TEXT, letzter_login TEXT, pw_geaendert TEXT);
"""

# ── Profil-Schlüssel umhüllen ─────────────────────────────────────────────────
_RK_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
FEHLER_RK = "Wiederherstellungsschlüssel falsch."


def _kek(geheim: bytes, salt: bytes) -> bytes:
    return hashlib.scrypt(geheim, salt=salt, n=_N, r=_R, p=_P, maxmem=64 * 1024 * 1024, dklen=32)


def _aad(uid: str, art: str) -> bytes:
    return f"financeflow-profil/1|{uid}|{art}".encode()


def huellen(key: bytes, geheim: bytes, uid: str, art: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    ct = AESGCM(_kek(geheim, salt)).encrypt(nonce, key, _aad(uid, art))
    return "v1$" + "$".join(base64.b64encode(x).decode() for x in (salt, nonce, ct))


def auspacken(gehuellt: str, geheim: bytes, uid: str, art: str) -> bytes | None:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        v, salt, nonce, ct = gehuellt.split("$")
        if v != "v1":
            return None
        salt, nonce, ct = (base64.b64decode(x) for x in (salt, nonce, ct))
        k = AESGCM(_kek(geheim, salt)).decrypt(nonce, ct, _aad(uid, art))
        return k if len(k) == 32 else None
    except (InvalidTag, ValueError, TypeError):
        return None


def neuer_rk() -> str:
    """Wiederherstellungsschlüssel: 160 Bit, Base32, 8 Gruppen à 4 Zeichen (ohne 0/1/8/9 – keine Verwechslung)."""
    t = base64.b32encode(secrets.token_bytes(20)).decode()
    return "-".join(t[i:i + 4] for i in range(0, 32, 4))


def rk_bytes(rk: str) -> bytes | None:
    t = "".join(c for c in (rk or "").upper() if c.isalnum()).replace("0", "O").replace("1", "I").replace("8", "B")
    if len(t) != 32 or any(c not in _RK_ALPHABET for c in t):
        return None
    return base64.b32decode(t)



class Konten:
    def __init__(self, basis: str):
        self.basis = basis
        os.makedirs(basis, exist_ok=True)
        self.path = os.path.join(basis, "benutzer.db")
        self.con = sqlite3.connect(self.path)
        self.con.row_factory = sqlite3.Row
        with self.con:
            self.con.executescript(SCHEMA)
            spalten = {r[1] for r in self.con.execute("PRAGMA table_info(benutzer)")}
            for sp in ("key_pw", "key_rk"):
                if sp not in spalten:
                    self.con.execute(f"ALTER TABLE benutzer ADD COLUMN {sp} TEXT")
        self.fehlversuche = 0

    def close(self):
        self.con.close()

    # ── Modus (Schuldner / Schuldenberater) ─────────────────────────────────
    def modus(self) -> str | None:
        r = self.con.execute("SELECT value FROM einrichtung WHERE key='modus'").fetchone()
        return r[0] if r and r[0] in MODI else None

    def ist_schuldner(self) -> bool:
        return self.modus() == MODUS_SCHULDNER

    def einrichtung(self, key: str, default: str = "") -> str:
        r = self.con.execute("SELECT value FROM einrichtung WHERE key=?", (key,)).fetchone()
        return r[0] if r and r[0] is not None else default

    def einrichtung_setzen(self, key: str, value: str):
        if key == "modus":
            raise KontoFehler("Der Modus wird nur bei der Ersteinrichtung festgelegt.")
        with self.con:
            self.con.execute("INSERT OR REPLACE INTO einrichtung (key, value) VALUES (?, ?)", (key, value))

    def _modus_setzen(self, modus: str):
        if modus not in MODI:
            raise KontoFehler("Unbekannter Modus.")
        with self.con:
            self.con.execute("INSERT OR REPLACE INTO einrichtung (key, value) VALUES ('modus', ?)", (modus,))

    def schuldner_einrichten(self, pw) -> dict:
        """Ersteinrichtung als Schuldner: ein Zugang (nur Passwort), der Datenbestand liegt im Basisordner."""
        pw_regel(pw)
        if not self.leer():
            raise KontoFehler("Das Programm ist bereits eingerichtet.")
        self._modus_setzen(MODUS_SCHULDNER)
        return self.admin_anlegen(SCHULDNER_KONTO, pw)

    def berater_einrichten(self, name, pw) -> dict:
        """Ersteinrichtung als Schuldenberatung: Administrator, danach Benutzer und Mandanten."""
        pw_regel(pw)
        if not self.leer():
            raise KontoFehler("Das Programm ist bereits eingerichtet.")
        self._modus_setzen(MODUS_BERATER)
        return self.admin_anlegen(name, pw)

    def schuldner_konto(self) -> dict | None:
        r = self.con.execute("SELECT * FROM benutzer WHERE rolle='ADMIN' ORDER BY erstellt LIMIT 1").fetchone()
        return dict(r) if r else None

    # ── Abfragen ────────────────────────────────────────────────────────────
    def leer(self) -> bool:
        return not self.con.execute("SELECT 1 FROM benutzer LIMIT 1").fetchone()

    def liste(self) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT id, name, rolle, aktiv, erstellt, letzter_login FROM benutzer ORDER BY rolle, name_norm")]

    def get(self, uid) -> dict | None:
        r = self.con.execute("SELECT * FROM benutzer WHERE id=?", (uid,)).fetchone()
        return dict(r) if r else None

    def profil_ordner(self, u: dict) -> str:
        d = self.basis if u["ordner"] in ("", ".") else os.path.join(self.basis, u["ordner"])
        os.makedirs(d, exist_ok=True)
        return d

    def db_pfad(self, u: dict) -> str:
        return os.path.join(self.profil_ordner(u), "daten.db")

    # ── Anmeldung ───────────────────────────────────────────────────────────
    def anmelden(self, name: str, pw: str) -> dict | None:
        """Gibt den Benutzer zurück oder None – ohne zu verraten, ob der Name existiert."""
        if self.fehlversuche >= 3:
            time.sleep(min(2 ** (self.fehlversuche - 3), 30))
        r = self.con.execute("SELECT * FROM benutzer WHERE name_norm=?", (_norm(name),)).fetchone()
        ok = pruefe_pw(pw or "", r["pw_hash"] if r else _DUMMY)
        if not (r and ok and r["aktiv"]):
            self.fehlversuche += 1
            return None
        self.fehlversuche = 0
        with self.con:
            self.con.execute("UPDATE benutzer SET letzter_login=? WHERE id=?", (_jetzt(), r["id"]))
        return self.get(r["id"])

    # ── Verwaltung ──────────────────────────────────────────────────────────
    def _sichern(self):
        d = os.path.join(self.basis, "Sicherungen", "Benutzer")
        os.makedirs(d, exist_ok=True)
        if os.path.exists(self.path) and not self.leer():
            ziel = sqlite3.connect(os.path.join(d, f"benutzer_{datetime.now():%Y-%m-%d_%H%M%S_%f}.db"))
            self.con.backup(ziel)
            ziel.close()
        alte = sorted(f for f in os.listdir(d) if f.endswith(".db"))
        for f in alte[:-30]:
            try:
                os.remove(os.path.join(d, f))
            except OSError:
                pass

    # ── Datenbankschlüssel ──────────────────────────────────────────────────
    def verschluesselt(self, u: dict) -> bool:
        r = self.get(u["id"])
        return bool(r and r["key_pw"])

    def schluessel(self, u: dict, pw: str) -> bytes | None:
        """Datenbankschlüssel des Profils mit dem Passwort öffnen (None: Profil hat noch keinen Schlüssel)."""
        r = self.get(u["id"])
        if not r or not r["key_pw"]:
            return None
        k = auspacken(r["key_pw"], (pw or "").encode("utf-8"), r["id"], "pw")
        if k is None:
            raise KontoFehler("Datenbankschlüssel lässt sich nicht öffnen (Passwort falsch?).")
        self._schluesseldatei(r)
        return k

    def schluessel_einrichten(self, u: dict, pw: str) -> tuple[bytes, str]:
        """Neuer Datenbankschlüssel für ein Profil ohne Schlüssel. Gibt (Schlüssel, Wiederherstellungsschlüssel) zurück."""
        r = self.get(u["id"])
        if not r or not pruefe_pw(pw or "", r["pw_hash"]):
            raise KontoFehler("Passwort falsch.")
        if r["key_pw"]:
            raise KontoFehler("Dieses Profil hat bereits einen Datenbankschlüssel.")
        key, rk = secrets.token_bytes(32), neuer_rk()
        self._sichern()
        with self.con:
            self.con.execute("UPDATE benutzer SET key_pw=?, key_rk=? WHERE id=?",
                             (huellen(key, pw.encode("utf-8"), r["id"], "pw"), huellen(key, rk_bytes(rk), r["id"], "rk"), r["id"]))
        self._schluesseldatei(self.get(r["id"]))
        return key, rk

    def neuer_wiederherstellungsschluessel(self, u: dict, pw: str) -> str:
        r = self.get(u["id"])
        if not r or not pruefe_pw(pw or "", r["pw_hash"]):
            raise KontoFehler("Das Passwort ist falsch.")
        key = self.schluessel(r, pw)
        if key is None:
            raise KontoFehler("Dieses Profil ist noch nicht verschlüsselt.")
        rk = neuer_rk()
        self._sichern()
        with self.con:
            self.con.execute("UPDATE benutzer SET key_rk=? WHERE id=?", (huellen(key, rk_bytes(rk), r["id"], "rk"), r["id"]))
        self._schluesseldatei(self.get(r["id"]))
        return rk

    def _mit_rk(self, r: dict, rk: str) -> bytes:
        b = rk_bytes(rk)
        k = auspacken(r["key_rk"] or "", b, r["id"], "rk") if b else None
        if k is None:
            raise KontoFehler(FEHLER_RK)
        return k

    def passwort_vergessen(self, name: str, rk: str, neu: str) -> dict:
        """Neues Passwort mit dem Wiederherstellungsschlüssel (Anmeldemaske). Meldung verrät nicht, ob der Name existiert."""
        pw_regel(neu)
        if self.fehlversuche >= 3:
            time.sleep(min(2 ** (self.fehlversuche - 3), 30))
        r = self.con.execute("SELECT * FROM benutzer WHERE name_norm=?", (_norm(name),)).fetchone()
        try:
            if not r or not r["aktiv"] or not r["key_rk"]:
                raise KontoFehler(FEHLER_RK)
            key = self._mit_rk(dict(r), rk)
        except KontoFehler:
            self.fehlversuche += 1
            raise KontoFehler("Benutzername oder Wiederherstellungsschlüssel ist falsch.") from None
        self.fehlversuche = 0
        self._pw_setzen(r["id"], neu, key)
        return self.get(r["id"])

    def schluesseldatei_pfad(self, u: dict) -> str:
        return os.path.join(self.profil_ordner(u), "schluessel.json")

    def _schluesseldatei(self, r: dict):
        """Kopie der umhüllten Schlüssel im Profilordner (nur verschlüsselt, ohne Passwort/Wiederherstellungsschlüssel
        wertlos) – damit das Profil auch ohne benutzer.db wiederhergestellt werden kann."""
        if not r or not r["key_pw"]:
            return
        inhalt = {"format": "financeflow-profilschluessel", "version": 1, "benutzer": r["id"], "name": r["name"],
                  "kdf": {"name": "scrypt", "n": _N, "r": _R, "p": _P}, "cipher": "AES-256-GCM",
                  "key_pw": r["key_pw"], "key_rk": r["key_rk"],
                  "hinweis": "Umhüllter SQLCipher-Schlüssel dieses Profils. Nicht löschen."}
        pfad = self.schluesseldatei_pfad(r)
        try:
            with open(pfad, encoding="utf-8") as f:
                if json.load(f) == inhalt:
                    return
        except (OSError, ValueError):
            pass
        tmp = pfad + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(inhalt, f, ensure_ascii=False, indent=1)
        os.replace(tmp, pfad)

    def _anlegen(self, name, pw, rolle, ordner) -> dict:
        name = (name or "").strip()
        if not name:
            raise KontoFehler("Benutzername fehlt.")
        if len(name) > 40:
            raise KontoFehler("Benutzername ist zu lang (höchstens 40 Zeichen).")
        pw_regel(pw)
        if self.con.execute("SELECT 1 FROM benutzer WHERE name_norm=?", (_norm(name),)).fetchone():
            raise KontoFehler("Dieser Benutzername ist bereits vergeben.")
        uid = secrets.token_hex(8)
        key, rk = secrets.token_bytes(32), neuer_rk()
        self._sichern()
        with self.con:
            self.con.execute("INSERT INTO benutzer (id, name, name_norm, pw_hash, rolle, aktiv, ordner, erstellt, pw_geaendert, "
                             "key_pw, key_rk) VALUES (?,?,?,?,?,1,?,?,?,?,?)",
                             (uid, name, _norm(name), hash_pw(pw), rolle, ordner(uid) if callable(ordner) else ordner,
                              _jetzt(), _jetzt(), huellen(key, pw.encode("utf-8"), uid, "pw"), huellen(key, rk_bytes(rk), uid, "rk")))
        u = self.get(uid)
        self._schluesseldatei(u)
        return {**u, "wiederherstellung": rk}

    def admin_anlegen(self, name, pw) -> dict:
        """Ersteinrichtung: Administrator übernimmt den bisherigen Datenbestand (daten.db im Basisordner)."""
        if not self.leer():
            raise KontoFehler("Es gibt bereits Benutzer.")
        return self._anlegen(name, pw, "ADMIN", "")

    def benutzer_anlegen(self, admin: dict, name, pw) -> dict:
        self._ist_admin(admin)
        if self.ist_schuldner():
            raise KontoFehler("Im Schuldner-Modus gibt es keine Benutzerverwaltung.")
        return self._anlegen(name, pw, "USER", lambda uid: os.path.join("profile", uid))

    def passwort_aendern(self, u: dict, alt, neu):
        r = self.get(u["id"])
        if not r or not pruefe_pw(alt or "", r["pw_hash"]):
            raise KontoFehler("Das bisherige Passwort ist falsch.")
        self._pw_setzen(u["id"], neu, self.schluessel(r, alt))

    def passwort_zuruecksetzen(self, admin: dict, uid, neu, rk: str | None = None):
        """Admin setzt ein Passwort neu. Bei verschlüsselten Profilen nur mit dem Wiederherstellungsschlüssel des Benutzers."""
        self._ist_admin(admin)
        r = self.get(uid)
        if not r:
            raise KontoFehler("Benutzer nicht gefunden.")
        key = self._mit_rk(r, rk) if r["key_pw"] else None
        self._pw_setzen(uid, neu, key)

    def _pw_setzen(self, uid, neu, key: bytes | None = None):
        pw_regel(neu)
        self._sichern()
        with self.con:
            self.con.execute("UPDATE benutzer SET pw_hash=?, pw_geaendert=? WHERE id=?", (hash_pw(neu), _jetzt(), uid))
            if key is not None:
                self.con.execute("UPDATE benutzer SET key_pw=? WHERE id=?", (huellen(key, neu.encode("utf-8"), uid, "pw"), uid))
        self._schluesseldatei(self.get(uid))

    def aktiv_setzen(self, admin: dict, uid, aktiv: bool):
        self._ist_admin(admin)
        u = self.get(uid)
        if not u:
            raise KontoFehler("Benutzer nicht gefunden.")
        if u["rolle"] == "ADMIN":
            raise KontoFehler("Der Administrator kann nicht deaktiviert werden.")
        self._sichern()
        with self.con:
            self.con.execute("UPDATE benutzer SET aktiv=? WHERE id=?", (1 if aktiv else 0, uid))

    def loeschen(self, admin: dict, uid) -> str:
        """Entfernt die Anmeldung. Der Datenordner wird nicht gelöscht, sondern nach
        „Gelöschte Profile“ verschoben (wiederherstellbar). Gibt den neuen Ordner zurück."""
        self._ist_admin(admin)
        u = self.get(uid)
        if not u:
            raise KontoFehler("Benutzer nicht gefunden.")
        if u["rolle"] == "ADMIN":
            raise KontoFehler("Der Administrator kann nicht gelöscht werden.")
        quelle = os.path.join(self.basis, u["ordner"])
        ziel = ""
        if os.path.isdir(quelle):
            d = os.path.join(self.basis, "Gelöschte Profile")
            os.makedirs(d, exist_ok=True)
            ziel = os.path.join(d, f"{datetime.now():%Y-%m-%d_%H%M%S}_{uid}")
            shutil.move(quelle, ziel)
        self._sichern()
        with self.con:
            self.con.execute("DELETE FROM benutzer WHERE id=?", (uid,))
        return ziel

    def _ist_admin(self, admin):
        r = self.get(admin["id"]) if admin else None
        if not r or r["rolle"] != "ADMIN" or not r["aktiv"]:
            raise KontoFehler("Nur der Administrator darf Benutzer verwalten.")


def _jetzt():
    return datetime.now().isoformat(timespec="seconds")
