"""Authentication routes: registration, login with an optional second factor, logout."""

import logging
import re
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, StringConstraints
from redis.asyncio import Redis
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from payamakyar.api import login, otp, sessions
from payamakyar.api.deps import (
    CurrentSession,
    SessionDep,
    client_ip,
    get_clock,
    get_redis,
    get_settings_dep,
)
from payamakyar.api.errors import ApiError
from payamakyar.api.notifier import OutboxNotifier, SystemNotifier
from payamakyar.api.ratelimit import RateLimiter
from payamakyar.core.crypto import SecretBox, SecretBoxError
from payamakyar.core.jalali import format_tehran
from payamakyar.core.masking import mask_mobile
from payamakyar.core.passwords import (
    hash_password,
    needs_rehash,
    password_problems,
    verify_password,
)
from payamakyar.core.phone import InvalidMobile, normalize_mobile
from payamakyar.core.settings import PanelSettings
from payamakyar.core.totp import totp_matching_step
from payamakyar.db import audit
from payamakyar.db.models import OtpChallenge, Role, User, UserRole
from payamakyar.db.settings_store import SettingsStore

log = logging.getLogger("payamakyar.api.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

MAX_PASSWORD_LENGTH = 128
CUSTOMER_ROLE = "customer"
_USERNAME = re.compile(r"[A-Za-z0-9_.]{3,32}")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


def get_notifier() -> SystemNotifier:
    return OutboxNotifier()


Clock = Annotated[Callable[[], datetime], Depends(get_clock)]
Notifier = Annotated[SystemNotifier, Depends(get_notifier)]
Settings = Annotated[PanelSettings, Depends(get_settings_dep)]


KIND_GRACE_SECONDS = 60


def _kind_key(challenge_id: uuid.UUID) -> str:
    return f"reg:kind:{challenge_id}"


async def _stored_kind(redis: Redis, challenge_id: uuid.UUID) -> str | None:
    """The account kind chosen at ``register/start`` (the challenge row has no column for it)."""
    raw = await redis.get(_kind_key(challenge_id))
    if raw is None:
        return None
    value = raw.decode() if isinstance(raw, bytes) else str(raw)
    return value if value in ("individual", "company") else None


def _invalid(detail: str, pointer: str) -> ApiError:
    return ApiError(422, "VALIDATION_FAILED", "داده‌های ارسالی نامعتبر است", detail, pointer)


async def _ensure_resend_window(
    s: AsyncSession, now: datetime, pointer: str | None, *where: Any
) -> int:
    """429 ``OTP_RESEND_TOO_SOON`` while the newest matching challenge is too recent."""
    resend = int(await SettingsStore(s).get("otp.resend_seconds"))
    last = (await s.execute(select(func.max(OtpChallenge.created_at)).where(*where))).scalar_one()
    if last is not None and (now - last).total_seconds() < resend:
        wait = max(int((last - now).total_seconds()) + resend, 1)
        raise ApiError(
            429,
            "OTP_RESEND_TOO_SOON",
            "ارسال مجدد کد هنوز ممکن نیست",
            f"{wait} ثانیهٔ دیگر دوباره تلاش کنید.",
            pointer,
            headers={"Retry-After": str(wait)},
        )
    return resend


class StartBody(BaseModel):
    mobile: str
    kind: Literal["individual", "company"]


class StartResult(BaseModel):
    challenge_id: uuid.UUID
    resend_after: int


class CompleteBody(BaseModel):
    challenge_id: uuid.UUID
    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16)]
    username: str
    password: str
    first_name: Name
    last_name: Name | None = None
    company_name: Name | None = None
    email: Annotated[str, StringConstraints(strip_whitespace=True, max_length=254)] | None = None


class CompleteResult(BaseModel):
    user_id: uuid.UUID


