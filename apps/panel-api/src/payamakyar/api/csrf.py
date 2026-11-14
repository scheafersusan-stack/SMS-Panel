"""Double-submit CSRF: cookie ``pk_csrf`` must equal header ``X-CSRF-Token`` on unsafe methods."""

import hmac

from starlette.requests import Request

PREFIXES = ("/panel/web/v1", "/panel/admin/v1")
HEADER = "x-csrf-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_EXEMPT_EXACT = frozenset(f"{p}/auth/login" for p in PREFIXES)
_EXEMPT_PREFIX = tuple(f"{p}/auth/{g}/" for p in PREFIXES for g in ("register", "reset"))


def is_protected(method: str, path: str) -> bool:
    if method.upper() in SAFE_METHODS:
        return False
    if not any(path == p or path.startswith(p + "/") for p in PREFIXES):
        return False
    if path in _EXEMPT_EXACT:
        return False
    return not any(path.startswith(e) and len(path) > len(e) for e in _EXEMPT_PREFIX)


def csrf_ok(request: Request, cookie_name: str) -> bool:
    cookie = request.cookies.get(cookie_name, "")
    header = request.headers.get(HEADER, "")
    if not cookie or not header:
        return False
    return hmac.compare_digest(cookie.encode(), header.encode())
