"""Server-side sessions: opaque random token (only its hash is stored) plus a CSRF token.

Idle and absolute lifetimes come from the settings store (``session.idle_seconds``,
``session.absolute_seconds``). A session also dies when its user is deactivated or expires.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from payamakyar.core.settings import PanelSettings
from payamakyar.db.models import Session, User
from payamakyar.db.settings_store import SettingsStore

TOUCH_INTERVAL_SECONDS = 60


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def absolute_lifetime(s: AsyncSession) -> int:
    return int(await SettingsStore(s).get("session.absolute_seconds"))


async def idle_lifetime(s: AsyncSession) -> int:
    return int(await SettingsStore(s).get("session.idle_seconds"))


def user_can_sign_in(user: User, at: datetime) -> bool:
    return user.status == "active" and (user.expires_at is None or at < user.expires_at)


async def create(
    s: AsyncSession,
    user: User,
    ip: str | None,
    ua: str | None,
    impersonator_id: uuid.UUID | None = None,
    *,
    now: datetime | None = None,
    absolute_seconds: int | None = None,
) -> tuple[str, str]:
    """Insert a session row and return ``(token, csrf)``. Does not commit."""
    at = now or datetime.now(UTC)
    lifetime = absolute_seconds if absolute_seconds is not None else await absolute_lifetime(s)
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    s.add(
        Session(
            user_id=user.id,
            token_hash=hash_token(token),
            csrf_hash=hash_token(csrf),
            ip=ip or None,
            user_agent=ua[:512] if ua else None,
            created_at=at,
            last_seen_at=at,
            expires_at=at + timedelta(seconds=lifetime),
            impersonator_id=impersonator_id,
        )
    )
    await s.flush()
    return token, csrf


async def resolve(
    s: AsyncSession,
    token: str,
    *,
    now: datetime | None = None,
    idle_seconds: int | None = None,
) -> Session | None:
    """Return the live session for ``token`` or None; refreshes ``last_seen_at`` at most
    once per ``TOUCH_INTERVAL_SECONDS``. Does not commit."""
    at = now or datetime.now(UTC)
    found = (
        await s.execute(
            select(Session, User)
            .join(User, User.id == Session.user_id)
            .where(Session.token_hash == hash_token(token))
        )
    ).first()
    if found is None:
        return None
    row, user = found
    if row.revoked_at is not None or at >= row.expires_at or not user_can_sign_in(user, at):
        return None
    idle = idle_seconds if idle_seconds is not None else await idle_lifetime(s)
    if at - row.last_seen_at >= timedelta(seconds=idle):
        return None
    if at - row.last_seen_at >= timedelta(seconds=TOUCH_INTERVAL_SECONDS):
        row.last_seen_at = at
        await s.flush()
    return row


def set_cookies(
    response: Response,
    settings: PanelSettings,
    token: str,
    csrf: str,
    *,
    max_age: int,
) -> None:
    """``pk_session`` is HttpOnly; ``pk_csrf`` must stay readable by the page's JavaScript.

    ``max_age`` is the session's absolute lifetime (``absolute_lifetime``, settings store).
    """
    age = max_age
    secure = settings.env not in ("dev", "test")
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=age,
        path="/",
        secure=secure,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf,
        max_age=age,
        path="/",
        secure=secure,
        httponly=False,
        samesite="lax",
    )


def clear_cookies(response: Response, settings: PanelSettings) -> None:
    secure = settings.env not in ("dev", "test")
    for name, httponly in (
        (settings.session_cookie_name, True),
        (settings.csrf_cookie_name, False),
    ):
        response.delete_cookie(name, path="/", secure=secure, httponly=httponly, samesite="lax")
