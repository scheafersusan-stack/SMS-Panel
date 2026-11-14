import itertools
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pyotp
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from payamakyar.api.deps import get_clock
from payamakyar.core.crypto import SecretBox
from payamakyar.core.passwords import hash_password, verify_password
from payamakyar.db.models import AuditEvent, Session, SystemMessage, User
from payamakyar.db.testing import flush_test_redis

pytestmark = pytest.mark.integration

LOGIN = "/panel/web/v1/auth/login"
MFA_CONFIRM = "/panel/web/v1/auth/mfa/confirm"
SESSIONS = "/panel/web/v1/account/sessions"
PASSWORD_URL = "/panel/web/v1/account/password"
TOTP_SETUP = "/panel/web/v1/account/mfa/totp/setup"
TOTP_ENABLE = "/panel/web/v1/account/mfa/totp/enable"
SMS_ENABLE = "/panel/web/v1/account/mfa/sms/enable"
MFA_DISABLE = "/panel/web/v1/account/mfa/disable"
SECURITY = "/panel/web/v1/account/security"
PASSWORD = "Str0ng!Passw0rd"
NEW_PASSWORD = "N3w!Passw0rdX"
# Saturday 2026-11-14 10:00 in Asia/Tehran (UTC+03:30).
SATURDAY_10_TEHRAN = datetime(2026, 11, 14, 6, 30, tzinfo=UTC)
_seq = itertools.count(1)
_HASH = hash_password(PASSWORD)


class Clock:
    def __init__(self) -> None:
        self.now = SATURDAY_10_TEHRAN

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture(autouse=True)
async def _reset_redis(app: FastAPI) -> None:
    await flush_test_redis(app.state.redis)


@pytest.fixture
def clock(app: FastAPI) -> Clock:
    c = Clock()
    app.dependency_overrides[get_clock] = lambda: c
    return c


def _client(app: FastAPI, host: str = "127.0.0.1") -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, client=(host, 40000))
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def _user(app: FastAPI, **over: Any) -> User:
    n = next(_seq)
    fields: dict[str, Any] = {
        "username": f"acct_{n}_{uuid.uuid4().hex[:6]}",
        "mobile": f"98938{n:03d}{uuid.uuid4().int % 10**4:04d}",
        "password_hash": _HASH,
        "first_name": "سارا",
        "last_name": "احمدی",
    }
    fields.update(over)
    async with app.state.session_factory() as s:
        user = User(**fields)
        s.add(user)
        await s.commit()
        await s.refresh(user)
    return user


async def _get_user(app: FastAPI, user_id: uuid.UUID) -> User:
    async with app.state.session_factory() as s:
        user: User = (await s.execute(select(User).where(User.id == user_id))).scalar_one()
        return user


async def _actions(app: FastAPI, user_id: uuid.UUID) -> list[str]:
    async with app.state.session_factory() as s:
        rows = await s.execute(
            select(AuditEvent.action)
            .where(AuditEvent.target_id == str(user_id))
            .order_by(AuditEvent.id)
        )
        return list(rows.scalars().all())


async def _audit_payloads(app: FastAPI, user_id: uuid.UUID) -> str:
    async with app.state.session_factory() as s:
        rows = await s.execute(
            select(AuditEvent.before, AuditEvent.after).where(AuditEvent.target_id == str(user_id))
        )
        return repr(rows.all())


async def _templates(app: FastAPI, mobile: str) -> list[str]:
    async with app.state.session_factory() as s:
        rows = await s.execute(
            select(SystemMessage.template_key)
            .where(SystemMessage.to_mobile == mobile)
            .order_by(SystemMessage.created_at)
        )
        return list(rows.scalars().all())


def _csrf(client: httpx.AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["pk_csrf"]}


def _err(r: httpx.Response) -> str:
    code: str = r.json()["error"]["code"]
    return code


@asynccontextmanager
async def _signed_in(
    app: FastAPI, user: User, host: str = "127.0.0.1"
) -> AsyncIterator[httpx.AsyncClient]:
    async with _client(app, host) as c:
        r = await c.post(LOGIN, json={"username": user.username, "password": PASSWORD})
        assert r.status_code == 200, r.text
        yield c


