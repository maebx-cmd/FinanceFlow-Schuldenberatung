"""Verschlüsselte Datenbanken (ab 2.0.0): Profil-Schlüssel, Wiederherstellungsschlüssel, Umstellung alter Profile."""
import json
import os
import sqlite3 as std

import pytest

from app import profilschutz, sqldb
from app.db import DB
from app.konten import Konten, KontoFehler, rk_bytes
from tests.demo_data import befuellen

GEHEIM = "Zahnarzt Dr. Geheimnis"


def _klartext_im(pfad, text=GEHEIM) -> bool:
    return text.encode() in open(pfad, "rb").read()


def test_neuer_benutzer_hat_schluessel(tmp_path):
    k = Konten(str(tmp_path))
    a = k.admin_anlegen("admin", "admin-pw-1")
    rk = a["wiederherstellung"]
    assert len(rk) == 39 and rk.count("-") == 7 and rk_bytes(rk) and len(rk_bytes(rk)) == 20
    key = k.schluessel(a, "admin-pw-1")
    assert len(key) == 32
    assert key.hex() not in open(k.path, "rb").read().decode("latin-1")          # nie im Klartext gespeichert
    sj = json.load(open(k.schluesseldatei_pfad(a), encoding="utf-8"))
    assert sj["format"] == "financeflow-profilschluessel" and sj["key_pw"].startswith("v1$") and key.hex() not in str(sj)
    with pytest.raises(KontoFehler):
        k.schluessel(a, "falsch-falsch")
    anna = k.benutzer_anlegen(a, "Anna", "anna-pw-1")
    assert anna["wiederherstellung"] != rk and k.schluessel(anna, "anna-pw-1") != key


def test_datenbank_verschluesselt_und_sicherungen(tmp_path):
    key = os.urandom(32)
    db = DB(str(tmp_path / "daten.db"), key=key)
    befuellen(db)
    db.insert("contact", {"name": GEHEIM, "role": "KREDITOR"})
    s1 = db.auto_backup("test")
    db.con.commit()
    for p in (db.path, s1):
        assert not sqldb.ist_klartext(p) and not _klartext_im(p), p
    c = sqldb.connect(s1, key)
    assert c.execute("SELECT count(*) FROM contact WHERE name=?", (GEHEIM,)).fetchone()[0] == 1
    with pytest.raises(sqldb.SchluesselFehler):
        sqldb.connect(s1, os.urandom(32))
    with pytest.raises(sqldb.SchluesselFehler, match="verschlüsselt"):
        DB(db.path)
    with pytest.raises(std.DatabaseError):
        std.connect(db.path).execute("SELECT * FROM contact").fetchall()


def test_passwort_aendern_und_vergessen(tmp_path):
    k = Konten(str(tmp_path))
    a = k.admin_anlegen("admin", "admin-pw-1")
    key = k.schluessel(a, "admin-pw-1")
    k.passwort_aendern(a, "admin-pw-1", "neues-pw-2")
    assert k.schluessel(a, "neues-pw-2") == key
    with pytest.raises(KontoFehler):
        k.schluessel(a, "admin-pw-1")
    # vergessen: mit Wiederherstellungsschlüssel (Schreibweise egal: klein, ohne Striche, 0 statt O)
    rk = a["wiederherstellung"].lower().replace("-", "").replace("o", "0")
    k.passwort_vergessen("ADMIN", rk, "drittes-pw-3")
    assert k.anmelden("admin", "drittes-pw-3") and k.schluessel(a, "drittes-pw-3") == key
    with pytest.raises(KontoFehler, match="Benutzername oder Wiederherstellungsschlüssel ist falsch"):
        k.passwort_vergessen("admin", "AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA", "viertes-pw-4")
    with pytest.raises(KontoFehler, match="Benutzername oder Wiederherstellungsschlüssel ist falsch"):
        k.passwort_vergessen("gibtsnicht", a["wiederherstellung"], "viertes-pw-4")
    assert k.anmelden("admin", "drittes-pw-3")


