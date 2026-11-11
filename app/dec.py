"""Geld-Arithmetik – 1:1 zu calculations/decimal.ts (decimal.js, precision 20, ROUND_HALF_UP)."""
from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Context, Decimal, localcontext, setcontext

# decimal.js: Decimal.set({ precision: 20, rounding: ROUND_HALF_UP })
CTX = Context(prec=20, rounding=ROUND_HALF_UP)
setcontext(CTX)

D0 = Decimal(0)
Q2 = Decimal("0.01")
Q6 = Decimal("0.000001")


def _normalize(value) -> str:
    if value is None or value == "":
        return "0"
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, float):
        value = repr(value)
    s = str(value).strip()
    if "," in s and "." not in s:
        return s.replace(",", ".")
    if "." in s and "," in s:
        return s.replace(".", "").replace(",", ".")
    return s


def D(value) -> Decimal:
    """Ungerundeter Decimal (entspricht new Decimal(String(x)))."""
    return Decimal(_normalize(value))


def d(value) -> Decimal:
    """Auf 2 Stellen ROUND_HALF_UP (entspricht d())."""
    return D(value).quantize(Q2, rounding=ROUND_HALF_UP)


def d6(value) -> Decimal:
    return D(value).quantize(Q6, rounding=ROUND_HALF_UP)


def dp(value: Decimal, places: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def floor_to_multiple(value: Decimal, multiple: Decimal) -> Decimal:
    return (value / multiple).to_integral_value(rounding=ROUND_FLOOR) * multiple


def ceil_to_multiple(value: Decimal, multiple: Decimal) -> Decimal:
    return (value / multiple).to_integral_value(rounding=ROUND_CEILING) * multiple


def f2(value) -> str:
    """toFixed(2)."""
    return str(d(value))


def f6(value) -> str:
    return str(d6(value))


def opt2(value):
    """None bleibt None, sonst toFixed(2)."""
    return None if value is None or value == "" else f2(value)


def dmax(*xs: Decimal) -> Decimal:
    return max(xs)


def dmin(*xs: Decimal) -> Decimal:
    return min(xs)


__all__ = ["D", "d", "d6", "dp", "D0", "floor_to_multiple", "ceil_to_multiple", "f2", "f6", "opt2",
           "Decimal", "localcontext"]