@router.post("/register/start", status_code=202)
async def register_start(
    body: StartBody,
    request: Request,
    s: SessionDep,
    clock: Clock,
    notifier: Notifier,
    redis: Annotated[Redis, Depends(get_redis)],
) -> StartResult:
    try:
        mobile = normalize_mobile(body.mobile)
    except InvalidMobile:
        raise _invalid("شمارهٔ موبایل معتبر نیست.", "/mobile") from None
    now = clock()
    ip = client_ip(request)
    limit = int(await SettingsStore(s).get("otp.start_rate_per_ip_per_hour"))
    limited = await RateLimiter(redis, lambda: now.timestamp()).hit(f"otp.start:{ip}", limit, 3600)
    if not limited.allowed:
        raise ApiError(
            429,
            "RATE_LIMITED",
            "تعداد درخواست‌ها زیاد است",
            "کمی بعد دوباره تلاش کنید.",
            headers={"Retry-After": str(limited.retry_after)},
        )
    # Serialise concurrent starts for one number so the resend window cannot be raced.
    await s.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"otp:{mobile}"})
    taken = (await s.execute(select(User.id).where(User.mobile == mobile))).first()
    if taken is not None:
        raise ApiError(
            409, "MOBILE_TAKEN", "این شماره قبلاً ثبت شده است", "با این شماره وارد شوید.", "/mobile"
        )
    resend = await _ensure_resend_window(
        s, now, "/mobile", OtpChallenge.purpose == "register", OtpChallenge.mobile == mobile
    )
    challenge_id, code = await otp.issue(s, "register", mobile, None, ip, now=now)
    await notifier.send_sms(s, mobile, "otp", {"code": code})
    ttl = int(await SettingsStore(s).get("otp.ttl_seconds"))
    await redis.set(_kind_key(challenge_id), body.kind, ex=ttl + KIND_GRACE_SECONDS)
    return StartResult(challenge_id=challenge_id, resend_after=resend)


async def _customer_role_id(s: AsyncSession) -> uuid.UUID:
    await s.execute(
        insert(Role)
        .values(name=CUSTOMER_ROLE, title_fa="مشتری")
        .on_conflict_do_nothing(index_elements=[Role.name])
    )
    return (await s.execute(select(Role.id).where(Role.name == CUSTOMER_ROLE))).scalar_one()


def _validate_complete(body: CompleteBody, kind: str) -> None:
    if kind == "company":
        if not body.company_name:
            raise _invalid("نام شرکت الزامی است.", "/company_name")
    elif not body.last_name:
        raise _invalid("نام خانوادگی الزامی است.", "/last_name")
    if not _USERNAME.fullmatch(body.username):
        raise _invalid("نام کاربری باید ۳ تا ۳۲ نویسهٔ انگلیسی، رقم، _ یا . باشد.", "/username")
    if body.email is not None and not _EMAIL.fullmatch(body.email):
        raise _invalid("نشانی ایمیل معتبر نیست.", "/email")


@router.post("/register/complete", status_code=201)
async def register_complete(
    body: CompleteBody,
    request: Request,
    response: Response,
    s: SessionDep,
    clock: Clock,
    settings: Settings,
    redis: Annotated[Redis, Depends(get_redis)],
) -> CompleteResult:
    now = clock()
    ip = client_ip(request)
    kind = await _stored_kind(redis, body.challenge_id)
    if kind is None:
        # Unknown, expired or foreign challenge: let check() name the precise reason.
        await otp.check(s, body.challenge_id, body.code, "register", now=now)
        raise ApiError(
            400, "OTP_EXPIRED", "کد تأیید منقضی شده است", "کد جدید درخواست کنید.", "/code"
        )
    # Validation that must not burn the one-time code comes before check().
    _validate_complete(body, kind)
    if len(body.password) > MAX_PASSWORD_LENGTH:
        raise ApiError(
            422,
            "PASSWORD_TOO_LONG",
            "رمز عبور بیش از حد طولانی است",
            f"رمز عبور نباید بیش از {MAX_PASSWORD_LENGTH} نویسه باشد.",
            "/password",
        )
    min_length = int(await SettingsStore(s).get("auth.password_min_length"))
    problems = password_problems(body.password, min_length)
    if problems:
        raise ApiError(422, "PASSWORD_WEAK", "رمز عبور ضعیف است", ",".join(problems), "/password")
    row = await otp.check(s, body.challenge_id, body.code, "register", now=now)
    user = User(
        kind="company" if kind == "company" else "person",
        username=body.username,
        mobile=row.mobile,
        email=body.email,
        password_hash=hash_password(body.password),
        status="active",
        identity_state="none",
        first_name=body.first_name,
        last_name=body.last_name if kind == "individual" else None,
        company_name=body.company_name if kind == "company" else None,
    )
    try:
        async with s.begin_nested():
            s.add(user)
            await s.flush()
    except IntegrityError as exc:
        cause = getattr(exc.orig, "__cause__", None)
        constraint = str(getattr(cause, "constraint_name", "") or "")
        if constraint == "uq_users_mobile":
            raise ApiError(
                409,
                "MOBILE_TAKEN",
                "این شماره قبلاً ثبت شده است",
                "با این شماره وارد شوید.",
                "/mobile",
            ) from None
        if constraint == "uq_users_username":
            raise ApiError(
                409,
                "USERNAME_TAKEN",
                "این نام کاربری قبلاً گرفته شده است",
                "نام کاربری دیگری انتخاب کنید.",
                "/username",
            ) from None
        raise
    s.add(UserRole(user_id=user.id, role_id=await _customer_role_id(s)))
    await audit.record(
        s,
        actor_id=user.id,
        actor_ip=ip or None,
        action="user.register",
        target_type="user",
        target_id=str(user.id),
        after={"kind": user.kind, "username": user.username},
    )
    lifetime = await sessions.absolute_lifetime(s)
    token, csrf = await sessions.create(
        s, user, ip, request.headers.get("user-agent"), now=now, absolute_seconds=lifetime
    )
    sessions.set_cookies(response, settings, token, csrf, max_age=lifetime)
    return CompleteResult(user_id=user.id)


