"""Schuldenberatungs-Ausgabe: Modus Schuldner/Berater, Mandantenverwaltung, Einspielen der Schuldner-Datei, Oberfläche."""
import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from app import sqldb  # noqa: E402
from app.abgleich import abgleich as ab  # noqa: E402
from app.konten import MODUS_BERATER, MODUS_SCHULDNER, SCHULDNER_KONTO, Konten, KontoFehler  # noqa: E402
from app.mandanten import MandantFehler, Mandanten, mandant_schluessel  # noqa: E402
from tests.demo_data import befuellen  # noqa: E402

APP = QApplication.instance() or QApplication([])
PW = "Datei-Passwort 2026"


@pytest.fixture(autouse=True)
def _fenster_aufraeumen():
    """Übrig gebliebene Fenster/Dialoge noch zu Lebzeiten der QApplication löschen (sonst Absturz beim Beenden)."""
    yield
    from PySide6.QtCore import QEvent
    for w in APP.topLevelWidgets():
        w.close()
        w.deleteLater()
    APP.sendPostedEvents(None, QEvent.DeferredDelete)
    APP.processEvents()


# ── Modus ─────────────────────────────────────────────────────────────────────
def test_schuldner_modus_ein_zugang_ohne_benutzerverwaltung(tmp_path):
    k = Konten(str(tmp_path))
    assert k.modus() is None and k.leer()
    with pytest.raises(KontoFehler, match="mindestens 8"):
        k.schuldner_einrichten("kurz")
    assert k.leer() and k.modus() is None                     # nichts halb eingerichtet
    u = k.schuldner_einrichten("mein-passwort")
    assert k.modus() == MODUS_SCHULDNER and k.ist_schuldner() and u["name"] == SCHULDNER_KONTO and u["wiederherstellung"]
    assert k.anmelden(SCHULDNER_KONTO, "mein-passwort")["id"] == u["id"]
    assert k.db_pfad(u) == os.path.join(str(tmp_path), "daten.db")
    with pytest.raises(KontoFehler, match="keine Benutzerverwaltung"):
        k.benutzer_anlegen(u, "Zweiter", "zweiter-pw-1")
    with pytest.raises(KontoFehler, match="bereits eingerichtet"):
        k.berater_einrichten("admin", "admin-pw-123")
    with pytest.raises(KontoFehler, match="Ersteinrichtung"):
        k.einrichtung_setzen("modus", MODUS_BERATER)
    k.einrichtung_setzen("anzeigename", "Maria Muster")
    assert Konten(str(tmp_path)).einrichtung("anzeigename") == "Maria Muster"


def test_berater_modus_mit_benutzern(tmp_path):
    k = Konten(str(tmp_path))
    a = k.berater_einrichten("admin", "admin-pw-1")
    assert k.modus() == MODUS_BERATER and not k.ist_schuldner()
    anna = k.benutzer_anlegen(a, "Anna", "anna-pw-1")
    assert anna["rolle"] == "USER" and k.profil_ordner(anna) != k.profil_ordner(a)


# ── Mandanten ─────────────────────────────────────────────────────────────────
def _verw(tmp_path, name="beratung"):
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    return Mandanten(str(d), os.urandom(32), "admin")


def test_mandanten_anlegen_verschluesselt_getrennt(tmp_path):
    v = _verw(tmp_path)
    with pytest.raises(MandantFehler, match="Name"):
        v.anlegen({"name": " "})
    m1 = v.anlegen({"name": "Maria Muster", "aktenzeichen": "SB-2026-001", "geburtsdatum": "1990-05-04"})
    m2 = v.anlegen({"name": "Franz Huber"})
    assert [m["name"] for m in v.liste()] == ["Franz Huber", "Maria Muster"]
    assert v.liste(suche="sb-2026") == [v.get(m1["id"])]
    db = v.oeffnen(m1["id"])
    assert db.setting("owner_name") == "Maria Muster" and db.mandant["id"] == m1["id"]
    assert not ab.status(db)["finanzen"]["geaendert"]           # neuer Mandant gilt nicht als geändert
    db.kontakt_speichern({"name": "Geheimbank AG"})
    db.con.close()
    pfad = v.db_pfad(m1["id"])
    assert not sqldb.ist_klartext(pfad) and b"Geheimbank" not in open(pfad, "rb").read()
    assert not sqldb.ist_klartext(v.path) and b"Maria" not in open(v.path, "rb").read()
    assert v.schluessel(m1["id"]) != v.schluessel(m2["id"]) != v.key
    with pytest.raises(sqldb.SchluesselFehler):
        sqldb.connect(pfad, v.schluessel(m2["id"]))
    with pytest.raises(sqldb.SchluesselFehler):
        sqldb.connect(pfad, v.key)
    assert mandant_schluessel(v.key, m1["id"]) == v.schluessel(m1["id"])
    with pytest.raises(MandantFehler):
        v.ordner_von("../profile")


