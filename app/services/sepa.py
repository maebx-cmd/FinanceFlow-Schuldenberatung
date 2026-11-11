"""SEPA-Zahlungsdatei: Auswahl fälliger Raten, Export (pain.001), als bezahlt erfassen, verwerfen.

Posten sind über liabilityId + monthNo mit dem Tilgungsplan verknüpft (nicht über die Planzeilen-ID, weil
unbezahlte Planzeilen bei jeder Neuberechnung neu angelegt werden).
"""
from __future__ import annotations

from datetime import date, datetime

from ..calc import iban as ib
from ..calc import ratenplan_cent as rc
from ..calc import sepa
from ..dates import iso, to_date
from ..db_base import FachFehler


def _now():
    return datetime.now().isoformat(timespec="seconds")


class SepaMixin:
    # ── Einstellungen ─────────────────────────────────────────────────────────
    def sepa_einstellungen(self) -> dict:
        return {"name": self.setting("sepa_auftraggeber_name", ""), "iban": self.setting("sepa_auftraggeber_iban", ""),
                "bic": self.setting("sepa_auftraggeber_bic", ""), "version": self.setting("sepa_version", "09") or "09",
                "sammelbuchung": self.setting("sepa_sammelbuchung", "0") == "1",
                "vorlage": self.setting("sepa_vorlage", "") or sepa.STANDARD_VORLAGE}

    def sepa_einstellungen_speichern(self, e: dict):
        iban = ib.normalisieren(e.get("iban"))
        bic = sepa.bic_normalisieren(e.get("bic"))
        if iban and not ib.gueltig(iban):
            raise FachFehler("IBAN des Auftraggebers ungültig (Prüfziffer oder Aufbau).")
        if bic and not sepa.bic_gueltig(bic):
            raise FachFehler("BIC des Auftraggebers ungültig.")
        if (e.get("version") or "09") not in sepa.VERSIONEN:
            raise FachFehler("Format ungültig.")
        with self.tx():
            self.set_setting("sepa_auftraggeber_name", (e.get("name") or "").strip())
            self.set_setting("sepa_auftraggeber_iban", iban or "")
            self.set_setting("sepa_auftraggeber_bic", bic or "")
            self.set_setting("sepa_version", e.get("version") or "09")
            self.set_setting("sepa_sammelbuchung", "1" if e.get("sammelbuchung") else "0")
            self.set_setting("sepa_vorlage", (e.get("vorlage") or "").strip() or sepa.STANDARD_VORLAGE)
            self.audit("UPDATE", "Setting", "sepa", None, {"version": e.get("version"), "iban": iban})

    # ── Auswahl ───────────────────────────────────────────────────────────────
    def sepa_exportiert(self) -> dict:
        """{(liabilityId, monthNo): Erstelldatum} aus nicht verworfenen Exporten."""
        out = {}
        for r in self.rows("SELECT p.liabilityId, p.monthNo, e.erstellt FROM sepa_export_posten p JOIN sepa_export e "
                           "ON e.id=p.exportId WHERE e.verworfenAm IS NULL ORDER BY e.erstellt"):
            out[(r["liabilityId"], r["monthNo"])] = r["erstellt"]
        return out

    def sepa_auswahl(self, bis=None) -> list[dict]:
        libs = self.rows("SELECT l.id, l.name, l.status, l.currentBalance, l.dueDay, l.iban, l.zahlungsreferenz, "
                         "l.verwendungszweck, c.name AS contactName, c.iban AS contactIban, c.bic AS contactBic "
                         "FROM liability l JOIN contact c ON c.id=l.contactId "
                         "WHERE l.status NOT IN ('GELOESCHT','BEZAHLT')")
        zeilen = self.rows("SELECT liabilityId, monthNo, monthDate, payment FROM debt_repayment_plan WHERE paidAt IS NULL")
        return sepa.auswahl(libs, zeilen, self.sepa_exportiert(), self.sepa_einstellungen()["vorlage"], bis)

    # ── Erstellen ─────────────────────────────────────────────────────────────
    def sepa_erstellen(self, keys, ausfuehrung, msg_id: str | None = None, heute: date | None = None) -> dict:
        """keys: [(liabilityId, monthNo)] – Beträge und Raten werden hier aus den aktuellen Planzeilen neu ermittelt."""
        e = self.sepa_einstellungen()
        jetzt = datetime.now()
        aktuell = {(a["liabilityId"], a["monthNo"]): a for a in self.sepa_auswahl()}
        offen = {r["id"]: r for r in self.rows("SELECT id, name FROM liability")}
        fehler, zahlungen, posten = [], [], []
        for lid, mno in keys:
            a = aktuell.get((int(lid), int(mno)))
            if not a:
                n = (offen.get(int(lid)) or {}).get("name") or f"Verbindlichkeit {lid}"
                fehler.append(f"{n}, Rate {mno} ist nicht mehr offen – Liste neu laden.")
                continue
            if a["problem"]:
                fehler.append(f"{a['empfaenger'] or a['bezeichnung']}, Rate {mno}: {a['problem']}")
                continue
            if a["exportiertAm"]:
                fehler.append(f"{a['empfaenger']}, Rate {mno} wurde bereits exportiert – zuerst die Datei verwerfen.")
                continue
            e2e = sepa.kennung(f"{a['endToEndBasis']}-{jetzt:%y%m%d}")
            zahlungen.append({"endToEndId": e2e, "betrag": a["betrag"], "empfaenger": a["empfaenger"], "iban": a["iban"],
                              "bic": a["bic"], "zweck": a["zweck"], "referenz": a["referenz"]})
            posten.append((a, e2e))
        if fehler:
            raise FachFehler("Zahlungsdatei kann nicht erstellt werden:\n• " + "\n• ".join(fehler))
        auftraggeber = {"name": e["name"], "iban": e["iban"], "bic": e["bic"]}
        msg = sepa.kennung(msg_id or sepa.msg_id(jetzt))
        if self.val("SELECT 1 FROM sepa_export WHERE msgId=?", (msg,)):
            raise FachFehler("Nachrichten-ID bereits vergeben – bitte erneut versuchen.")
        try:
            xml = sepa.erstelle_xml(auftraggeber, zahlungen, ausfuehrung, e["version"], e["sammelbuchung"], msg, jetzt, heute)
        except sepa.SepaFehler as ex:
            raise FachFehler(str(ex)) from ex
        summe = sum(z["betrag"] for z in zahlungen)
        von = (getattr(self, "benutzer", None) or {}).get("name")
        with self.tx():
            eid = self.insert("sepa_export", {"msgId": msg, "version": e["version"], "erstellt": jetzt.isoformat(timespec="seconds"),
                                              "erstelltVon": von, "ausfuehrung": iso(ausfuehrung), "anzahl": len(zahlungen),
                                              "summe": sepa.betrag_text(summe), "auftraggeberIban": ib.normalisieren(e["iban"]),
                                              "xml": xml})
            for a, e2e in posten:
                self.insert("sepa_export_posten", {"exportId": eid, "liabilityId": a["liabilityId"], "monthNo": a["monthNo"],
                                                   "faellig": a["faellig"].isoformat(), "betrag": sepa.betrag_text(a["betrag"]),
                                                   "empfaenger": a["empfaenger"], "iban": a["iban"],
                                                   "zweck": a["referenz"] or a["zweck"], "endToEndId": e2e})
            self.audit("CREATE", "SepaExport", eid, None, {"msgId": msg, "anzahl": len(zahlungen), "summe": sepa.betrag_text(summe)})
        return {"id": eid, "msgId": msg, "xml": xml, "anzahl": len(zahlungen), "summe": summe}

    # ── Erstellte Dateien ─────────────────────────────────────────────────────
    def sepa_exporte(self) -> list[dict]:
        rows = self.rows("SELECT e.id, e.msgId, e.version, e.erstellt, e.erstelltVon, e.ausfuehrung, e.anzahl, e.summe, "
                         "e.verworfenAm, e.bezahltAm, (SELECT COUNT(*) FROM sepa_export_posten p WHERE p.exportId=e.id "
                         "AND p.bezahltAm IS NOT NULL) AS erfasst FROM sepa_export e ORDER BY e.erstellt DESC, e.id DESC")
        for r in rows:
            if r["verworfenAm"]:
                r["status"] = "verworfen"
            elif r["bezahltAm"] or (r["erfasst"] and r["erfasst"] >= r["anzahl"]):
                r["status"] = "bezahlt erfasst"
            elif r["erfasst"]:
                r["status"] = "teilweise erfasst"
            else:
                r["status"] = "offen"
        return rows

    def sepa_posten(self, export_id) -> list[dict]:
        return self.rows("SELECT * FROM sepa_export_posten WHERE exportId=? ORDER BY faellig, empfaenger", (export_id,))

    def sepa_xml(self, export_id) -> tuple[str, str]:
        e = self.must("sepa_export", export_id, "Zahlungsdatei nicht gefunden")
        return e["msgId"], e["xml"]

    def sepa_als_bezahlt(self, export_id, datum=None) -> dict:
        """Je Posten die offene Planzeile mit gleicher liabilityId+monthNo als RATENZAHLUNG (Postenbetrag) bezahlen."""
        e = self.must("sepa_export", export_id, "Zahlungsdatei nicht gefunden")
        if e["verworfenAm"]:
            raise FachFehler("Diese Zahlungsdatei wurde verworfen.")
        datum = to_date(datum) or to_date(e["ausfuehrung"]) or date.today()
        erfasst, uebersprungen = 0, []
        with self.tx():
            for p in self.sepa_posten(export_id):
                if p["bezahltAm"]:
                    continue
                z = self.row("SELECT id FROM debt_repayment_plan WHERE liabilityId=? AND monthNo=? AND paidAt IS NULL",
                             (p["liabilityId"], p["monthNo"]))
                if not z:
                    uebersprungen.append(f"{p['empfaenger']}, Rate {p['monthNo']} (nicht mehr offen)")
                    continue
                self.planrate_bezahlen(p["liabilityId"], z["id"], p["betrag"], datum)
                self.update("sepa_export_posten", p["id"], {"bezahltAm": iso(datum)})
                erfasst += 1
            offen = self.val("SELECT COUNT(*) FROM sepa_export_posten WHERE exportId=? AND bezahltAm IS NULL", (export_id,))
            if not offen:
                self.update("sepa_export", export_id, {"bezahltAm": iso(datum)})
            self.audit("PAY", "SepaExport", export_id, None, {"erfasst": erfasst, "uebersprungen": len(uebersprungen),
                                                              "datum": iso(datum)})
        return {"erfasst": erfasst, "uebersprungen": uebersprungen, "vollstaendig": not offen}

    def sepa_verwerfen(self, export_id):
        e = self.must("sepa_export", export_id, "Zahlungsdatei nicht gefunden")
        if e["verworfenAm"]:
            raise FachFehler("Bereits verworfen.")
        if self.val("SELECT COUNT(*) FROM sepa_export_posten WHERE exportId=? AND bezahltAm IS NOT NULL", (export_id,)):
            raise FachFehler("Es wurden bereits Zahlungen als bezahlt erfasst – Verwerfen nicht möglich.")
        with self.tx():
            self.update("sepa_export", export_id, {"verworfenAm": _now()})
            self.audit("DISCARD", "SepaExport", export_id, None, {"msgId": e["msgId"]})

    @staticmethod
    def sepa_summe_text(cent: int) -> str:
        return f"{rc.cents_to_dec(cent):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