# --- login ------------------------------------------------------------------------------

Password = Annotated[str, StringConstraints(min_length=1, max_length=MAX_PASSWORD_LENGTH)]
MfaToken = Annotated[str, StringConstraints(min_length=1, max_length=2048)]
Code = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16)]


class LoginBody(BaseModel):
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=254)]
    password: Password


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    kind: str
    first_name: str | None
    last_name: str | None
    company_name: str | None
    mfa_method: str


class LoginOk(BaseModel):
    status: Literal["ok"] = "ok"
    user: UserOut


class MfaRequired(BaseModel):
    status: Literal["mfa_required"] = "mfa_required"
    method: Literal["totp", "sms"]
    mfa_token: str


class MfaSendBody(BaseModel):
    mfa_token: MfaToken


class MfaSendResult(BaseModel):
    resend_after: int


class MfaConfirmBody(BaseModel):
    mfa_token: MfaToken
    code: Code


def _box(settings: PanelSettings) -> SecretBox:
    return SecretBox(settings.secret_key.get_secret_value().encode())


async def _find_user(s: AsyncSession, tried: str) -> User | None:
    """By username first, then by mobile in any accepted format. Locks the row."""
    user = (
        await s.execute(select(User).where(User.username == tried).with_for_update())
    ).scalar_one_or_none()
    if user is not None:
        return user
    try:
        mobile = normalize_mobile(tried)
    except InvalidMobile:
        return None
    return (
        await s.execute(select(User).where(User.mobile == mobile).with_for_update())
    ).scalar_one_or_none()


async def _fail(
    s: AsyncSession,
    error: ApiError,
    *,
    user_id: uuid.UUID | None,
    tried: str | None,
    ip: str,
    ua: str | None,
    outcome: str,
    at: datetime,
) -> ApiError:
    """Record the attempt and commit it (the request rolls back on error), then return
    ``error`` for the caller to raise."""
    await login.record_event(s, user_id=user_id, tried=tried, ip=ip, ua=ua, outcome=outcome, at=at)
    await s.commit()
    return error


async def _limit(s: AsyncSession, redis: Redis, key: str, now: datetime) -> int:
    """0 when allowed, else the Retry-After seconds."""
    limit = int(await SettingsStore(s).get("auth.login_rate_per_ip_per_min"))
    result = await RateLimiter(redis, lambda: now.timestamp()).hit(key, limit, 60)
    return 0 if result.allowed else result.retry_after


