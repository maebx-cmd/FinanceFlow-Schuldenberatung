"""SQLite-Schema – 1:1 zum Prisma-Schema (packages/api/prisma/schema.prisma).

Konventionen: Spaltennamen wie in Prisma (camelCase), Decimal als TEXT, Boolean als 0/1,
@db.Date als 'YYYY-MM-DD', DateTime als ISO-Text, Json als TEXT.
Weggelassen (Web-only): auth_*, TotpSecret, TempToken, UserLiabilityAccess, ProfileChangeRequest,
SmartHomeState, GpsFavorite, GpsPoint, VehicleTelemetry, ReportTemplate, IncomeEntry.
Schuldenberatungs-Ausgabe: ohne HR & Worktime, Aviation Tools und Tankbuch (deren Modelle werden beim Abgleich ignoriert).
Konten und Buchungen gibt es ab 1.6.0 nicht mehr (wie Web): IBAN an der Verbindlichkeit, Zahlungen als Korrektur/ClaimPayment.
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS contact (id INTEGER PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'BEIDE',
  company TEXT, address TEXT, zipCode TEXT, city TEXT, country TEXT DEFAULT 'Österreich', phone TEXT, email TEXT,
  iban TEXT, bic TEXT, notes TEXT, correctionMinutes INTEGER NOT NULL DEFAULT 0, isActive INTEGER NOT NULL DEFAULT 1,
  createdAt TEXT);

CREATE TABLE IF NOT EXISTS category (id INTEGER PRIMARY KEY, name TEXT NOT NULL, parentId INTEGER REFERENCES category(id),
  catType TEXT NOT NULL DEFAULT 'FIX', color TEXT NOT NULL DEFAULT '#4F6BED', sortOrder INTEGER NOT NULL DEFAULT 0,
  isActive INTEGER NOT NULL DEFAULT 1);

CREATE TABLE IF NOT EXISTS household_scenario (id INTEGER PRIMARY KEY, name TEXT NOT NULL, salaryScenarioId INTEGER,
  manualNetMonthly TEXT, manualNetSz13 TEXT, manualNetSz14 TEXT, createdAt TEXT);

CREATE TABLE IF NOT EXISTS fixed_cost (id INTEGER PRIMARY KEY, name TEXT NOT NULL, categoryId INTEGER REFERENCES category(id),
  plannedAmount TEXT NOT NULL, actualAmount TEXT, dueDay INTEGER, isActive INTEGER NOT NULL DEFAULT 1, notes TEXT,
  correctionMinutes INTEGER NOT NULL DEFAULT 0, createdAt TEXT,
  householdScenarioId INTEGER REFERENCES household_scenario(id));

CREATE TABLE IF NOT EXISTS variable_expense (id INTEGER PRIMARY KEY, name TEXT NOT NULL, categoryId INTEGER REFERENCES category(id),
  plannedAmount TEXT NOT NULL, isActive INTEGER NOT NULL DEFAULT 1, notes TEXT, correctionMinutes INTEGER NOT NULL DEFAULT 0,
  createdAt TEXT, householdScenarioId INTEGER REFERENCES household_scenario(id));

CREATE TABLE IF NOT EXISTS liability (id INTEGER PRIMARY KEY, contactId INTEGER NOT NULL REFERENCES contact(id), name TEXT NOT NULL,
  originalBalance TEXT NOT NULL, currentBalance TEXT NOT NULL, interestRate TEXT NOT NULL DEFAULT '0', interestType TEXT NOT NULL DEFAULT 'FIX',
  repaymentType TEXT NOT NULL, repaymentValue TEXT, repaymentPercentage TEXT, repaymentMinimum TEXT, totalInstallments INTEGER,
  startDate TEXT, endDate TEXT, dueDay INTEGER, allowAvalanche INTEGER NOT NULL DEFAULT 0, isBankruptcyEligible INTEGER NOT NULL DEFAULT 1,
  isPaymentPlan INTEGER NOT NULL DEFAULT 0, paymentPlanRate TEXT, paymentPlanMonths INTEGER, paymentPlanInterval INTEGER DEFAULT 1,
  paymentPlanStart TEXT, status TEXT NOT NULL DEFAULT 'OFFEN', notes TEXT, correctionMinutes INTEGER NOT NULL DEFAULT 0,
  deletedAt TEXT, version INTEGER NOT NULL DEFAULT 1, createdAt TEXT, updatedAt TEXT, isInAbschoepfung INTEGER NOT NULL DEFAULT 0,
  iban TEXT, zahlungsreferenz TEXT, verwendungszweck TEXT);

CREATE TABLE IF NOT EXISTS abschoepfungs_verfahren (id INTEGER PRIMARY KEY, startDate TEXT NOT NULL, durationMonths INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'AKTIV', restschuldbefreiungAt TEXT, notes TEXT, createdAt TEXT, updatedAt TEXT);

CREATE TABLE IF NOT EXISTS abschoepfungs_liability (id INTEGER PRIMARY KEY, verfahrenId INTEGER NOT NULL REFERENCES abschoepfungs_verfahren(id),
  liabilityId INTEGER NOT NULL REFERENCES liability(id), snapshotBalance TEXT NOT NULL, quota TEXT NOT NULL,
  UNIQUE(verfahrenId, liabilityId));

CREATE TABLE IF NOT EXISTS abschoepfungs_rate (id INTEGER PRIMARY KEY, verfahrenId INTEGER NOT NULL REFERENCES abschoepfungs_verfahren(id),
  rateNo INTEGER NOT NULL, month TEXT NOT NULL, sollAmount TEXT, paidAmount TEXT, paidAt TEXT,
  createdAt TEXT, UNIQUE(verfahrenId, rateNo));

CREATE TABLE IF NOT EXISTS liability_correction (id INTEGER PRIMARY KEY, liabilityId INTEGER NOT NULL REFERENCES liability(id),
  correctionType TEXT NOT NULL, amountBefore TEXT NOT NULL, amountChange TEXT NOT NULL, amountAfter TEXT NOT NULL,
  description TEXT, correctionDate TEXT NOT NULL, createdAt TEXT, abschoepfungsRateId INTEGER);

CREATE TABLE IF NOT EXISTS fixed_cost_payment (id INTEGER PRIMARY KEY, fixedCostId INTEGER NOT NULL REFERENCES fixed_cost(id),
  month TEXT NOT NULL, plannedAmount TEXT NOT NULL, paidAt TEXT, paidAmount TEXT, createdAt TEXT,
  UNIQUE(fixedCostId, month));

CREATE TABLE IF NOT EXISTS claim (id INTEGER PRIMARY KEY, contactId INTEGER NOT NULL REFERENCES contact(id), name TEXT NOT NULL,
  originalAmount TEXT NOT NULL, currentAmount TEXT NOT NULL, interestRate TEXT NOT NULL DEFAULT '0', interestType TEXT NOT NULL DEFAULT 'FIX',
  dueDate TEXT, paymentTerms TEXT, status TEXT NOT NULL DEFAULT 'OFFEN', notes TEXT, correctionMinutes INTEGER NOT NULL DEFAULT 0,
  createdAt TEXT, updatedAt TEXT);

CREATE TABLE IF NOT EXISTS claim_payment (id INTEGER PRIMARY KEY, claimId INTEGER NOT NULL REFERENCES claim(id),
  amount TEXT NOT NULL, description TEXT, paymentDate TEXT NOT NULL, createdAt TEXT);

CREATE TABLE IF NOT EXISTS salary_calculation (id INTEGER PRIMARY KEY, calcType TEXT NOT NULL, name TEXT NOT NULL,
  periodMonth INTEGER, periodYear INTEGER, kvName TEXT, lohnGruppe TEXT, stufe TEXT, hoursTarget TEXT, hoursActual TEXT,
  hourlyRate TEXT, monthlyBase TEXT, allowance TEXT, grossMonthly TEXT, svRateKv TEXT, svRatePv TEXT, svRateAv TEXT, svRateAk TEXT,
  svRateWbf TEXT, svTotalRate TEXT, svAmount TEXT, bmgLst TEXT, lstRate TEXT, lstAmount TEXT, trafficDeduction TEXT,
  generalDeduction TEXT, netMonthly TEXT, grossSz13 TEXT, svRateSz TEXT, svSz13 TEXT, bmgLstSz13 TEXT, lstSz13 TEXT, netSz13 TEXT,
  grossSz14 TEXT, svSz14 TEXT, bmgLstSz14 TEXT, lstSz14 TEXT, netSz14 TEXT, existenzminimumLfd TEXT, seizableLfd TEXT,
  existenzminimumSz13 TEXT, seizableSz13 TEXT, existenzminimumSz14 TEXT, seizableSz14 TEXT, seizableAnnual TEXT,
  seizableMonthlyBasis TEXT, deviationGross TEXT, deviationNet TEXT, isActive INTEGER NOT NULL DEFAULT 1, notes TEXT,
  correctionMinutes INTEGER NOT NULL DEFAULT 0, createdAt TEXT);

CREATE TABLE IF NOT EXISTS debt_repayment_plan (id INTEGER PRIMARY KEY, liabilityId INTEGER NOT NULL REFERENCES liability(id),
  monthNo INTEGER NOT NULL, monthDate TEXT NOT NULL, payment TEXT, interest TEXT, principal TEXT, endBalance TEXT,
  calculatedAt TEXT, paidAt TEXT, paidAmount TEXT, paidCorrectionId INTEGER);
CREATE INDEX IF NOT EXISTS ix_plan_l ON debt_repayment_plan(liabilityId, monthNo);

CREATE TABLE IF NOT EXISTS avalanche_result (id INTEGER PRIMARY KEY, runId TEXT NOT NULL, liabilityId INTEGER NOT NULL,
  monthNo INTEGER NOT NULL, monthDate TEXT NOT NULL, payment TEXT, interest TEXT, principal TEXT, endBalance TEXT,
  isTarget INTEGER NOT NULL DEFAULT 0, calculatedAt TEXT);

CREATE TABLE IF NOT EXISTS avalanche_run (id INTEGER PRIMARY KEY, runId TEXT UNIQUE NOT NULL, planBudget TEXT NOT NULL,
  totalInterest TEXT, totalMonths INTEGER, interestSaved TEXT, calculatedAt TEXT, isCurrent INTEGER NOT NULL DEFAULT 1);

CREATE TABLE IF NOT EXISTS bankruptcy_scenario (id INTEGER PRIMARY KEY, scenarioType TEXT NOT NULL, name TEXT, salaryCalcId INTEGER,
  grossMonthly TEXT, netMonthly TEXT, netSz13 TEXT, netSz14 TEXT, seizableLfd TEXT, seizableSz13 TEXT, seizableSz14 TEXT,
  seizableAnnual TEXT, seizableMonthlyBasis TEXT, totalEligibleDebt TEXT, monthlyAmount TEXT, durationMonths INTEGER,
  intervalMonths INTEGER DEFAULT 1, totalPayment TEXT, lastInstallment TEXT, quote TEXT, tilgungsplanMonths INTEGER DEFAULT 36, tilgungsplanTotal TEXT,
  tilgungsplanQuote TEXT, householdSurplus TEXT, creditorSnapshot TEXT, calculationSnapshot TEXT, notes TEXT,
  correctionMinutes INTEGER NOT NULL DEFAULT 0, createdAt TEXT);

CREATE TABLE IF NOT EXISTS sepa_export (id INTEGER PRIMARY KEY, msgId TEXT NOT NULL UNIQUE, version TEXT NOT NULL,
  erstellt TEXT NOT NULL, erstelltVon TEXT, ausfuehrung TEXT NOT NULL, anzahl INTEGER NOT NULL, summe TEXT NOT NULL,
  auftraggeberIban TEXT NOT NULL, xml TEXT NOT NULL, verworfenAm TEXT, bezahltAm TEXT);
CREATE TABLE IF NOT EXISTS sepa_export_posten (id INTEGER PRIMARY KEY, exportId INTEGER NOT NULL REFERENCES sepa_export(id),
  liabilityId INTEGER NOT NULL, monthNo INTEGER NOT NULL, faellig TEXT NOT NULL, betrag TEXT NOT NULL, empfaenger TEXT NOT NULL,
  iban TEXT NOT NULL, zweck TEXT, endToEndId TEXT NOT NULL, bezahltAm TEXT);
CREATE INDEX IF NOT EXISTS ix_sepa_posten_lm ON sepa_export_posten(liabilityId, monthNo);

-- 1.9.0 (nur EXE): Kontoblatt-Import. Zuordnung Konto → Verbindlichkeit und Gedächtnis je Kontoblatt-Zeile
-- (gebucht oder bewusst ignoriert), damit nichts doppelt gebucht und Ignoriertes nicht erneut angeboten wird.
CREATE TABLE IF NOT EXISTS kontoblatt_zuordnung (konto TEXT PRIMARY KEY, liabilityId INTEGER NOT NULL, geaendertAm TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kontoblatt_zeile (schluessel TEXT PRIMARY KEY, konto TEXT NOT NULL, datum TEXT NOT NULL,
  beleg TEXT, text TEXT, soll TEXT NOT NULL, haben TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('GEBUCHT','IGNORIERT')), liabilityId INTEGER, correctionId INTEGER,
  correctionType TEXT, amountChange TEXT, datei TEXT, erfasstAm TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_kontoblatt_corr ON kontoblatt_zeile(correctionId);

CREATE TABLE IF NOT EXISTS setting (id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, value TEXT, description TEXT,
  valueType TEXT NOT NULL DEFAULT 'string', updatedAt TEXT);

CREATE TABLE IF NOT EXISTS post_entry (id INTEGER PRIMARY KEY, entryType TEXT NOT NULL, entryDate TEXT NOT NULL,
  correspondent TEXT NOT NULL, purpose TEXT, reference TEXT, trackingNumber TEXT, notes TEXT,
  correctionMinutes INTEGER NOT NULL DEFAULT 0, isProcessed INTEGER NOT NULL DEFAULT 0, followupDate TEXT,
  isDone INTEGER NOT NULL DEFAULT 0, threadId INTEGER REFERENCES post_entry(id), contactId INTEGER, createdAt TEXT, updatedAt TEXT);

CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY, userId TEXT, action TEXT NOT NULL, entityType TEXT NOT NULL,
  entityId TEXT, oldValue TEXT, newValue TEXT, ipAddress TEXT, createdAt TEXT);
CREATE INDEX IF NOT EXISTS ix_audit ON audit_log(entityType, entityId);

"""

