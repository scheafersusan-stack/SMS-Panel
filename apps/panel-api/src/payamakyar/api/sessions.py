"""Server-side sessions: opaque random token (only its hash is stored) plus a CSRF token."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from payamakyar.core.settings import PanelSettings
from payamakyar.db.models import Session, User

DEFAULT_IDLE_SECONDS = 1800
DEFAULT_ABSOLUTE_SECONDS = 43200
TOUCH_INTERVAL_SECONDS = 60


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create(
    s: AsyncSession,
    user: User,
    ip: str | None,
    ua: str | None,
    impersonator_id: uuid.UUID | None = None,
    *,
    now: datetime | None = None,
    absolute_seconds: int = DEFAULT_ABSOLUTE_SECONDS,
) -> tuple[str, str]:
    """Insert a session row and return ``(token, csrf)``. Does not commit."""
    at = now or datetime.now(UTC)
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    s.add(
        Session(
            user_id=user.id,
            token_hash=hash_token(token),
            csrf_hash=hash_token(csrf),
            ip=ip or None,
            user_agent=ua,
            created_at=at,
            last_seen_at=at,
            expires_at=at + timedelta(seconds=absolute_seconds),
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
    idle_seconds: int = DEFAULT_IDLE_SECONDS,
) -> Session | None:
    """Return the live session for ``token`` or None; refreshes ``last_seen_at`` at most
    once per ``TOUCH_INTERVAL_SECONDS``. Does not commit."""
    at = now or datetime.now(UTC)
    row = (
        await s.execute(select(Session).where(Session.token_hash == hash_token(token)))
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None or at >= row.expires_at:
        return None
    if at - row.last_seen_at >= timedelta(seconds=idle_seconds):
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
    max_age: int | None = None,
) -> None:
    """``pk_session`` is HttpOnly; ``pk_csrf`` must stay readable by the page's JavaScript."""
    age = settings.session_absolute_seconds if max_age is None else max_age
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
