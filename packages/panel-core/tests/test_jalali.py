from datetime import UTC, date, datetime

import pytest

from payamakyar.core.jalali import format_tehran, to_jalali


@pytest.mark.parametrize(
    ("g", "j"),
    [
        (date(2026, 3, 21), (1405, 1, 1)),
        (date(2026, 3, 20), (1404, 12, 29)),
        (date(2025, 3, 21), (1404, 1, 1)),
        (date(2025, 3, 20), (1403, 12, 30)),  # 1403 is a leap year
        (date(2026, 11, 14), (1405, 8, 23)),
        (date(2026, 9, 23), (1405, 7, 1)),
        (date(2000, 1, 1), (1378, 10, 11)),
    ],
)
def test_to_jalali(g: date, j: tuple[int, int, int]) -> None:
    assert to_jalali(g) == j


def test_format_tehran_uses_local_time_and_persian_digits() -> None:
    # 16:30 UTC is 20:00 in Tehran (UTC+03:30).
    assert format_tehran(datetime(2026, 11, 13, 16, 30, tzinfo=UTC)) == "۱۴۰۵/۰۸/۲۲ ۲۰:۰۰"
    # Crossing midnight in Tehran moves the Jalali date forward.
    assert format_tehran(datetime(2026, 11, 13, 21, 0, tzinfo=UTC)) == "۱۴۰۵/۰۸/۲۳ ۰۰:۳۰"
