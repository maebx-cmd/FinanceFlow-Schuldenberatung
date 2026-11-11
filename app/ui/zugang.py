"""Karten „Mein Zugang“ und „Benutzerverwaltung“.

Schuldner:  nur „Mein Zugang“ (Passwort ändern, neuer Wiederherstellungsschlüssel) – unter Einstellungen.
Berater:    „Mein Zugang“ und – für den Administrator – „Benutzerverwaltung“ (Kolleg:innen der Beratungsstelle),
            erreichbar in der Mandantenübersicht.
"""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QLineEdit, QVBoxLayout, QWidget

from .. import APP_TITEL
from ..konten import KontoFehler
from .common import Tabelle, frage
from .widgets import Card, Form, button, hbox, label, set_strip, strip


class ZugangKarten(QWidget):
    def __init__(self, konten, ich: dict, meldung, mit_benutzern: bool):
        super().__init__()
        self.konten, self.ich, self.meldung = konten, ich, meldung
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(16)
        schuldner = konten.ist_schuldner()
        c = Card("Mein Zugang")
        if not schuldner:
            c.lay.addWidget(label(f"Angemeldet als {ich['name']}" + (" (Administrator)" if ich["rolle"] == "ADMIN" else ""), "sub"))
        f = Form(3)
        self.pw_alt, self.pw_neu, self.pw_neu2 = (QLineEdit() for _ in range(3))
        for e in (self.pw_alt, self.pw_neu, self.pw_neu2):
            e.setEchoMode(QLineEdit.Password)
        f.add("alt", "Bisheriges Passwort", self.pw_alt)
        f.add("neu", "Neues Passwort (mind. 8 Zeichen)", self.pw_neu)
        f.add("neu2", "Neues Passwort wiederholen", self.pw_neu2)
        c.lay.addWidget(f)
        c.lay.addLayout(hbox(None, button("Neuen Wiederherstellungsschlüssel …", cb=self._rk_neu),
                             button("Passwort ändern", cb=self._pw_aendern)))
        c.lay.addWidget(label(
            ("Deine Daten und alle Sicherungen sind verschlüsselt. Passwort ändern behält die Daten. Ein neuer "
             "Wiederherstellungsschlüssel braucht das bisherige Passwort (oben) und macht den alten ungültig.") if schuldner else
            ("Mandantenverzeichnis, alle Mandanten-Datenstände und Sicherungen dieses Zugangs sind verschlüsselt (SQLCipher, "
             "AES-256). Passwort ändern behält die Daten. Ein neuer Wiederherstellungsschlüssel braucht das bisherige Passwort "
             "(oben) und macht den alten ungültig."), "sub", wrap=True))
        v.addWidget(c)
        if schuldner or not mit_benutzern or ich["rolle"] != "ADMIN":
            return
        c = Card("Benutzerverwaltung")
        c.lay.addWidget(label("Jede Beraterin und jeder Berater hat einen eigenen Zugang mit eigenen, getrennt verschlüsselten "
                              "Mandanten. Kolleg:innen sehen die Mandanten der anderen nicht – zum Übergeben eines Falls die "
                              "Abgleich-Datei des Mandanten erstellen und beim Kollegen als neuen Mandanten einspielen. "
                              "Gelöschte Benutzer werden nicht endgültig entfernt: ihr Datenordner wird nach „Gelöschte Profile“ "
                              "verschoben.", "sub", wrap=True))
        self.t_user = Tabelle(["Benutzer", "Rolle", "Status", "Angelegt", "Letzte Anmeldung"], [None, 120, 100, 150, 150])
        self.t_user.setMinimumHeight(160)
        c.lay.addWidget(self.t_user)
        c.lay.addLayout(hbox(button("+ Benutzer anlegen", emph=True, cb=self._u_neu), button("Passwort zurücksetzen …", cb=self._u_pw),
                             button("Aktivieren / Deaktivieren", cb=self._u_aktiv), None,
                             button("Löschen …", flat=True, neg=True, cb=self._u_loeschen)))
        v.addWidget(c)
        self._u_laden()

    def tu(self, fn, *args, ok=None):
        try:
            res = fn(*args)
        except (KontoFehler, ValueError) as e:
            self.meldung(str(e), "error")
            return None
        if ok:
            self.meldung(ok if isinstance(ok, str) else ok(res), "ok")
        return res if res is not None else True

    def _u_laden(self):
        if not hasattr(self, "t_user"):
            return
        us = self.konten.liste()
        z = lambda v: (v or "")[:16].replace("T", " ")
        self.t_user.set_rows([[x["name"], "Administrator" if x["rolle"] == "ADMIN" else "Berater:in",
                               "aktiv" if x["aktiv"] else "deaktiviert", z(x["erstellt"]), z(x["letzter_login"])] for x in us],
                             [x["id"] for x in us])

    def _pw_aendern(self):
        if self.pw_neu.text() != self.pw_neu2.text():
            self.meldung("Die neuen Passwörter stimmen nicht überein.", "error")
            return
        if self.tu(self.konten.passwort_aendern, self.ich, self.pw_alt.text(), self.pw_neu.text(), ok="Passwort geändert."):
            for e in (self.pw_alt, self.pw_neu, self.pw_neu2):
                e.clear()

    def _rk_neu(self):
        from .anmeldung import WiederherstellungDialog
        if not self.pw_alt.text():
            self.meldung("Bitte oben das bisherige Passwort eingeben.", "warn")
            return
        if not frage(self, "Wiederherstellungsschlüssel", "Neuen Wiederherstellungsschlüssel erzeugen? Der bisherige wird "
                                                          "dadurch ungültig."):
            return
        rk = self.tu(self.konten.neuer_wiederherstellungsschluessel, self.ich, self.pw_alt.text(),
                     ok="Neuer Wiederherstellungsschlüssel erzeugt – der alte gilt nicht mehr.")
        if isinstance(rk, str):
            self.pw_alt.clear()
            WiederherstellungDialog(rk, "" if self.konten.ist_schuldner() else self.ich["name"],
                                    "Neuer Wiederherstellungsschlüssel").exec()

    def _u_neu(self):
        from .anmeldung import PasswortDialog, WiederherstellungDialog
        dlg = PasswortDialog("Benutzer anlegen", "Der neue Zugang startet ohne Mandanten (eigener, verschlüsselter Bereich).",
                             mit_name=True)
        if dlg.exec() and dlg.werte:
            u = self.tu(self.konten.benutzer_anlegen, self.ich, dlg.werte["name"], dlg.werte["pw"],
                        ok=lambda u: f"Benutzer „{u['name']}“ angelegt.")
            self._u_laden()
            if isinstance(u, dict):
                WiederherstellungDialog(u["wiederherstellung"], u["name"],
                                        "Wiederherstellungsschlüssel – dem Benutzer übergeben").exec()

    def _u_sel(self):
        uid = self.t_user.sel_id()
        if not uid:
            self.meldung("Bitte zuerst einen Benutzer in der Liste markieren.", "warn")
        return uid

    def _u_pw(self):
        uid = self._u_sel()
        if not uid:
            return
        from .anmeldung import PasswortDialog
        u = self.konten.get(uid)
        name, rk = u["name"], self.konten.verschluesselt(u)
        dlg = PasswortDialog("Passwort zurücksetzen", f"Neues Passwort für „{name}“." + (
            " Die Daten sind verschlüsselt – zum Zurücksetzen wird der Wiederherstellungsschlüssel dieses Benutzers "
            "gebraucht (ohne ihn bleibt der Zugang gesperrt)." if rk else ""), mit_rk=rk)
        if dlg.exec() and dlg.werte:
            self.tu(self.konten.passwort_zuruecksetzen, self.ich, uid, dlg.werte["pw"], dlg.werte["rk"],
                    ok=f"Passwort für „{name}“ gesetzt.")

    def _u_aktiv(self):
        uid = self._u_sel()
        if not uid:
            return
        u = self.konten.get(uid)
        self.tu(self.konten.aktiv_setzen, self.ich, uid, not u["aktiv"],
                ok=f"„{u['name']}“ {'deaktiviert' if u['aktiv'] else 'aktiviert'}.")
        self._u_laden()

    def _u_loeschen(self):
        uid = self._u_sel()
        if not uid:
            return
        u = self.konten.get(uid)
        if not frage(self, "Benutzer löschen", f"Benutzer „{u['name']}“ löschen? Die Anmeldung wird entfernt; der Datenordner "
                                                "(mit seinen Mandanten) wird nach „Gelöschte Profile“ verschoben."):
            return
        self.tu(self.konten.loeschen, self.ich, uid, ok=lambda z: f"„{u['name']}“ gelöscht. Daten verschoben nach: {z or '–'}")
        self._u_laden()


class ZugangDialog(QDialog):
    """Für die Mandantenübersicht der Beratung: Mein Zugang + Benutzerverwaltung in einem Fenster."""

    def __init__(self, parent, konten, ich):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_TITEL} – Zugang und Benutzer")
        self.setObjectName("page")
        self.setMinimumWidth(820)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        self.msg = strip("")
        self.msg.setVisible(False)
        v.addWidget(ZugangKarten(konten, ich, self.meldung, mit_benutzern=True))
        v.addWidget(self.msg)
        v.addLayout(hbox(None, button("Schließen", emph=True, cb=self.accept)))

    def meldung(self, text, art="info"):
        set_strip(self.msg, text, art)
