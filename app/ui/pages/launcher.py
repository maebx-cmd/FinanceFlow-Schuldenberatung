"""Launcher: neutrale Startseite nach der Anmeldung – nur Kacheln, keine Beträge, Namen oder sonstigen Daten.

Gedacht für die Nutzung in der Öffentlichkeit: Erst ein Klick auf eine Kachel öffnet ein Programm.
Schuldner sehen zusätzlich „Erste Schritte“ (nur ✓ / ○, ohne Zahlen), die Schuldenberatung die Kachel „Mandanten“.
"""
from __future__ import annotations

from PySide6.QtWidgets import QFrame, QGridLayout, QLayout, QScrollArea, QVBoxLayout, QWidget

from ..widgets import Card, Tile, button, hbox, label

# (Ziel, Titel, Beschreibung, Kürzel) – Ziel ist ein Bereich („bereich:…“), eine Seite oder eine Aktion („aktion:…“)
PROGRAMME = [
    ("bereich:finance", "FinanceFlow", "Verbindlichkeiten, Haushalt, Privatkonkurs, Reports", "FF"),
    ("kontakte", "Gläubiger", "Kontakte der Gläubiger anlegen", "GL"),
    ("verbindlichkeiten", "Schulden", "Verbindlichkeiten erfassen", "VB"),
]
ALLGEMEIN = [
    ("abgleich", "Abgleich", "Verschlüsselte Datei für Schuldner / Schuldenberatung", "AB"),
    ("einstellungen", "Einstellungen", "Profil, Datensicherung, Zugang", "ES"),
]
SCHULDNER = [
    ("aktion:einfuehrung", "Einführung", "Kurz erklärt: so funktioniert FinanceFlow", "?"),
    ("aktion:hilfe_schuldner", "Anleitung", "Ausführliche Anleitung (PDF)", "PDF"),
]
BERATER = [
    ("aktion:mandanten", "Mandanten", "Zurück zur Mandantenübersicht", "MA"),
    ("aktion:hilfe_berater", "Handbuch", "Handbuch für die Schuldenberatung (PDF)", "PDF"),
]

SCHRITTE = [("kontakte", "Gläubiger als Kontakte anlegen"), ("verbindlichkeiten", "Schulden unter Verbindlichkeiten erfassen"),
            ("abgleich", "Datei für die Schuldenberatung erstellen")]


class LauncherSeite(QWidget):
    def __init__(self, oeffnen, modus: str | None = None, db=None):
        """oeffnen(ziel): öffnet einen Bereich („bereich:key“), eine Seite oder führt eine Aktion aus."""
        super().__init__()
        self.setObjectName("page")
        self.modus, self.db = modus, db
        aussen = QVBoxLayout(self)
        aussen.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        inhalt = QWidget()
        inhalt.setObjectName("page")
        sc.setWidget(inhalt)
        aussen.addWidget(sc)
        v = QVBoxLayout(inhalt)
        v.setSizeConstraint(QLayout.SetMinimumSize)
        v.setContentsMargins(32, 24, 32, 24)
        v.addWidget(label("Willkommen", "h1"))
        v.addWidget(label("Wähle ein Programm.", "sub"))
        self.kacheln = {}
        self.schritte = {}
        if modus == "SCHULDNER":
            c = Card("Erste Schritte")
            for i, (ziel, text) in enumerate(SCHRITTE, start=1):
                z = label("", "sub")
                self.schritte[ziel] = z
                c.lay.addLayout(hbox(z, label(f"Schritt {'①②③'[i - 1]}  {text}"), None,
                                     button("Öffnen", flat=True, cb=lambda _=False, x=ziel: oeffnen(x))))
            v.addWidget(c)
        gruppen = [("Programme", PROGRAMME), ("Allgemein", ALLGEMEIN + (SCHULDNER if modus == "SCHULDNER" else
                                                                         BERATER if modus == "BERATER" else []))]
        for gname, liste in gruppen:
            v.addSpacing(8)
            v.addWidget(label(gname, "h2"))
            g = QGridLayout()
            g.setSpacing(16)
            for i, (ziel, titel, sub, kurz) in enumerate(liste):
                t = Tile(titel, sub, kurz)
                t.clicked.connect(lambda z=ziel: oeffnen(z))
                g.addWidget(t, i // 6, i % 6)
                self.kacheln[ziel] = t
            g.setColumnStretch(6, 1)
            v.addLayout(g)
        v.addStretch()

    def refresh(self):
        if not self.schritte or self.db is None:
            return
        from ...abgleich import abgleich as ab
        erledigt = {"kontakte": bool(self.db.val("SELECT 1 FROM contact WHERE isActive=1 LIMIT 1")),
                    "verbindlichkeiten": bool(self.db.val("SELECT 1 FROM liability WHERE status!='GELOESCHT' LIMIT 1")),
                    "abgleich": self.db.geraet_einstellung("export_erstellt", "") == "1"
                    or any(s.get("letzte_richtung") == "Export" for s in ab.status(self.db).values())}
        for ziel, z in self.schritte.items():
            z.setText("✓" if erledigt[ziel] else "○")
            z.setStyleSheet(f"color:{'#256F3A' if erledigt[ziel] else '#556B82'}; font-size:14pt;")

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()
