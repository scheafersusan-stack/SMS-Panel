import pytest

from payamakyar.core.phone import (
    InvalidMobile,
    format_mobile_local,
    normalize_mobile,
    to_ascii_digits,
)


@pytest.mark.parametrize(
    "raw",
    [
        "09123456789",
        "9123456789",
        "+989123456789",
        "989123456789",
        "00989123456789",
        "۰۹۱۲۳۴۵۶۷۸۹",
        "٠٩١٢٣٤٥٦٧٨٩",
        " 0912 345 6789 ",
        "0912-345-6789",
    ],
)
def test_normalize_mobile_variants(raw: str) -> None:
    assert normalize_mobile(raw) == "989123456789"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "0812345678",
        "091234567",
        "0912345678901",
        "abc",
        "09123456a89",
        "++989123456789",
        "0912345678‌9x",
        "98912345678",
        "+0989123456789",
    ],
)
def test_normalize_mobile_rejects(raw: str) -> None:
    with pytest.raises(InvalidMobile):
        normalize_mobile(raw)


def test_format_mobile_local() -> None:
    assert format_mobile_local("989123456789") == "09123456789"


def test_to_ascii_digits() -> None:
    assert to_ascii_digits("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩ab1") == "01234567890123456789ab1"
