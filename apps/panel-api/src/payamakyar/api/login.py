"""Login policy: lockout, IP and hours restrictions, the sealed ``mfa_token``, login events.

``login_hours`` shape (stored on ``users.login_hours``)::

    [{"days": [0, 1, 2], "from": "08:00", "to": "18:00"}, ...]

``days`` counts from Saturday (0 = Saturday ... 6 = Friday); times are ``HH:MM`` in
Asia/Tehran, ``from`` inclusive and ``to`` exclusive, ``to`` may be ``24:00``; windows do
not wrap past midnight (use two entries). An empty or missing list means no restriction;
a non-empty list allows only the listed windows (malformed entries allow nothing).
"""

import ipaddress
import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from functools import lru_cache
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from payamakyar.api.errors import ApiError
from payamakyar.core.crypto import SecretBox, SecretBoxError
from payamakyar.core.jalali import TEHRAN
from payamakyar.core.passwords import hash_password, password_problems
from payamakyar.core.settings import PanelSettings
from payamakyar.db.models import LoginEvent, User
from payamakyar.db.settings_store import SettingsStore

MFA_TOKEN_TTL_SECONDS = 300
MAX_PASSWORD_LENGTH = 128
MAX_LOCKOUT_SECONDS = 86400
_MFA_TYP = "mfa"
_NIL_UUID = uuid.UUID(int=0)


def secret_box(settings: PanelSettings) -> SecretBox:
    """The box that seals mfa tokens and TOTP secrets (keyed by ``settings.secret_key``)."""
    return SecretBox(settings.secret_key.get_secret_value().encode())


@lru_cache(maxsize=1)
def dummy_hash() -> str:
    """An argon2 hash nobody's password matches, verified for unknown users (equal timing)."""
    return hash_password(uuid.uuid4().hex + "Aa1!")


# --- errors -------------------------------------------------------------------------------


def invalid_credentials() -> ApiError:
    return ApiError(
        401,
        "INVALID_CREDENTIALS",
        "نام کاربری یا رمز عبور نادرست است",
        "نام کاربری یا رمز عبور را بررسی کنید.",
    )


def account_locked(until: datetime, now: datetime) -> ApiError:
    wait = max(1, int((until - now).total_seconds() + 0.999))
    return ApiError(
        423,
        "ACCOUNT_LOCKED",
        "حساب به‌طور موقت قفل شده است",
        until.astimezone(UTC).isoformat(),
        headers={"Retry-After": str(wait)},
    )


def mfa_token_invalid() -> ApiError:
    return ApiError(401, "MFA_TOKEN_INVALID", "مرحلهٔ ورود منقضی شده است", "دوباره وارد حساب شوید.")


def rate_limited(retry_after: int) -> ApiError:
    return ApiError(
        429,
        "RATE_LIMITED",
        "تعداد درخواست‌ها زیاد است",
        "کمی بعد دوباره تلاش کنید.",
        headers={"Retry-After": str(retry_after)},
    )


_ACCESS_ERRORS: dict[str, tuple[str, str, str]] = {
    "inactive": ("ACCOUNT_INACTIVE", "حساب غیرفعال است", "با پشتیبانی تماس بگیرید."),
    "expired": ("ACCOUNT_EXPIRED", "اعتبار حساب به پایان رسیده است", "با پشتیبانی تماس بگیرید."),
    "ip_not_allowed": (
        "LOGIN_IP_NOT_ALLOWED",
        "ورود از این نشانی مجاز نیست",
        "از نشانی مجاز وارد شوید.",
    ),
    "outside_hours": (
        "LOGIN_OUTSIDE_HOURS",
        "ورود در این ساعت مجاز نیست",
        "در ساعت‌های مجاز وارد شوید.",
    ),
}


def access_error(outcome: str) -> ApiError:
    code, title, detail = _ACCESS_ERRORS[outcome]
    return ApiError(403, code, title, detail)


async def check_new_password(s: AsyncSession, password: str, pointer: str) -> None:
    """422 ``PASSWORD_TOO_LONG`` / ``PASSWORD_WEAK`` (detail: comma-joined problem codes)."""
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ApiError(
            422,
            "PASSWORD_TOO_LONG",
            "رمز عبور بیش از حد طولانی است",
            f"رمز عبور نباید بیش از {MAX_PASSWORD_LENGTH} نویسه باشد.",
            pointer,
        )
    min_length = int(await SettingsStore(s).get("auth.password_min_length"))
    problems = password_problems(password, min_length)
    if problems:
        raise ApiError(422, "PASSWORD_WEAK", "رمز عبور ضعیف است", ",".join(problems), pointer)


# --- restrictions -------------------------------------------------------------------------


def ip_allowed(allowed: Iterable[Any] | None, ip: str) -> bool:
    nets = list(allowed or [])
    if not nets:
        return True
    try:
        addr: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped  # ::ffff:a.b.c.d matches IPv4 networks
    for net in nets:
        try:
            if addr in ipaddress.ip_network(str(net), strict=False):
                return True
        except ValueError:
            continue
    return False


def _parse_hhmm(value: Any) -> time | None:
    if not isinstance(value, str):
        return None
    if value == "24:00":
        return time.max
    try:
        return time.fromisoformat(value) if len(value) == 5 else None
    except ValueError:
        return None


def within_hours(windows: list[dict[str, Any]] | None, at: datetime) -> bool:
    if not windows:
        return True
    local = at.astimezone(TEHRAN)
    day = (local.weekday() + 2) % 7  # Monday=0 -> Saturday-first index
    now_t = local.time().replace(tzinfo=None)
    for window in windows:
        if not isinstance(window, dict):
            continue
        days = window.get("days")
        start, end = _parse_hhmm(window.get("from")), _parse_hhmm(window.get("to"))
        if not isinstance(days, list) or start is None or end is None:
            continue
        if day in days and start <= now_t < end:
            return True
    return False


