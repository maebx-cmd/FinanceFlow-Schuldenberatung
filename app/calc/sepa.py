"""SEPA-Überweisungsdatei (ISO 20022 pain.001.001.09 / .03) für fällige Raten – wie die Web-Version.

Reine Funktionen (ohne Datenbank): Zeichensatz, Auswahl der Raten, Prüfungen, XML.
Beträge ausschließlich in ganzen Cent (int).
"""
from __future__ import annotations

import calendar
import re
import secrets
import unicodedata
from datetime import date, datetime
from xml.sax.saxutils import escape

from . import iban as ib
from . import ratenplan_cent as rc

VERSIONEN = {"09": "pain.001.001.09", "03": "pain.001.001.03"}
STANDARD_VORLAGE = "{bezeichnung} Rate {rate} {monat}"
_BIC = re.compile(r"^[A-Z]{6}[A-Z2-9][A-NP-Z0-9]([A-Z0-9]{3})?$")
_REF = re.compile(r"^[A-Za-z0-9+?/\-:().,']{1,35}$")
_ERLAUBT = re.compile(r"[^a-zA-Z0-9/\-?:().,'+ ]")
_ERSATZ = [("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue"), ("ß", "ss"), ("&", "+"),
           ("€", "EUR"), ("–", "-"), ("—", "-"), ("_", "-"), ("§", "Par."), ('"', "'"), ("#", "Nr."), (";", ","),
           ("!", "."), ("@", "(at)"), ("*", "."), ("=", "-")]

PROBLEM_KEINE_IBAN = "keine IBAN (bei Verbindlichkeit oder Kontakt eintragen)"
PROBLEM_IBAN = "IBAN ungültig"
PROBLEM_NAME = "Empfängername fehlt"
PROBLEM_ZWECK = "Verwendungszweck leer"


class SepaFehler(ValueError):
    pass


# ── Zeichensatz ───────────────────────────────────────────────────────────────
def text(s, maxlen: int | None = None) -> str:
    """Auf den EPC-Basiszeichensatz bringen: Umlaute umschreiben, Akzente weg, Rest → Leerzeichen, kürzen."""
    t = "" if s is None else str(s)
    for a, b in _ERSATZ:
        t = t.replace(a, b)
    t = "".join(ch for ch in unicodedata.normalize("NFKD", t) if not unicodedata.combining(ch))
    t = _ERLAUBT.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if maxlen:
        t = t[:maxlen].strip()
    return t


def name(s) -> str:
    return text(s, 70)


def zweck(s) -> str:
    return text(s, 140)


def kennung(s) -> str:
    """MsgId, EndToEndId, Referenz: Basiszeichen, ohne Leerzeichen, kein „//“, kein „/“ am Rand, max. 35."""
    t = text(s).replace(" ", "")
    while "//" in t:
        t = t.replace("//", "/")
    t = t.strip("/")[:35].strip("/")
    return t


def bic_normalisieren(s) -> str | None:
    t = re.sub(r"\s", "", str(s or "")).upper()
    return t or None


def bic_gueltig(s) -> bool:
    t = bic_normalisieren(s)
    return bool(t and _BIC.match(t))


def referenz_normalisieren(s) -> str | None:
    t = re.sub(r"\s", "", str(s or ""))
    return t or None


def referenz_gueltig(s) -> bool:
    t = referenz_normalisieren(s)
    return bool(t and _REF.match(t))


def vorlage_fuellen(vorlage, bezeichnung, glaeubiger, rate, faellig: date) -> str:
    return (str(vorlage or "").replace("{bezeichnung}", bezeichnung or "").replace("{glaeubiger}", glaeubiger or "")
            .replace("{rate}", str(rate)).replace("{faellig}", faellig.strftime("%d.%m.%Y"))
            .replace("{monat}", faellig.strftime("%m/%Y")))


def betrag_text(cent: int) -> str:
    return f"{cent // 100}.{cent % 100:02d}"


def msg_id(jetzt: datetime | None = None) -> str:
    jetzt = jetzt or datetime.now()
    return f"FF-{jetzt:%y%m%d-%H%M}-{secrets.token_hex(4).upper()}"


def end_to_end_basis(liability_id, month_no) -> str:
    return f"FF-L{liability_id}-R{month_no}"


def naechster_werktag(ab: date, feiertage=()) -> date:
    from datetime import timedelta
    d = ab + timedelta(days=1)
    while d.weekday() >= 5 or d in feiertage:
        d += timedelta(days=1)
    return d


