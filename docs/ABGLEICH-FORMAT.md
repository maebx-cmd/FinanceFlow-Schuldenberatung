# FinanceFlow – Abgleich-Format (*.ffsync), Version 1

> **Schuldenberatungs-Ausgabe:** schreibt nur den Teil `finanzen` (ohne HR-, Aviation- und Tankbuch-Modelle) und das
> zusätzliche Feld `"edition": "Schuldenberatung"` im Klartext. Beim Einspielen wird ein Teil `mobil` ignoriert; eine
> Datei ohne `finanzen` wird abgelehnt („Die Datei enthält keine Finanzdaten“). Die Vollversion ignoriert `edition`.

Gilt identisch für EXE (Desktop), APK (Android) und iOS. Referenzimplementierung: `app/abgleich/krypto.py`, `app/abgleich/abgleich.py`.

## Datei (JSON, UTF-8)
```json
{"format": "financeflow-sync", "version": 1,
 "kdf":    {"name": "PBKDF2-HMAC-SHA256", "iterations": 600000, "salt": "<Base64, 16 Zufallsbytes>"},
 "cipher": {"name": "AES-256-GCM", "nonce": "<Base64, 12 Zufallsbytes>"},
 "data":   "<Base64 von Ciphertext||Tag (16 Byte)>"}
```
- Schlüssel = PBKDF2-HMAC-SHA256(Passwort UTF-8, salt, 600000, 32 Byte); AAD = `financeflow-sync/1`; Salt und Nonce je Export neu.
- Dateiname: `FinanceFlow-JJJJ-MM-TT-hhmm-<Gerät>.ffsync` (Gerät: nur A–Z, a–z, 0–9, „-“).
- Testvektor: Passwort `Test-Passwort 123`, salt `AAECAwQFBgcICQoLDA0ODw==`, nonce `ZGVmZ2hpamtsbW5v`,
  Schlüssel `bf30a34136d2aa901a886beed01e182eda1adc67ddaf5a1daa24cf9bb5dbc540`, Klartext `{"hallo":"welt","betrag":"241.94"}`,
  data `ITa9cyty+9EMjOCd1gp9gpQpxfLmV75p9/1DmHWfO9g7+Jy7m7B2jNzCsZqU9RCT5uk=`.
- Fehler: Tag-Fehler/falsches Passwort → „Passwort falsch oder Datei beschädigt“; `version`/`schemaVersion` höher → „… Bitte App aktualisieren.“

## Klartext
```json
{"schemaVersion": 1, "exportedAt": "JJJJ-MM-TTThh:mm:ss", "device": "...", "appVersion": "...",
 "teile": {"finanzen": {"geaendertAm": "...|null", "daten": {"<Prisma-Modell>": [{Zeile}]}},
           "mobil":    {"geaendertAm": "...|null", "daten": {"<Tabelle>": [{Zeile}]}}}}
```
- **finanzen**: vollständiger Finanzbestand als {Modell: [Zeilen]} (Schlüssel = Prisma-Modellnamen wie „Liability“, Beträge als Dezimal-Strings). Seit 2.0.0 der einzige Weg, Daten zwischen Geräten zu übertragen – unverschlüsselte JSON-Exporte gibt es nicht mehr.
- **mobil**: Tabellen unten, Zeilen als Objekte (Spaltenname → Wert), sortiert nach Primärschlüssel.
  Euro immer in **Cent (Ganzzahl)**, Fremdwährung in **kleinsten Einheiten (Ganzzahl)**, Kurse als Dezimal-String, Datum `JJJJ-MM-TT`,
  Zeitpunkte `JJJJ-MM-TTThh:mm:ss` (Ortszeit), Ja/Nein als 0/1. **Nie Gleitkommazahlen** (Import lehnt ab).
- Import: Ein gewählter Teil ersetzt den lokalen Teil vollständig in einer Transaktion, vorher Sicherung. `mobile_zaehler`
  (M-Nummernzähler) kommt immer mit „mobil“ mit; Prüfung: jeder festgeschriebene Beleg ausgeglichen, Zähler ≥ höchste `nr`.

