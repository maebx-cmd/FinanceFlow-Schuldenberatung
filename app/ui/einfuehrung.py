"""Kurze Einführung für Schuldner:innen – in einfacher Sprache, Schritt für Schritt.

Erscheint beim ersten Öffnen automatisch und ist danach jederzeit über die Kachel „Einführung“ am Start erreichbar.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget

from .. import APP_TITEL
from .widgets import button, label

# (Überschrift, Absätze) – kurze Sätze, ein Gedanke je Satz, keine Fachwörter ohne Erklärung
SEITEN = [
    ("Willkommen bei FinanceFlow",
     ["Mit FinanceFlow hast du alle deine Schulden an einem Ort.",
      "Du siehst auf einen Blick: <b>Wem</b> schuldest du Geld? <b>Wie viel</b> ist noch offen? <b>Wann</b> ist die "
      "nächste Rate fällig?",
      "Deine Schuldenberatung hilft dir dabei. Sie bekommt deine Daten aber nur, wenn <b>du</b> ihr eine Datei gibst.",
      "Für den Anfang brauchst du nur zwei Schritte. Wir zeigen sie dir jetzt."]),
    ("Schritt 1: Gläubiger anlegen",
     ["Ein <b>Gläubiger</b> ist jemand, dem du Geld schuldest. Zum Beispiel: eine Bank, ein Inkasso-Büro, die Handy-Firma, "
      "der Vermieter oder das Finanzamt.",
      "So geht es: Links auf <b>„Kontakte (Gläubiger)“</b> klicken. Dann auf <b>„+ Kontakt“</b>.",
      "Trag den Namen ein. Wenn du sie hast, auch Adresse, Telefon und IBAN (steht oft auf dem Brief oder der Rechnung). "
      "Bei „Rolle“ steht schon <b>Gläubiger</b>. Dann auf <b>„Speichern“</b>.",
      "Mach das für <b>jeden</b> Gläubiger einmal.",
      "Tipp: Schreibt dir ein Inkasso-Büro statt der Firma? Dann leg das Inkasso-Büro an und schreib die Firma in die "
      "Notizen."]),
    ("Schritt 2: Schulden erfassen",
     ["Erst wenn die Gläubiger angelegt sind, trägst du die Schulden ein.",
      "So geht es: Links auf <b>„Verbindlichkeiten“</b> klicken. Dann auf <b>„+ Neu“</b>.",
      "Wähle den <b>Gläubiger</b> aus der Liste. Gib der Schuld einen kurzen Namen, zum Beispiel „Kredit Auto“ oder "
      "„Handy-Rechnung“.",
      "Bei <b>„Saldo“</b> trägst du ein, wie viel <b>jetzt noch offen</b> ist. Den Betrag findest du meist im letzten "
      "Brief oder Kontoauszug.",
      "Zahlst du Raten? Dann trag bei <b>„Rate (€/Monat)“</b> die Höhe der Rate ein und bei „Fälligkeitstag“ den Tag "
      "im Monat. Zahlst du gerade nichts, wähl bei „Rückzahlungstyp“ „Offen / revolvierend“.",
      "Dann auf <b>„Speichern“</b>. Das machst du für jede Schuld.",
      "Du weißt etwas nicht genau? Kein Problem. Lass das Feld leer oder schreib es in die Notizen. Deine "
      "Schuldenberatung hilft dir."]),
    ("Was FinanceFlow noch kann",
     ["<b>Offene Raten:</b> Welche Raten sind als Nächstes fällig? Bezahlte Raten hakst du hier ab.",
      "<b>Haushaltsrechnung und Fixkosten:</b> Was kommt im Monat herein, was geht hinaus? Was bleibt übrig?",
      "<b>Postbuch:</b> Hier notierst du Briefe von Gläubigern und Fristen, damit nichts vergessen wird.",
      "<b>Reports:</b> Druckt eine Liste aller Gläubiger als PDF – praktisch für den Termin bei der Beratung.",
      "<b>Privatkonkurs:</b> Rechnet aus, wie ein Zahlungsplan aussehen könnte. Das besprichst du am besten mit "
      "deiner Beratung."]),
    ("Daten an die Schuldenberatung geben",
     ["Links auf <b>„Abgleich“</b> klicken. Dann auf <b>„Datei für die Schuldenberatung erstellen“</b>.",
      "Denk dir ein Passwort aus. Es muss mindestens <b>12 Zeichen</b> lang sein. Die Datei wird damit verschlüsselt.",
      "Gib die Datei deiner Beraterin oder deinem Berater – per E-Mail oder auf einem USB-Stick.",
      "Das Passwort sagst du <b>getrennt</b> davon, am besten am Telefon oder persönlich. Schreib es nie in dieselbe "
      "E-Mail.",
      "Bekommst du von der Beratung eine Datei zurück, spielst du sie unter „Abgleich“ ein."]),
    ("Deine Daten sind geschützt",
     ["Deine Daten bleiben auf deinem Computer. Sie sind <b>verschlüsselt</b>. Ohne dein Passwort kann sie niemand lesen.",
      "Heb den <b>Wiederherstellungsschlüssel</b> gut auf, zum Beispiel ausgedruckt in einer Mappe. Damit kannst du ein "
      "neues Passwort setzen, wenn du deines vergisst.",
      "Andere schauen dir über die Schulter? Mit <b>„Beträge verbergen“</b> oben (oder Strg + B) werden alle Beträge "
      "ausgeblendet.",
      "FinanceFlow macht jeden Tag selbst eine Sicherung.",
      "Diese Einführung findest du jederzeit wieder am Start unter <b>„Einführung“</b>. Die ausführliche Anleitung "
      "unter <b>„Anleitung“</b>."]),
]


class EinfuehrungDialog(QDialog):
    """Ergebnis: self.ziel = 'kontakte_neu' (gleich ersten Gläubiger anlegen) oder None."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_TITEL} – Einführung")
        self.setObjectName("page")
        self.setMinimumSize(720, 560)
        self.ziel = None
        v = QVBoxLayout(self)
        v.setContentsMargins(36, 28, 36, 24)
        v.setSpacing(14)
        self.schritt = label("", "sub")
        v.addWidget(self.schritt)
        self.stack = QStackedWidget()
        for titel, absaetze in SEITEN:
            w = QWidget()
            w.setObjectName("page")
            sv = QVBoxLayout(w)
            sv.setContentsMargins(0, 0, 0, 0)
            sv.setSpacing(12)
            h = label(titel, "h1")
            sv.addWidget(h)
            for a in absaetze:
                p = QLabel(a)
                p.setWordWrap(True)
                p.setTextFormat(Qt.RichText)
                p.setStyleSheet("font-size:12.5pt; color:#1D2D3E; line-height:140%;")
                sv.addWidget(p)
            sv.addStretch()
            self.stack.addWidget(w)
        v.addWidget(self.stack, 1)
        self.punkte = QHBoxLayout()
        self.punkte.setSpacing(6)
        self.punkt = []
        self.punkte.addStretch()
        for _ in SEITEN:
            f = QFrame()
            f.setFixedSize(10, 10)
            self.punkt.append(f)
            self.punkte.addWidget(f)
        self.punkte.addStretch()
        v.addLayout(self.punkte)
        unten = QHBoxLayout()
        self.b_zurueck = button("‹ Zurück", flat=True, cb=lambda: self._gehe(-1))
        self.b_spaeter = button("Später ansehen", flat=True, cb=self.reject)
        self.b_weiter = button("Weiter ›", emph=True, cb=lambda: self._gehe(1))
        self.b_los = button("Jetzt ersten Gläubiger anlegen", emph=True, cb=self._los)
        self.b_fertig = button("Fertig", cb=self.accept)
        for b in (self.b_zurueck, self.b_spaeter):
            unten.addWidget(b)
        unten.addStretch()
        for b in (self.b_fertig, self.b_los, self.b_weiter):
            unten.addWidget(b)
        v.addLayout(unten)
        self._zeigen(0)

    def _zeigen(self, i):
        self.stack.setCurrentIndex(i)
        n = len(SEITEN)
        self.schritt.setText(f"Einführung · Seite {i + 1} von {n}")
        for k, f in enumerate(self.punkt):
            f.setStyleSheet(f"background:{'#0064D9' if k == i else '#D5DADD'}; border-radius:5px;")
        letzte = i == n - 1
        self.b_zurueck.setEnabled(i > 0)
        self.b_weiter.setVisible(not letzte)
        self.b_los.setVisible(letzte)
        self.b_fertig.setVisible(letzte)
        self.b_spaeter.setVisible(not letzte)

    def _gehe(self, d):
        self._zeigen(max(0, min(len(SEITEN) - 1, self.stack.currentIndex() + d)))

    def _los(self):
        self.ziel = "kontakte_neu"
        self.accept()
