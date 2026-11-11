"""Mitgelieferte Anleitungen (PDF) öffnen: Anleitung für Schuldner, Handbuch für die Schuldenberatung.

Die PDFs liegen im Ordner „hilfe“ (Entwicklung: neben main.py; EXE: von PyInstaller eingebettet; MSI: zusätzlich im
Programmordner mit Startmenü-Verknüpfung). Zum Öffnen wird die Datei in den Datenordner kopiert, weil der
Entpackordner der EXE beim Beenden gelöscht wird.
"""
from __future__ import annotations

import os
import shutil
import sys

DATEIEN = {
    "schuldner": "FinanceFlow-Anleitung-Schuldner.pdf",
    "berater": "FinanceFlow-Handbuch-Schuldenberatung.pdf",
}


SMARTPHONE = "FinanceFlow-Schuldner.html"


def _basis() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def quellordner() -> str:
    return os.path.join(_basis(), "hilfe")


def smartphone_pfad() -> str | None:
    """Smartphone-Version für Schuldner (eine HTML-Datei), eingebettet wie die PDFs."""
    p = os.path.join(_basis(), "web", SMARTPHONE)
    return p if os.path.exists(p) else None


def pfad(art: str) -> str | None:
    p = os.path.join(quellordner(), DATEIEN[art])
    return p if os.path.exists(p) else None


def oeffnen(art: str, ziel_ordner: str | None = None) -> str | None:
    """Kopiert die Anleitung nach ziel_ordner/Hilfe und öffnet sie im PDF-Programm. Gibt den Pfad zurück (None: fehlt)."""
    from PySide6.QtCore import QStandardPaths, QUrl
    from PySide6.QtGui import QDesktopServices
    q = pfad(art)
    if not q:
        return None
    d = os.path.join(ziel_ordner or QStandardPaths.writableLocation(QStandardPaths.AppDataLocation), "Hilfe")
    os.makedirs(d, exist_ok=True)
    z = os.path.join(d, DATEIEN[art])
    try:
        shutil.copyfile(q, z)
    except OSError:           # z. B. noch im PDF-Programm geöffnet → vorhandene Kopie bzw. Original verwenden
        if not os.path.exists(z):
            z = q
    QDesktopServices.openUrl(QUrl.fromLocalFile(z))
    return z
