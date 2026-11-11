"""Datums-Helfer (lib/date.ts addMonths, ISO-Wochen)."""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta


def to_date(v) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def iso(v) -> str | None:
    x = to_date(v)
    return x.isoformat() if x else None


def add_months(dt: date, n: int) -> date:
    """Überlaufsicher, Tag wird auf Monatsende geklemmt (lib/date.ts)."""
    m0 = dt.month - 1 + n
    y = dt.year + m0 // 12
    m = m0 % 12 + 1
    return date(y, m, min(dt.day, calendar.monthrange(y, m)[1]))


def first_of_month(dt: date) -> date:
    return dt.replace(day=1)


def month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def today() -> date:
    return date.today()


def iso_week_start(year: int) -> date:
    """Montag der KW 1 (Logik wie im TS-Code: Woche, die den 4. Jänner enthält)."""
    jan4 = date(year, 1, 4)
    return jan4 - timedelta(days=jan4.weekday())


def week_bounds(year: int, week: int) -> tuple[date, date]:
    start = iso_week_start(year) + timedelta(days=(week - 1) * 7)
    return start, start + timedelta(days=6)


def week_of(dt: date) -> tuple[int, int]:
    """(Jahr, KW) – wie recalcWeekForDate: Jahr = Kalenderjahr des Datums."""
    w1 = iso_week_start(dt.year)
    return dt.year, (dt - w1).days // 7 + 1


def daterange(a: date, b: date):
    x = a
    while x <= b:
        yield x
        x += timedelta(days=1)


MONATE = ["Jänner", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
          "November", "Dezember"]
