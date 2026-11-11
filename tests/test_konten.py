import os

import pytest

from app import importer
from app.db import DB
from app.konten import KontoFehler, Konten
from tests.demo_data import befuellen


def test_anmeldung_und_trennung(tmp_path):
    k = Konten(str(tmp_path))
    assert k.leer()
    admin = k.admin_anlegen("admin", "geheim123")
    assert admin["rolle"] == "ADMIN" and k.db_pfad(admin) == os.path.join(str(tmp_path), "daten.db")
    with pytest.raises(KontoFehler):
        k.admin_anlegen("zweiter", "geheim123")           # nur bei leerer Benutzertabelle

    # Anmeldung: richtiges Passwort, falsches Passwort, unbekannter Name → identisches Ergebnis (None)
    assert k.anmelden("ADMIN", "geheim123")["id"] == admin["id"]   # Groß/Klein egal
    k.fehlversuche = 0
    assert k.anmelden("admin", "falsch") is None
    assert k.anmelden("gibtsnicht", "geheim123") is None
    k.fehlversuche = 0

    # Benutzer anlegen: nur Admin, Mindestlänge, eindeutiger Name, eigener Ordner mit Zufalls-ID
    with pytest.raises(KontoFehler):
        k.benutzer_anlegen(admin, "anna", "kurz")
    anna = k.benutzer_anlegen(admin, "Anna", "passwort1")
    with pytest.raises(KontoFehler):
        k.benutzer_anlegen(admin, "anna", "passwort2")
    with pytest.raises(KontoFehler):
        k.benutzer_anlegen(anna, "bert", "passwort2")       # kein Admin
    assert "anna" not in k.db_pfad(anna).lower() and k.db_pfad(anna) != k.db_pfad(admin)

    # Datenstände sind getrennt
    da = DB(k.db_pfad(admin), key=k.schluessel(admin, "geheim123")); befuellen(da)
    dn = DB(k.db_pfad(anna), key=k.schluessel(anna, "passwort1"))
    assert da.val("SELECT COUNT(*) FROM liability") > 0 and dn.val("SELECT COUNT(*) FROM liability") == 0
    assert da.backup_ordner() != dn.backup_ordner()

    # Passwort ändern / zurücksetzen, Deaktivieren sperrt die Anmeldung
    with pytest.raises(KontoFehler):
        k.passwort_aendern(anna, "falsch", "neuesPasswort")
    k.passwort_aendern(anna, "passwort1", "neuesPasswort")
    assert k.anmelden("anna", "neuesPasswort")
    k.passwort_zuruecksetzen(admin, anna["id"], "vomAdmin1", anna["wiederherstellung"])
    assert k.anmelden("anna", "vomAdmin1")
    k.aktiv_setzen(admin, anna["id"], False)
    k.fehlversuche = 0
    assert k.anmelden("anna", "vomAdmin1") is None
    with pytest.raises(KontoFehler):
        k.aktiv_setzen(admin, admin["id"], False)

    # Löschen verschiebt den Datenordner (nichts geht verloren)
    dn.con.close()
    ziel = k.loeschen(admin, anna["id"])
    assert os.path.exists(os.path.join(ziel, "daten.db")) and k.get(anna["id"]) is None
    assert "geheim123" not in open(k.path, "rb").read().decode("latin-1")   # nur Hash gespeichert


def test_export_import_rundlauf_verschluesselt(tmp_path):
    """Datenstand in ein anderes Profil: nur noch verschlüsselt (*.ffsync)."""
    from app.abgleich import abgleich as ab
    for x in "ab":
        (tmp_path / x).mkdir()
    a = DB(str(tmp_path / "a" / "daten.db")); befuellen(a)
    p = str(tmp_path / "x.ffsync")
    ab.exportieren(a, p, "ein langes Passwort", "Laptop")
    assert b"Teststra" not in open(p, "rb").read() and b"liability" not in open(p, "rb").read().lower()
    b = DB(str(tmp_path / "b" / "daten.db"))
    ab.importieren(b, ab.lesen(p, "ein langes Passwort"))
    from app.schema import TABLES
    for m in importer.ORDER:
        t = TABLES[m]
        assert a.rows(f"SELECT * FROM {t} ORDER BY id") == b.rows(f"SELECT * FROM {t} ORDER BY id"), m


def test_profil_oeffnen_ueberschreibt_keine_db_methoden(tmp_path):
    """Regression 1.2.0: Benutzerverwaltung darf keine DB-Methoden überschreiben."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.main import _profil_oeffnen
    k = Konten(str(tmp_path))
    admin = k.admin_anlegen("admin", "geheim123")
    db, lock = _profil_oeffnen(k, admin, "geheim123")
    assert db.key == k.schluessel(admin, "geheim123") and not __import__("app.sqldb").sqldb.ist_klartext(db.path)
    befuellen(db)
    assert len(db.verbindlichkeiten()) > 0
    assert db.benutzerverwaltung is k and db.benutzer["id"] == admin["id"]
    db.con.close()
    lock.unlock()
