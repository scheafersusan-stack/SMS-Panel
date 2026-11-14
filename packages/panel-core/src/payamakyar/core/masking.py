"""Masking of mobiles and secrets for logs and error bodies."""

import itertools
import re
from typing import Any

from pydantic import SecretStr

from payamakyar.core.phone import (
    InvalidMobile,
    format_mobile_local,
    normalize_mobile,
    to_ascii_digits,
)

_SECRET_SEGMENTS = frozenset(
    {"password", "passwd", "secret", "token", "otp", "authorization", "apikey"}
)
_CODE_PREFIXES = frozenset(
    {"otp", "totp", "mfa", "verification", "verify", "sms", "auth", "login", "pin", "reset"}
)
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_SPLIT = re.compile(r"[\s_\-.]+")
_OTP_LIKE = re.compile(r"[0-9]{4,10}")
_D = "0-9۰-۹٠-٩"
# Mobile embedded in free text: needs an explicit prefix so bare digit runs are left alone.
_EMBEDDED = re.compile(rf"(?<![{_D}])(?:\+98|0098|98|0)[9۹٩][{_D}]{{9}}(?![{_D}])")


def _segments(key: str) -> list[str]:
    segs = [p.lower() for p in _SPLIT.split(_CAMEL.sub("_", key)) if p]
    # a trailing plural "s" is the same word (tokens, passwords, api_keys)
    return [x[:-1] if len(x) > 3 and x.endswith("s") and x != "pass" else x for x in segs]


def _looks_like_otp(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        value = str(value)
    return isinstance(value, str) and bool(_OTP_LIKE.fullmatch(to_ascii_digits(value)))


def is_secret_key(key: str, value: Any = None) -> bool:
    """Whether ``key`` names a secret, judged on whole key segments.

    A bare ``code`` key counts only when its value looks like an OTP (4-10 ASCII digits), so
    ``status_code`` and API error codes stay visible.
    """
    segs = _segments(key)
    if any(s in _SECRET_SEGMENTS for s in segs):
        return True
    if any(a == "api" and b == "key" for a, b in itertools.pairwise(segs)):
        return True
    if "code" in segs:
        i = segs.index("code")
        if i > 0 and segs[i - 1] in _CODE_PREFIXES:
            return True
        return segs == ["code"] and _looks_like_otp(value)
    return False


def mask_mobile(s: str) -> str:
    """``0912***6789`` for any value ``normalize_mobile`` accepts; other values unchanged."""
    try:
        local = format_mobile_local(normalize_mobile(s))
    except InvalidMobile:
        return s
    return f"{local[:4]}***{local[-4:]}"


def mask_secret(s: str) -> str:
    """``****<last4>``; values of four characters or fewer are fully hidden."""
    return f"****{s[-4:]}" if len(s) > 4 else "****"


def _mask_text(s: str) -> str:
    try:
        normalize_mobile(s)
    except InvalidMobile:
        return _EMBEDDED.sub(lambda m: mask_mobile(m.group(0)), s)
    return mask_mobile(s)


def redact(obj: Any) -> Any:
    """Recursively mask secret-named keys and mobile-looking strings."""
    if isinstance(obj, SecretStr):
        return "****"
    if isinstance(obj, dict):
        return {
            k: "****" if isinstance(k, str) and is_secret_key(k, v) else redact(v)
            for k, v in obj.items()
        }
    if isinstance(obj, tuple):
        return tuple(redact(v) for v in obj)
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        return type(obj)(redact(v) for v in obj)
    if isinstance(obj, str):
        return _mask_text(obj)
    return obj
