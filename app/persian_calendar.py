"""Dependency-free Solar Hijri month boundaries for fixed-cost accounting.

The March equinox year-start computation is based on the Borkowski leap-cycle
algorithm documented by jalaali-js (MIT license). The 1900–2120 range agrees
with the browser's Intl Persian calendar used by app/jalali.js.

Dates in SQLite remain ISO Gregorian; only month *boundaries* are Solar Hijri.
"""
from datetime import date, timedelta

# Cycle boundaries for the Borkowski algorithm; same values as jalaali-js v2.
_BREAKS = (-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181,
           1210, 1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178)


def new_year(year):
    """Return Gregorian date corresponding to 1 Farvardin of a Jalali year."""
    if type(year) is not int or not 1200 <= year <= 1499:
        raise ValueError('سال شمسی خارج از بازه قابل پشتیبانی است')
    gy = year + 621
    leap_j = -14
    prior = _BREAKS[0]
    for following in _BREAKS[1:]:
        gap = following - prior
        if year < following:
            break
        leap_j += (gap // 33) * 8 + (gap % 33) // 4
        prior = following
    n = year - prior
    leap_j += (n // 33) * 8 + ((n % 33) + 3) // 4
    if gap % 33 == 4 and gap - n == 4:
        leap_j += 1
    leap_g = gy // 4 - (((gy // 100) + 1) * 3) // 4 - 150
    return date(gy, 3, 20 + leap_j - leap_g)


def from_date(day):
    """Return (Jalali year, month, day) for an ISO-date-compatible date."""
    if not isinstance(day, date):
        raise ValueError('تاریخ نامعتبر است')
    jy = day.year - 621
    start = new_year(jy)
    if day < start:
        jy -= 1
        start = new_year(jy)
    elapsed = (day - start).days
    if elapsed < 186:
        return jy, 1 + elapsed // 31, 1 + elapsed % 31
    elapsed -= 186
    return jy, 7 + elapsed // 30, 1 + elapsed % 30


def month_start(year, month):
    """ISO Gregorian date of the first day of a named Solar Hijri month."""
    if type(month) is not int or not 1 <= month <= 12:
        raise ValueError('ماه شمسی نامعتبر است')
    offset = (month - 1) * 31 if month <= 6 else 186 + (month - 7) * 30
    return new_year(year) + timedelta(days=offset)


def following_month(year, month):
    if month == 12:
        return year + 1, 1
    return year, month + 1