@pytest.fixture
async def signed(app: FastAPI, clock: Clock) -> AsyncIterator[tuple[User, httpx.AsyncClient]]:
    user = await _user(app)
    async with _signed_in(app, user) as c:
        yield user, c


# --- password change --------------------------------------------------------------------


async def test_change_password_revokes_other_sessions(
    app: FastAPI, clock: Clock, signed: tuple[User, httpx.AsyncClient]
) -> None:
    user, c = signed
    async with _signed_in(app, user) as other:
        r = await c.post(
            PASSWORD_URL,
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
            headers=_csrf(c),
        )
        assert r.status_code == 204, r.text
        assert (await c.get(SESSIONS)).status_code == 200
        assert (await other.get(SESSIONS)).status_code == 401
    fresh = await _get_user(app, user.id)
    assert verify_password(fresh.password_hash, NEW_PASSWORD)
    assert (await _templates(app, user.mobile))[-1] == "password_changed"
    assert "user.password_change" in await _actions(app, user.id)
    assert PASSWORD not in await _audit_payloads(app, user.id)
    assert NEW_PASSWORD not in await _audit_payloads(app, user.id)


async def test_change_password_needs_csrf(
    clock: Clock, signed: tuple[User, httpx.AsyncClient]
) -> None:
    _, c = signed
    r = await c.post(
        PASSWORD_URL, json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    )
    assert r.status_code == 403


async def test_change_password_wrong_current_counts_toward_lockout(
    app: FastAPI, clock: Clock, signed: tuple[User, httpx.AsyncClient]
) -> None:
    user, c = signed
    for _ in range(4):
        r = await c.post(
            PASSWORD_URL,
            json={"current_password": "Wrong!Pass1", "new_password": NEW_PASSWORD},
            headers=_csrf(c),
        )
        assert r.status_code == 400
        assert _err(r) == "CURRENT_PASSWORD_INVALID"
    assert (await _get_user(app, user.id)).failed_logins == 4
    r = await c.post(
        PASSWORD_URL,
        json={"current_password": "Wrong!Pass1", "new_password": NEW_PASSWORD},
        headers=_csrf(c),
    )
    assert r.status_code == 400
    fresh = await _get_user(app, user.id)
    assert fresh.locked_until is not None
    # Locked: even the right password is refused until the lock ends.
    r = await c.post(
        PASSWORD_URL,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=_csrf(c),
    )
    assert r.status_code == 423
    assert _err(r) == "ACCOUNT_LOCKED"


async def test_change_password_policy(clock: Clock, signed: tuple[User, httpx.AsyncClient]) -> None:
    _, c = signed
    r = await c.post(
        PASSWORD_URL, json={"current_password": PASSWORD, "new_password": "short"}, headers=_csrf(c)
    )
    assert r.status_code == 422
    assert _err(r) == "PASSWORD_WEAK"
    r = await c.post(
        PASSWORD_URL,
        json={"current_password": PASSWORD, "new_password": "Aa1!" + "x" * 130},
        headers=_csrf(c),
    )
    assert r.status_code == 422
    assert _err(r) == "PASSWORD_TOO_LONG"


# --- mfa --------------------------------------------------------------------------------