def test_mandant_archivieren_loeschen_protokoll(tmp_path):
    v = _verw(tmp_path)
    m = v.anlegen({"name": "Maria Muster"})
    v.oeffnen(m["id"]).con.close()
    v.aendern(m["id"], {"name": "Maria Muster-Huber", "notiz": "Termin 12.11."})
    v.archivieren(m["id"])
    assert v.liste() == [] and v.liste(archiv=True)[0]["name"] == "Maria Muster-Huber"
    assert v.anzahl() == {"ARCHIV": 1}
    v.archivieren(m["id"], False)
    ziel = v.loeschen(m["id"])
    assert os.path.exists(os.path.join(ziel, "daten.db")) and "Gelöschte Mandanten" in ziel
    assert v.liste() == [] and [p["aktion"] for p in v.protokoll(m["id"])][:2] == ["GELOESCHT", "REAKTIVIERT"]


def test_schuldner_datei_beim_mandanten_einspielen_und_zurueck(tmp_path):
    """Kernablauf: Schuldner erfasst auf eigenem Gerät → Datei → Beratung spielt sie beim Mandanten ein → Datei zurück."""
    from tests.schluessel import TEST_KEY
    from app.db import DB
    (tmp_path / "schuldner").mkdir()
    s = DB(str(tmp_path / "schuldner" / "daten.db"), key=TEST_KEY)
    befuellen(s)
    s.set_setting("owner_name", "Maria Muster")
    datei = str(tmp_path / "maria.ffsync")
    ab.exportieren(s, datei, PW, "Marias-Laptop")
    assert s.geraet_einstellung("export_erstellt") == "1"

    v = _verw(tmp_path)
    nutz = ab.lesen(datei, PW)
    i = ab.info(nutz)
    assert i["name"] == "Maria Muster" and i["glaeubiger"] == 6 and i["verbindlichkeiten"] == 5
    m = v.anlegen({"name": i["name"]})
    db = v.oeffnen(m["id"])
    db.mandanten_verwaltung = v
    ab.importieren(db, nutz)                                    # ohne Konfliktwarnung (neuer Mandant)
    v.vermerken(m["id"], "Import", nutz["device"], nutz["exportedAt"], datei)
    assert db.val("SELECT count(*) FROM liability") == s.val("SELECT count(*) FROM liability")
    # Berater ändert etwas → Merker gesetzt → zweites Einspielen nur mit Bestätigung
    db.kontakt_speichern({"name": "Nachtrag Beratung"})
    with pytest.raises(ab.Konflikt):
        ab.importieren(db, nutz)
    zurueck = str(tmp_path / "zurueck.ffsync")
    ab.exportieren(db, zurueck, PW, "Schuldenberatung")
    v.vermerken(m["id"], "Export", "Schuldenberatung", datei=zurueck)
    db.con.close()
    x = v.get(m["id"])
    assert x["import_geraet"] == "Marias-Laptop" and x["import_stand"] == nutz["exportedAt"] and x["letzter_export"]
    # Schuldner spielt die Antwort ein (er hat seit seinem Export nichts geändert)
    ab.importieren(s, ab.lesen(zurueck, PW))
    assert s.val("SELECT count(*) FROM contact WHERE name='Nachtrag Beratung'") == 1


# ── Oberfläche ────────────────────────────────────────────────────────────────
def _fenster(db):
    from app.ui import diskret
    from app.ui.bereiche import BereichsFenster
    from app.ui.navigation import BEREICHE
    diskret.umschalten(False)
    w = BereichsFenster(db, BEREICHE)
    w.resize(1440, 900)
    w.show()
    APP.processEvents()
    return w


