"""Masking of mobiles and secrets for logs and error bodies."""

import re
from typing import Any

from pydantic import SecretStr

from payamakyar.core.phone import InvalidMobile, format_mobile_local, normalize_mobile

_SECRET_KEY = re.compile(r"password|secret|token|otp|code|api_key|authorization", re.IGNORECASE)
_D = "0-9۰-۹٠-٩"
# Mobile embedded in free text: needs an explicit prefix so bare digit runs are left alone.
_EMBEDDED = re.compile(rf"(?<![{_D}])(?:\+98|0098|98|0)[9۹٩][{_D}]{{9}}(?![{_D}])")


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
            k: "****" if isinstance(k, str) and _SECRET_KEY.search(k) else redact(v)
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