async def test_totp_enable_needs_valid_code(
    app: FastAPI, clock: Clock, signed: tuple[User, httpx.AsyncClient]
) -> None:
    user, c = signed
    pw = {"password": PASSWORD}
    r = await c.post(TOTP_ENABLE, json={"code": "123456", **pw}, headers=_csrf(c))
    assert r.status_code == 409
    assert _err(r) == "TOTP_SETUP_REQUIRED"
    r = await c.post(TOTP_SETUP, headers=_csrf(c))
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    assert r.json()["otpauth_uri"].startswith("otpauth://totp/")
    # Pending only: nothing active yet.
    pending = await _get_user(app, user.id)
    assert pending.mfa_method == "none"
    assert pending.totp_secret_sealed is None
    totp = pyotp.TOTP(secret)
    wrong = "000000" if totp.at(clock.now) != "000000" else "111111"
    r = await c.post(TOTP_ENABLE, json={"code": wrong, **pw}, headers=_csrf(c))
    assert r.status_code == 400
    assert _err(r) == "OTP_INVALID"
    assert (await _get_user(app, user.id)).mfa_method == "none"
    # The password is always required, and a wrong one counts toward the lockout.
    r = await c.post(TOTP_ENABLE, json={"code": totp.at(clock.now)}, headers=_csrf(c))
    assert r.status_code == 422
    r = await c.post(
        TOTP_ENABLE,
        json={"code": totp.at(clock.now), "password": "Wrong!Pass1"},
        headers=_csrf(c),
    )
    assert r.status_code == 400
    assert _err(r) == "CURRENT_PASSWORD_INVALID"
    assert (await _get_user(app, user.id)).failed_logins == 1
    assert (await _get_user(app, user.id)).mfa_method == "none"
    assert "mfa_changed" not in await _templates(app, user.mobile)
    r = await c.post(TOTP_ENABLE, json={"code": totp.at(clock.now), **pw}, headers=_csrf(c))
    assert r.status_code == 204, r.text
    assert (await _templates(app, user.mobile))[-1] == "mfa_changed"
    fresh = await _get_user(app, user.id)
    assert fresh.mfa_method == "totp"
    assert fresh.totp_last_step == int(clock.now.timestamp()) // 30
    box = SecretBox(app.state.settings.secret_key.get_secret_value().encode())
    assert box.open(fresh.totp_secret_sealed or "") == secret
    assert "user.mfa_enable" in await _actions(app, user.id)
    assert secret not in await _audit_payloads(app, user.id)
    # Login now needs the second factor and the enable code cannot be replayed.
    async with _client(app) as fresh_client:
        r = await fresh_client.post(LOGIN, json={"username": user.username, "password": PASSWORD})
        assert r.json()["status"] == "mfa_required"
        token = r.json()["mfa_token"]
        r = await fresh_client.post(
            MFA_CONFIRM, json={"mfa_token": token, "code": totp.at(clock.now)}
        )
        assert r.status_code == 400
        clock.advance(30)
        r = await fresh_client.post(
            MFA_CONFIRM, json={"mfa_token": token, "code": totp.at(clock.now)}
        )
        assert r.status_code == 200, r.text


async def test_sms_enable_and_disable_needs_password(
    app: FastAPI, clock: Clock, signed: tuple[User, httpx.AsyncClient]
) -> None:
    user, c = signed
    r = await c.post(SMS_ENABLE, headers=_csrf(c))
    assert r.status_code == 422
    r = await c.post(SMS_ENABLE, json={"password": "Wrong!Pass1"}, headers=_csrf(c))
    assert r.status_code == 400
    assert _err(r) == "CURRENT_PASSWORD_INVALID"
    assert (await _get_user(app, user.id)).mfa_method == "none"
    assert (await _get_user(app, user.id)).failed_logins == 1
    r = await c.post(SMS_ENABLE, json={"password": PASSWORD}, headers=_csrf(c))
    assert r.status_code == 204, r.text
    assert (await _get_user(app, user.id)).mfa_method == "sms"
    assert (await _templates(app, user.mobile)).count("mfa_changed") == 1
    r = await c.post(MFA_DISABLE, json={"password": "Wrong!Pass1"}, headers=_csrf(c))
    assert r.status_code == 400
    assert _err(r) == "CURRENT_PASSWORD_INVALID"
    assert (await _get_user(app, user.id)).mfa_method == "sms"
    assert (await _get_user(app, user.id)).failed_logins == 1
    r = await c.post(MFA_DISABLE, json={"password": PASSWORD}, headers=_csrf(c))
    assert r.status_code == 204, r.text
    assert (await _templates(app, user.mobile)).count("mfa_changed") == 2
    fresh = await _get_user(app, user.id)
    assert fresh.mfa_method == "none"
    assert fresh.totp_secret_sealed is None
    actions = await _actions(app, user.id)
    assert "user.mfa_enable" in actions
    assert "user.mfa_disable" in actions
    assert PASSWORD not in await _audit_payloads(app, user.id)