## Tabellen des Teils „mobil“ (Einfüge-Reihenfolge)
- **mobile_konto**: `konto` TEXT, `bezeichnung` TEXT, `uebergeordnet` TEXT, `klasse` TEXT, `gruppe` TEXT, `kontotyp` TEXT, `steuercode` TEXT, `bebuchbar` INTEGER, `aktiv` INTEGER, `herkunft` TEXT, `extra` TEXT, `erstellt_am` TEXT, `geaendert_am` TEXT
- **mobile_export**: `id` INTEGER, `erstellt_am` TEXT, `erstellt_von` TEXT, `dateiname` TEXT, `anzahl_belege` INTEGER, `anzahl_zeilen` INTEGER, `csv` TEXT
- **mobile_beleg**: `id` INTEGER, `status` TEXT, `nr` INTEGER, `belegnummer` TEXT, `belegdatum` TEXT, `fremdbeleg` TEXT, `buchungstext` TEXT, `erstellt_von` TEXT, `erstellt_am` TEXT, `geaendert_am` TEXT, `festgeschrieben_am` TEXT, `export_id` INTEGER
- **mobile_zeile**: `id` INTEGER, `beleg_id` INTEGER, `pos` INTEGER, `konto` TEXT, `soll` INTEGER, `haben` INTEGER, `text` TEXT
- **mobile_zaehler**: `name` TEXT, `wert` INTEGER
- **devisen_einstellung**: `key` TEXT, `value` TEXT
- **devisen_kassabuch**: `id` INTEGER, `bezeichnung` TEXT, `waehrung` TEXT, `waehrung_name` TEXT, `dezimalstellen` INTEGER, `eroeffnung` TEXT, `beschreibung` TEXT, `kassakonto` TEXT, `bankkonto` TEXT, `gebuehrkonto` TEXT, `kursgewinnkonto` TEXT, `kursverlustkonto` TEXT, `aktiv` INTEGER, `erstellt_am` TEXT, `erstellt_von` TEXT, `geaendert_am` TEXT
- **devisen_vorgang**: `id` INTEGER, `kassabuch_id` INTEGER, `lfd_nr` INTEGER, `art` TEXT, `belegdatum` TEXT, `gebucht_am` TEXT, `text` TEXT, `empfaenger` TEXT, `referenz` TEXT, `notiz` TEXT, `gegenkonto` TEXT, `fw_zugang` INTEGER, `fw_abgang` INTEGER, `eur_zugang` INTEGER, `eur_abgang` INTEGER, `kurs` TEXT, `kurs_quelle` TEXT, `bank_kurs` TEXT, `eur_belastung` INTEGER, `gebuehr_eur` INTEGER, `gebuehr_fw` INTEGER, `gebuehr_enthalten` INTEGER, `eur_gegenwert` INTEGER, `kursdifferenz` INTEGER, `bezug_vorgang_id` INTEGER, `storniert_durch` INTEGER, `beleg_id` INTEGER, `belegnummer` TEXT, `hinweise` TEXT, `erstellt_von` TEXT
- **devisen_tranche**: `id` INTEGER, `kassabuch_id` INTEGER, `vorgang_id` INTEGER, `nr` INTEGER, `datum` TEXT, `fw_ursprung` INTEGER, `eur_ursprung` INTEGER, `kurs` TEXT, `fw_rest` INTEGER, `eur_rest` INTEGER, `storniert` INTEGER
- **devisen_verbrauch**: `id` INTEGER, `vorgang_id` INTEGER, `tranche_id` INTEGER, `richtung` INTEGER, `fw_menge` INTEGER, `eur_wert` INTEGER, `eur_exakt` TEXT, `rundungsdiff` TEXT, `kurs` TEXT, `fw_rest_danach` INTEGER, `eur_rest_danach` INTEGER
- **devisen_protokoll**: `id` INTEGER, `kassabuch_id` INTEGER, `vorgang_id` INTEGER, `aktion` TEXT, `details` TEXT, `benutzer` TEXT, `zeit` TEXT

## Merker und Status (nicht Teil der Datei)
Je Teil „lokal geändert seit letztem Abgleich“ (bei jeder Änderung gesetzt, nach Export/Import des Teils gelöscht) sowie
letzter Abgleich (Zeitpunkt, Gerät, Richtung Export/Import). Warnung beim Import:
„Auf diesem Gerät gibt es Änderungen in <Teil> seit dem letzten Abgleich – sie gehen verloren“ mit Knopf „Zuerst exportieren“.
Hinweis in der App: Mobile Erfassung immer nur auf dem Gerät weiterführen, das zuletzt importiert hat (lückenlose M-Nummern).