async def _complete_login(
    s: AsyncSession,
    user: User,
    response: Response,
    settings: PanelSettings,
    notifier: SystemNotifier,
    *,
    ip: str,
    ua: str | None,
    tried: str | None,
    now: datetime,
    factor: str,
) -> LoginOk:
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    await login.record_event(
        s, user_id=user.id, tried=tried, ip=ip, ua=ua, outcome="success", at=now
    )
    await audit.record(
        s,
        actor_id=user.id,
        actor_ip=ip or None,
        action="user.login",
        target_type="user",
        target_id=str(user.id),
        after={"factor": factor},
    )
    if user.login_notice:
        await notifier.send_sms(
            s, user.mobile, "login_notice", {"time": format_tehran(now), "ip": ip or "-"}
        )
        log.info(
            "login notice queued",
            extra={"user_id": str(user.id), "mobile": mask_mobile(user.mobile)},
        )
    lifetime = await sessions.absolute_lifetime(s)
    token, csrf = await sessions.create(s, user, ip, ua, now=now, absolute_seconds=lifetime)
    sessions.set_cookies(response, settings, token, csrf, max_age=lifetime)
    return LoginOk(
        user=UserOut(
            id=user.id,
            username=user.username,
            kind=user.kind,
            first_name=user.first_name,
            last_name=user.last_name,
            company_name=user.company_name,
            mfa_method=user.mfa_method,
        )
    )


@router.post("/login")
async def login_route(
    body: LoginBody,
    request: Request,
    response: Response,
    s: SessionDep,
    clock: Clock,
    settings: Settings,
    notifier: Notifier,
    redis: Annotated[Redis, Depends(get_redis)],
) -> LoginOk | MfaRequired:
    now = clock()
    ip = client_ip(request)
    ua = request.headers.get("user-agent")
    tried = body.username[:128]
    user = await _find_user(s, body.username)
    uid = user.id if user is not None else None
    ctx: dict[str, Any] = {"user_id": uid, "tried": tried, "ip": ip, "ua": ua, "at": now}
    retry = await _limit(s, redis, f"auth.login:{ip}", now)
    if retry:
        raise await _fail(s, login.rate_limited(retry), outcome="rate_limited", **ctx)
    if user is None:
        verify_password(login.dummy_hash(), body.password)  # equalise timing
        raise await _fail(s, login.invalid_credentials(), outcome="unknown_user", **ctx)
    if (until := login.locked_until(user, now)) is not None:
        error = login.account_locked(until, now)
        raise await _fail(s, error, outcome="locked_out", **ctx)
    if not verify_password(user.password_hash, body.password):
        locked = await login.register_failure(s, user, now) == "locked"
        outcome = "locked" if locked else "bad_password"
        raise await _fail(s, login.invalid_credentials(), outcome=outcome, **ctx)
    problem = login.access_problem(user, ip, now)
    if problem is not None:
        raise await _fail(s, login.access_error(problem), outcome=problem, **ctx)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    if user.mfa_method in ("totp", "sms"):
        await login.record_event(s, outcome="mfa_required", **ctx)
        method: Literal["totp", "sms"] = "totp" if user.mfa_method == "totp" else "sms"
        token = login.seal_mfa_token(_box(settings), user.id, method, now)
        return MfaRequired(method=method, mfa_token=token)
    return await _complete_login(
        s, user, response, settings, notifier, ip=ip, ua=ua, tried=tried, now=now, factor="password"
    )


async def _mfa_user(s: AsyncSession, user_id: uuid.UUID, method: str) -> User:
    user = (
        await s.execute(select(User).where(User.id == user_id).with_for_update())
    ).scalar_one_or_none()
    if user is None or user.mfa_method != method:
        raise login.mfa_token_invalid()
    return user