def test_admin_braucht_wiederherstellungsschluessel(tmp_path):
    k = Konten(str(tmp_path))
    a = k.admin_anlegen("admin", "admin-pw-1")
    anna = k.benutzer_anlegen(a, "Anna", "anna-pw-1")
    key = k.schluessel(anna, "anna-pw-1")
    with pytest.raises(KontoFehler, match="Wiederherstellungsschlüssel falsch"):
        k.passwort_zuruecksetzen(a, anna["id"], "neu-pw-123")
    with pytest.raises(KontoFehler, match="Wiederherstellungsschlüssel falsch"):
        k.passwort_zuruecksetzen(a, anna["id"], "neu-pw-123", a["wiederherstellung"])   # fremder Schlüssel
    assert k.anmelden("anna", "anna-pw-1")
    k.passwort_zuruecksetzen(a, anna["id"], "neu-pw-123", anna["wiederherstellung"])
    assert k.schluessel(anna, "neu-pw-123") == key


def test_neuer_wiederherstellungsschluessel(tmp_path):
    k = Konten(str(tmp_path))
    a = k.admin_anlegen("admin", "admin-pw-1")
    alt = a["wiederherstellung"]
    neu = k.neuer_wiederherstellungsschluessel(a, "admin-pw-1")
    assert neu != alt
    with pytest.raises(KontoFehler):
        k.passwort_vergessen("admin", alt, "x-pw-12345")
    k.passwort_vergessen("admin", neu, "x-pw-12345")
    with pytest.raises(KontoFehler, match="Passwort ist falsch"):
        k.neuer_wiederherstellungsschluessel(a, "falsch-falsch")


def _altes_profil(tmp_path):
    """Stand wie vor 2.0.0: benutzer.db ohne Schlüsselspalten, unverschlüsselte daten.db/mobil.db/Sicherungen."""
    k = Konten(str(tmp_path))
    a = k.admin_anlegen("admin", "admin-pw-1")
    with k.con:
        k.con.execute("UPDATE benutzer SET key_pw=NULL, key_rk=NULL")
    os.remove(k.schluesseldatei_pfad(a))
    db = DB(k.db_pfad(a))
    befuellen(db)
    db.insert("contact", {"name": GEHEIM, "role": "KREDITOR"})
    db.auto_backup("alt")
    vorher = {t: db.rows(f"SELECT * FROM {t} ORDER BY rowid") for t in ("contact", "liability", "liability_correction")}
    db.con.close()
    return k, k.get(a["id"]), vorher, None


def test_umstellung_altes_profil(tmp_path):
    k, a, vorher, _ = _altes_profil(tmp_path)
    ordner = k.profil_ordner(a)
    offen = profilschutz.offen(ordner)
    assert len(offen) >= 2 and all(sqldb.ist_klartext(p) for p in offen)
    assert k.schluessel(a, "admin-pw-1") is None
    key, rk = k.schluessel_einrichten(a, "admin-pw-1")
    with pytest.raises(KontoFehler, match="bereits"):
        k.schluessel_einrichten(a, "admin-pw-1")
    fertig = profilschutz.verschluesseln(ordner, key)
    assert sorted(fertig) == sorted(offen) and profilschutz.offen(ordner) == []
    for p in fertig:
        assert not _klartext_im(p), p
    assert not any(f.endswith((".tmp", "-wal")) for f in os.listdir(ordner))
    db = DB(k.db_pfad(a), key=key)
    assert {t: db.rows(f"SELECT * FROM {t} ORDER BY rowid") for t in vorher} == vorher
    assert db.val("SELECT count(*) FROM sqlite_master WHERE type='trigger'") > 5      # Abgleich-Trigger mit umgezogen
    assert db.integritaet() == "ok" and k.schluessel(a, "admin-pw-1") == key
    assert profilschutz.verschluesseln(ordner, key) == []                                # zweiter Lauf: nichts zu tun


