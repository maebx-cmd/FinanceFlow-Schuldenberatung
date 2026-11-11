"""Fenstergerüst: Shell Bar oben, Seitennavigation links, Seitenstapel rechts.

Neue Seite = Klasse mit __init__(self, state) + Eintrag in NAV (key, Titel, Klasse).
Seiten kommunizieren nur über AppState-Signale (daten_geaendert, kontext_geaendert).
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QListWidget, QListWidgetItem, QMainWindow, QStackedWidget,
                               QVBoxLayout, QWidget)

from .. import APP_NAME, APP_TITEL, APP_VERSION
from .widgets import label


class AppState(QObject):
    daten_geaendert = Signal()      # nach jedem Speichern auslösen -> alle Seiten aktualisieren
    kontext_geaendert = Signal()    # z. B. Periode/Mandant in der Shell Bar geändert

    def __init__(self, db):
        super().__init__()
        self.db = db


class MainWindow(QMainWindow):
    def __init__(self, db, nav, shell_rechts=None):
        """nav: Liste von (key, Titel, Seitenklasse) oder None für einen Abstand."""
        super().__init__()
        self.setWindowTitle(f"{APP_TITEL} {APP_VERSION}")
        self.resize(1440, 900)
        self.state = AppState(db)
        central = QWidget()
        root = QVBoxLayout(central); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        shell = QFrame(); shell.setObjectName("shellbar"); shell.setFixedHeight(52)
        sh = QHBoxLayout(shell); sh.setContentsMargins(16, 0, 16, 0)
        logo = label("◆"); logo.setStyleSheet("color:#0064D9; font-size:18pt;")
        self.logo = logo
        sh.addWidget(logo)
        sh.addWidget(label(APP_NAME, "shelltitle"))
        self.shell_sub = label("", "shellsub")
        sh.addSpacing(12); sh.addWidget(self.shell_sub); sh.addStretch()
        for w in shell_rechts or []:          # z. B. Periodenwahl, Suchfeld, Benutzer
            sh.addWidget(w)
        root.addWidget(shell)

        body = QHBoxLayout(); body.setSpacing(0)
        self.nav = QListWidget(); self.nav.setObjectName("sidenav"); self.nav.setFixedWidth(210)
        self.stack = QStackedWidget()
        self.pages = {}
        for eintrag in nav:
            if eintrag is None:
                sep = QListWidgetItem(""); sep.setFlags(Qt.NoItemFlags); self.nav.addItem(sep)
                continue
            key, titel, cls = eintrag
            page = cls(self.state, self.navigate) if getattr(cls, "WANTS_NAVIGATE", False) else cls(self.state)
            self.pages[key] = page
            it = QListWidgetItem(titel); it.setData(Qt.UserRole, key)
            self.nav.addItem(it)
            self.stack.addWidget(page)
        self.nav.currentItemChanged.connect(
            lambda it, _p: it and it.data(Qt.UserRole) and self.stack.setCurrentWidget(self.pages[it.data(Qt.UserRole)]))
        body.addWidget(self.nav); body.addWidget(self.stack, 1)
        root.addLayout(body, 1)
        self.setCentralWidget(central)
        self.navigate(nav[0][0])

    def navigate(self, key):
        for i in range(self.nav.count()):
            if self.nav.item(i).data(Qt.UserRole) == key:
                self.nav.setCurrentRow(i)
                return