def test_navigation_ohne_gestrichene_module():
    from app.ui.navigation import BEREICHE
    assert [b[0] for b in BEREICHE] == ["finance"]
    keys = [e[0] for e in BEREICHE[0][2] if e]
    assert keys.index("kontakte") < keys.index("verbindlichkeiten")          # erst Gläubiger, dann Schulden
    assert not [k for k in keys if re.match(r"(hr_|av_|mobil|devisen|tankbuch)", k)]
    basis = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app")
    for wurzel, _d, dateien in os.walk(basis):
        for f in dateien:
            if f.endswith(".py"):
                text = open(os.path.join(wurzel, f), encoding="utf-8").read()
                assert not re.search(r"from \S*(mobil|aviation|calc\.hr|bcbp|bp_druck|drucker)\b import|import (hr|aviation)\b",
                                     text), f


def test_schuldner_oberflaeche(db, monkeypatch):
    db.modus = MODUS_SCHULDNER
    db.set_geraet_einstellung("einfuehrung_gesehen", "1")      # automatische Einführung im Test unterdrücken
    w = _fenster(db)
    try:
        l = w.launcher
        assert {"aktion:einfuehrung", "aktion:hilfe_schuldner"} <= set(l.kacheln) and "aktion:mandanten" not in l.kacheln
        assert [z.text() for z in l.schritte.values()] == ["○", "○", "○"]
        texte = " ".join(x.text() for x in l.findChildren(QLabel))
        assert not re.search(r"\d", texte)                    # Start bleibt ohne Zahlen
        befuellen(db)
        l.refresh()
        assert [z.text() for z in l.schritte.values()] == ["✓", "✓", "○"]
        # Einführung: „Jetzt ersten Gläubiger anlegen“ öffnet Kontakte mit neuem, leerem Kontakt (Rolle Gläubiger)
        from app.ui import einfuehrung
        monkeypatch.setattr(einfuehrung.EinfuehrungDialog, "exec", lambda self: setattr(self, "ziel", "kontakte_neu") or 1)
        db.set_geraet_einstellung("einfuehrung_gesehen", "0")
        w.launcher.kacheln["aktion:einfuehrung"].clicked.emit()
        APP.processEvents()
        assert w.stack.currentWidget() is w.pages["kontakte"]
        assert w.pages["kontakte"].f.get()["role"] == "KREDITOR"
        assert db.geraet_einstellung("einfuehrung_gesehen") == "1"
        assert not hasattr(w.pages["einstellungen"], "zugang")    # ohne Konten-Objekt keine Zugangskarte
    finally:
        w.hide()
        w.deleteLater()


def test_einfuehrung_seiten():
    from app.ui.einfuehrung import SEITEN, EinfuehrungDialog
    d = EinfuehrungDialog()
    assert "Gläubiger" in SEITEN[1][0] and "Schulden" in SEITEN[2][0]
    assert d.b_weiter.isVisibleTo(d) and not d.b_los.isVisibleTo(d)
    for _ in SEITEN:
        d._gehe(1)
    assert d.stack.currentIndex() == len(SEITEN) - 1 and d.b_los.isVisibleTo(d) and not d.b_weiter.isVisibleTo(d)
    d._los()
    assert d.ziel == "kontakte_neu"


def test_verbindlichkeit_ohne_glaeubiger_gibt_hinweis(db):
    db.modus = MODUS_SCHULDNER
    db.set_geraet_einstellung("einfuehrung_gesehen", "1")
    w = _fenster(db)
    try:
        w.navigate("verbindlichkeiten")
        w.pages["verbindlichkeiten"].neu()
        assert "Zuerst den Gläubiger anlegen" in w.pages["verbindlichkeiten"].msg.text()
    finally:
        w.hide()
        w.deleteLater()


def test_mandant_fenster_und_shell(tmp_path):
    v = _verw(tmp_path)
    m = v.anlegen({"name": "Maria Muster"})
    db = v.oeffnen(m["id"])
    db.benutzer, db.modus, db.mandanten_verwaltung = {"id": "x", "name": "admin", "rolle": "ADMIN"}, MODUS_BERATER, v
    w = _fenster(db)
    try:
        assert "Mandant: Maria Muster" in w.l_mandant.text()
        assert {"aktion:mandanten", "aktion:hilfe_berater"} <= set(w.launcher.kacheln) and not w.launcher.schritte
        assert "Datei des Schuldners einspielen" in " ".join(b.text() for b in w.pages["abgleich"].findChildren(
            __import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton))
        w.launcher.kacheln["aktion:mandanten"].clicked.emit()
        assert w.mandant_wechseln and not w.abgemeldet
    finally:
        w.hide()
        w.deleteLater()
        db.con.close()


