"""Runtime settings stored in the ``settings`` table, with code-level defaults.

``get`` falls back to ``DEFAULTS`` when no row exists; ``set`` only accepts keys known to
``DEFAULTS`` and records a ``settings.update`` audit event (with before/after) in the
caller's transaction. Neither method commits.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from payamakyar.db import audit
from payamakyar.db.models import Setting

DEFAULTS: dict[str, Any] = {
    "auth.max_failed_tries": 5,
    "auth.lockout_seconds": 900,
    "auth.password_min_length": 8,
    "auth.login_rate_per_ip_per_min": 20,
    "session.idle_seconds": 1800,
    "session.absolute_seconds": 43200,
    "otp.start_rate_per_ip_per_hour": 10,
    "otp.ttl_seconds": 120,
    "otp.max_attempts": 5,
    "otp.resend_seconds": 60,
    "system_sms.otp": "کد تأیید پیامک‌یار: $code\nاین کد را به کسی ندهید.",
    "system_sms.login_notice": "ورود به حساب پیامک‌یار شما در $time از نشانی $ip انجام شد.",
    "system_sms.password_changed": "رمز عبور حساب پیامک‌یار شما تغییر کرد.",
    "system_sms.mfa_changed": (
        "روش ورود دومرحله‌ای حساب پیامک‌یار شما تغییر کرد. اگر شما نبودید با پشتیبانی تماس بگیرید."
    ),
    "system_sms.security_changed": (
        "تنظیمات امنیتی ورود حساب پیامک‌یار شما تغییر کرد. اگر شما نبودید با پشتیبانی تماس بگیرید."
    ),
}

_MISSING: Any = object()

__all__ = ["DEFAULTS", "SettingsStore"]


class SettingsStore:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get(self, key: str, default: Any = _MISSING) -> Any:
        row = (await self._s.execute(select(Setting.value).where(Setting.key == key))).first()
        if row is not None:
            return row[0]
        if key in DEFAULTS:
            return DEFAULTS[key]
        if default is _MISSING:
            raise KeyError(key)
        return default

    async def set(
        self,
        key: str,
        value: Any,
        actor_id: UUID | None,
        reason: str | None = None,
        *,
        actor_ip: str | None = None,
    ) -> None:
        if key not in DEFAULTS:
            raise ValueError(f"unknown setting: {key}")
        expected = type(DEFAULTS[key])
        if type(value) is not expected:
            raise ValueError(f"setting {key} must be {expected.__name__}")
        before = await self.get(key)
        await self._s.execute(
            insert(Setting)
            .values(key=key, value=value, updated_by=actor_id)
            .on_conflict_do_update(
                index_elements=[Setting.key],
                set_={"value": value, "updated_by": actor_id},
            )
        )
        await audit.record(
            self._s,
            actor_id=actor_id,
            actor_ip=actor_ip,
            action="settings.update",
            target_type="setting",
            target_id=key,
            before={"value": before},
            after={"value": value},
            reason=reason,
        )
