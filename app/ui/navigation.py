"""Navigation: Bereiche (Shell-Bar-Auswahl) mit ihren Seiten. None = Trenner.

Schuldenberatungs-Ausgabe: nur der Bereich FinanceFlow (ohne HR & Worktime, Aviation Tools, Tankbuch,
Mobile Erfassung und Kassabuch Devisen)."""
from .pages import abgleich as ag
from .pages import finanz1 as f1
from .pages import finanz2 as f2
from .pages import finanz3 as f3
from .pages import kontoblatt as kbl
from .pages import sepa as sp

BEREICHE = [
    ("finance", "FinanceFlow", [
        ("start", "Übersicht", f1.StartSeite),
        ("dashboard", "Dashboard", f1.DashboardSeite),
        None,
        ("kontakte", "Kontakte (Gläubiger)", f3.KontakteSeite),
        ("verbindlichkeiten", "Verbindlichkeiten", f1.VerbindlichkeitenSeite),
        ("offene_raten", "Offene Raten", f1.OffeneRatenSeite),
        ("zahlungsdatei", "Zahlungsdatei", sp.ZahlungsdateiSeite),
        ("kontoblatt", "Kontoblatt-Import", kbl.KontoblattSeite),
        ("forderungen", "Forderungen", f1.ForderungenSeite),
        ("haushalt", "Haushaltsrechnung", f2.HaushaltSeite),
        ("fixkosten", "Fixkosten", f2.FixkostenSeite),
        None,
        ("lohn", "Lohnberechnung", f2.LohnSeite),
        ("steuertarif", "Steuertarif", f2.SteuertarifSeite),
        ("avalanche", "Avalanche", f2.AvalancheSeite),
        ("privatkonkurs", "Privatkonkurs", f3.PrivatkonkursSeite),
        ("abschoepfung", "Abschöpfung", f3.AbschoepfungSeite),
        ("zahlungsplan", "Zahlungsplan", f3.ZahlungsplanSeite),
        ("postbuch", "Postbuch", f3.PostbuchSeite),
        ("reports", "Reports", f3.ReportsSeite),
        None,
        ("kategorien", "Kategorien", f3.KategorienSeite),
        ("einstellungen", "Einstellungen", f3.EinstellungenSeite),
        ("abgleich", "Abgleich", ag.AbgleichSeite),
    ]),
]
