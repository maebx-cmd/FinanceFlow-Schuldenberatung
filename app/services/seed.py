"""Standardwerte für eine neue, leere Datenbank (seed-settings.ts).

Wird nur ergänzt, wenn ein Schlüssel fehlt – vorhandene (z. B. importierte) Werte bleiben unangetastet.
"""
from __future__ import annotations

import json
from datetime import datetime

from ..calc.lohn import FALLBACK_TARIF

SETTINGS = [
    ("grundbetrag", "1308.00", "Grundbetrag Existenzminimum 2026 (§ 291a EO)", "number"),
    ("existenzminimum_stufe", "20", "Rundungsintervall Existenzminimum", "number"),
    ("existenzminimum_pct", "0.30", "Prozentsatz Existenzminimum (30%)", "number"),
    ("verkehrsabsetzbetrag", "41.33", "Verkehrsabsetzbetrag monatlich", "number"),
    ("sz_freibetrag", "620.00", "Freibetrag Sonderzahlung (13. Gehalt)", "number"),
    ("sv_kv", "0.0387", "KV-Beitrag Arbeitnehmer", "number"),
    ("sv_pv", "0.1025", "PV-Beitrag Arbeitnehmer", "number"),
    ("sv_ak", "0.005", "AK-Umlage", "number"),
    ("sv_wbf", "0.005", "WBF-Beitrag", "number"),
    ("av_grenze_1", "2225.00", "AV 0% bis Brutto", "number"),
    ("av_grenze_2", "2427.00", "AV 1% bis Brutto", "number"),
    ("av_grenze_3", "2630.00", "AV 2% bis Brutto", "number"),
    ("av_satz_1", "0.00", "AV-Satz Stufe 1 (0%)", "number"),
    ("av_satz_2", "0.01", "AV-Satz Stufe 2 (1%)", "number"),
    ("av_satz_3", "0.02", "AV-Satz Stufe 3 (2%)", "number"),
    ("av_satz_4", "0.0295", "AV-Satz Stufe 4 (2,95%)", "number"),
    ("lst_sz_satz", "0.06", "Lohnsteuersatz Sonderzahlungen (6%)", "number"),
    ("tilgungsplan_jahre", "3", "Laufzeit Tilgungsplan in Jahren", "number"),
    ("app_name", "FinanceFlow", "Anwendungsname", "string"),
    ("owner_name", "", "Name des Inhabers", "string"),
    ("owner_street", "", "Straße und Hausnummer (PDF-Kopf)", "string"),
    ("owner_city", "", "PLZ und Ort (PDF-Kopf)", "string"),
    ("currency", "EUR", "Währung", "string"),
    ("sepa_auftraggeber_name", "", "SEPA: Kontoinhaber (Auftraggeber)", "string"),
    ("sepa_auftraggeber_iban", "", "SEPA: IBAN des Auftraggebers", "string"),
    ("sepa_auftraggeber_bic", "", "SEPA: BIC des Auftraggebers (optional)", "string"),
    ("sepa_version", "09", "SEPA: Format pain.001.001.09 oder .03", "string"),
    ("sepa_sammelbuchung", "0", "SEPA: Sammelbuchung (1) oder Einzelbuchung (0)", "string"),
    ("sepa_vorlage", "{bezeichnung} Rate {rate} {monat}", "SEPA: Standard-Verwendungszweck", "string"),
    ("lst_tarif", json.dumps(FALLBACK_TARIF), "Lohnsteuertarif Österreich (7 Stufen)", "json"),
]

def seed_defaults(db):
    now = datetime.now().isoformat(timespec="seconds")
    with db.tx():
        have = {r["key"] for r in db.rows("SELECT key FROM setting")}
        for k, v, desc, typ in SETTINGS:
            if k not in have:
                db.insert("setting", {"key": k, "value": v, "description": desc, "valueType": typ, "updatedAt": now})
