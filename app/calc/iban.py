"""IBAN normalisieren, prüfen (Aufbau + Prüfziffer mod 97) und in 4er-Gruppen formatieren – wie die Web-Version."""
from __future__ import annotations

import re

_AUFBAU = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$")
FEHLER = "IBAN ungültig (Prüfziffer oder Aufbau)"


def normalisieren(s) -> str | None:
    """Leerzeichen und Bindestriche entfernen, Großbuchstaben; leer → None."""
    if s is None:
        return None
    t = re.sub(r"[\s\-]", "", str(s)).upper()
    return t or None


def gueltig(s) -> bool:
    t = normalisieren(s)
    if not t or not _AUFBAU.match(t):
        return False
    umgestellt = t[4:] + t[:4]
    zahl = "".join(str(int(ch, 36)) for ch in umgestellt)   # A=10 … Z=35
    return int(zahl) % 97 == 1


def formatieren(s) -> str:
    t = normalisieren(s)
    if not t:
        return ""
    return " ".join(t[i:i + 4] for i in range(0, len(t), 4))