def monatsende(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


# ── Auswahl ───────────────────────────────────────────────────────────────────
def _datum(x) -> date:
    return x if isinstance(x, date) else date.fromisoformat(str(x)[:10])


def auswahl(libs: list[dict], offene_zeilen: list[dict], exportiert: dict | None = None,
            vorlage: str | None = None, bis=None) -> list[dict]:
    """Nächste offene Rate je Verbindlichkeit.

    libs: id, name, status, currentBalance, dueDay, iban, zahlungsreferenz, verwendungszweck,
          contactName, contactIban, contactBic
    offene_zeilen: unbezahlte Planzeilen (liabilityId, monthNo, monthDate, payment)
    exportiert: {(liabilityId, monthNo): Erstelldatum} aus nicht verworfenen Exporten
    """
    exportiert = exportiert or {}
    vorlage = vorlage or STANDARD_VORLAGE
    bis = _datum(bis) if bis else None
    erste: dict[int, dict] = {}
    for z in offene_zeilen:
        cur = erste.get(z["liabilityId"])
        if cur is None or z["monthNo"] < cur["monthNo"]:
            erste[z["liabilityId"]] = z
    out = []
    for l in libs:
        if l.get("status") in ("GELOESCHT", "BEZAHLT") or rc.to_cents(l.get("currentBalance") or 0) <= 0:
            continue
        z = erste.get(l["id"])
        if not z:
            continue
        cent = rc.to_cents(z["payment"] or 0)
        if cent <= 0:
            continue
        md = _datum(z["monthDate"])
        faellig = md.replace(day=min(int(l["dueDay"]), calendar.monthrange(md.year, md.month)[1])) if l.get("dueDay") else md
        if bis and faellig > bis:
            continue
        probleme = []
        eigene, kontakt = ib.normalisieren(l.get("iban")), ib.normalisieren(l.get("contactIban"))
        iban, quelle = (eigene, "verbindlichkeit") if eigene else ((kontakt, "kontakt") if kontakt else (None, None))
        if not iban:
            probleme.append(PROBLEM_KEINE_IBAN)
        elif not ib.gueltig(iban):
            probleme.append(PROBLEM_IBAN)
        bic = bic_normalisieren(l.get("contactBic")) if quelle == "kontakt" and bic_gueltig(l.get("contactBic")) else None
        empfaenger = (l.get("contactName") or "").strip() or (l.get("name") or "").strip()
        if not name(empfaenger):
            probleme.append(PROBLEM_NAME)
        referenz = referenz_normalisieren(l.get("zahlungsreferenz"))
        if referenz:
            zw = ""
        else:
            zw = vorlage_fuellen((l.get("verwendungszweck") or "").strip() or vorlage, l.get("name"), l.get("contactName"),
                                 z["monthNo"], faellig)
            if not zweck(zw):
                probleme.append(PROBLEM_ZWECK)
        key = (l["id"], z["monthNo"])
        out.append({"key": f"{l['id']}:{z['monthNo']}", "liabilityId": l["id"], "monthNo": z["monthNo"], "monthDate": md,
                    "faellig": faellig, "betrag": cent, "empfaenger": empfaenger, "bezeichnung": l.get("name") or "",
                    "iban": iban, "ibanQuelle": quelle, "bic": bic, "zweck": zw, "referenz": referenz,
                    "endToEndBasis": end_to_end_basis(l["id"], z["monthNo"]),
                    "probleme": probleme, "problem": "; ".join(probleme) or None, "exportiertAm": exportiert.get(key)})
    out.sort(key=lambda x: (x["faellig"], x["empfaenger"].lower()))
    return out


# ── Prüfen + XML ──────────────────────────────────────────────────────────────
def pruefen(auftraggeber: dict, zahlungen: list[dict], ausfuehrung, heute: date | None = None) -> list[str]:
    f = []
    heute = heute or date.today()
    if not name(auftraggeber.get("name")):
        f.append("Auftraggeber: Kontoinhaber (Name) fehlt.")
    if not ib.gueltig(auftraggeber.get("iban")):
        f.append("Auftraggeber: IBAN ungültig (Prüfziffer oder Aufbau).")
    if auftraggeber.get("bic") and not bic_gueltig(auftraggeber["bic"]):
        f.append("Auftraggeber: BIC ungültig.")
    if not ausfuehrung:
        f.append("Ausführungsdatum fehlt.")
    elif _datum(ausfuehrung) < heute:
        f.append("Ausführungsdatum liegt in der Vergangenheit.")
    if not zahlungen:
        f.append("Keine Zahlung ausgewählt.")
    gesehen = set()
    for i, z in enumerate(zahlungen, 1):
        wer = name(z.get("empfaenger")) or f"Zahlung {i}"
        if not name(z.get("empfaenger")):
            f.append(f"Zahlung {i}: Empfängername fehlt.")
        if not ib.gueltig(z.get("iban")):
            f.append(f"{wer}: IBAN ungültig.")
        if z.get("bic") and not bic_gueltig(z["bic"]):
            f.append(f"{wer}: BIC ungültig.")
        if int(z.get("betrag") or 0) <= 0:
            f.append(f"{wer}: Betrag muss größer als 0 sein.")
        e2e = kennung(z.get("endToEndId"))
        if not e2e:
            f.append(f"{wer}: EndToEndId fehlt.")
        elif e2e in gesehen:
            f.append(f"{wer}: EndToEndId {e2e} doppelt.")
        gesehen.add(e2e)
    return f


def erstelle_xml(auftraggeber: dict, zahlungen: list[dict], ausfuehrung, version="09", sammelbuchung=False,
                 msg: str | None = None, erstellt: datetime | None = None, heute: date | None = None) -> str:
    """auftraggeber: name, iban, bic; zahlungen: endToEndId, betrag (Cent), empfaenger, iban, bic, zweck, referenz."""
    if version not in VERSIONEN:
        raise SepaFehler("Unbekanntes Format (erlaubt: 09 oder 03).")
    fehler = pruefen(auftraggeber, zahlungen, ausfuehrung, heute)
    if fehler:
        raise SepaFehler("Zahlungsdatei kann nicht erstellt werden:\n• " + "\n• ".join(fehler))
    erstellt = erstellt or datetime.now()
    msg = kennung(msg or msg_id(erstellt))
    x = lambda s: escape(s)
    neu = version == "09"
    bic_tag = "BICFI" if neu else "BIC"
    anzahl = len(zahlungen)
    summe = betrag_text(sum(int(z["betrag"]) for z in zahlungen))
    ausf = _datum(ausfuehrung).isoformat()
    a_bic = bic_normalisieren(auftraggeber.get("bic"))
    o = ['<?xml version="1.0" encoding="UTF-8"?>',
         f'<Document xmlns="urn:iso:std:iso:20022:tech:xsd:{VERSIONEN[version]}" '
         'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
         "<CstmrCdtTrfInitn>",
         "<GrpHdr>", f"<MsgId>{x(msg)}</MsgId>", f"<CreDtTm>{erstellt:%Y-%m-%dT%H:%M:%S}</CreDtTm>",
         f"<NbOfTxs>{anzahl}</NbOfTxs>", f"<CtrlSum>{summe}</CtrlSum>",
         f"<InitgPty><Nm>{x(name(auftraggeber['name']))}</Nm></InitgPty>", "</GrpHdr>",
         "<PmtInf>", f"<PmtInfId>{x(kennung(msg + '-1'))}</PmtInfId>", "<PmtMtd>TRF</PmtMtd>",
         f"<BtchBookg>{'true' if sammelbuchung else 'false'}</BtchBookg>",
         f"<NbOfTxs>{anzahl}</NbOfTxs>", f"<CtrlSum>{summe}</CtrlSum>",
         "<PmtTpInf><SvcLvl><Cd>SEPA</Cd></SvcLvl></PmtTpInf>",
         f"<ReqdExctnDt><Dt>{ausf}</Dt></ReqdExctnDt>" if neu else f"<ReqdExctnDt>{ausf}</ReqdExctnDt>",
         f"<Dbtr><Nm>{x(name(auftraggeber['name']))}</Nm></Dbtr>",
         f"<DbtrAcct><Id><IBAN>{ib.normalisieren(auftraggeber['iban'])}</IBAN></Id><Ccy>EUR</Ccy></DbtrAcct>",
         (f"<DbtrAgt><FinInstnId><{bic_tag}>{a_bic}</{bic_tag}></FinInstnId></DbtrAgt>" if a_bic else
          "<DbtrAgt><FinInstnId><Othr><Id>NOTPROVIDED</Id></Othr></FinInstnId></DbtrAgt>"),
         "<ChrgBr>SLEV</ChrgBr>"]
    for z in zahlungen:
        o += ["<CdtTrfTxInf>", f"<PmtId><EndToEndId>{x(kennung(z['endToEndId']))}</EndToEndId></PmtId>",
              f'<Amt><InstdAmt Ccy="EUR">{betrag_text(int(z["betrag"]))}</InstdAmt></Amt>']
        c_bic = bic_normalisieren(z.get("bic"))
        if c_bic:
            o.append(f"<CdtrAgt><FinInstnId><{bic_tag}>{c_bic}</{bic_tag}></FinInstnId></CdtrAgt>")
        o += [f"<Cdtr><Nm>{x(name(z['empfaenger']))}</Nm></Cdtr>",
              f"<CdtrAcct><Id><IBAN>{ib.normalisieren(z['iban'])}</IBAN></Id></CdtrAcct>"]
        ref = kennung(z.get("referenz")) if z.get("referenz") else ""
        txt = zweck(z.get("zweck"))
        if ref:
            o.append("<RmtInf><Strd><CdtrRefInf><Tp><CdOrPrtry><Cd>SCOR</Cd></CdOrPrtry></Tp>"
                     f"<Ref>{x(ref)}</Ref></CdtrRefInf></Strd></RmtInf>")
        elif txt:
            o.append(f"<RmtInf><Ustrd>{x(txt)}</Ustrd></RmtInf>")
        o.append("</CdtTrfTxInf>")
    o += ["</PmtInf>", "</CstmrCdtTrfInitn>", "</Document>"]
    return "\n".join(o) + "\n"
