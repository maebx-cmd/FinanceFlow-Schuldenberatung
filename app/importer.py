"""Teil „finanzen“ der verschlüsselten Abgleich-Datei (*.ffsync) einspielen.

Seit 2.0.0 gibt es keinen Import aus der Web-Version und keinen unverschlüsselten JSON-Export mehr: Daten wechseln
zwischen Geräten und Profilen nur noch als *.ffsync (AES-256-GCM). Struktur: {Modell: [Zeilen]} in der Reihenfolge ORDER.
Der Import ersetzt den gesamten Bestand in EINER Transaktion (bei Fehler bleibt alles unverändert).
"""
from __future__ import annotations

import json
from decimal import Decimal

from .schema import DATE_COLS, TABLES

ORDER = ["Contact", "Category", "HouseholdScenario", "FixedCost", "VariableExpense", "Liability",
         "AbschoepfungsVerfahren", "AbschoepfungsLiability", "AbschoepfungsRate", "LiabilityCorrection",
         "FixedCostPayment", "Claim", "ClaimPayment", "SalaryCalculation", "DebtRepaymentPlan", "AvalancheRun",
         "AvalancheResult", "BankruptcyScenario", "SepaExport", "SepaExportPosten", "Setting", "PostEntry", "AuditLog"]


def _conv(v, col, table):
    if v is None:
        return None
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=str)
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, str) and col in DATE_COLS.get(table, ()):
        return v[:10]
    return v


def importieren_daten(db, data: dict) -> dict:
    """Ersetzt den gesamten Datenbestand in EINER Transaktion. IDs (auch des Protokolls) bleiben erhalten,
    damit Export → Import → Export denselben Datenstand ergibt."""
    counts = {}
    con = db.con
    con.execute("PRAGMA foreign_keys=OFF")
    try:
        with db.tx():
            for model in reversed(ORDER):
                if model in data:
                    con.execute(f"DELETE FROM {TABLES[model]}")
            for model in ORDER:
                rows = data.get(model)
                if rows is None:
                    continue
                table = TABLES[model]
                cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
                n = 0
                for r in rows:
                    rec = {k: _conv(v, k, table) for k, v in r.items() if k in cols}
                    if not rec:
                        continue
                    ks = list(rec)
                    con.execute(f"INSERT INTO {table} ({','.join(ks)}) VALUES ({','.join('?' * len(ks))})",
                                [rec[k] for k in ks])
                    n += 1
                counts[model] = n
            bad = con.execute("PRAGMA foreign_key_check").fetchall()
            if bad:
                raise ValueError(f"Referenzfehler in der Datei ({len(bad)} Zeilen), Import abgebrochen. Beispiel: {tuple(bad[0])}")
    finally:
        con.execute("PRAGMA foreign_keys=ON")
    from .services.seed import seed_defaults
    seed_defaults(db)
    return counts