@router.post("/mfa/sms/send", status_code=202)
async def mfa_sms_send(
    body: MfaSendBody,
    request: Request,
    s: SessionDep,
    clock: Clock,
    settings: Settings,
    notifier: Notifier,
    redis: Annotated[Redis, Depends(get_redis)],
) -> MfaSendResult:
    now = clock()
    ip = client_ip(request)
    user_id, method, _ = login.open_mfa_token(_box(settings), body.mfa_token, now)
    if method != "sms":
        raise ApiError(
            409,
            "MFA_METHOD_MISMATCH",
            "روش تأیید دومرحله‌ای پیامک نیست",
            "کد را از برنامهٔ احراز هویت وارد کنید.",
        )
    limit = int(await SettingsStore(s).get("otp.start_rate_per_ip_per_hour"))
    limited = await RateLimiter(redis, lambda: now.timestamp()).hit(f"otp.start:{ip}", limit, 3600)
    if not limited.allowed:
        raise login.rate_limited(limited.retry_after)
    user = await _mfa_user(s, user_id, "sms")
    if (until := login.locked_until(user, now)) is not None:
        raise login.account_locked(until, now)
    resend = await _ensure_resend_window(
        s, now, None, OtpChallenge.purpose == "login", OtpChallenge.user_id == user.id
    )
    _, code = await otp.issue(s, "login", user.mobile, user.id, ip, now=now)
    await notifier.send_sms(s, user.mobile, "otp", {"code": code})
    return MfaSendResult(resend_after=resend)


def _otp_invalid() -> ApiError:
    return ApiError(400, "OTP_INVALID", "کد تأیید نامعتبر است", "کد واردشده درست نیست.", "/code")


@router.post("/mfa/confirm")
async def mfa_confirm(
    body: MfaConfirmBody,
    request: Request,
    response: Response,
    s: SessionDep,
    clock: Clock,
    settings: Settings,
    notifier: Notifier,
    redis: Annotated[Redis, Depends(get_redis)],
) -> LoginOk:
    now = clock()
    ip = client_ip(request)
    ua = request.headers.get("user-agent")
    box = _box(settings)
    user_id, method, issued_at = login.open_mfa_token(box, body.mfa_token, now)
    ctx: dict[str, Any] = {"user_id": user_id, "tried": None, "ip": ip, "ua": ua, "at": now}
    retry = await _limit(s, redis, f"auth.mfa:{ip}", now)
    if retry:
        raise await _fail(s, login.rate_limited(retry), outcome="rate_limited", **ctx)
    user = await _mfa_user(s, user_id, method)
    if (until := login.locked_until(user, now)) is not None:
        raise await _fail(s, login.account_locked(until, now), outcome="locked_out", **ctx)
    problem = login.access_problem(user, ip, now)
    if problem is not None:
        raise await _fail(s, login.access_error(problem), outcome=problem, **ctx)
    if method == "sms":
        challenge_id = (
            await s.execute(
                select(OtpChallenge.id)
                .where(
                    OtpChallenge.purpose == "login",
                    OtpChallenge.user_id == user.id,
                    OtpChallenge.consumed_at.is_(None),
                    OtpChallenge.created_at >= issued_at,
                )
                .order_by(OtpChallenge.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if challenge_id is None:
            raise await _fail(s, _otp_invalid(), outcome="mfa_failed", **ctx)
        try:
            # check() commits a wrong attempt itself; nothing else is pending at this point.
            await otp.check(s, challenge_id, body.code, "login", now=now)
        except ApiError as exc:
            outcome = "mfa_failed"
            if exc.code == "OTP_INVALID" and await login.register_failure(s, user, now) == "locked":
                outcome = "locked"
            raise await _fail(s, exc, outcome=outcome, **ctx) from None
    else:
        try:
            secret = box.open(user.totp_secret_sealed or "")
        except SecretBoxError:
            secret = None
        step = totp_matching_step(secret, body.code, at=now) if secret else None
        if step is None or (user.totp_last_step is not None and step <= user.totp_last_step):
            locked = await login.register_failure(s, user, now) == "locked"
            outcome = "locked" if locked else "mfa_failed"
            raise await _fail(s, _otp_invalid(), outcome=outcome, **ctx)
        user.totp_last_step = step
    return await _complete_login(
        s, user, response, settings, notifier, ip=ip, ua=ua, tried=None, now=now, factor=method
    )


@router.post("/logout", status_code=204)
async def logout(
    row: CurrentSession,
    request: Request,
    response: Response,
    s: SessionDep,
    clock: Clock,
    settings: Settings,
) -> None:
    row.revoked_at = clock()
    await audit.record(
        s,
        actor_id=row.user_id,
        actor_ip=client_ip(request) or None,
        action="session.logout",
        target_type="session",
        target_id=str(row.id),
    )
    sessions.clear_cookies(response, settings)