async def test_mfa_changes_refused_while_locked(
    app: FastAPI, clock: Clock, signed: tuple[User, httpx.AsyncClient]
) -> None:
    user, c = signed
    r = await c.post(SMS_ENABLE, json={"password": PASSWORD}, headers=_csrf(c))
    assert r.status_code == 204
    async with app.state.session_factory() as s:
        row = await s.get(User, user.id)
        assert row is not None
        row.locked_until = clock.now + timedelta(minutes=10)
        await s.commit()
    r = await c.post(MFA_DISABLE, json={"password": PASSWORD}, headers=_csrf(c))
    assert r.status_code == 423
    assert _err(r) == "ACCOUNT_LOCKED"
    r = await c.post(SMS_ENABLE, json={"password": PASSWORD}, headers=_csrf(c))
    assert r.status_code == 423
    assert (await _get_user(app, user.id)).mfa_method == "sms"


# --- security settings ------------------------------------------------------------------


async def test_security_update_and_read(
    app: FastAPI, clock: Clock, signed: tuple[User, httpx.AsyncClient]
) -> None:
    user, c = signed
    body = {
        "password": PASSWORD,
        "login_notice": True,
        "allowed_ips": ["127.0.0.0/8", "10.1.2.3", "2001:db8::/32"],
        "login_hours": [{"days": [0, 1], "from": "08:00", "to": "24:00"}],
    }
    r = await c.put(SECURITY, json=body, headers=_csrf(c))
    assert r.status_code == 200, r.text
    assert r.json()["allowed_ips"] == ["127.0.0.0/8", "10.1.2.3/32", "2001:db8::/32"]
    fresh = await _get_user(app, user.id)
    assert fresh.login_notice is True
    assert [str(x) for x in fresh.allowed_ips or []] == [
        "127.0.0.0/8",
        "10.1.2.3/32",
        "2001:db8::/32",
    ]
    assert fresh.login_hours == [{"days": [0, 1], "from": "08:00", "to": "24:00"}]
    got = await c.get(SECURITY)
    assert got.status_code == 200
    assert got.json() == r.json()
    assert "user.security_update" in await _actions(app, user.id)
    assert (await _templates(app, user.mobile))[-1] == "security_changed"
    assert PASSWORD not in await _audit_payloads(app, user.id)
    # Empty lists clear the restriction.
    r = await c.put(
        SECURITY,
        json={"password": PASSWORD, "login_notice": False, "allowed_ips": [], "login_hours": []},
        headers=_csrf(c),
    )
    assert r.status_code == 200
    fresh = await _get_user(app, user.id)
    assert not fresh.allowed_ips
    assert not fresh.login_hours


async def test_security_rejects_bad_cidr_with_pointer(
    clock: Clock, signed: tuple[User, httpx.AsyncClient]
) -> None:
    _, c = signed
    r = await c.put(
        SECURITY,
        json={
            "password": PASSWORD,
            "login_notice": False,
            "allowed_ips": ["127.0.0.1", "10.0.0.0/33"],
            "login_hours": [],
        },
        headers=_csrf(c),
    )
    assert r.status_code == 422
    assert _err(r) == "VALIDATION_FAILED"
    assert r.json()["error"]["source"]["pointer"] == "/allowed_ips/1"


@pytest.mark.parametrize(
    ("window", "pointer"),
    [
        ({"days": [7], "from": "08:00", "to": "18:00"}, "/login_hours/0/days"),
        ({"days": [], "from": "08:00", "to": "18:00"}, "/login_hours/0/days"),
        ({"days": [0], "from": "8:00", "to": "18:00"}, "/login_hours/0/from"),
        ({"days": [0], "from": "08:00", "to": "25:00"}, "/login_hours/0/to"),
        ({"days": [0], "from": "18:00", "to": "08:00"}, "/login_hours/0/to"),
    ],
)
async def test_security_rejects_bad_window(
    clock: Clock, signed: tuple[User, httpx.AsyncClient], window: dict[str, Any], pointer: str
) -> None:
    _, c = signed
    r = await c.put(
        SECURITY,
        json={
            "password": PASSWORD,
            "login_notice": False,
            "allowed_ips": [],
            "login_hours": [window],
        },
        headers=_csrf(c),
    )
    assert r.status_code == 422, r.text
    assert _err(r) == "VALIDATION_FAILED"
    assert r.json()["error"]["source"]["pointer"] == pointer


