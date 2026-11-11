"""Eine Rechenregel für Quoten, Raten und Gläubigerverteilung – centgenau, identisch zur Web-Version.

Gerechnet wird ausschließlich in ganzen Cent (int), nie mit float. Verwendet von:
Szenario-Rechner (Privatkonkurs), Umwandlung in den Zahlungsplan, Planaufbau der Ratenzeilen
und der Vorschau auf der Zahlungsplan-Seite.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from ..dec import _normalize


def _dec(x) -> Decimal:
    if isinstance(x, float):
        x = repr(x)          # 1.005 → "1.005" (nicht 1.00499999…)
    return Decimal(_normalize(x))


def to_cents(x) -> int:
    """„1.234,56“ / „1234,56“ / „1234.56“ / Decimal / int → Cent, kaufmännisch gerundet."""
    return int((_dec(x) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def pct(x) -> int:
    """Quote in Prozent → Hundertstel-Prozent (int): „12,345“ → 1235."""
    return int((_dec(x) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def cents_to_dec(c: int) -> Decimal:
    return (Decimal(int(c)) / 100).quantize(Decimal("0.01"))


def round_div(a: int, b: int) -> int:
    """Kaufmännisch gerundete Ganzzahldivision (a ≥ 0, b > 0)."""
    return (2 * a + b) // (2 * b)


def quotenbetrag(saldo_cent: int, quote_hundertstel: int) -> int:
    return round_div(saldo_cent * quote_hundertstel, 10000)


def split_rates(z: int, n: int) -> tuple[int, int]:
    """(rate, letzte): n−1 × rate + letzte = z; letzte ≥ 0; nie eine zusätzliche Rate."""
    if n <= 0 or z <= 0:
        return 0, max(0, z)
    if n == 1:
        return z, z
    rate = round_div(z, n)
    if rate * (n - 1) > z:
        rate = z // n
    return rate, z - rate * (n - 1)


def allocate(total: int, weights: list[int]) -> list[int]:
    """Verteilung nach größtem Rest; Summe = total exakt (Gleichstand → Reihenfolge)."""
    if not weights:
        return []
    w = [max(0, int(x)) for x in weights]
    W = sum(w)
    if W == 0:
        w, W = [1] * len(w), len(w)
    base = [total * x // W for x in w]
    rest = [total * x % W for x in w]
    fehlt = total - sum(base)
    for i in sorted(range(len(w)), key=lambda i: (-rest[i], i))[:fehlt]:
        base[i] += 1
    return base


def quote6(gesamt: int, schuld: int) -> Decimal:
    """Quote als 6-stelliger Bruch (0,173300)."""
    if schuld <= 0:
        return Decimal("0.000000")
    return (Decimal(round_div(gesamt * 1_000_000, schuld)) / 1_000_000).quantize(Decimal("0.000001"))


def plan_by_quote(salden: list[int], quote_hundertstel: int, n: int) -> dict:
    """Szenario „% der Schuld“ – identisch mit der späteren Zahlungsplan-Umwandlung."""
    gl = []
    for s in salden:
        z = quotenbetrag(s, quote_hundertstel)
        r, last = split_rates(z, n)
        gl.append({"saldo": s, "gesamt": z, "rate": r, "letzte": last, "min": min(r, last) if n > 1 else last,
                   "max": max(r, last) if n > 1 else last})
    rate, last = sum(g["rate"] for g in gl), sum(g["letzte"] for g in gl)
    termine = ([rate] * (n - 1) + [last]) if n > 0 else []
    gesamt = sum(g["gesamt"] for g in gl)
    return {"glaeubiger": gl, "gesamt": gesamt, "rate": rate if n > 1 else last, "letzte": last, "termine": termine,
            "quote": quote6(gesamt, sum(salden))}


def plan_by_installment(salden: list[int], monatsbetrag_cent: int, intervall: int, n: int) -> dict:
    """Szenario „freier Monatsbetrag“: jede Rate exakt R, Gläubigersummen exakt R × n."""
    R = monatsbetrag_cent * intervall
    vorher = [0] * len(salden)
    zahl = [[] for _ in salden]
    for k in range(1, n + 1):
        kum = allocate(R * k, salden)
        for i in range(len(salden)):
            zahl[i].append(kum[i] - vorher[i])
        vorher = kum
    gl = [{"saldo": s, "gesamt": sum(zahl[i]), "rate": zahl[i][0] if n else 0, "letzte": zahl[i][-1] if n else 0,
           "min": min(zahl[i]) if n else 0, "max": max(zahl[i]) if n else 0, "zahlungen": zahl[i]}
          for i, s in enumerate(salden)]
    gesamt = R * n
    return {"glaeubiger": gl, "gesamt": gesamt, "rate": R if n else 0, "letzte": R if n else 0, "termine": [R] * n,
            "quote": quote6(gesamt, sum(salden))}


def merge_rounding_tail(zahlungen: list[int], geplant: int) -> list[int]:
    """Rundungsrest (≤ 1 Cent je Rate) in die letzte planmäßige Rate legen; echte Mehrschuld bleibt."""
    if geplant <= 0 or len(zahlungen) <= geplant:
        return list(zahlungen)
    rest = sum(zahlungen[geplant:])
    if rest > geplant:
        return list(zahlungen)
    neu = list(zahlungen[:geplant])
    neu[-1] += rest
    return neu
