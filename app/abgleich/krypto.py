"""Verschlüsselte Abgleich-Datei *.ffsync – identisch in EXE, APK und iOS.

Datei (JSON):
  {"format": "financeflow-sync", "version": 1,
   "kdf":    {"name": "PBKDF2-HMAC-SHA256", "iterations": 600000, "salt": "<Base64, 16 Bytes>"},
   "cipher": {"name": "AES-256-GCM", "nonce": "<Base64, 12 Bytes>"},
   "data":   "<Base64 von Ciphertext||Tag (16 Byte)>"}
Schlüssel = PBKDF2-HMAC-SHA256(Passwort UTF-8, salt, 600000, 32 Byte); AAD = „financeflow-sync/1“.
Salt und Nonce werden bei jedem Export neu zufällig erzeugt.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

FORMAT = "financeflow-sync"
VERSION = 1
KDF = "PBKDF2-HMAC-SHA256"
CIPHER = "AES-256-GCM"
ITERATIONEN = 600_000
AAD = b"financeflow-sync/1"
MIN_PASSWORT = 12

FEHLER_PASSWORT = "Passwort falsch oder Datei beschädigt"


class AbgleichFehler(ValueError):
    pass


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _unb64(s, feld) -> bytes:
    try:
        return base64.b64decode(str(s), validate=True)
    except Exception as e:  # noqa: BLE001
        raise AbgleichFehler(f"Keine gültige Abgleich-Datei ({feld} beschädigt).") from e


def schluessel(passwort: str, salt: bytes, iterationen: int = ITERATIONEN) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", passwort.encode("utf-8"), salt, iterationen, 32)


def verschluesseln(klartext: bytes, passwort: str, *, salt: bytes | None = None, nonce: bytes | None = None) -> dict:
    """Liefert das Datei-Objekt. salt/nonce nur für Testvektoren vorgeben – sonst immer zufällig."""
    salt = salt if salt is not None else os.urandom(16)
    nonce = nonce if nonce is not None else os.urandom(12)
    if len(salt) != 16 or len(nonce) != 12:
        raise AbgleichFehler("Salt muss 16 und Nonce 12 Bytes lang sein.")
    daten = AESGCM(schluessel(passwort, salt)).encrypt(nonce, klartext, AAD)
    return {"format": FORMAT, "version": VERSION,
            "kdf": {"name": KDF, "iterations": ITERATIONEN, "salt": _b64(salt)},
            "cipher": {"name": CIPHER, "nonce": _b64(nonce)},
            "data": _b64(daten)}


def entschluesseln(datei: dict, passwort: str) -> bytes:
    if not isinstance(datei, dict) or datei.get("format") != FORMAT:
        raise AbgleichFehler("Keine FinanceFlow-Abgleichdatei.")
    if not isinstance(datei.get("version"), int) or datei["version"] > VERSION:
        raise AbgleichFehler("Die Datei stammt aus einer neueren App-Version. Bitte App aktualisieren.")
    kdf, cipher = datei.get("kdf") or {}, datei.get("cipher") or {}
    if kdf.get("name") != KDF or cipher.get("name") != CIPHER:
        raise AbgleichFehler("Unbekanntes Verschlüsselungsverfahren. Bitte App aktualisieren.")
    it = kdf.get("iterations")
    if not isinstance(it, int) or not 100_000 <= it <= 10_000_000:
        raise AbgleichFehler("Keine gültige Abgleich-Datei (Iterationen).")
    salt, nonce, daten = _unb64(kdf.get("salt"), "salt"), _unb64(cipher.get("nonce"), "nonce"), _unb64(datei.get("data"), "data")
    if len(salt) != 16 or len(nonce) != 12 or len(daten) < 16:
        raise AbgleichFehler(FEHLER_PASSWORT)
    try:
        return AESGCM(schluessel(passwort, salt, it)).decrypt(nonce, daten, AAD)
    except InvalidTag as e:
        raise AbgleichFehler(FEHLER_PASSWORT) from e


def datei_schreiben(pfad: str, klartext: bytes, passwort: str):
    """Schreibt atomar (temporäre Datei + Umbenennen)."""
    obj = verschluesseln(klartext, passwort)
    tmp = pfad + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, pfad)


def datei_lesen(pfad: str, passwort: str) -> bytes:
    try:
        with open(pfad, encoding="utf-8") as f:
            obj = json.load(f)
    except (OSError, ValueError) as e:
        raise AbgleichFehler(f"Datei kann nicht gelesen werden: {e}") from e
    return entschluesseln(obj, passwort)
