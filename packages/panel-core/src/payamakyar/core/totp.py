"""TOTP helpers (RFC 6238)."""

import re
from datetime import datetime

import pyotp

from payamakyar.core.phone import to_ascii_digits

_SEP = re.compile(r"[\s‌‎‏-]")


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, account: str, issuer: str = "Payamakyar") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=issuer)


def verify_totp(secret: str, code: str, *, valid_window: int = 1) -> bool:
    cleaned = _SEP.sub("", to_ascii_digits(code))
    if not (cleaned.isascii() and cleaned.isdigit()):
        return False
    return bool(pyotp.TOTP(secret).verify(cleaned, valid_window=valid_window))


def totp_matching_step(
    secret: str, code: str, *, at: datetime, valid_window: int = 1
) -> int | None:
    """The time-step (counter) whose code equals ``code`` within ``valid_window``, else None.

    Callers store the accepted step and refuse any later code whose step is not greater
    (replay protection); the earliest matching step is returned.
    """
    cleaned = _SEP.sub("", to_ascii_digits(code))
    if not (cleaned.isascii() and cleaned.isdigit()):
        return None
    totp = pyotp.TOTP(secret)
    current = totp.timecode(at)
    for offset in range(-valid_window, valid_window + 1):
        if pyotp.utils.strings_equal(cleaned, totp.generate_otp(current + offset)):
            return current + offset
    return None
