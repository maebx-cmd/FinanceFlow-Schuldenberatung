"""Lohn-, Lohnsteuer-, SV- und Pfändungsberechnung.

1:1 portiert aus calculations/lohnsteuer.ts, lohn.ts, pfaendung.ts (FinanceFlow-TS).
Alle fachlichen Werte kommen aus den Einstellungen (`S` = dict key -> str), nichts ist hartcodiert
außer den Fallbacks, die auch im TS-Code stehen (Stand 2026).
Quellen der Fallbacks: Lohnsteuertarifstufen 2026 (forum-media.at), Grundbetrag 2026 € 1.308,00
(forvismazars.com, Lohnpfändungswerte 2026).
"""
from __future__ import annotations

import json
from decimal import Decimal

from ..dec import D, D0, d, floor_to_multiple

FALLBACK_TARIF = [
    {"stufe": 1, "satz": 0.00, "bmg_von": 0, "bmg_bis": 1139.25, "allg_abzug": 0, "hilfswert": 0},
    {"stufe": 2, "satz": 0.20, "bmg_von": 1139.25, "bmg_bis": 1843.67, "allg_abzug": 227.85, "hilfswert": 412.22},
    {"stufe": 3, "satz": 0.30, "bmg_von": 1843.67, "bmg_bis": 3049.17, "allg_abzug": 412.22, "hilfswert": 502.53},
    {"stufe": 4, "satz": 0.40, "bmg_von": 3049.17, "bmg_bis": 5874.75, "allg_abzug": 717.13, "hilfswert": 1219.67},
    {"stufe": 5, "satz": 0.48, "bmg_von": 5874.75, "bmg_bis": 8749.25, "allg_abzug": 1187.11, "hilfswert": 2819.88},
    {"stufe": 6, "satz": 0.50, "bmg_von": 8749.25, "bmg_bis": 83344.33, "allg_abzug": 1362.10, "hilfswert": 4374.63},
    {"stufe": 7, "satz": 0.55, "bmg_von": 83344.33, "bmg_bis": 9999999, "allg_abzug": 5529.32, "hilfswert": 0},
]

FALLBACK_JAHRESTARIF = [
    {"stufe": 1, "satz": 0.00, "jahresgrenze": 13539},
    {"stufe": 2, "satz": 0.20, "jahresgrenze": 21992},
    {"stufe": 3, "satz": 0.30, "jahresgrenze": 36458},
    {"stufe": 4, "satz": 0.40, "jahresgrenze": 70365},
    {"stufe": 5, "satz": 0.48, "jahresgrenze": 104859},
    {"stufe": 6, "satz": 0.50, "jahresgrenze": 1000000},
    {"stufe": 7, "satz": 0.55, "jahresgrenze": 9999999},
]


def snum(S: dict, key: str, default) -> Decimal:
    """getSettingNum: Wert aus Einstellungen, sonst Default."""
    v = S.get(key)
    if v is None or v == "":
        return D(default)
    try:
        return Decimal(str(v))
    except Exception:
        return D(default)


def sjson(S: dict, key: str):
    v = S.get(key)
    if not v:
        return None
    try:
        return json.loads(v)
    except Exception:
        return None


def _num(x) -> Decimal:
    return Decimal(repr(x)) if isinstance(x, float) else Decimal(str(x))


def lst_tarif(S: dict) -> list:
    return sjson(S, "lst_tarif") or FALLBACK_TARIF


def jahrestarif(S: dict) -> list:
    return sjson(S, "lst_jahrestarif") or FALLBACK_JAHRESTARIF


