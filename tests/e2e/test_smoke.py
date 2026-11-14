"""End-to-end smoke: register -> login -> admin bootstrap -> TOTP -> audit, over real HTTP routes.

Runs ``create_app`` against real Postgres and Redis (root ``conftest.py`` fixtures). The only
test-only shortcut is reading the OTP out of ``system_messages`` (no production endpoint).
"""

import re
import time
from collections.abc import AsyncIterator

import httpx
import pyotp
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from payamakyar.api.app import create_app
from payamakyar.api.cli import create_admin
from payamakyar.core.passwords import password_problems
from payamakyar.core.settings import PanelSettings
from payamakyar.db.audit import verify_chain
from payamakyar.db.models import SystemMessage
from payamakyar.db.testing import flush_test_redis

pytestmark = pytest.mark.integration

WEB = "/panel/web/v1"
ADMIN = "/panel/admin/v1"
USER_PASSWORD = "Str0ng!Passw0rd"


@pytest.fixture
async def app(db_url: str, redis_url: str) -> AsyncIterator[FastAPI]:
    settings = PanelSettings(
        env="test", database_url=db_url, redis_url=redis_url, trusted_proxies="10.0.0.0/8"
    )
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        await flush_test_redis(application.state.redis)
        yield application


def _client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 40000))
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


def _csrf(client: httpx.AsyncClient) -> dict[str, str]:
    """The real double-submit flow: echo the ``pk_csrf`` cookie in ``X-CSRF-Token``."""
    token = client.cookies.get("pk_csrf")
    assert token, "no pk_csrf cookie: log in first"
    return {"X-CSRF-Token": token}


async def _otp_for(app: FastAPI, canonical_mobile: str) -> str:
    """Test-only: read the latest OTP SMS body from the outbox."""
    async with app.state.session_factory() as s:
        body = (
            await s.execute(
                select(SystemMessage.body)
                .where(SystemMessage.to_mobile == canonical_mobile)
                .order_by(SystemMessage.created_at.desc())
                .limit(1)
            )
        ).scalar_one()
    match = re.search(r"\d{6}", body.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))
    assert match, "no 6-digit code in the OTP message"
    return match.group(0)


async def test_smoke(app: FastAPI) -> None:
    # 1. register (OTP via the outbox) -> session cookies
    async with _client(app) as c:
        r = await c.post(
            f"{WEB}/auth/register/start", json={"mobile": "09121234567", "kind": "person"}
        )
        assert r.status_code == 202, r.text
        code = await _otp_for(app, "989121234567")
        r = await c.post(
            f"{WEB}/auth/register/complete",
            json={
                "challenge_id": r.json()["challenge_id"],
                "code": code,
                "username": "smoke_user",
                "password": USER_PASSWORD,
                "first_name": "علی",
                "last_name": "رضایی",
            },
        )
        assert r.status_code == 201, r.text
        assert c.cookies.get("pk_session") and c.cookies.get("pk_csrf")

    # 2. fresh login -> /account/me
    async with _client(app) as c:
        r = await c.post(
            f"{WEB}/auth/login", json={"username": "smoke_user", "password": USER_PASSWORD}
        )
        assert r.status_code == 200 and r.json()["status"] == "ok", r.text
        r = await c.get(f"{WEB}/account/me")
        assert r.status_code == 200, r.text
        me = r.json()
        assert me["username"] == "smoke_user"
        assert "admin" not in me["roles"]
        # a customer cannot reach admin routes
        assert (await c.get(f"{ADMIN}/audit")).status_code == 403

    # 3. bootstrap an admin through the CLI function
    password = await create_admin(app.state.session_factory, "smoke_admin", "09127654321")
    assert password_problems(password) == []

    # 4. admin logs in; admin routes are gated on MFA until TOTP is enabled
    async with _client(app) as admin:
        r = await admin.post(
            f"{WEB}/auth/login", json={"username": "smoke_admin", "password": password}
        )
        assert r.status_code == 200 and r.json()["status"] == "ok", r.text
        gated = await admin.get(f"{ADMIN}/audit")
        assert gated.status_code == 403 and gated.json()["error"]["code"] == "MFA_REQUIRED"

        r = await admin.post(f"{WEB}/account/mfa/totp/setup", headers=_csrf(admin))
        assert r.status_code == 200, r.text
        totp = pyotp.TOTP(r.json()["secret"])
        r = await admin.post(
            f"{WEB}/account/mfa/totp/enable",
            json={"code": totp.now(), "password": password},
            headers=_csrf(admin),
        )
        assert r.status_code == 204, r.text
        # This session signed in with the password only: still gated until a fresh MFA login.
        gated = await admin.get(f"{ADMIN}/audit")
        assert gated.status_code == 403 and gated.json()["error"]["code"] == "MFA_REQUIRED"

    # 5. login again: password -> mfa_required -> mfa/confirm with the next TOTP step
    async with _client(app) as admin:
        r = await admin.post(
            f"{WEB}/auth/login", json={"username": "smoke_admin", "password": password}
        )
        assert r.json()["status"] == "mfa_required" and r.json()["method"] == "totp"
        # The enable code is burned (replay protection): use the following 30-second step.
        r = await admin.post(
            f"{WEB}/auth/mfa/confirm",
            json={"mfa_token": r.json()["mfa_token"], "code": totp.at(int(time.time()) + 30)},
        )
        assert r.status_code == 200, r.text

        # 6. the audit viewer shows the registration and the bootstrap
        r = await admin.get(f"{ADMIN}/audit", params={"action": "user.register"})
        assert r.status_code == 200, r.text
        assert any(i["action"] == "user.register" for i in r.json()["items"])
        r = await admin.get(f"{ADMIN}/audit", params={"action": "user.create_admin"})
        assert [i["action"] for i in r.json()["items"]] == ["user.create_admin"]
        assert (await admin.get(f"{ADMIN}/audit/verify")).json()["ok"] is True

    async with app.state.session_factory() as s:
        assert await verify_chain(s) is None
