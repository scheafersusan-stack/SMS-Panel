"""The signed-in user's own account: sessions, password, second factor, sign-in limits."""

import ipaddress
import re
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from payamakyar.api import login, otp, profile, sessions
from payamakyar.api.deps import (
    CurrentSession,
    CurrentUser,
    Permissions,
    SessionDep,
    client_ip,
    get_clock,
    get_redis,
    get_settings_dep,
    not_authenticated,
)
from payamakyar.api.errors import ApiError, validation_failed
from payamakyar.api.notifier import Notifier, SystemNotifier
from payamakyar.core.crypto import SecretBoxError
from payamakyar.core.passwords import hash_password, verify_password
from payamakyar.core.settings import PanelSettings
from payamakyar.core.totp import new_totp_secret, totp_matching_step, totp_uri
from payamakyar.db import audit
from payamakyar.db.models import Role, Session, User, UserRole

router = APIRouter(prefix="/account", tags=["account"])


Clock = Annotated[Callable[[], datetime], Depends(get_clock)]
Settings = Annotated[PanelSettings, Depends(get_settings_dep)]
RedisDep = Annotated[Redis, Depends(get_redis)]


class SessionOut(BaseModel):
    id: uuid.UUID
    ip: str | None
    user_agent: str | None
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    current: bool
    impersonated: bool


class SessionList(BaseModel):
    sessions: list[SessionOut]


async def _me(s: AsyncSession, user: User, perms: frozenset[str]) -> profile.MeOut:
    names = (
        await s.execute(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user.id)
            .order_by(Role.name)
        )
    ).scalars()
    return profile.build_me(user, list(names), perms)


@router.get("/me")
async def me(user: CurrentUser, perms: Permissions, s: SessionDep) -> profile.MeOut:
    return await _me(s, user, perms)


class ProfileBody(BaseModel):
    """Partial update (PATCH semantics on PUT): only the fields sent are changed; null clears."""

    model_config = ConfigDict(extra="forbid")
    first_name: str | None = None
    last_name: str | None = None
    national_code: str | None = None
    birth_date: str | None = None
    email: str | None = None
    phone: str | None = None
    postal_code: str | None = None
    address: str | None = None
    company_name: str | None = None
    company_national_id: str | None = None
    economic_code: str | None = None
    ceo_name: str | None = None
    ceo_national_code: str | None = None


@router.put("/profile")
async def update_profile(
    body: ProfileBody,
    current: CurrentSession,
    request: Request,
    s: SessionDep,
    clock: Clock,
    perms: Permissions,
) -> profile.MeOut:
    user = await _locked_user(s, current)
    allowed = profile.fields_for(user.kind)
    today = profile.today_utc(clock())
    values: dict[str, Any] = {}
    for field in body.model_fields_set:
        if field not in allowed:
            raise validation_failed("این فیلد برای نوع حساب شما مجاز نیست.", f"/{field}")
        raw = getattr(body, field)
        values[field] = (
            None if raw is None or not raw.strip() else profile.normalise(field, raw, today)
        )
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for field, new in values.items():
        old = getattr(user, field)
        if old != new:
            before[field] = profile.display(field, old)
            after[field] = profile.display(field, new)
            setattr(user, field, new)
    if before:
        if (
            profile.IDENTITY_FIELDS.get(user.kind, frozenset()) & before.keys()
            and user.identity_state != "none"
        ):
            before["identity_state"] = user.identity_state
            after["identity_state"] = "none"
            user.identity_state = "none"
        await _audit_user(s, user, request, "user.profile_update", before=before, after=after)
        await s.flush()
    return await _me(s, user, perms)