def leite_monatstarif_ab(jahresstufen: list, werbungskosten_jahr=132) -> list:
    """Monatliche LSt-Tabelle aus Jahresstufen (§ 66 EStG); Abzug ungerundet weitergeführt."""
    wk_monat = _num(werbungskosten_jahr) / 12
    grenzen = [d(_num(js["jahresgrenze"]) / 12) + wk_monat for js in jahresstufen]
    result = []
    prev_raw = D0
    for i, js in enumerate(jahresstufen):
        satz = _num(js["satz"])
        von = D0 if i == 0 else grenzen[i - 1]
        bis = grenzen[i]
        if i == 0:
            raw = D0
        elif i == 1:
            raw = satz * grenzen[0]
        else:
            raw = prev_raw + (satz - _num(jahresstufen[i - 1]["satz"])) * grenzen[i - 1]
        result.append({"stufe": js["stufe"], "satz": float(satz), "bmg_von": float(von), "bmg_bis": float(bis),
                       "allg_abzug": float(d(raw)), "hilfswert": 0})
        prev_raw = raw
    return result


def berechne_lohnsteuer(bmg: Decimal, S: dict) -> dict:
    tarif = lst_tarif(S)
    vab = snum(S, "verkehrsabsetzbetrag", "41.33")
    lst = satz = abzug = D0
    for st in tarif:
        von, bis, s, h = _num(st["bmg_von"]), _num(st["bmg_bis"]), _num(st["satz"]), _num(st["allg_abzug"])
        if bmg <= von:
            break
        lst = d(bmg * s - h - vab)
        satz, abzug = s, h
        if bmg <= bis or bis == Decimal(9999999):
            break
    lst = max(lst, D0)
    return {"lohnsteuer": d(lst), "steuersatz": satz, "allgAbzug": d(abzug)}


def av_satz(brutto: Decimal, S: dict) -> Decimal:
    if brutto <= snum(S, "av_grenze_1", "2225.00"):
        return snum(S, "av_satz_1", "0.00")
    if brutto <= snum(S, "av_grenze_2", "2427.00"):
        return snum(S, "av_satz_2", "0.01")
    if brutto <= snum(S, "av_grenze_3", "2630.00"):
        return snum(S, "av_satz_3", "0.02")
    return snum(S, "av_satz_4", "0.0295")


def sv_tarif(brutto: Decimal, S: dict, sonderzahlung=False) -> Decimal:
    base = snum(S, "sv_kv", "0.0387") + snum(S, "sv_pv", "0.1025") + av_satz(brutto, S)
    if sonderzahlung:
        return base
    return base + snum(S, "sv_ak", "0.005") + snum(S, "sv_wbf", "0.005")


def berechne_pfaendung(netto: Decimal, S: dict) -> dict:
    """§ 291a EO: floor(Netto/Stufe)*Stufe; EM = Grundbetrag + (BMG-Grundbetrag)*pct."""
    grund = snum(S, "grundbetrag", "1308.00")
    stufe = snum(S, "existenzminimum_stufe", "20")
    pct = snum(S, "existenzminimum_pct", "0.30")
    bmg = floor_to_multiple(netto, stufe)
    diff = max(bmg - grund, D0)
    em = d(grund + diff * pct)
    pf = max(d(netto - em), D0)
    return {"netto": netto, "bmgEm": bmg, "existenzminimum": em, "pfaendbarer_betrag": pf}


