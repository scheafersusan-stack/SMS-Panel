"""Gregorian to Jalali (Solar Hijri) conversion and Tehran-local formatting."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_G_DAYS_BEFORE_MONTH = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)


def to_jalali(d: date) -> tuple[int, int, int]:
    """``(year, month, day)`` in the Jalali calendar (33-year arithmetic rule)."""
    gy, gm, gd = d.year, d.month, d.day
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        355666
        + 365 * gy
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        + gd
        + _G_DAYS_BEFORE_MONTH[gm - 1]
    )
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        return jy, 1 + days // 31, 1 + days % 31
    return jy, 7 + (days - 186) // 30, 1 + (days - 186) % 30


def to_persian_digits(s: str) -> str:
    return s.translate(_FA_DIGITS)


def format_tehran(at: datetime) -> str:
    """``۱۴۰۵/۰۸/۲۲ ۲۰:۰۰``: Jalali date and 24-hour time in Asia/Tehran, Persian digits."""
    local = at.astimezone(TEHRAN)
    y, m, d = to_jalali(local.date())
    return to_persian_digits(f"{y:04d}/{m:02d}/{d:02d} {local:%H:%M}")