def test_mandantenuebersicht(tmp_path):
    from app.ui.mandanten_fenster import MandantenFenster
    k = Konten(str(tmp_path))
    a = k.berater_einrichten("admin", "admin-pw-1")
    key = k.schluessel(a, "admin-pw-1")
    v = Mandanten(k.profil_ordner(a), key, a["name"])
    v.anlegen({"name": "Maria Muster", "aktenzeichen": "SB-1"})
    v.anlegen({"name": "Franz Huber"})
    f = MandantenFenster(v, k, a)
    assert f.t.rowCount() == 2 and f.t.item(0, 0).text() == "Franz Huber"
    assert "2 aktiv" in f.anzahl.text()
    f.suche.setText("SB-1")
    assert f.t.rowCount() == 1
    f.t.selectRow(0)
    f.oeffnen(f._sel())
    assert f.ergebnis == "oeffnen" and f.mandant_id == v.liste()[1]["id"]
    from app.ui.zugang import ZugangDialog
    z = ZugangDialog(f, k, a)
    assert hasattr(z.findChild(__import__("app.ui.zugang", fromlist=["ZugangKarten"]).ZugangKarten), "t_user")
    v.close()


def test_anmeldung_schuldner_nur_passwort(tmp_path):
    from app.ui.anmeldung import AnmeldeDialog, ModusDialog
    k = Konten(str(tmp_path))
    k.schuldner_einrichten("mein-passwort")
    d = AnmeldeDialog(k)
    d.show()
    APP.processEvents()
    assert not d.name.isVisible() and d.pw.isVisible() and d.name.text() == SCHULDNER_KONTO
    d.pw.setText("mein-passwort")
    d._ok()
    assert d.benutzer and d.benutzer["name"] == SCHULDNER_KONTO
    m = ModusDialog()
    m._waehlen("BERATER")
    assert m.modus == "BERATER"


def test_anleitungen_vorhanden():
    from app import hilfe
    assert hilfe.smartphone_pfad() and hilfe.smartphone_pfad().endswith("FinanceFlow-Schuldner.html")
    for art in hilfe.DATEIEN:
        p = hilfe.pfad(art)
        assert p and os.path.getsize(p) > 20_000, art


# ── Startablauf (main.py) mit simulierten Dialogen ────────────────────────────
def test_startablauf_schuldner(tmp_path, monkeypatch):
    from app import main as m
    from app.ui import anmeldung as an
    monkeypatch.setattr(an.ModusDialog, "exec", lambda self: (self._waehlen("SCHULDNER"), self.result())[1])

    def einrichten(self):
        self.anzeige.setText("Maria Muster")
        self.pw.setText("mein-passwort")
        self.pw2.setText("mein-passwort")
        self._ok()
        return self.result()
    monkeypatch.setattr(an.SchuldnerEinrichtungDialog, "exec", einrichten)
    monkeypatch.setattr(an.WiederherstellungDialog, "exec", lambda self: 1)
    k = Konten(str(tmp_path))
    assert m._ersteinrichtung(k) and k.ist_schuldner()
    u = k.anmelden(SCHULDNER_KONTO, "mein-passwort")
    db, lock = m._profil_oeffnen(k, u, "mein-passwort")
    try:
        assert db.setting("owner_name") == "Maria Muster" and db.modus == MODUS_SCHULDNER and db.mandant is None
        assert db.benutzerverwaltung is k
    finally:
        db.con.close()
        lock.unlock()


def test_startablauf_berater_mandant_wechseln(tmp_path, monkeypatch):
    from app import main as m
    from app.ui.mandanten_fenster import MandantenFenster
    k = Konten(str(tmp_path))
    a = k.berater_einrichten("admin", "admin-pw-1")
    ablauf = iter(["oeffnen", "oeffnen", "abmelden"])
    geoeffnet = []

    def uebersicht(self):
        schritt = next(ablauf)
        if schritt == "oeffnen":
            ms = self.verw.liste()
            mid = ms[0]["id"] if ms else self.verw.anlegen({"name": "Maria Muster"})["id"]
            self.oeffnen(mid)
        else:
            self._abmelden()
        return 1

    def fenster(db):
        geoeffnet.append((db.mandant["name"], db.modus, db.benutzerverwaltung, db.mandanten_verwaltung is not None))
        return "mandanten"
    monkeypatch.setattr(MandantenFenster, "exec", uebersicht)
    monkeypatch.setattr(m, "_fenster", fenster)
    assert m._berater(k, a, "admin-pw-1") == "abmelden"
    assert geoeffnet == [("Maria Muster", MODUS_BERATER, None, True)] * 2