def berechne_lohn(brutto_monthly, hours_actual=None, hourly_rate=None, allowance=D0, S: dict | None = None) -> dict:
    S = S or {}
    if hourly_rate and hours_actual:
        brutto = d(hourly_rate * hours_actual)
    else:
        brutto = d(brutto_monthly or 0)
    brutto = d(brutto + allowance)

    sv_t_lfd = sv_tarif(brutto, S, False)
    sv_lfd = d(brutto * sv_t_lfd)
    bmg_lfd = d(brutto - sv_lfd)
    l = berechne_lohnsteuer(bmg_lfd, S)
    netto_lfd = d(brutto - sv_lfd - l["lohnsteuer"])

    freib = snum(S, "sz_freibetrag", "620.00")
    lst_sz = snum(S, "lst_sz_satz", "0.06")
    sv_t_sz = sv_tarif(brutto, S, True)
    sv13 = d(brutto * sv_t_sz)
    bmg13 = d(max(brutto - sv13 - freib, D0))
    lst13 = d(bmg13 * lst_sz)
    n13 = d(brutto - sv13 - lst13)
    sv14 = d(brutto * sv_t_sz)
    bmg14 = d(max(brutto - sv14, D0))
    lst14 = d(bmg14 * lst_sz)
    n14 = d(brutto - sv14 - lst14)

    p_l, p13, p14 = berechne_pfaendung(netto_lfd, S), berechne_pfaendung(n13, S), berechne_pfaendung(n14, S)
    annual = d(p_l["pfaendbarer_betrag"] * 12 + p13["pfaendbarer_betrag"] + p14["pfaendbarer_betrag"])
    return {
        "brutto": brutto, "allowance": d(allowance),
        "svKv": snum(S, "sv_kv", "0.0387"), "svPv": snum(S, "sv_pv", "0.1025"), "svAv": av_satz(brutto, S),
        "svAk": snum(S, "sv_ak", "0.005"), "svWbf": snum(S, "sv_wbf", "0.005"),
        "svTarifLfd": sv_t_lfd, "svTarifSz": sv_t_sz, "svLfd": sv_lfd, "bmgLstLfd": bmg_lfd,
        "lstSatzLfd": l["steuersatz"], "allgAbzugLfd": l["allgAbzug"], "lstLfd": l["lohnsteuer"], "nettoLfd": netto_lfd,
        "svSz13": sv13, "bmgLstSz13": bmg13, "lstSz13": lst13, "nettoSz13": n13,
        "svSz14": sv14, "bmgLstSz14": bmg14, "lstSz14": lst14, "nettoSz14": n14,
        "bmgEmLfd": p_l["bmgEm"], "existenzminimumLfd": p_l["existenzminimum"], "seizableLfd": p_l["pfaendbarer_betrag"],
        "bmgEmSz13": p13["bmgEm"], "existenzminimumSz13": p13["existenzminimum"], "seizableSz13": p13["pfaendbarer_betrag"],
        "bmgEmSz14": p14["bmgEm"], "existenzminimumSz14": p14["existenzminimum"], "seizableSz14": p14["pfaendbarer_betrag"],
        "seizableAnnual": annual, "seizableMonthlyBasis": d(annual / 12),
    }


def q4(x: Decimal) -> str:
    return str(x.quantize(Decimal("0.0001")))


def lohn_to_record(r: dict) -> dict:
    """Ergebnis -> DB-Felder (wie routes/salary.ts POST)."""
    s2 = lambda x: str(d(x))
    return {
        "grossMonthly": s2(r["brutto"]), "svRateKv": q4(r["svKv"]), "svRatePv": q4(r["svPv"]), "svRateAv": q4(r["svAv"]),
        "svRateAk": q4(r["svAk"]), "svRateWbf": q4(r["svWbf"]), "svTotalRate": q4(r["svTarifLfd"]),
        "svAmount": s2(r["svLfd"]), "bmgLst": s2(r["bmgLstLfd"]), "lstRate": q4(r["lstSatzLfd"]),
        "lstAmount": s2(r["lstLfd"]), "netMonthly": s2(r["nettoLfd"]),
        "grossSz13": s2(r["brutto"]), "svRateSz": q4(r["svTarifSz"]), "svSz13": s2(r["svSz13"]),
        "bmgLstSz13": s2(r["bmgLstSz13"]), "lstSz13": s2(r["lstSz13"]), "netSz13": s2(r["nettoSz13"]),
        "grossSz14": s2(r["brutto"]), "svSz14": s2(r["svSz14"]), "bmgLstSz14": s2(r["bmgLstSz14"]),
        "lstSz14": s2(r["lstSz14"]), "netSz14": s2(r["nettoSz14"]),
        "existenzminimumLfd": s2(r["existenzminimumLfd"]), "seizableLfd": s2(r["seizableLfd"]),
        "existenzminimumSz13": s2(r["existenzminimumSz13"]), "seizableSz13": s2(r["seizableSz13"]),
        "existenzminimumSz14": s2(r["existenzminimumSz14"]), "seizableSz14": s2(r["seizableSz14"]),
        "seizableAnnual": s2(r["seizableAnnual"]), "seizableMonthlyBasis": s2(r["seizableMonthlyBasis"]),
    }
