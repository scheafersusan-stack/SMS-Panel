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
from datetime import UTC, datetime, time, timedelta
from functools import lru_cache
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from payamakyar.api.errors import ApiError
from payamakyar.core.crypto import SecretBox, SecretBoxError
from payamakyar.core.jalali import TEHRAN
from payamakyar.core.passwords import hash_password
from payamakyar.db.models import LoginEvent, User
from payamakyar.db.settings_store import SettingsStore

MFA_TOKEN_TTL_SECONDS = 300
MAX_LOCKOUT_SECONDS = 86400
_MFA_TYP = "mfa"
_NIL_UUID = uuid.UUID(int=0)


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


# --- restrictions -------------------------------------------------------------------------


def ip_allowed(allowed: Iterable[Any] | None, ip: str) -> bool:
    nets = list(allowed or [])
    if not nets:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
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

    The n-th lock since the last successful login lasts ``lockout_seconds * 2**(n-1)``,
    capped at 86400 s. The lock count is derived from ``login_events`` (outcome ``locked``).
    """
    store = SettingsStore(s)
    max_tries = int(await store.get("auth.max_failed_tries"))
    base = int(await store.get("auth.lockout_seconds"))
    user.failed_logins = (user.failed_logins or 0) + 1
    if user.failed_logins < max_tries:
        return "failed"
    prior = await _locks_since_last_success(s, user.id)
    seconds = min(base * 2 ** min(prior, 20), MAX_LOCKOUT_SECONDS)
    user.locked_until = now + timedelta(seconds=seconds)
    user.failed_logins = 0
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
    }
    return box.seal(json.dumps(payload, separators=(",", ":")))


def open_mfa_token(box: SecretBox, token: str, now: datetime) -> tuple[uuid.UUID, str, datetime]:
    """``(user_id, method, issued_at)`` or 401 ``MFA_TOKEN_INVALID``."""
    try:
        data = json.loads(box.open(token))
        if data.get("typ") != _MFA_TYP or data.get("method") not in ("totp", "sms"):
            raise ValueError("wrong token type")
        user_id = uuid.UUID(str(data["user_id"]))
        iat, exp = int(data["iat"]), int(data["exp"])
    except (SecretBoxError, ValueError, KeyError, TypeError, AttributeError):
        raise mfa_token_invalid() from None
    if now.timestamp() >= exp:
        raise mfa_token_invalid()
    return user_id, str(data["method"]), datetime.fromtimestamp(iat, UTC)
