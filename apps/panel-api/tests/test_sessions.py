import hashlib
import zlib
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from fastapi import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from payamakyar.api import sessions
from payamakyar.core.settings import PanelSettings
from payamakyar.db.models import Session, User

pytestmark = pytest.mark.integration

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


async def _user(s: AsyncSession, name: str) -> User:
    mobile = "98912" + f"{zlib.crc32(name.encode()) % 10_000_000:07d}"
    user = User(username=name, mobile=mobile, password_hash="x")
    s.add(user)
    await s.flush()
    return user


async def test_create_stores_only_hashes(db_session: AsyncSession) -> None:
    user = await _user(db_session, "sess_a")
    token, csrf = await sessions.create(db_session, user, "203.0.113.9", "UA/1", now=T0)
    row = (await db_session.execute(select(Session).where(Session.user_id == user.id))).scalar_one()
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert row.csrf_hash == hashlib.sha256(csrf.encode()).hexdigest()
    assert token not in (row.token_hash, row.csrf_hash)
    assert row.expires_at == T0 + timedelta(seconds=43200)
    await db_session.rollback()


async def test_resolve_idle_absolute_revoked_and_touch(db_session: AsyncSession) -> None:
    user = await _user(db_session, "sess_b")
    token, _ = await sessions.create(db_session, user, None, None, now=T0)
    assert await sessions.resolve(db_session, "nope", now=T0) is None
    got = await sessions.resolve(db_session, token, now=T0 + timedelta(seconds=30))
    assert got is not None
    assert got.last_seen_at == T0  # touched at most every 60 s
    got = await sessions.resolve(db_session, token, now=T0 + timedelta(seconds=90))
    assert got is not None
    assert got.last_seen_at == T0 + timedelta(seconds=90)
    # idle expiry (1800 s since last seen)
    assert await sessions.resolve(db_session, token, now=T0 + timedelta(seconds=90 + 1801)) is None
    # keep alive, then hit the absolute limit
    t = T0
    while t < T0 + timedelta(seconds=43200):
        t += timedelta(seconds=1000)
        got = await sessions.resolve(db_session, token, now=t)
        if t >= T0 + timedelta(seconds=43200):
            assert got is None
        else:
            assert got is not None
    token2, _ = await sessions.create(db_session, user, None, None, now=T0)
    row = (
        await db_session.execute(
            select(Session).where(Session.token_hash == hashlib.sha256(token2.encode()).hexdigest())
        )
    ).scalar_one()
    row.revoked_at = T0
    await db_session.flush()
    assert await sessions.resolve(db_session, token2, now=T0) is None
    await db_session.rollback()


@pytest.mark.parametrize(("env", "secure"), [("test", False), ("dev", False), ("prod", True)])
def test_cookie_attributes(env: str, secure: bool) -> None:
    kwargs = {
        "database_url": "postgresql+asyncpg://x/y",
        "redis_url": "redis://x",
        "public_base_url": "https://x",
        "secret_key": Fernet.generate_key().decode(),
    }
    settings = PanelSettings(env=env, **kwargs)  # type: ignore[arg-type]
    response = Response()
    sessions.set_cookies(response, settings, "tok", "csr", max_age=600)
    raw = {h.split("=", 1)[0]: h for h in response.headers.getlist("set-cookie")}
    sess, csrf = raw["pk_session"].lower(), raw["pk_csrf"].lower()
    assert "httponly" in sess
    assert "httponly" not in csrf
    for c in (sess, csrf):
        assert "samesite=lax" in c
        assert "path=/" in c
        assert ("secure" in c) is secure
        assert "max-age=600" in c


async def test_resolve_rejects_inactive_or_expired_user(db_session: AsyncSession) -> None:
    user = await _user(db_session, "sess_c")
    token, _ = await sessions.create(db_session, user, None, None, now=T0)
    assert await sessions.resolve(db_session, token, now=T0) is not None
    user.status = "inactive"
    await db_session.flush()
    assert await sessions.resolve(db_session, token, now=T0) is None
    user.status = "active"
    user.expires_at = T0 + timedelta(seconds=10)
    await db_session.flush()
    assert await sessions.resolve(db_session, token, now=T0) is not None
    assert await sessions.resolve(db_session, token, now=T0 + timedelta(seconds=10)) is None
    await db_session.rollback()


async def test_lifetimes_come_from_settings_store(db_session: AsyncSession) -> None:
    from payamakyar.db.settings_store import DEFAULTS, SettingsStore

    assert DEFAULTS["session.idle_seconds"] == 1800
    assert DEFAULTS["session.absolute_seconds"] == 43200
    store = SettingsStore(db_session)
    await store.set("session.idle_seconds", 120, None)
    await store.set("session.absolute_seconds", 600, None)
    user = await _user(db_session, "sess_d")
    token, _ = await sessions.create(db_session, user, None, None, now=T0)
    row = (await db_session.execute(select(Session).where(Session.user_id == user.id))).scalar_one()
    assert row.expires_at == T0 + timedelta(seconds=600)
    assert await sessions.resolve(db_session, token, now=T0 + timedelta(seconds=119)) is not None
    assert await sessions.resolve(db_session, token, now=T0 + timedelta(seconds=119 + 120)) is None
    await db_session.rollback()