@router.get("/sessions")
async def list_sessions(current: CurrentSession, s: SessionDep, clock: Clock) -> SessionList:
    now = clock()
    idle = await sessions.idle_lifetime(s)
    rows = (
        (
            await s.execute(
                select(Session)
                .where(
                    Session.user_id == current.user_id,
                    Session.revoked_at.is_(None),
                    Session.expires_at > now,
                    Session.last_seen_at > now - timedelta(seconds=idle),
                )
                .order_by(Session.last_seen_at.desc(), Session.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return SessionList(
        sessions=[
            SessionOut(
                id=row.id,
                ip=str(row.ip) if row.ip is not None else None,
                user_agent=row.user_agent,
                created_at=row.created_at,
                last_seen_at=row.last_seen_at,
                expires_at=row.expires_at,
                current=row.id == current.id,
                impersonated=row.impersonator_id is not None,
            )
            for row in rows
        ]
    )


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(
    session_id: uuid.UUID,
    current: CurrentSession,
    request: Request,
    response: Response,
    s: SessionDep,
    clock: Clock,
    settings: Settings,
) -> None:
    row = (
        await s.execute(
            select(Session).where(Session.id == session_id, Session.user_id == current.user_id)
        )
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        raise ApiError(
            404,
            "SESSION_NOT_FOUND",
            "نشست یافت نشد",
            "این نشست وجود ندارد یا پیش‌تر بسته شده است.",
            "/session_id",
        )
    row.revoked_at = clock()
    await audit.record(
        s,
        actor_id=current.user_id,
        actor_ip=client_ip(request) or None,
        action="session.revoke",
        target_type="session",
        target_id=str(row.id),
    )
    if row.id == current.id:
        sessions.clear_cookies(response, settings)


# --- helpers ----------------------------------------------------------------------------

TOTP_PENDING_TTL_SECONDS = 600
Secret = Annotated[str, StringConstraints(min_length=1, max_length=1024)]
Code = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16)]


async def _locked_user(s: AsyncSession, current: Session) -> User:
    user = (
        await s.execute(select(User).where(User.id == current.user_id).with_for_update())
    ).scalar_one_or_none()
    if user is None:
        raise not_authenticated()
    return user


async def _reauthenticate(
    s: AsyncSession,
    user: User,
    password: str,
    *,
    request: Request,
    now: datetime,
    pointer: str,
) -> None:
    """Check the account password again. A wrong one counts toward the login lockout (and is
    committed before raising); while the account is locked even the right one is refused.
    A right one resets the failure count."""
    if (until := login.locked_until(user, now)) is not None:
        raise login.account_locked(until, now)
    if verify_password(user.password_hash, password):
        user.failed_logins = 0  # as a successful sign-in does
        return
    locked = await login.register_failure(s, user, now) == "locked"
    ua = request.headers.get("user-agent")
    await login.record_event(
        s,
        user_id=user.id,
        tried=None,
        ip=client_ip(request),
        ua=ua,
        outcome="locked" if locked else "reauth_failed",
        at=now,
    )
    await s.commit()
    raise ApiError(
        400,
        "CURRENT_PASSWORD_INVALID",
        "رمز عبور فعلی نادرست است",
        "رمز عبور فعلی را بررسی کنید.",
        pointer,
    )


async def _audit_user(
    s: AsyncSession,
    user: User,
    request: Request,
    action: str,
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    await audit.record(
        s,
        actor_id=user.id,
        actor_ip=client_ip(request) or None,
        action=action,
        target_type="user",
        target_id=str(user.id),
        before=before,
        after=after,
    )


# --- password ---------------------------------------------------------------------------


class PasswordChangeBody(BaseModel):
    current_password: Secret
    new_password: Secret


@router.post("/password", status_code=204)
async def change_password(
    body: PasswordChangeBody,
    current: CurrentSession,
    request: Request,
    s: SessionDep,
    clock: Clock,
    notifier: Notifier,
) -> None:
    now = clock()
    await login.check_new_password(s, body.new_password, "/new_password")
    user = await _locked_user(s, current)
    await _reauthenticate(
        s, user, body.current_password, request=request, now=now, pointer="/current_password"
    )
    user.password_hash = hash_password(body.new_password)
    revoked = await sessions.revoke_all(s, user.id, now=now, except_id=current.id)
    await _audit_user(s, user, request, "user.password_change", after={"sessions_revoked": revoked})
    await notifier.send_sms(s, user.mobile, "password_changed", {})


# --- second factor ----------------------------------------------------------------------


def _pending_key(user_id: uuid.UUID) -> str:
    return f"mfa:totp:pending:{user_id}"


class TotpSetup(BaseModel):
    secret: str
    otpauth_uri: str


class PasswordBody(BaseModel):
    password: Secret


class TotpEnableBody(BaseModel):
    code: Code
    password: Secret


@router.post("/mfa/totp/setup")
async def totp_setup(
    current: CurrentSession,
    request: Request,
    s: SessionDep,
    settings: Settings,
    redis: RedisDep,
) -> TotpSetup:
    """A new secret, kept sealed in Redis (``TOTP_PENDING_TTL_SECONDS``) until ``enable``
    proves the authenticator has it; the active factor is unchanged until then."""
    user = await _locked_user(s, current)
    secret = new_totp_secret()
    sealed = login.secret_box(settings).seal(secret)
    await redis.set(_pending_key(user.id), sealed, ex=TOTP_PENDING_TTL_SECONDS)
    await _audit_user(s, user, request, "user.mfa_setup", after={"method": "totp"})
    return TotpSetup(secret=secret, otpauth_uri=totp_uri(secret, user.username))


def _setup_required() -> ApiError:
    return ApiError(
        409,
        "TOTP_SETUP_REQUIRED",
        "راه‌اندازی برنامهٔ احراز هویت لازم است",
        "ابتدا کد QR تازه بگیرید.",
    )


async def _set_mfa(
    s: AsyncSession,
    user: User,
    request: Request,
    notifier: SystemNotifier,
    redis: Redis,
    method: str,
    *,
    sealed: str | None = None,
    step: int | None = None,
) -> None:
    """Switch the second factor, audit it, tell the owner by SMS, drop any pending setup."""
    before = {"method": user.mfa_method}
    user.mfa_method = method
    user.totp_secret_sealed = sealed
    user.totp_last_step = step
    action = "user.mfa_disable" if method == "none" else "user.mfa_enable"
    await _audit_user(s, user, request, action, before=before, after={"method": method})
    await notifier.send_sms(s, user.mobile, "mfa_changed", {})
    await s.flush()
    await redis.delete(_pending_key(user.id))


@router.post("/mfa/totp/enable", status_code=204)
async def totp_enable(
    body: TotpEnableBody,
    current: CurrentSession,
    request: Request,
    s: SessionDep,
    clock: Clock,
    settings: Settings,
    notifier: Notifier,
    redis: RedisDep,
) -> None:
    now = clock()
    user = await _locked_user(s, current)
    await _reauthenticate(s, user, body.password, request=request, now=now, pointer="/password")
    raw = await redis.get(_pending_key(user.id))
    if raw is None:
        raise _setup_required()
    sealed = raw.decode() if isinstance(raw, bytes) else str(raw)
    try:
        secret = login.secret_box(settings).open(sealed)
    except SecretBoxError:
        await redis.delete(_pending_key(user.id))
        raise _setup_required() from None
    step = totp_matching_step(secret, body.code, at=now)
    if step is None:
        raise otp.invalid_code()
    # The accepted step is stored, so the enable code cannot be replayed at sign-in.
    await _set_mfa(s, user, request, notifier, redis, "totp", sealed=sealed, step=step)


@router.post("/mfa/sms/enable", status_code=204)
async def sms_enable(
    body: PasswordBody,
    current: CurrentSession,
    request: Request,
    s: SessionDep,
    clock: Clock,
    notifier: Notifier,
    redis: RedisDep,
) -> None:
    now = clock()
    user = await _locked_user(s, current)
    await _reauthenticate(s, user, body.password, request=request, now=now, pointer="/password")
    if not user.mobile:
        raise ApiError(
            409, "MOBILE_REQUIRED", "شمارهٔ موبایل ثبت نشده است", "ابتدا شمارهٔ موبایل را ثبت کنید."
        )
    await _set_mfa(s, user, request, notifier, redis, "sms")


@router.post("/mfa/disable", status_code=204)
async def mfa_disable(
    body: PasswordBody,
    current: CurrentSession,
    request: Request,
    s: SessionDep,
    clock: Clock,
    notifier: Notifier,
    redis: RedisDep,
) -> None:
    now = clock()
    user = await _locked_user(s, current)
    await _reauthenticate(s, user, body.password, request=request, now=now, pointer="/password")
    await _set_mfa(s, user, request, notifier, redis, "none")


# --- sign-in restrictions ---------------------------------------------------------------

MAX_ALLOWED_IPS = 50
MAX_LOGIN_WINDOWS = 28
_HHMM = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")


class LoginWindow(BaseModel):
    """See ``payamakyar.api.login``: 0 = Saturday, Tehran time, ``to`` exclusive (may be
    ``24:00``), no wrap past midnight."""

    model_config = ConfigDict(populate_by_name=True)

    days: list[int] = Field(max_length=7)
    from_: str = Field(alias="from", max_length=5)
    to: str = Field(max_length=5)


class SecurityBody(BaseModel):
    login_notice: bool
    allowed_ips: list[Annotated[str, StringConstraints(max_length=64)]] = Field(
        max_length=MAX_ALLOWED_IPS
    )
    login_hours: list[LoginWindow] = Field(max_length=MAX_LOGIN_WINDOWS)


class SecurityOut(BaseModel):
    login_notice: bool
    allowed_ips: list[str]
    login_hours: list[LoginWindow]


def _normalize_ips(items: list[str]) -> list[str]:
    out: list[str] = []
    for i, item in enumerate(items):
        try:
            net = ipaddress.ip_network(item.strip(), strict=False)
        except ValueError:
            raise validation_failed("نشانی IP یا CIDR معتبر نیست.", f"/allowed_ips/{i}") from None
        if str(net) not in out:
            out.append(str(net))
    return out


def _minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def _normalize_windows(windows: list[LoginWindow]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, w in enumerate(windows):
        base = f"/login_hours/{i}"
        if not w.days or any(d < 0 or d > 6 for d in w.days):
            raise validation_failed("روزها باید از ۰ (شنبه) تا ۶ (جمعه) باشند.", f"{base}/days")
        if not _HHMM.fullmatch(w.from_):
            raise validation_failed("ساعت شروع باید به شکل HH:MM باشد.", f"{base}/from")
        if w.to != "24:00" and not _HHMM.fullmatch(w.to):
            raise validation_failed("ساعت پایان باید به شکل HH:MM یا 24:00 باشد.", f"{base}/to")
        if _minutes(w.to) <= _minutes(w.from_):
            raise validation_failed("ساعت پایان باید بعد از ساعت شروع باشد.", f"{base}/to")
        out.append({"days": sorted(set(w.days)), "from": w.from_, "to": w.to})
    return out


def _would_lock_out(pointer: str, detail: str) -> ApiError:
    return ApiError(
        422, "WOULD_LOCK_YOU_OUT", "این تنظیم دسترسی خود شما را می‌بندد", detail, pointer
    )


def _security_of(user: User) -> SecurityOut:
    return SecurityOut(
        login_notice=user.login_notice,
        allowed_ips=[str(x) for x in user.allowed_ips or []],
        login_hours=[LoginWindow.model_validate(w) for w in user.login_hours or []],
    )


def _snapshot(user: User) -> dict[str, Any]:
    return {
        "login_notice": user.login_notice,
        "allowed_ips": [str(x) for x in user.allowed_ips or []],
        "login_hours": list(user.login_hours or []),
    }


@router.get("/security")
async def get_security(current: CurrentSession, s: SessionDep) -> SecurityOut:
    user = await s.get(User, current.user_id)
    if user is None:
        raise not_authenticated()
    return _security_of(user)


@router.put("/security")
async def put_security(
    body: SecurityBody,
    current: CurrentSession,
    request: Request,
    s: SessionDep,
    clock: Clock,
) -> SecurityOut:
    """Empty lists lift a restriction. Refuses (422 ``WOULD_LOCK_YOU_OUT``) a non-empty
    ``allowed_ips`` that excludes the caller's address, and a non-empty ``login_hours`` that
    excludes the current Tehran time."""
    now = clock()
    ips = _normalize_ips(body.allowed_ips)
    windows = _normalize_windows(body.login_hours)
    ip = client_ip(request)
    if ips and not login.ip_allowed(ips, ip):
        raise _would_lock_out("/allowed_ips", "نشانی فعلی شما در فهرست مجاز نیست.")
    if windows and not login.within_hours(windows, now):
        raise _would_lock_out("/login_hours", "ساعت فعلی در بازه‌های مجاز نیست.")
    user = await _locked_user(s, current)
    before = _snapshot(user)
    user.login_notice = body.login_notice
    user.allowed_ips = ips or None
    user.login_hours = windows or None
    await s.flush()
    await _audit_user(
        s, user, request, "user.security_update", before=before, after=_snapshot(user)
    )
    return _security_of(user)
