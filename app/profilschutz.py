"""Umstellung eines Profils auf verschlüsselte Datenbanken (ab 2.0.0).

Betroffen: daten.db und mobil.db im Profilordner sowie alle Sicherungen daten_*.db / mobil_*.db im Ordner „Sicherungen“.
Jede Datei wird einzeln umgewandelt und geprüft (sqldb.verschluesseln); bereits verschlüsselte Dateien werden übersprungen.
Dadurch kann die Umstellung nach einem Abbruch (Stromausfall …) beim nächsten Anmelden einfach fortgesetzt werden.
"""
from __future__ import annotations

import os

from . import sqldb


def dateien(ordner: str) -> list[str]:
    aus = [os.path.join(ordner, n) for n in ("daten.db", "mobil.db")]
    sich = os.path.join(ordner, "Sicherungen")
    if os.path.isdir(sich):
        aus += [os.path.join(sich, f) for f in sorted(os.listdir(sich))
                if f.endswith(".db") and (f.startswith("daten_") or f.startswith("mobil_"))]
    return [p for p in aus if os.path.isfile(p) and os.path.getsize(p) > 0]


def offen(ordner: str) -> list[str]:
    """Noch unverschlüsselte Datenbanken des Profils."""
    return [p for p in dateien(ordner) if sqldb.ist_klartext(p)]


def verschluesseln(ordner: str, key: bytes, fortschritt=None) -> list[str]:
    """Wandelt alle noch unverschlüsselten Datenbanken des Profils um. Gibt die umgewandelten Dateien zurück.
    Ein Fehler bricht ab (die betroffene Datei bleibt unverändert); bereits umgewandelte bleiben verschlüsselt."""
    liste = offen(ordner)
    fertig = []
    for i, p in enumerate(liste, 1):
        if fortschritt:
            fortschritt(i, len(liste), os.path.basename(p))
        if sqldb.verschluesseln(p, key):
            fertig.append(p)
    return fertig
