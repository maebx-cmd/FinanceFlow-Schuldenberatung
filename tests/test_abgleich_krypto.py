"""Abgleich-Datei *.ffsync: Testvektor (muss in EXE, APK und iOS exakt gleich herauskommen)."""
import base64
import json

import pytest

from app.abgleich import krypto as k

PASSWORT = "Test-Passwort 123"
SALT = bytes(range(0x00, 0x10))
NONCE = bytes(range(0x64, 0x70))
KLARTEXT = b'{"hallo":"welt","betrag":"241.94"}'
DATA = "ITa9cyty+9EMjOCd1gp9gpQpxfLmV75p9/1DmHWfO9g7+Jy7m7B2jNzCsZqU9RCT5uk="


@pytest.fixture(scope="module")
def vektor():
    return k.verschluesseln(KLARTEXT, PASSWORT, salt=SALT, nonce=NONCE)


def test_schluessel():
    assert k.schluessel(PASSWORT, SALT).hex() == "bf30a34136d2aa901a886beed01e182eda1adc67ddaf5a1daa24cf9bb5dbc540"


def test_testvektor(vektor):
    assert vektor == {"format": "financeflow-sync", "version": 1,
                      "kdf": {"name": "PBKDF2-HMAC-SHA256", "iterations": 600000, "salt": "AAECAwQFBgcICQoLDA0ODw=="},
                      "cipher": {"name": "AES-256-GCM", "nonce": "ZGVmZ2hpamtsbW5v"},
                      "data": DATA}
    assert k.entschluesseln(vektor, PASSWORT) == KLARTEXT


def test_veraendertes_byte_scheitert(vektor):
    roh = bytearray(base64.b64decode(DATA))
    for i in (0, len(roh) // 2, len(roh) - 1):          # Ciphertext Anfang/Mitte, Tag
        kaputt = bytearray(roh)
        kaputt[i] ^= 0x01
        with pytest.raises(k.AbgleichFehler, match="Passwort falsch oder Datei beschädigt"):
            k.entschluesseln({**vektor, "data": base64.b64encode(bytes(kaputt)).decode()}, PASSWORT)
    s = bytearray(SALT)
    s[0] ^= 1
    with pytest.raises(k.AbgleichFehler, match="Passwort falsch"):
        k.entschluesseln({**vektor, "kdf": {**vektor["kdf"], "salt": base64.b64encode(bytes(s)).decode()}}, PASSWORT)


def test_falsches_passwort(vektor):
    with pytest.raises(k.AbgleichFehler, match="Passwort falsch oder Datei beschädigt"):
        k.entschluesseln(vektor, "Test-Passwort 124")


def test_zufaellige_salt_und_nonce():
    a, b = k.verschluesseln(KLARTEXT, PASSWORT), k.verschluesseln(KLARTEXT, PASSWORT)
    assert a["kdf"]["salt"] != b["kdf"]["salt"] and a["cipher"]["nonce"] != b["cipher"]["nonce"]
    assert len(base64.b64decode(a["kdf"]["salt"])) == 16 and len(base64.b64decode(a["cipher"]["nonce"])) == 12


def test_format_und_version(vektor):
    with pytest.raises(k.AbgleichFehler, match="Keine FinanceFlow"):
        k.entschluesseln({**vektor, "format": "x"}, PASSWORT)
    with pytest.raises(k.AbgleichFehler, match="Bitte App aktualisieren"):
        k.entschluesseln({**vektor, "version": 2}, PASSWORT)


def test_datei(tmp_path):
    p = str(tmp_path / "x.ffsync")
    k.datei_schreiben(p, KLARTEXT, PASSWORT)
    obj = json.load(open(p, encoding="utf-8"))
    assert obj["format"] == "financeflow-sync" and k.datei_lesen(p, PASSWORT) == KLARTEXT