def test_umstellung_nach_abbruch_fortsetzen(tmp_path, monkeypatch):
    k, a, vorher, _ = _altes_profil(tmp_path)
    ordner = k.profil_ordner(a)
    key, _rk = k.schluessel_einrichten(a, "admin-pw-1")
    echt, n = sqldb.verschluesseln, []

    def bricht_ab(p, kk):
        if n:
            raise OSError("Stromausfall")
        n.append(p)
        return echt(p, kk)
    monkeypatch.setattr(sqldb, "verschluesseln", bricht_ab)
    with pytest.raises(OSError):
        profilschutz.verschluesseln(ordner, key)
    monkeypatch.setattr(sqldb, "verschluesseln", echt)
    assert profilschutz.offen(ordner)                                  # Rest noch offen, Originale unverändert lesbar
    profilschutz.verschluesseln(ordner, key)
    assert profilschutz.offen(ordner) == []
    db = DB(k.db_pfad(a), key=key)
    assert {t: db.rows(f"SELECT * FROM {t} ORDER BY rowid") for t in vorher} == vorher


def test_kopie_wird_vor_dem_ersetzen_geprueft(tmp_path, monkeypatch):
    p = str(tmp_path / "x.db")
    c = std.connect(p)
    c.executescript("CREATE TABLE t(a); INSERT INTO t VALUES (1),(2);")
    c.close()
    roh = open(p, "rb").read()
    monkeypatch.setattr(sqldb, "_zaehlen", lambda c, _z=iter([{"t": 2}, {"t": 1}]): next(_z))
    with pytest.raises(sqldb.DatabaseError, match="weicht ab"):
        sqldb.verschluesseln(p, os.urandom(32))
    assert open(p, "rb").read() == roh


def test_alte_benutzer_db_bekommt_spalten(tmp_path):
    c = std.connect(str(tmp_path / "benutzer.db"))
    c.executescript("CREATE TABLE benutzer (id TEXT PRIMARY KEY, name TEXT NOT NULL, name_norm TEXT NOT NULL UNIQUE, "
                    "pw_hash TEXT NOT NULL, rolle TEXT NOT NULL DEFAULT 'USER', aktiv INTEGER NOT NULL DEFAULT 1, "
                    "ordner TEXT NOT NULL, erstellt TEXT, letzter_login TEXT, pw_geaendert TEXT);")
    c.close()
    k = Konten(str(tmp_path))
    assert {"key_pw", "key_rk"} <= {r[1] for r in k.con.execute("PRAGMA table_info(benutzer)")}


def test_testvektor_schluesselhuelle():
    """Gleicher Testvektor in EXE, APK und iOS (siehe Prompt / README)."""
    import base64
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from app.konten import _aad, _kek, auspacken
    key, uid = bytes(range(32)), "0123456789abcdef"
    salt, nonce = bytes(range(0x10, 0x20)), bytes(range(0x20, 0x2C))
    assert _kek(b"Test-Passwort 123", salt).hex() == "ec24246c4f56d18b90e98e66e6603266badcf5eb77701fe9d3da0035cd1daf20"
    w = "v1$" + "$".join(base64.b64encode(x).decode() for x in
                         (salt, nonce, AESGCM(_kek(b"Test-Passwort 123", salt)).encrypt(nonce, key, _aad(uid, "pw"))))
    assert w == "v1$EBESExQVFhcYGRobHB0eHw==$ICEiIyQlJicoKSor$KWivGKs/+DTmoGrGS+WzXe4xMRJwmoGAMpw62b4LQ4aGyG0HxT5EcevyG9Ei/rKV"
    assert auspacken(w, b"Test-Passwort 123", uid, "pw") == key and auspacken(w, b"Test-Passwort 124", uid, "pw") is None
    assert auspacken(w, b"Test-Passwort 123", uid, "rk") is None                     # AAD bindet Art und Benutzer
    rk = "IBAU-EQ2E-IVDE-OSCJ-JJFU-YTKO-J5IF-CUST"
    assert rk_bytes(rk) == bytes(range(0x40, 0x54)) == rk_bytes("ibaueq2eivde0scjjjfuytk0j5ifcust")
    w2 = "v1$EBESExQVFhcYGRobHB0eHw==$ICEiIyQlJicoKSor$IDsnQff2IEmoyt1BF8e7SBYfieR+Diw7sFPGmHNlW60d3rA50mdvtG/FcYGJsUfh"
    assert auspacken(w2, rk_bytes(rk), uid, "rk") == key
