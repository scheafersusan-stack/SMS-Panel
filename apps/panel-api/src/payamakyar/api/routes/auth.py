"""Authentication routes (registration part; login/logout/reset live alongside)."""

import re
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, StringConstraints
from redis.asyncio import Redis
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from payamakyar.api import otp, sessions
from payamakyar.api.deps import SessionDep, client_ip, get_clock, get_redis, get_settings_dep
from payamakyar.api.errors import ApiError
from payamakyar.api.notifier import OutboxNotifier, SystemNotifier
from payamakyar.core.passwords import hash_password, password_problems
from payamakyar.core.phone import InvalidMobile, normalize_mobile
from payamakyar.core.settings import PanelSettings
from payamakyar.db import audit
from payamakyar.db.models import OtpChallenge, Role, User, UserRole
from payamakyar.db.settings_store import SettingsStore

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
    # Serialise concurrent starts for one number so the resend window cannot be raced.
    await s.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"otp:{mobile}"})
    taken = (await s.execute(select(User.id).where(User.mobile == mobile))).first()
    if taken is not None:
        raise ApiError(
            409, "MOBILE_TAKEN", "این شماره قبلاً ثبت شده است", "با این شماره وارد شوید.", "/mobile"
        )
    resend = int(await SettingsStore(s).get("otp.resend_seconds"))
    last = (
        await s.execute(
            select(func.max(OtpChallenge.created_at)).where(
                OtpChallenge.purpose == "register", OtpChallenge.mobile == mobile
            )
        )
    ).scalar_one()
    if last is not None:
        wait = int((last - now).total_seconds()) + resend
        if (now - last).total_seconds() < resend:
            raise ApiError(
                429,
                "OTP_RESEND_TOO_SOON",
                "ارسال مجدد کد هنوز ممکن نیست",
                f"{max(wait, 1)} ثانیهٔ دیگر دوباره تلاش کنید.",
                "/mobile",
                headers={"Retry-After": str(max(wait, 1))},
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
        if constraint.endswith("mobile_key"):
            raise ApiError(
                409, "MOBILE_TAKEN", "این شماره قبلاً ثبت شده است", "", "/mobile"
            ) from None
        raise ApiError(
            409, "USERNAME_TAKEN", "این نام کاربری قبلاً گرفته شده است", "", "/username"
        ) from None
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
    token, csrf = await sessions.create(
        s,
        user,
        ip,
        request.headers.get("user-agent"),
        now=now,
        absolute_seconds=settings.session_absolute_seconds,
    )
    sessions.set_cookies(response, settings, token, csrf)
    return CompleteResult(user_id=user.id)
