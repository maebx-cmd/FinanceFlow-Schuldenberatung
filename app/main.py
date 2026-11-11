from __future__ import annotations

import os
import sys

from PySide6.QtCore import QLockFile, QStandardPaths, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from . import APP_NAME, APP_TITEL, EDITION, sqldb
from .db import DB
from .db_base import VersionsFehler
from .ui.bereiche import BereichsFenster
from .ui.navigation import BEREICHE
from .ui.style import QSS



def basis_ordner() -> str:
    """Programmordner in %APPDATA%. Für Tests überschreibbar: Programm.exe <Ordner>."""
    if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]):
        return sys.argv[1]
    basis = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    os.makedirs(basis, exist_ok=True)
    return basis


def _sperren(pfad):
    lock = QLockFile(pfad + ".lock"); lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        if QMessageBox.question(None, APP_NAME, "Dieses Profil ist bereits geöffnet. Nur nach einem Absturz: Sperre aufheben?",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return None
        lock.removeStaleLockFile()
        if not lock.tryLock(100):
            return None
    return lock


def _kontenmigration(db) -> bool:
    """Ab 1.6.0 gibt es keine Konten/Buchungen mehr. Einmalig: anzeigen, was übernommen/gelöscht wird, bestätigen lassen,
    dann mit Sicherung in EINER Transaktion übernehmen. Abbrechen → Programm startet nicht, nichts wird gelöscht."""
    from .services import kontenmigration as km
    if not km.noetig(db.con):
        return True
    v = km.vorschau(db.con)
    box = QMessageBox(QMessageBox.Question, f"{APP_NAME} – Umstellung ohne Konten",
                      "Ab dieser Version gibt es kein Konten- und Buchungsmodul mehr (wie in der Web-Version). "
                      "Die IBAN steht künftig direkt an der Verbindlichkeit, bezahlte Raten werden als Korrektur "
                      "„Ratenzahlung“ gespeichert.\n\n" + km.vorschau_text(v) +
                      "\n\nVorher wird automatisch eine Sicherung der Datenbank angelegt.")
    box.setInformativeText("Jetzt übernehmen? Bei „Abbrechen“ wird nichts geändert und das Programm nicht geöffnet.")
    ok = box.addButton("Übernehmen", QMessageBox.AcceptRole)
    box.addButton("Abbrechen", QMessageBox.RejectRole)
    box.exec()
    if box.clickedButton() is not ok:
        return False
    try:
        km.migrieren(db)
    except Exception as e:  # noqa: BLE001 – Transaktion wurde zurückgerollt, Daten unverändert
        QMessageBox.critical(None, APP_NAME, f"Übernahme fehlgeschlagen, es wurde nichts geändert:\n{e}")
        return False
    QMessageBox.information(None, APP_NAME, f"Übernahme abgeschlossen. Sicherung: {db.backup_ordner()}")
    return True


def _schluessel_holen(konten, u, pw):
    """Datenbankschlüssel des Profils. Profile von vor 2.0.0 bekommen jetzt einen (Wiederherstellungsschlüssel anzeigen)."""
    from .konten import KontoFehler
    from .ui.anmeldung import WiederherstellungDialog
    try:
        key = konten.schluessel(u, pw)
        if key is None:
            QMessageBox.information(None, f"{APP_NAME} – Verschlüsselung",
                                    "Ab dieser Version sind alle Datenbanken verschlüsselt (SQLCipher, AES-256). Dein "
                                    "Datenbestand und alle Sicherungen werden jetzt einmalig umgestellt. Vorher wird dir "
                                    "ein Wiederherstellungsschlüssel angezeigt – bitte notieren.")
            key, rk = konten.schluessel_einrichten(u, pw)
            WiederherstellungDialog(rk, u["name"]).exec()
    except KontoFehler as e:
        QMessageBox.critical(None, APP_NAME, str(e))
        return None
    return key


def _profil_verschluesseln(ordner, key) -> bool:
    from . import profilschutz
    if not profilschutz.offen(ordner):
        return True
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        fertig = profilschutz.verschluesseln(ordner, key)
    except Exception as e:  # noqa: BLE001 – betroffene Datei bleibt unverändert, Umstellung läuft beim nächsten Mal weiter
        QApplication.restoreOverrideCursor()
        QMessageBox.critical(None, APP_NAME, f"Verschlüsseln fehlgeschlagen (Datei unverändert, beim nächsten Anmelden "
                                             f"wird fortgesetzt):\n{e}")
        return False
    QApplication.restoreOverrideCursor()
    QMessageBox.information(None, APP_NAME, f"Verschlüsselt: {len(fertig)} Datenbank(en) inkl. Sicherungen. "
                                            "Die unverschlüsselten Fassungen wurden ersetzt.")
    return True


def _profil_oeffnen(konten, u, pw):
    """Öffnet den Datenbestand des angemeldeten Benutzers. Neue Profile bekommen den Namen als PDF-Kopf."""
    pfad = konten.db_pfad(u)
    neu = not os.path.exists(pfad)
    lock = _sperren(pfad)
    if not lock:
        return None, None
    key = _schluessel_holen(konten, u, pw)
    if key is None or not _profil_verschluesseln(konten.profil_ordner(u), key):
        lock.unlock(); return None, None
    try:
        db = DB(pfad, key=key)
    except (VersionsFehler, sqldb.DatabaseError) as e:
        QMessageBox.critical(None, APP_NAME, str(e)); lock.unlock(); return None, None
    if db.integritaet() != "ok":
        QMessageBox.critical(None, APP_NAME, f"Datenbank beschädigt – Sicherung aus „{db.backup_ordner()}“ zurückspielen.")
        lock.unlock(); return None, None
    if not _kontenmigration(db):
        db.con.close(); lock.unlock(); return None, None
    if neu and konten.einrichtung("anzeigename"):
        db.set_setting("owner_name", konten.einrichtung("anzeigename"))
    db.benutzer, db.benutzerverwaltung, db.modus = u, konten, konten.modus()
    return db, lock


def _mandant_oeffnen(verw, u, mid):
    """Datenstand eines Mandanten öffnen (Schuldenberatung)."""
    pfad = verw.db_pfad(mid)
    lock = _sperren(pfad)
    if not lock:
        return None, None
    try:
        db = verw.oeffnen(mid)
    except (VersionsFehler, sqldb.DatabaseError) as e:
        QMessageBox.critical(None, APP_NAME, str(e)); lock.unlock(); return None, None
    if db.integritaet() != "ok":
        QMessageBox.critical(None, APP_NAME, f"Datenbank beschädigt – Sicherung aus „{db.backup_ordner()}“ zurückspielen.")
        db.con.close(); lock.unlock(); return None, None
    db.benutzer, db.benutzerverwaltung, db.modus, db.mandanten_verwaltung = u, None, "BERATER", verw
    return db, lock


def _fenster(db):
    """Hauptfenster zeigen, bis es geschlossen wird. Gibt "abmelden", "mandanten" oder "beenden" zurück."""
    app = QApplication.instance()
    w = BereichsFenster(db, BEREICHE)
    w.show()
    app.exec()
    if getattr(w, "mandant_wechseln", False):
        erg = "mandanten"
    elif getattr(w, "abgemeldet", False):
        erg = "abmelden"
    else:
        erg = "beenden"
    w.deleteLater()
    return erg


def _berater(konten, u, pw) -> str:
    """Schuldenberatung: Mandantenübersicht ↔ Mandant. Gibt "abmelden" oder "beenden" zurück."""
    from .mandanten import Mandanten
    from .ui.mandanten_fenster import MandantenFenster
    key = _schluessel_holen(konten, u, pw)
    if key is None:
        return "abmelden"
    ordner = konten.profil_ordner(u)
    sperre = _sperren(os.path.join(ordner, "mandanten.db"))
    if not sperre:
        return "abmelden"
    verw = Mandanten(ordner, key, u["name"])
    try:
        while True:
            f = MandantenFenster(verw, konten, u)
            f.exec()
            if f.ergebnis == "abmelden":
                return "abmelden"
            if f.ergebnis != "oeffnen":
                return "beenden"
            db, lock = _mandant_oeffnen(verw, u, f.mandant_id)
            if not db:
                continue
            try:
                erg = _fenster(db)
            finally:
                db.con.close()
                lock.unlock()
            if erg != "mandanten":
                return erg
    finally:
        verw.close()
        sperre.unlock()


def _ersteinrichtung(konten) -> bool:
    """Erster Start: Schuldner oder Schuldenberatung? Danach Zugang anlegen und Wiederherstellungsschlüssel zeigen."""
    from .ui.anmeldung import ErsteinrichtungDialog, ModusDialog, SchuldnerEinrichtungDialog, WiederherstellungDialog
    while True:
        m = ModusDialog()
        if m.exec() != ModusDialog.Accepted or not m.modus:
            return False
        dlg = SchuldnerEinrichtungDialog(konten) if m.modus == "SCHULDNER" else ErsteinrichtungDialog(konten)
        if dlg.exec() == QDialog.Accepted:
            break
    WiederherstellungDialog(dlg.benutzer["wiederherstellung"], "" if m.modus == "SCHULDNER" else dlg.benutzer["name"]).exec()
    return True


def main():
    from .konten import Konten
    from .ui.anmeldung import AnmeldeDialog
    app = QApplication(sys.argv)
    # Eigener Datenordner (%APPDATA%\FinanceFlow\Schuldenberatung) – getrennt von FinanceFlow Desktop
    app.setApplicationName(EDITION); app.setOrganizationName(APP_NAME); app.setApplicationDisplayName(APP_TITEL)
    app.setStyle("Fusion"); app.setFont(QFont("Segoe UI", 10)); app.setStyleSheet(QSS)
    app.setQuitOnLastWindowClosed(False)  # Hauptfenster beendet die Schleife selbst (Abmelden → zurück zur Anmeldung)
    basis = basis_ordner()
    konten = Konten(basis)
    if konten.leer():
        if not _ersteinrichtung(konten):
            sys.exit(0)
    while True:
        dlg = AnmeldeDialog(konten)
        if dlg.exec() != AnmeldeDialog.Accepted:
            break
        u, pw = dlg.benutzer, dlg.passwort
        dlg.passwort = ""
        if konten.modus() == "BERATER":
            erg = _berater(konten, u, pw)
        else:
            db, lock = _profil_oeffnen(konten, u, pw)
            if not db:
                continue
            try:
                erg = _fenster(db)
            finally:
                db.con.close()
                lock.unlock()
        if erg != "abmelden":
            break
    konten.close()
    sys.exit(0)