async def test_security_refuses_to_lock_you_out(
    app: FastAPI, clock: Clock, signed: tuple[User, httpx.AsyncClient]
) -> None:
    user, c = signed
    r = await c.put(
        SECURITY,
        json={
            "password": PASSWORD,
            "login_notice": False,
            "allowed_ips": ["10.9.0.0/16"],
            "login_hours": [],
        },
        headers=_csrf(c),
    )
    assert r.status_code == 422
    assert _err(r) == "WOULD_LOCK_YOU_OUT"
    assert r.json()["error"]["source"]["pointer"] == "/allowed_ips"
    # Saturday 10:00 Tehran is outside a Sunday-only window.
    r = await c.put(
        SECURITY,
        json={
            "password": PASSWORD,
            "login_notice": False,
            "allowed_ips": [],
            "login_hours": [{"days": [1], "from": "00:00", "to": "24:00"}],
        },
        headers=_csrf(c),
    )
    assert r.status_code == 422
    assert _err(r) == "WOULD_LOCK_YOU_OUT"
    assert r.json()["error"]["source"]["pointer"] == "/login_hours"
    fresh = await _get_user(app, user.id)
    assert not fresh.allowed_ips
    assert not fresh.login_hours
    async with app.state.session_factory() as s:
        n = (
            await s.execute(
                select(func.count()).select_from(Session).where(Session.user_id == user.id)
            )
        ).scalar_one()
    assert n == 1


async def test_security_requires_the_password(
    app: FastAPI, clock: Clock, signed: tuple[User, httpx.AsyncClient]
) -> None:
    user, c = signed
    body: dict[str, Any] = {"login_notice": True, "allowed_ips": [], "login_hours": []}
    r = await c.put(SECURITY, json=body, headers=_csrf(c))
    assert r.status_code == 422
    assert r.json()["error"]["source"] == {"pointer": "/password"}
    r = await c.put(SECURITY, json={**body, "password": "wrong"}, headers=_csrf(c))
    assert r.status_code == 400
    assert _err(r) == "CURRENT_PASSWORD_INVALID"
    assert r.json()["error"]["source"] == {"pointer": "/password"}
    fresh = await _get_user(app, user.id)
    assert fresh.failed_logins == 1  # counts toward the lockout
    assert fresh.login_notice is False
    assert "security_changed" not in await _templates(app, user.mobile)
    async with app.state.session_factory() as s:
        row = await s.get(User, user.id)
        assert row is not None
        row.locked_until = clock.now + timedelta(minutes=10)
        await s.commit()
    r = await c.put(SECURITY, json={**body, "password": PASSWORD}, headers=_csrf(c))
    assert r.status_code == 423
    assert _err(r) == "ACCOUNT_LOCKED"
    assert (await _get_user(app, user.id)).login_notice is False


async def test_security_no_change_sends_no_notice(
    app: FastAPI, clock: Clock, signed: tuple[User, httpx.AsyncClient]
) -> None:
    user, c = signed
    body = {"password": PASSWORD, "login_notice": False, "allowed_ips": [], "login_hours": []}
    r = await c.put(SECURITY, json=body, headers=_csrf(c))
    assert r.status_code == 200
    assert "security_changed" not in await _templates(app, user.mobile)


async def test_security_requires_auth(client: httpx.AsyncClient, clock: Clock) -> None:
    r = await client.get(SECURITY)
    assert r.status_code == 401


async def test_ipv4_mapped_ipv6_matches_ipv4_cidr(app: FastAPI, clock: Clock) -> None:
    mapped = "::ffff:10.1.2.3"
    user = await _user(app, allowed_ips=["10.0.0.0/8"])
    async with _signed_in(app, user, host=mapped) as c:
        r = await c.put(
            SECURITY,
            json={
                "password": PASSWORD,
                "login_notice": False,
                "allowed_ips": ["10.0.0.0/8"],
                "login_hours": [],
            },
            headers=_csrf(c),
        )
        assert r.status_code == 200, r.text
        r = await c.put(
            SECURITY,
            json={
                "password": PASSWORD,
                "login_notice": False,
                "allowed_ips": ["192.168.0.0/16"],
                "login_hours": [],
            },
            headers=_csrf(c),
        )
        assert r.status_code == 422
        assert _err(r) == "WOULD_LOCK_YOU_OUT"