def access_problem(user: User, ip: str, at: datetime) -> str | None:
    """The first restriction that refuses this sign-in (checked after the password)."""
    if user.status != "active":
        return "inactive"
    if user.expires_at is not None and at >= user.expires_at:
        return "expired"
    if not ip_allowed(user.allowed_ips, ip):
        return "ip_not_allowed"
    if not within_hours(user.login_hours, at):
        return "outside_hours"
    return None


# --- lockout ------------------------------------------------------------------------------


async def _locks_since_last_success(s: AsyncSession, user_id: uuid.UUID) -> int:
    # Event ids are UUIDv7 (insertion-ordered), which stays exact when timestamps tie.
    last_success = (
        select(LoginEvent.id)
        .where(LoginEvent.user_id == user_id, LoginEvent.outcome == "success")
        .order_by(LoginEvent.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    count = (
        await s.execute(
            select(func.count())
            .select_from(LoginEvent)
            .where(
                LoginEvent.user_id == user_id,
                LoginEvent.outcome == "locked",
                LoginEvent.id > func.coalesce(last_success, _NIL_UUID),
            )
        )
    ).scalar_one()
    return int(count)


async def register_failure(s: AsyncSession, user: User, now: datetime) -> str:
    """Count a failed credential/second-factor attempt; returns ``"locked"`` when it locks.

    The increment and the lock are single SQL statements, so concurrent failures are never
    lost even when the caller no longer holds the row lock (``otp.check`` commits). The n-th
    lock since the last successful login lasts ``lockout_seconds * 2**(n-1)``, capped at
    86400 s; the lock count is derived from ``login_events`` (outcome ``locked``).
    """
    store = SettingsStore(s)
    max_tries = int(await store.get("auth.max_failed_tries"))
    base = int(await store.get("auth.lockout_seconds"))
    count = (
        await s.execute(
            update(User)
            .where(User.id == user.id)
            .values(failed_logins=User.failed_logins + 1)
            .returning(User.failed_logins)
            .execution_options(synchronize_session=False)
        )
    ).scalar_one()
    set_committed_value(user, "failed_logins", count)
    if count < max_tries:
        return "failed"
    prior = await _locks_since_last_success(s, user.id)
    until = now + timedelta(seconds=min(base * 2 ** min(prior, 20), MAX_LOCKOUT_SECONDS))
    # Only one of several concurrent threshold crossings locks (the others see the reset).
    locked = (
        await s.execute(
            update(User)
            .where(User.id == user.id, User.failed_logins >= max_tries)
            .values(failed_logins=0, locked_until=until)
            .returning(User.id)
            .execution_options(synchronize_session=False)
        )
    ).first()
    if locked is None:
        return "failed"
    set_committed_value(user, "failed_logins", 0)
    set_committed_value(user, "locked_until", until)
    return "locked"


def locked_until(user: User, now: datetime) -> datetime | None:
    """When the current lock ends, or None if the account is not locked at ``now``."""
    if user.locked_until is not None and now < user.locked_until:
        return user.locked_until
    return None


async def record_event(
    s: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    tried: str | None,
    ip: str,
    ua: str | None,
    outcome: str,
    at: datetime,
) -> None:
    s.add(
        LoginEvent(
            user_id=user_id,
            username_tried=tried,
            ip=ip or None,
            user_agent=ua[:512] if ua else None,
            outcome=outcome,
            at=at,
        )
    )
    await s.flush()


# --- mfa token ----------------------------------------------------------------------------


def seal_mfa_token(box: SecretBox, user_id: uuid.UUID, method: str, now: datetime) -> str:
    iat = int(now.timestamp())
    payload = {
        "typ": _MFA_TYP,
        "user_id": str(user_id),
        "method": method,
        "iat": iat,
        "exp": iat + MFA_TOKEN_TTL_SECONDS,
        "jti": uuid.uuid4().hex,
    }
    return box.seal(json.dumps(payload, separators=(",", ":")))


@dataclass(frozen=True)
class MfaClaims:
    user_id: uuid.UUID
    method: str
    issued_at: datetime
    expires_at: datetime
    jti: str


def _used_key(jti: str) -> str:
    return f"mfa:used:{jti}"


async def open_mfa_token(box: SecretBox, redis: Redis, token: str, now: datetime) -> MfaClaims:
    """The token's claims, or 401 ``MFA_TOKEN_INVALID`` (bad, expired or already used)."""
    try:
        data = json.loads(box.open(token))
        if data.get("typ") != _MFA_TYP or data.get("method") not in ("totp", "sms"):
            raise ValueError("wrong token type")
        claims = MfaClaims(
            user_id=uuid.UUID(str(data["user_id"])),
            method=str(data["method"]),
            issued_at=datetime.fromtimestamp(int(data["iat"]), UTC),
            expires_at=datetime.fromtimestamp(int(data["exp"]), UTC),
            jti=str(data["jti"]),
        )
    except (SecretBoxError, ValueError, KeyError, TypeError, AttributeError):
        raise mfa_token_invalid() from None
    if now >= claims.expires_at or not claims.jti or await redis.exists(_used_key(claims.jti)):
        raise mfa_token_invalid()
    return claims


async def consume_mfa_token(redis: Redis, claims: MfaClaims, now: datetime) -> None:
    """Mark the token used (until it would expire anyway); 401 if another request won."""
    ttl = max(1, int((claims.expires_at - now).total_seconds()) + 1)
    if not await redis.set(_used_key(claims.jti), "1", nx=True, ex=ttl):
        raise mfa_token_invalid()
