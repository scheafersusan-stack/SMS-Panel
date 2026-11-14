"""Iranian national code (10 digits) and legal-entity id (11 digits) checks."""

import re

from payamakyar.core.phone import to_ascii_digits

_COMPANY_WEIGHTS = (29, 27, 23, 19, 17, 29, 27, 23, 19, 17)


def _digits(code: str, length: int) -> str | None:
    d = to_ascii_digits(code)
    return d if re.fullmatch(rf"[0-9]{{{length}}}", d) else None


def is_valid_national_code(code: str) -> bool:
    d = _digits(code, 10)
    if d is None or len(set(d)) == 1:
        return False
    r = sum(int(d[i]) * (10 - i) for i in range(9)) % 11
    return int(d[9]) == (r if r < 2 else 11 - r)


def is_valid_company_id(code: str) -> bool:
    d = _digits(code, 11)
    if d is None:
        return False
    k = int(d[9]) + 2
    s = sum((int(d[i]) + k) * w for i, w in enumerate(_COMPANY_WEIGHTS))
    r = s % 11
    if r == 10:
        r = 0
    return r == int(d[10])
