"""One-time codes sent by SMS: issue a challenge, then check a submitted code against it.

Only ``sha256(code + challenge_id)`` is stored. Failed attempts are committed immediately
(the request dependency rolls back on error, which would otherwise erase the counter).
"""

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from payamakyar.api.errors import ApiError
from payamakyar.core.ids import new_id
from payamakyar.db.models import OtpChallenge
from payamakyar.db.settings_store import SettingsStore

CODE_DIGITS = 6


def _digest(code: str, challenge_id: uuid.UUID) -> str:
    return hashlib.sha256((code + str(challenge_id)).encode()).hexdigest()


async def issue(
    s: AsyncSession,
    purpose: str,
    mobile: str,
    user_id: uuid.UUID | None = None,
    ip: str | None = None,
    *,
    now: datetime,
) -> tuple[uuid.UUID, str]:
    """Create a challenge and return ``(challenge_id, code)``. Does not commit."""
    store = SettingsStore(s)
    ttl = int(await store.get("otp.ttl_seconds"))
    max_attempts = int(await store.get("otp.max_attempts"))
    challenge_id = new_id()
    code = f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"
    s.add(
        OtpChallenge(
            id=challenge_id,
            purpose=purpose,
            mobile=mobile,
            user_id=user_id,
            code_hash=_digest(code, challenge_id),
            attempts=0,
            max_attempts=max_attempts,
            expires_at=now + timedelta(seconds=ttl),
            created_ip=ip or None,
            created_at=now,
        )
    )
    await s.flush()
    return challenge_id, code


def _invalid() -> ApiError:
    return ApiError(400, "OTP_INVALID", "کد تأیید نامعتبر است", "کد واردشده درست نیست.", "/code")


async def check(
    s: AsyncSession,
    challenge_id: uuid.UUID,
    code: str,
    purpose: str,
    *,
    now: datetime,
) -> OtpChallenge:
    """Verify ``code`` and mark the challenge consumed (the caller commits that).

    A wrong code increments ``attempts`` and commits that increment before raising.
    """
    row = (
        await s.execute(
            select(OtpChallenge).where(OtpChallenge.id == challenge_id).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None or row.purpose != purpose or row.consumed_at is not None:
        raise _invalid()
    if now >= row.expires_at:
        raise ApiError(
            400, "OTP_EXPIRED", "کد تأیید منقضی شده است", "کد جدید درخواست کنید.", "/code"
        )
    if row.attempts >= row.max_attempts:
        raise ApiError(
            400,
            "OTP_TOO_MANY_ATTEMPTS",
            "تعداد تلاش‌ها بیش از حد مجاز است",
            "کد جدید درخواست کنید.",
            "/code",
        )
    if not hmac.compare_digest(row.code_hash, _digest(code, challenge_id)):
        row.attempts += 1
        await s.commit()
        raise _invalid()
    row.consumed_at = now
    await s.flush()
    return row
