# FinanceFlow Schuldenberatung

**Schulden erfassen, ordnen und mit der Schuldenberatung austauschen – für Windows, ohne Server.**

FinanceFlow Schuldenberatung ist ein Windows-Programm für Schuldnerinnen und Schuldner **und** für
Schuldenberatungsstellen. Schuldner tragen ihre Gläubiger und Schulden auf dem eigenen Gerät ein und geben der
Beratung eine verschlüsselte Datei. Die Beratung führt damit ihre Mandanten, rechnet Zahlungspläne und gibt einen
überarbeiteten Stand zurück.

**⬇ Download:** [neueste Version (MSI-Installationspaket)](https://github.com/maebx-cmd/FinanceFlow-Schuldenberatung/releases/latest) ·
**📱 Ohne Computer:** [FinanceFlow Light](https://maebx-cmd.github.io/FinanceFlow-Light/) fürs Smartphone

---

## Zwei Betriebsarten

Beim ersten Start wird gewählt, wer das Programm auf diesem Computer verwendet:

| | Schuldnerin / Schuldner | Schuldenberatung |
|---|---|---|
| Anmeldung | nur Passwort | Benutzername und Passwort |
| Benutzerverwaltung | – | Administrator legt Zugänge für Kolleg:innen an |
| Mandanten | – (ein eigener Datenstand) | beliebig viele, je eigener verschlüsselter Datenstand |
| Hilfe | Einführung in einfacher Sprache, „Erste Schritte“, Anleitung (PDF) | Handbuch (PDF) |
| Abgleich | Datei für die Beratung erstellen / Datei der Beratung einspielen | Datei des Schuldners einspielen / Datei für den Schuldner erstellen |

## Funktionen

- **Gläubiger und Verbindlichkeiten** mit Tilgungsplan, Korrekturen (Zinsen, Inkasso- und Gerichtskosten,
  Teilerlass, Ratenzahlung …), IBAN-Prüfung, Offene Raten
- **Haushaltsrechnung** mit Szenarien, Fixkosten, Forderungen
- **Lohnberechnung** nach österreichischem Recht mit **Existenzminimum und pfändbarem Betrag (§ 291a EO)**, Steuertarif
- **Privatkonkurs:** Zahlungsplan- und Tilgungsplan-Szenarien, Vergleich, Abschöpfungsverfahren, Zahlungsplan mit
  einheitlicher Quote – centgenau
- **Postbuch** mit Wiedervorlagen, **SEPA-Zahlungsdatei**, Kontoblatt-Import
- **Reports als PDF:** Gläubigerverzeichnis, Verbindlichkeitenübersicht, Zahlungsplan-Übersicht, 12-Monats-Vorschau,
  Haushaltsrechnung, Privatkonkurs-Szenarien u. v. m.
- **Mandantenverwaltung** für Beratungsstellen: Suche, Archiv, Protokoll, Übergabe an Kolleg:innen
- **Beträge verbergen** (Strg + B) für Gespräche mit Publikum

## Datenschutz und Sicherheit

- Alle Daten bleiben auf dem Computer – **kein Server, keine Cloud, keine Internetverbindung nötig**.
- Datenbanken und Sicherungen sind mit **SQLCipher (AES-256)** verschlüsselt; jeder Zugang und jeder Mandant hat einen
  eigenen Schlüssel. Ein **Wiederherstellungsschlüssel** ersetzt ein vergessenes Passwort.
- Die Abgleich-Datei (`*.ffsync`) ist mit **PBKDF2-HMAC-SHA256 (600.000) und AES-256-GCM** verschlüsselt; das Passwort
  wird getrennt weitergegeben.
- Automatische Sicherungen täglich, vor Updates und vor jedem Einspielen.

## Installation

1. Unter [Releases](https://github.com/maebx-cmd/FinanceFlow-Schuldenberatung/releases/latest) die Datei `FinanceFlow-Schuldenberatung-<Version>.msi` herunterladen.
2. Doppelklick, Windows-Rückfrage mit **Ja** bestätigen.
3. Programm über Desktop oder Startmenü starten; dort liegen auch Anleitung, Handbuch und die Smartphone-Version.

Für die IT: stille Installation mit `msiexec /i FinanceFlow-Schuldenberatung-<Version>.msi /qn`. Neue Versionen
ersetzen die alte automatisch. Daten liegen je Benutzer in `%APPDATA%\FinanceFlow\Schuldenberatung` und bleiben bei der
Deinstallation erhalten.

Voraussetzung: Windows 10 oder 11, 64 Bit.

## Dokumentation

- [Anleitung für Schuldnerinnen und Schuldner](hilfe/FinanceFlow-Anleitung-Schuldner.pdf) (einfache Sprache)
- [Handbuch für die Schuldenberatung](hilfe/FinanceFlow-Handbuch-Schuldenberatung.pdf)
- [Abgleich-Format](docs/ABGLEICH-FORMAT.md)

---

## Für Entwickler

Python 3.12 · PySide6 (SAP-Fiori-Optik) · SQLite/SQLCipher · ReportLab · PyInstaller · MSI mit wixl bzw. WiX 3.
Beruht auf FinanceFlow Desktop 2.2.0, ohne die Module HR & Worktime, Aviation Tools (inkl. Tankbuch), Mobile Erfassung
und Kassabuch Devisen. Das Abgleich-Format ist mit FinanceFlow Desktop, Android und iOS kompatibel.

### Aufbau

| Pfad | Inhalt |
|---|---|
| `app/konten.py` | Zugänge, Betriebsart (Tabelle `einrichtung` in `benutzer.db`), umhüllte Profilschlüssel |
| `app/mandanten.py`, `app/ui/mandanten_fenster.py` | Mandantenverzeichnis (SQLCipher), Mandantenschlüssel = HMAC-SHA256(Profilschlüssel, ID), Übersicht |
| `app/abgleich/` | `*.ffsync` – nur Teil „finanzen“; Pläne werden nach dem Einspielen ergänzt (`plaene_ergaenzen`) |
| `app/ui/einfuehrung.py`, `app/ui/pages/launcher.py` | Einführung und „Erste Schritte“ für Schuldner |
| `web/FinanceFlow-Schuldner.html` | Smartphone-Version (veröffentlicht als [FinanceFlow Light](https://github.com/maebx-cmd/FinanceFlow-Light)) |
| `docs/*.md` → `hilfe/*.pdf` | Anleitung und Handbuch (`python tools/handbuecher.py`) |
| `installer/` | MSI-Beschreibung (`*.wxs`) und Programmsymbol |

### Bauen

**GitHub Actions:** Jeder Push auf `main` testet, baut die EXE (Windows) und daraus das MSI (Ubuntu, wixl) und
veröffentlicht das Release `v<APP_VERSION>` mit MSI, EXE, PDFs und Smartphone-Version. Neue Version veröffentlichen =
`APP_VERSION` in `app/__init__.py` erhöhen und pushen (ein Push mit gleicher Version aktualisiert das bestehende Release).

**Windows:** `build.bat` → `dist\FinanceFlow-Schuldenberatung.exe`, mit installiertem WiX Toolset 3 auch das MSI.

**Linux (aus einer fertigen EXE):** `sudo apt-get install wixl`, dann `tools/msi_bauen.sh <Ordner mit der EXE>`.

### Entwicklung

```
pip install -r requirements.txt pytest
python -m pytest -q tests
python main.py
QT_QPA_PLATFORM=offscreen python tools/bildschirmfotos.py docs/bilder_neu   # Bildschirmfotos für die Handbücher
python tools/handbuecher.py                                                # PDFs nach hilfe/
```

Der UpgradeCode im MSI (`installer/FinanceFlow-Schuldenberatung.wxs`) darf nie geändert werden, sonst ersetzen neue
Versionen die alten nicht mehr.