# Prisma-Modellname -> SQLite-Tabelle (für den Import)
TABLES = {
    "Contact": "contact", "Category": "category", "HouseholdScenario": "household_scenario",
    "FixedCost": "fixed_cost", "VariableExpense": "variable_expense", "Liability": "liability",
    "AbschoepfungsVerfahren": "abschoepfungs_verfahren",
    "AbschoepfungsLiability": "abschoepfungs_liability", "AbschoepfungsRate": "abschoepfungs_rate",
    "LiabilityCorrection": "liability_correction",
    "FixedCostPayment": "fixed_cost_payment", "Claim": "claim", "ClaimPayment": "claim_payment", "SalaryCalculation": "salary_calculation",
    "DebtRepaymentPlan": "debt_repayment_plan", "AvalancheRun": "avalanche_run", "AvalancheResult": "avalanche_result",
    "BankruptcyScenario": "bankruptcy_scenario", "SepaExport": "sepa_export",
    "SepaExportPosten": "sepa_export_posten", "Setting": "setting", "PostEntry": "post_entry", "AuditLog": "audit_log",
}

# Spalten mit Prisma-Typ @db.Date (nur Datum)
DATE_COLS = {
    "liability": {"startDate", "endDate", "paymentPlanStart"},
    "abschoepfungs_verfahren": {"startDate"},
    "abschoepfungs_rate": {"month"},
    "liability_correction": {"correctionDate"},
    "fixed_cost_payment": {"month"},
    "claim": {"dueDate"},
    "claim_payment": {"paymentDate"},
    "debt_repayment_plan": {"monthDate"},
    "avalanche_result": {"monthDate"},
    "post_entry": {"entryDate", "followupDate"},
    "sepa_export": {"ausfuehrung"},
    "sepa_export_posten": {"faellig"},
}
