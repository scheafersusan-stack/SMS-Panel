"""Iranian mobile number normalisation."""

import re

_DIGIT_MAP = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)
_STRIP = re.compile(r"[\s\-().]")
_LOCAL = re.compile(r"9\d{9}")


class InvalidMobile(ValueError):  # noqa: N818
    """Raised when a value is not a valid Iranian mobile number."""


def to_ascii_digits(s: str) -> str:
    """Convert Persian (۰-۹) and Arabic-Indic (٠-٩) digits to ASCII."""
    return s.translate(_DIGIT_MAP)


def normalize_mobile(raw: str) -> str:
    """Return the canonical form ``989XXXXXXXXX`` or raise ``InvalidMobile``."""
    s = _STRIP.sub("", to_ascii_digits(raw))
    if s.startswith("+"):
        s = s[1:]
        if s.startswith("0"):
            raise InvalidMobile("invalid mobile number")
        if s.startswith("98"):
            s = s[2:]
    elif s.startswith("0098"):
        s = s[4:]
    elif s.startswith("98") and len(s) == 12:
        s = s[2:]
    elif s.startswith("0"):
        s = s[1:]
    if not _LOCAL.fullmatch(s):
        raise InvalidMobile("invalid mobile number")
    return "98" + s


def format_mobile_local(canon: str) -> str:
    """Convert canonical ``989XXXXXXXXX`` to local ``09XXXXXXXXX``."""
    return "0" + canon[2:]
