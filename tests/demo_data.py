"""Demo-Bestand für Tests und Screenshots."""
from datetime import date, timedelta


def befuellen(db):
    k = {n: db.kontakt_speichern({"name": n, "role": "KREDITOR", "address": "Hauptstraße 1", "zipCode": "6020",
                                   "city": "Innsbruck", "iban": "AT611904300234573201"})
         for n in ["BAWAG P.S.K.", "Raiffeisen Tirol", "Inkasso Graz", "A1 Telekom", "Magenta"]}
    max_ = db.kontakt_speichern({"name": "Max Mustermann", "role": "DEBITOR"})
    l1 = db.verbindlichkeit_speichern({"contactId": k["BAWAG P.S.K."], "name": "Konsumkredit", "currentBalance": "18450",
                                       "interestRate": "6.9", "repaymentType": "FIX", "repaymentValue": "320", "dueDay": 5,
                                       "allowAvalanche": True, "iban": "AT48 3200 0000 1234 5864"})
    l2 = db.verbindlichkeit_speichern({"contactId": k["Raiffeisen Tirol"], "name": "Kontoüberziehung", "currentBalance": "4200",
                                       "interestRate": "11.5", "repaymentType": "PERCENT", "repaymentPercentage": "3",
                                       "repaymentMinimum": "50", "dueDay": 15, "allowAvalanche": True})
    l3 = db.verbindlichkeit_speichern({"contactId": k["Inkasso Graz"], "name": "Inkassoforderung", "currentBalance": "2380",
                                       "repaymentType": "OPEN", "dueDay": 1})
    l4 = db.verbindlichkeit_speichern({"contactId": k["A1 Telekom"], "name": "Handyrechnung", "currentBalance": "640",
                                       "repaymentType": "FIX", "repaymentValue": "40", "dueDay": 20})
    db.verbindlichkeit_speichern({"contactId": k["Magenta"], "name": "Altvertrag", "currentBalance": "310",
                                  "repaymentType": "OPEN", "isBankruptcyEligible": False})
    db.korrektur_buchen(l3, "INKASSOKOSTEN", betrag="125.40", beschreibung="Mahnspesen")
    db.in_zahlungsplan_umwandeln(l4, "50", 12, 3, date.today().replace(day=1).isoformat())
    l = db.verbindlichkeit(l1)
    db.planrate_bezahlen(l1, l["plan"][0]["id"])
    f = db.forderung_speichern({"contactId": max_, "name": "Privatdarlehen", "originalAmount": "1500",
                                "dueDate": (date.today() - timedelta(days=10)).isoformat()})
    db.forderung_zahlung(f, "300")
    for n, v, dd in [("Miete", "780", 1), ("Strom", "85", 10), ("Versicherung", "42.30", 15), ("Internet", "39.90", 20)]:
        db.ausgabe_speichern("fixed_cost", {"name": n, "plannedAmount": v, "dueDay": dd})
    for n, v in [("Lebensmittel", "380"), ("Tanken", "140"), ("Freizeit", "90")]:
        db.ausgabe_speichern("variable_expense", {"name": n, "plannedAmount": v})
    db.kategorie_speichern({"name": "Wohnen", "catType": "FIX", "color": "#0064D9"})
    db.lohn_speichern({"calcType": "SOLL", "name": "Soll 2026", "monthlyBase": "2650", "periodYear": 2026})
    db.lohn_speichern({"calcType": "SZENARIO", "name": "Mehr Stunden", "hourlyRate": "17.50", "hoursActual": "167"})
    r = db.konkurs_berechnen({"scenarioType": "ZAHLUNGSPLAN", "monthlyAmount": "350", "durationMonths": 60, "intervalMonths": 1,
                              "useExtended": True, "startDatum": date.today().isoformat()})
    db.konkurs_speichern(r, "Angebot 60 Monate")
    r = db.konkurs_berechnen({"scenarioType": "ZAHLUNGSPLAN", "inputMode": "PERCENT", "percentOfDebt": "25",
                              "durationMonths": 36, "intervalMonths": 6, "startDatum": date.today().isoformat()})
    db.konkurs_speichern(r, "25 % halbjährlich")
    db.post_speichern({"entryType": "EINGANG", "entryDate": date.today().isoformat(), "correspondent": "Bezirksgericht Innsbruck",
                       "purpose": "Ladung Tagsatzung", "reference": "12 S 34/26", "followupDate": (date.today() + timedelta(days=7)).isoformat()})
    return {"l1": l1, "l2": l2, "l3": l3, "l4": l4, "claim": f}
