"""Bildschirmfotos für Handbuch und Anleitung (headless).
Aufruf: QT_QPA_PLATFORM=offscreen python tools/bildschirmfotos.py <zielordner>"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui.style import QSS  # noqa: E402

ziel = sys.argv[1] if len(sys.argv) > 1 else "/tmp/bilder"
os.makedirs(ziel, exist_ok=True)
app = QApplication(sys.argv)
app.setStyle("Fusion")
app.setFont(QFont("DejaVu Sans", 9))
app.setStyleSheet(QSS)


def foto(w, name, groesse=None):
    if groesse:
        w.resize(*groesse)
    w.show()
    for _ in range(3):
        app.processEvents()
    w.grab().save(os.path.join(ziel, name + ".png"))


from app.db import DB  # noqa: E402
from app.konten import Konten  # noqa: E402
from app.mandanten import Mandanten  # noqa: E402
from app.ui.anmeldung import (AnmeldeDialog, ErsteinrichtungDialog, ModusDialog, SchuldnerEinrichtungDialog,  # noqa: E402
                              WiederherstellungDialog)
from app.ui.bereiche import BereichsFenster  # noqa: E402
from app.ui.einfuehrung import EinfuehrungDialog  # noqa: E402
from app.ui.mandanten_fenster import MandantenFenster  # noqa: E402
from app.ui.navigation import BEREICHE  # noqa: E402
from tests.demo_data import befuellen  # noqa: E402

t = tempfile.mkdtemp()
foto(ModusDialog(), "01_modus")
ks = Konten(os.path.join(t, "s"))
d = SchuldnerEinrichtungDialog(ks)
d.anzeige.setText("Maria Muster")
foto(d, "02_schuldner_einrichten")
u = ks.schuldner_einrichten("mein-passwort")
foto(WiederherstellungDialog(u["wiederherstellung"]), "03_wiederherstellung")
foto(AnmeldeDialog(ks), "04_anmeldung_schuldner")
e = EinfuehrungDialog()
for i in range(6):
    e._zeigen(i)
    foto(e, f"05_einfuehrung_{i + 1}")

db = DB(os.path.join(t, "s", "daten.db"), key=ks.schluessel(u, "mein-passwort"))
db.modus, db.benutzer, db.benutzerverwaltung = "SCHULDNER", u, ks
db.set_geraet_einstellung("einfuehrung_gesehen", "1")
db.set_setting("owner_name", "Maria Muster")
w = BereichsFenster(db, BEREICHE)
foto(w, "06_start_schuldner_leer", (1440, 900))
w.navigate("kontakte")
w.pages["kontakte"].neu()
f = w.pages["kontakte"].f
f.felder["name"].setText("Bank Austria")
f.felder["address"].setText("Rothschildplatz 1")
f.felder["zipCode"].setText("1020")
f.felder["city"].setText("Wien")
foto(w, "07_kontakt_neu")
w.close()
befuellen(db)
w = BereichsFenster(db, BEREICHE)
foto(w, "08_start_schuldner", (1440, 900))
w.navigate("verbindlichkeiten")
p = w.pages["verbindlichkeiten"]
p.liste.setCurrentRow(0)
foto(w, "09_verbindlichkeit")
p.neu()
foto(w, "10_verbindlichkeit_neu")
for k in ("start", "offene_raten", "haushalt", "postbuch", "reports", "abgleich", "einstellungen", "privatkonkurs", "dashboard"):
    w.navigate(k)
    pg = w.pages[k]
    if hasattr(pg, "liste") and pg.liste.count():
        pg.liste.setCurrentRow(0)
    foto(w, f"11_{k}")
w.close()

kb = Konten(os.path.join(t, "b"))
foto(ErsteinrichtungDialog(kb), "20_berater_einrichten")
a = kb.berater_einrichten("admin", "admin-pw-1")
foto(AnmeldeDialog(kb), "21_anmeldung_berater")
v = Mandanten(kb.profil_ordner(a), kb.schluessel(a, "admin-pw-1"), "admin")
for name, az in (("Maria Muster", "SB-2026-014"), ("Franz Huber", "SB-2026-015"), ("Ayşe Yılmaz", "SB-2026-021")):
    m = v.anlegen({"name": name, "aktenzeichen": az, "notiz": "Erstgespräch erledigt"})
    if name == "Maria Muster":
        x = v.oeffnen(m["id"])
        befuellen(x)
        x.con.close()
        v.vermerken(m["id"], "Import", "Marias-Laptop", "2026-11-10T18:42:00")
mf = MandantenFenster(v, kb, a)
mf.t.selectRow(1)
foto(mf, "22_mandanten", (1440, 820))
from app.ui.zugang import ZugangDialog  # noqa: E402
foto(ZugangDialog(mf, kb, a), "23_zugang_benutzer")
mid = [m for m in v.liste() if m["name"] == "Maria Muster"][0]["id"]
mdb = v.oeffnen(mid)
mdb.benutzer, mdb.modus, mdb.mandanten_verwaltung = a, "BERATER", v
w = BereichsFenster(mdb, BEREICHE)
foto(w, "24_mandant_start", (1440, 900))
for k in ("start", "verbindlichkeiten", "abgleich", "privatkonkurs", "zahlungsplan", "reports"):
    w.navigate(k)
    pg = w.pages[k]
    if hasattr(pg, "liste") and pg.liste.count():
        pg.liste.setCurrentRow(0)
    foto(w, f"25_mandant_{k}")
print("fertig:", ziel)
