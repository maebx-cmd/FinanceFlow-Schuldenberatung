"""Beträge verbergen (wie in Banking-Apps): alle angezeigten Geldbeträge werden zu „•••••“.

Wirkt auf die Anzeige – Beschriftungen (QLabel, auch Kacheln/KPI), Tabellen (Tabelle) und Auswahllisten, die das
Programm befüllt. Erkannt wird jede Zahl mit Dezimalkomma (1.234,56 · −12,30 € · 0,0263) und jede ganze Zahl vor € oder einem
Währungscode (25.465 € · 500 THB). Datumsangaben, Stückzahlen und Uhrzeiten bleiben sichtbar.
Nicht betroffen: Eingabefelder (zum Bearbeiten braucht man den echten Wert), Meldungsfenster, PDFs und Exporte.
Der Originaltext bleibt am Widget gespeichert, deshalb wird beim Umschalten nichts neu berechnet.
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QListWidget, QTableWidget

MASKE = "•••••"
ROH = "ff_roh"                  # Property am QLabel
ROLLE = Qt.UserRole + 77        # Rolle am Tabellen-/Combo-Eintrag
# a) jede Zahl mit Dezimalkomma  b) ganze Zahlen direkt vor € / EUR / Währungscode (THB …)  c) 12.000 (Tausenderpunkt)
_BETRAG = re.compile(r"(?<![\w,.])[-−+]?(?:\d+(?:\.\d{3})*(?:,\d+|(?=\s?(?:€|[A-Z]{3}\b)))"
                     r"|\d{1,3}(?:\.\d{3})+(?![\d.]))")
_ZIFFER = re.compile(r"\d")

_aktiv = False
_orig_set_text = QLabel.setText


def aktiv() -> bool:
    return _aktiv


def verdecken(text):
    """Text mit verdeckten Beträgen (unverändert, wenn ausgeschaltet oder kein Text)."""
    if not _aktiv or not isinstance(text, str) or not _ZIFFER.search(text):
        return text
    return _BETRAG.sub(MASKE, text)


def _label_set_text(self, text):
    if isinstance(text, str) and _ZIFFER.search(text):
        self.setProperty(ROH, text)
    elif self.property(ROH) is not None:
        self.setProperty(ROH, None)
    _orig_set_text(self, verdecken(text))


QLabel.setText = _label_set_text


def tabellen_text(item, text: str):
    """Für Tabelle.set_rows: Original merken, ggf. verdeckt anzeigen."""
    if _ZIFFER.search(text):
        item.setData(ROLLE, text)
        item.setText(verdecken(text))


def listen_text(item):
    """QListWidgetItem bzw. QTableWidgetItem: Original merken, ggf. verdeckt anzeigen (gibt das Item zurück)."""
    t = item.text()
    if _ZIFFER.search(t):
        item.setData(ROLLE, t)
        item.setText(verdecken(t))
    return item


def combo_text(cb: QComboBox, i: int):
    t = cb.itemText(i)
    if _ZIFFER.search(t):
        cb.setItemData(i, t, ROLLE)
        cb.setItemText(i, verdecken(t))


def umschalten(an: bool | None = None) -> bool:
    """Ein-/Ausschalten und alle vorhandenen Anzeigen sofort umstellen."""
    global _aktiv
    _aktiv = (not _aktiv) if an is None else bool(an)
    app = QApplication.instance()
    if app is None:
        return _aktiv
    for w in app.allWidgets():
        if isinstance(w, QLabel):
            roh = w.property(ROH)
            if roh is not None:
                _orig_set_text(w, verdecken(roh))
        elif isinstance(w, QTableWidget):
            for r in range(w.rowCount()):
                for c in range(w.columnCount()):
                    it = w.item(r, c)
                    roh = it.data(ROLLE) if it else None
                    if roh is not None:
                        it.setText(verdecken(roh))
        elif isinstance(w, QListWidget):
            for i in range(w.count()):
                it = w.item(i)
                roh = it.data(ROLLE)
                if roh is not None:
                    it.setText(verdecken(roh))
        elif isinstance(w, QComboBox):
            for i in range(w.count()):
                roh = w.itemData(i, ROLLE)
                if roh is not None:
                    w.setItemText(i, verdecken(roh))
    return _aktiv
