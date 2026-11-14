"""Password policy and argon2id hashing."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


def password_problems(pw: str, min_length: int = 8) -> list[str]:
    """Return the policy codes ``pw`` violates (empty list when acceptable).

    Only ASCII Latin letters count as upper/lower; Persian letters count as
    neither. "Special" means ASCII punctuation or symbols (no spaces).
    """
    problems: list[str] = []
    if len(pw) < min_length:
        problems.append("TOO_SHORT")
    if not any("A" <= c <= "Z" for c in pw):
        problems.append("NO_UPPER")
    if not any("a" <= c <= "z" for c in pw):
        problems.append("NO_LOWER")
    if not any("0" <= c <= "9" for c in pw):
        problems.append("NO_DIGIT")
    if not any(c.isascii() and c.isprintable() and not c.isalnum() and c != " " for c in pw):
        problems.append("NO_SPECIAL")
    return problems


def hash_password(pw: str) -> str:
    return _HASHER.hash(pw)


def verify_password(hashed: str, pw: str) -> bool:
    try:
        return _HASHER.verify(hashed, pw)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    return _HASHER.check_needs_rehash(hashed)
