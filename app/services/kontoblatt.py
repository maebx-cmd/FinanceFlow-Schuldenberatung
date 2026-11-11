"""Kontoblatt-Import (nur EXE): Buchungen aus einem Kontoblatt (CSV aus der Buchhaltung, z. B. 3121 inkl. Subkonten)
als Korrekturen bei der zugeordneten Verbindlichkeit einbuchen.

Regeln
- Jede Kontoblatt-Zeile hat einen Schlüssel aus Konto, Datum, Beleg, Belegkreis, Fremdbeleg, Text, Gegenkonto, Soll, Haben
  (+ laufende Nummer bei völlig gleichen Zeilen). NICHT im Schlüssel: Saldo (läuft mit) und Storno (ändert sich nachträglich).
- Gedächtnis je Schlüssel: GEBUCHT (mit Korrektur-Id) oder IGNORIERT. Gebuchtes wird nie doppelt gebucht, Ignoriertes
  beim nächsten Mal wieder ignoriert (kann bewusst doch gebucht werden).
- Verbindlichkeit = Passivkonto: Haben erhöht die Schuld, Soll vermindert sie. Änderung = Haben − Soll.
- Zuordnung Konto → Verbindlichkeit wird gemerkt.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from ..dates import iso
from ..db_base import FachFehler
from ..dec import d, f2

PFLICHT = ["Datum", "Beleg", "Konto", "Text", "Gegenkonto", "Soll", "Haben"]
OPTIONAL = ["Belegkreis", "Fremdbeleg", "Storno"]
_BETRAG = re.compile(r"^(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?$")
_DATUM = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$")

TYPEN_IMPORT = [("RATENZAHLUNG", "Ratenzahlung"), ("ZINSNACHTRAG", "Zinsnachtrag"), ("SALDOANPASSUNG", "Saldoanpassung"),
                ("GERICHTSKOSTEN", "Gerichtskosten / Verfahrenskosten"), ("INKASSOKOSTEN", "Inkassokosten"),
                ("ERLASS", "Teilerlass / Verzicht"), ("SONSTIG", "Sonstige Korrektur")]

# Status in der Vorschau
NEU, GEBUCHT, IGNORIERT, FEHLT, NULL = "NEU", "GEBUCHT", "IGNORIERT", "FEHLT", "NULL"
STATUS_TEXT = {NEU: "Neu", GEBUCHT: "Bereits gebucht", IGNORIERT: "Ignoriert (gemerkt)",
               FEHLT: "Neu – frühere Buchung nicht mehr vorhanden", NULL: "Ohne Saldowirkung – wird übersprungen"}


def betrag(text: str, wo: str) -> Decimal:
    t = (text or "").strip()
    if t == "":
        return Decimal("0.00")
    if not _BETRAG.match(t):
        raise FachFehler(f"{wo}: Betrag „{text}“ ist ungültig.")
    return d(t.replace(".", "").replace(",", "."))


def de_betrag(x: Decimal) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


@dataclass
class Zeile:
    nr: int                      # Zeile in der Datei (Kopfzeile = 1)
    datum: date
    beleg: str
    belegkreis: str
    fremdbeleg: str
    konto: str
    text: str
    gegenkonto: str
    soll: Decimal
    haben: Decimal
    storno: bool
    schluessel: str = ""
    gegenkonten: list = field(default_factory=list)

    @property
    def aenderung(self) -> Decimal:
        return self.haben - self.soll

    def vorschlag_typ(self) -> str:
        if self.soll > self.haben:
            return "RATENZAHLUNG"
        if self.gegenkonten and all(g.startswith("83") for g in self.gegenkonten):
            return "ZINSNACHTRAG"
        return "SALDOANPASSUNG"

    def beschreibung(self) -> str:
        teile = [self.text.strip() or (f"Gegenkonto {self.gegenkonto}" if self.gegenkonto else "Kontoblatt-Buchung")]
        teile.append(f"(Kontoblatt {self.konto}, {self.beleg})" if self.beleg else f"(Kontoblatt {self.konto})")
        return " ".join(teile)


def lesen(daten: bytes) -> list[Zeile]:
    """CSV (Semikolon, deutsches Zahlenformat) → Zeilen. Fehler brechen ab und nennen die Zeile."""
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = daten.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    r = list(csv.reader(io.StringIO(text), delimiter=";"))
    while r and not any(c.strip() for c in r[-1]):
        r.pop()
    if not r:
        raise FachFehler("Die Datei ist leer.")
    kopf = [c.strip() for c in r[0]]
    fehlt = [s for s in PFLICHT if s not in kopf]
    if fehlt:
        raise FachFehler("Kein Kontoblatt: Spalte(n) " + ", ".join(fehlt) + " fehlen. Erwartet: "
                         "Datum;Beleg;Belegkreis;Fremdbeleg;Konto;Text;Gegenkonto;Soll;Haben;Saldo;S/H;Storno")
    ix = {s: kopf.index(s) for s in PFLICHT + OPTIONAL if s in kopf}
    zeilen, zaehler = [], {}
    for n, roh in enumerate(r[1:], start=2):
        if not any(c.strip() for c in roh):
            continue
        if len(roh) < len(kopf):
            raise FachFehler(f"Zeile {n}: zu wenige Spalten ({len(roh)} statt {len(kopf)}).")
        g = lambda s: roh[ix[s]].strip() if s in ix else ""   # noqa: E731
        m = _DATUM.match(g("Datum"))
        if not m:
            raise FachFehler(f"Zeile {n}: Datum „{g('Datum')}“ ist ungültig (erwartet TT.MM.JJJJ).")
        try:
            dt = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            raise FachFehler(f"Zeile {n}: Datum „{g('Datum')}“ gibt es nicht.") from None
        if not g("Konto"):
            raise FachFehler(f"Zeile {n}: Konto fehlt.")
        z = Zeile(nr=n, datum=dt, beleg=g("Beleg"), belegkreis=g("Belegkreis"), fremdbeleg=g("Fremdbeleg"), konto=g("Konto"),
                  text=g("Text"), gegenkonto=g("Gegenkonto"), soll=betrag(g("Soll"), f"Zeile {n} Soll"),
                  haben=betrag(g("Haben"), f"Zeile {n} Haben"), storno=g("Storno").lower() in ("ja", "j", "x", "1", "true"))
        z.gegenkonten = [x.strip() for x in z.gegenkonto.split(",") if x.strip()]
        basis = "|".join([z.konto, z.datum.isoformat(), z.beleg, z.belegkreis, z.fremdbeleg, z.text, z.gegenkonto,
                          f2(z.soll), f2(z.haben)])
        zaehler[basis] = zaehler.get(basis, 0) + 1
        z.schluessel = f"{basis}#{zaehler[basis]}"
        zeilen.append(z)
    if not zeilen:
        raise FachFehler("Das Kontoblatt enthält keine Buchungen.")
    return zeilen


def _jetzt():
    return datetime.now().isoformat(timespec="seconds")


class KontoblattMixin:
    # ── Zuordnung ─────────────────────────────────────────────────────────────
    def kb_zuordnungen(self) -> dict:
        return {r["konto"]: r["liabilityId"] for r in self.rows("SELECT konto, liabilityId FROM kontoblatt_zuordnung")}

    def kb_zuordnen(self, konto: str, lid: int | None):
        with self.tx():
            if lid:
                self.must("liability", lid, "Verbindlichkeit nicht gefunden")
                self.exec("INSERT OR REPLACE INTO kontoblatt_zuordnung (konto, liabilityId, geaendertAm) VALUES (?,?,?)",
                          (konto, lid, _jetzt()))
            else:
                self.exec("DELETE FROM kontoblatt_zuordnung WHERE konto=?", (konto,))

    def kb_verbindlichkeiten(self):
        return self.rows("SELECT l.id, l.name, l.currentBalance, l.status, c.name AS contactName FROM liability l "
                         "JOIN contact c ON c.id=l.contactId WHERE l.status!='GELOESCHT' AND l.deletedAt IS NULL "
                         "ORDER BY c.name, l.name")

    # ── Vorschau ──────────────────────────────────────────────────────────────
    def _kb_gebucht_gueltig(self, g) -> bool:
        """Gemerkte Buchung zählt nur, wenn die Korrektur noch genau so existiert (z. B. nach Löschen/Datenimport nicht)."""
        if not g["correctionId"]:
            return False
        c = self.get("liability_correction", g["correctionId"])
        return bool(c) and c["liabilityId"] == g["liabilityId"] and d(c["amountChange"]) == d(g["amountChange"]) \
            and c["correctionType"] == g["correctionType"]

    def kb_vorschau(self, zeilen: list[Zeile]) -> list[dict]:
        """Je Zeile: status, vorschlag (BUCHEN/IGNORIEREN), typ, liabilityId (aus Zuordnung)."""
        zuo = self.kb_zuordnungen()
        gem = {r["schluessel"]: r for r in self.rows("SELECT * FROM kontoblatt_zeile")}
        aus = []
        for z in zeilen:
            g = gem.get(z.schluessel)
            if z.aenderung == 0:
                st = NULL
            elif g and g["status"] == "IGNORIERT":
                st = IGNORIERT
            elif g and g["status"] == "GEBUCHT":
                st = GEBUCHT if self._kb_gebucht_gueltig(g) else FEHLT
            else:
                st = NEU
            ignorieren = st == IGNORIERT or (st == NEU and z.belegkreis.upper() == "EB")
            aus.append({"zeile": z, "status": st, "ignorieren": ignorieren,
                        "typ": (g["correctionType"] if g and g["correctionType"] else z.vorschlag_typ()),
                        "liabilityId": zuo.get(z.konto), "gemerkt": dict(g) if g else None})
        return aus

    def kb_abstimmung(self, zeilen: list[Zeile]) -> list[dict]:
        """Je Konto: Saldo laut Kontoblatt (Haben − Soll, alle Zeilen) und Saldo der zugeordneten Verbindlichkeit."""
        zuo = self.kb_zuordnungen()
        konten = {}
        for z in zeilen:
            konten[z.konto] = konten.get(z.konto, Decimal("0.00")) + z.aenderung
        aus = []
        for k in sorted(konten):
            lid = zuo.get(k)
            l = self.get("liability", lid) if lid else None
            ff = d(l["currentBalance"]) if l else None
            aus.append({"konto": k, "kontoblatt": konten[k], "liabilityId": lid, "financeflow": ff,
                        "differenz": (ff - konten[k]) if ff is not None else None})
        return aus

    # ── Buchen ────────────────────────────────────────────────────────────────
    def kb_buchen(self, zeilen: list[Zeile], entscheidungen: dict, datei: str = "") -> dict:
        """entscheidungen: schluessel → {"aktion": "BUCHEN"|"IGNORIEREN", "typ": ...}. Zeilen ohne Entscheidung
        (Bereits gebucht, Nullbetrag, Konto ohne Zuordnung) bleiben unberührt. Alles oder nichts."""
        vorschau = {v["zeile"].schluessel: v for v in self.kb_vorschau(zeilen)}
        typen = {t for t, _ in TYPEN_IMPORT}
        buchen, ignorieren = [], []
        for s, e in entscheidungen.items():
            v = vorschau.get(s)
            if not v:
                raise FachFehler("Interner Fehler: Zeile nicht im Kontoblatt.")
            z = v["zeile"]
            if v["status"] in (GEBUCHT, NULL):
                raise FachFehler(f"Zeile {z.nr}: ist {STATUS_TEXT[v['status']].lower()} und kann nicht gebucht werden.")
            if e["aktion"] == "IGNORIEREN":
                ignorieren.append(z)
            elif e["aktion"] == "BUCHEN":
                if not v["liabilityId"]:
                    raise FachFehler(f"Zeile {z.nr}: Konto {z.konto} ist keiner Verbindlichkeit zugeordnet.")
                if e.get("typ") not in typen:
                    raise FachFehler(f"Zeile {z.nr}: Korrekturart fehlt.")
                buchen.append((z, e["typ"], v["liabilityId"]))
            else:
                raise FachFehler("Interner Fehler: unbekannte Aktion.")
        if not buchen and not ignorieren:
            raise FachFehler("Nichts zu buchen oder zu ignorieren.")
        buchen.sort(key=lambda x: (x[0].datum, x[0].nr))
        sicherung = self.auto_backup("vor_kontoblatt")
        jetzt = _jetzt()
        betroffen, summe = set(), Decimal("0.00")
        with self.tx():
            for z, typ, lid in buchen:
                l = self.must("liability", lid, "Verbindlichkeit nicht gefunden")
                if l["status"] == "GELOESCHT" or l["deletedAt"]:
                    raise FachFehler(f"Zeile {z.nr}: Die Verbindlichkeit „{l['name']}“ ist gelöscht.")
                if l["status"] == "BEZAHLT":
                    raise FachFehler(f"Zeile {z.nr}: Die Verbindlichkeit „{l['name']}“ ist als bezahlt markiert – "
                                     "zuerst reaktivieren.")
                if d(l["currentBalance"]) + z.aenderung < 0:
                    raise FachFehler(f"Zeile {z.nr} ({z.datum:%d.%m.%Y}, {z.beleg}): Saldo von „{l['name']}“ würde negativ "
                                     f"({de_betrag(d(l['currentBalance']))} − {de_betrag(z.soll - z.haben)}). Nichts gebucht.")
                cid = self.create_correction(lid, typ, z.aenderung, z.beschreibung(), z.datum)
                self.exec("INSERT OR REPLACE INTO kontoblatt_zeile (schluessel, konto, datum, beleg, text, soll, haben, status, "
                          "liabilityId, correctionId, correctionType, amountChange, datei, erfasstAm) "
                          "VALUES (?,?,?,?,?,?,?,'GEBUCHT',?,?,?,?,?,?)",
                          (z.schluessel, z.konto, iso(z.datum), z.beleg, z.text, f2(z.soll), f2(z.haben), lid, cid, typ,
                           f2(z.aenderung), datei, jetzt))
                betroffen.add(lid)
                summe += z.aenderung
            for z in ignorieren:
                self.exec("INSERT OR REPLACE INTO kontoblatt_zeile (schluessel, konto, datum, beleg, text, soll, haben, status, "
                          "datei, erfasstAm) VALUES (?,?,?,?,?,?,?,'IGNORIERT',?,?)",
                          (z.schluessel, z.konto, iso(z.datum), z.beleg, z.text, f2(z.soll), f2(z.haben), datei, jetzt))
            for lid in betroffen:
                self.recalculate_plan(lid)
            self.audit("IMPORT_KONTOBLATT", "LiabilityCorrection", None, None,
                       {"datei": datei, "gebucht": len(buchen), "ignoriert": len(ignorieren), "summe": f2(summe)})
        return {"gebucht": len(buchen), "ignoriert": len(ignorieren), "verbindlichkeiten": len(betroffen),
                "summe": summe, "sicherung": sicherung}

    def kb_merker_loeschen(self, schluessel: str):
        """Gemerktes „Ignoriert“ zurücknehmen (Zeile erscheint wieder als neu)."""
        with self.tx():
            self.exec("DELETE FROM kontoblatt_zeile WHERE schluessel=? AND status='IGNORIERT'", (schluessel,))
