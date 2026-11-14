"""TOTP helpers (RFC 6238)."""

import re

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
