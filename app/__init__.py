"""FinanceFlow Schuldenberatung – PySide6 + SQLite/SQLCipher, Fiori-Look.

Ausgabe von FinanceFlow Desktop 2.2.0 für den Einsatz in der Schuldenberatung: ohne HR & Worktime, Aviation Tools,
Tankbuch, Mobile Erfassung und Kassabuch Devisen. Beim ersten Start wird gewählt, wer das Programm nutzt:
  SCHULDNER – ein einziger Zugang, eigener Datenstand, Einführung in einfacher Sprache
  BERATER   – Schuldenberatung mit Benutzer- und Mandantenverwaltung; spielt Abgleich-Dateien der Schuldner ein
"""

APP_NAME = "FinanceFlow"
EDITION = "Schuldenberatung"
APP_TITEL = f"{APP_NAME} {EDITION}"
APP_VERSION = "1.0.0"
BASIS_VERSION = "2.2.0"   # FinanceFlow Desktop, auf dem diese Ausgabe beruht
SCHEMA_VERSION = 5   # bei jeder Strukturänderung erhöhen + Migration in db_base.MIGRATIONEN
