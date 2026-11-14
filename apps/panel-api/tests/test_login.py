import asyncio
import itertools
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pyotp
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from payamakyar.api import otp
from payamakyar.api.deps import get_clock
from payamakyar.core.crypto import SecretBox
from payamakyar.core.passwords import hash_password, verify_password
from payamakyar.db.models import AuditEvent, LoginEvent, Session, SystemMessage, User
from payamakyar.db.settings_store import SettingsStore
from payamakyar.db.testing import flush_test_redis

pytestmark = pytest.mark.integration

LOGIN = "/panel/web/v1/auth/login"
MFA_SEND = "/panel/web/v1/auth/mfa/sms/send"
MFA_CONFIRM = "/panel/web/v1/auth/mfa/confirm"
LOGOUT = "/panel/web/v1/auth/logout"
SESSIONS = "/panel/web/v1/account/sessions"
PASSWORD = "Str0ng!Passw0rd"
# Friday 2026-11-13 20:00 in Asia/Tehran (UTC+03:30).
FRIDAY_20_TEHRAN = datetime(2026, 11, 13, 16, 30, tzinfo=UTC)
# Saturday 2026-11-14 10:00 in Asia/Tehran.
SATURDAY_10_TEHRAN = datetime(2026, 11, 14, 6, 30, tzinfo=UTC)
_seq = itertools.count(1)
_HASH = hash_password(PASSWORD)


class Clock:
    def __init__(self) -> None:
        self.now = FRIDAY_20_TEHRAN

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


@pytest.fixture
async def other_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with _client(app) as c:
        yield c


async def _user(app: FastAPI, **over: Any) -> User:
    n = next(_seq)
    fields: dict[str, Any] = {
        "username": f"login_{n}",
        "mobile": f"98935{n:07d}",
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


async def _set_setting(app: FastAPI, key: str, value: Any) -> None:
    async with app.state.session_factory() as s:
        await SettingsStore(s).set(key, value, None)
        await s.commit()


async def _events(app: FastAPI, user_id: uuid.UUID) -> list[str]:
    async with app.state.session_factory() as s:
        rows = await s.execute(
            select(LoginEvent.outcome)
            .where(LoginEvent.user_id == user_id)
            .order_by(LoginEvent.at, LoginEvent.id)
        )
        return list(rows.scalars().all())


async def _login(
    client: httpx.AsyncClient, username: str, password: str = PASSWORD
) -> httpx.Response:
    return await client.post(LOGIN, json={"username": username, "password": password})


def _csrf(client: httpx.AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["pk_csrf"]}


async def _session_mfa_at(app: FastAPI, user_id: uuid.UUID) -> list[datetime | None]:
    async with app.state.session_factory() as s:
        rows = await s.execute(
            select(Session.mfa_at).where(Session.user_id == user_id).order_by(Session.id)
        )
        return list(rows.scalars())


def _err(r: httpx.Response) -> str:
    code: str = r.json()["error"]["code"]
    return code


# --- credentials ------------------------------------------------------------------------


async def test_login_ok_sets_cookies_and_records(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    user = await _user(app)
    r = await _login(client, user.username)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["user"]["id"] == str(user.id)
    assert body["user"]["username"] == user.username
    assert "password_hash" not in body["user"]
    set_cookie = r.headers.get_list("set-cookie")
    assert any(h.startswith("pk_session=") and "HttpOnly" in h for h in set_cookie)
    assert any(h.startswith("pk_csrf=") and "HttpOnly" not in h for h in set_cookie)
    fresh = await _get_user(app, user.id)
    assert fresh.last_login_at == clock.now
    assert fresh.failed_logins == 0
    assert await _events(app, user.id) == ["success"]
    assert await _session_mfa_at(app, user.id) == [None]  # password only: no second factor
    async with app.state.session_factory() as s:
        audit = (
            await s.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "user.login", AuditEvent.target_id == str(user.id)
                )
            )
        ).scalar_one()
        assert audit.actor_id == user.id
    me = await client.get(SESSIONS)
    assert me.status_code == 200


async def test_login_by_mobile_any_format(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    user = await _user(app)
    local = "0" + user.mobile[2:]
    r = await _login(client, local)
    assert r.status_code == 200, r.text
    assert r.json()["user"]["id"] == str(user.id)


async def test_login_errors_indistinguishable(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _user(app)
    calls: list[str] = []
    real = verify_password

    def spy(hashed: str, pw: str) -> bool:
        calls.append(hashed)
        return real(hashed, pw)

    monkeypatch.setattr("payamakyar.api.routes.auth.verify_password", spy)
    wrong = await _login(client, user.username, "Wr0ng!Password")
    unknown = await _login(client, "no_such_user_xyz", "Wr0ng!Password")
    assert wrong.status_code == unknown.status_code == 401
    assert _err(wrong) == "INVALID_CREDENTIALS"
    assert wrong.json() == unknown.json()
    assert wrong.headers.get("set-cookie") is None
    assert unknown.headers.get("set-cookie") is None
    # Both paths ran exactly one argon2 verify (a dummy hash for the unknown user).
    assert len(calls) == 2
    assert calls[1].startswith("$argon2id$")
    assert calls[1] != user.password_hash
    async with app.state.session_factory() as s:
        tried = (
            await s.execute(
                select(LoginEvent).where(LoginEvent.username_tried == "no_such_user_xyz")
            )
        ).scalar_one()
        assert tried.user_id is None
        assert tried.outcome == "unknown_user"
    assert await _events(app, user.id) == ["bad_password"]


async def test_lockout_after_five_and_sixth_correct_still_423(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    user = await _user(app)
    for _ in range(4):
        r = await _login(client, user.username, "bad")
        assert r.status_code == 401
    r = await _login(client, user.username, "bad")  # 5th failure locks the account
    assert r.status_code == 401
    fresh = await _get_user(app, user.id)
    assert fresh.locked_until == clock.now + timedelta(seconds=900)
    async with app.state.session_factory() as s:
        lock = (
            await s.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "user.lock", AuditEvent.target_id == str(user.id)
                )
            )
        ).scalar_one()
    assert (lock.actor_id, lock.target_type) == (None, "user")
    assert lock.after == {"locked_until": fresh.locked_until.isoformat()}
    r = await _login(client, user.username)  # 6th attempt, correct password
    assert r.status_code == 423
    assert _err(r) == "ACCOUNT_LOCKED"
    unlock = datetime.fromisoformat(r.json()["error"]["detail"])
    assert unlock == clock.now + timedelta(seconds=900)
    assert int(r.headers["Retry-After"]) == 900
    assert r.headers.get("set-cookie") is None
    clock.advance(901)
    r = await _login(client, user.username)
    assert r.status_code == 200
    events = await _events(app, user.id)
    assert events == ["bad_password"] * 4 + ["locked", "locked_out", "success"]


async def test_lockout_doubles_per_further_lock_and_caps(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    user = await _user(app)

    async def lock() -> timedelta:
        start = clock.now
        for _ in range(5):
            assert (await _login(client, user.username, "bad")).status_code == 401
        until = (await _get_user(app, user.id)).locked_until
        assert until is not None
        return until - start

    assert await lock() == timedelta(seconds=900)
    clock.advance(901)
    assert await lock() == timedelta(seconds=1800)
    clock.advance(1801)
    assert await lock() == timedelta(seconds=3600)
    clock.advance(3601)
    # A success resets the doubling.
    assert (await _login(client, user.username)).status_code == 200
    assert await lock() == timedelta(seconds=900)
    # Cap at 86400 seconds.
    await _set_setting(app, "auth.lockout_seconds", 50000)
    try:
        clock.advance(901)
        assert await lock() == timedelta(seconds=86400)
    finally:
        await _set_setting(app, "auth.lockout_seconds", 900)


async def test_login_rate_limited_per_ip(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    await _set_setting(app, "auth.login_rate_per_ip_per_min", 2)
    try:
        user = await _user(app)
        assert (await _login(client, user.username, "bad")).status_code == 401
        assert (await _login(client, user.username, "bad")).status_code == 401
        r = await _login(client, user.username)
        assert r.status_code == 429
        assert _err(r) == "RATE_LIMITED"
        assert "Retry-After" in r.headers
        assert (await _events(app, user.id))[-1] == "rate_limited"
        clock.advance(61)
        assert (await _login(client, user.username)).status_code == 200
    finally:
        await _set_setting(app, "auth.login_rate_per_ip_per_min", 20)


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"status": "inactive"}, "ACCOUNT_INACTIVE"),
        ({"expires_at": FRIDAY_20_TEHRAN - timedelta(seconds=1)}, "ACCOUNT_EXPIRED"),
    ],
)
async def test_inactive_and_expired_only_after_correct_password(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock, over: dict[str, Any], code: str
) -> None:
    user = await _user(app, **over)
    r = await _login(client, user.username, "bad")
    assert r.status_code == 401
    r = await _login(client, user.username)
    assert r.status_code == 403
    assert _err(r) == code
    assert r.headers.get("set-cookie") is None


async def test_future_expiry_allows_login(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    user = await _user(app, expires_at=clock.now + timedelta(days=1))
    assert (await _login(client, user.username)).status_code == 200


# --- IP and hours -----------------------------------------------------------------------


async def test_allowed_ips_blocks_other_networks(app: FastAPI, clock: Clock) -> None:
    user = await _user(app, allowed_ips=["10.0.0.0/8"])
    async with _client(app, "192.168.1.1") as outside:
        r = await _login(outside, user.username)
        assert r.status_code == 403
        assert _err(r) == "LOGIN_IP_NOT_ALLOWED"
        assert r.headers.get("set-cookie") is None
        # A forged X-Forwarded-For from an untrusted peer is ignored.
        r = await outside.post(
            LOGIN,
            json={"username": user.username, "password": PASSWORD},
            headers={"X-Forwarded-For": "10.1.1.1"},
        )
        assert r.status_code == 403
    async with _client(app, "10.20.30.40") as inside:
        assert (await _login(inside, user.username)).status_code == 200
    assert "ip_not_allowed" in await _events(app, user.id)
    # Wrong password from a blocked IP is still a plain credential failure.
    async with _client(app, "192.168.1.1") as outside:
        assert (await _login(outside, user.username, "bad")).status_code == 401


async def test_allowed_ips_via_trusted_proxy(app: FastAPI, clock: Clock) -> None:
    user = await _user(app, allowed_ips=["203.0.113.0/24"])
    async with _client(app, "10.0.0.5") as proxy:  # 10.0.0.0/8 is the trusted proxy range
        r = await proxy.post(
            LOGIN,
            json={"username": user.username, "password": PASSWORD},
            headers={"X-Forwarded-For": "203.0.113.7"},
        )
        assert r.status_code == 200, r.text


async def test_login_hours_saturday_window_blocks_friday_evening(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    user = await _user(app, login_hours=[{"days": [0], "from": "08:00", "to": "18:00"}])
    r = await _login(client, user.username)  # Friday 20:00 Tehran
    assert r.status_code == 403
    assert _err(r) == "LOGIN_OUTSIDE_HOURS"
    clock.now = SATURDAY_10_TEHRAN
    assert (await _login(client, user.username)).status_code == 200
    clock.now = SATURDAY_10_TEHRAN + timedelta(hours=8)  # Saturday 18:00: end is exclusive
    assert (await _login(client, user.username)).status_code == 403
    assert (await _events(app, user.id)).count("outside_hours") == 2


async def test_login_hours_friday_entry_allows(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    user = await _user(app, login_hours=[{"days": [6], "from": "19:30", "to": "24:00"}])
    assert (await _login(client, user.username)).status_code == 200


# --- second factor ----------------------------------------------------------------------


def _box(app: FastAPI) -> SecretBox:
    return SecretBox(app.state.settings.secret_key.get_secret_value().encode())


async def test_totp_flow_and_replay(app: FastAPI, client: httpx.AsyncClient, clock: Clock) -> None:
    secret = pyotp.random_base32()
    user = await _user(app, mfa_method="totp", totp_secret_sealed=_box(app).seal(secret))
    r = await _login(client, user.username)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "mfa_required"
    assert body["method"] == "totp"
    token = body["mfa_token"]
    assert str(user.id) not in token
    assert r.headers.get("set-cookie") is None
    assert (await _get_user(app, user.id)).last_login_at is None

    if pyotp.TOTP(secret).verify("000000", for_time=clock.now, valid_window=1):
        pytest.skip("random secret produced 000000")
    bad = await client.post(MFA_CONFIRM, json={"mfa_token": token, "code": "000000"})
    assert bad.status_code == 400
    assert _err(bad) == "OTP_INVALID"

    code = pyotp.TOTP(secret).at(clock.now)
    ok = await client.post(MFA_CONFIRM, json={"mfa_token": token, "code": code})
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "ok"
    assert "pk_session" in ok.cookies
    fresh = await _get_user(app, user.id)
    assert fresh.totp_last_step == int(clock.now.timestamp()) // 30
    assert fresh.last_login_at == clock.now
    events = await _events(app, user.id)
    assert events == ["mfa_required", "mfa_failed", "success"]
    assert await _session_mfa_at(app, user.id) == [clock.now]  # second factor recorded

    # Replay of the same code (same time-step) is refused, even through a fresh login.
    r = await _login(client, user.username)
    token2 = r.json()["mfa_token"]
    replay = await client.post(MFA_CONFIRM, json={"mfa_token": token2, "code": code})
    assert replay.status_code == 400
    assert _err(replay) == "OTP_INVALID"
    # An earlier step inside the window is also refused once a later one was accepted.
    older = pyotp.TOTP(secret).at(clock.now, -1)
    replay = await client.post(MFA_CONFIRM, json={"mfa_token": token2, "code": older})
    assert replay.status_code == 400
    clock.advance(30)
    nxt = pyotp.TOTP(secret).at(clock.now)
    assert (
        await client.post(MFA_CONFIRM, json={"mfa_token": token2, "code": nxt})
    ).status_code == 200


async def test_mfa_token_expiry_and_tamper(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    secret = pyotp.random_base32()
    user = await _user(app, mfa_method="totp", totp_secret_sealed=_box(app).seal(secret))
    token = (await _login(client, user.username)).json()["mfa_token"]
    for bad_token in (token[:-4] + "AAAA", "garbage", _box(app).seal('{"user_id": 1}')):
        r = await client.post(MFA_CONFIRM, json={"mfa_token": bad_token, "code": "123456"})
        assert r.status_code == 401
        assert _err(r) == "MFA_TOKEN_INVALID"
    clock.advance(301)
    code = pyotp.TOTP(secret).at(clock.now)
    r = await client.post(MFA_CONFIRM, json={"mfa_token": token, "code": code})
    assert r.status_code == 401
    assert _err(r) == "MFA_TOKEN_INVALID"


async def test_totp_failures_count_toward_lockout(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    secret = pyotp.random_base32()
    user = await _user(app, mfa_method="totp", totp_secret_sealed=_box(app).seal(secret))
    token = (await _login(client, user.username)).json()["mfa_token"]
    wrong = "999999" if pyotp.TOTP(secret).at(clock.now) != "999999" else "111111"
    for _ in range(5):
        r = await client.post(MFA_CONFIRM, json={"mfa_token": token, "code": wrong})
        assert r.status_code == 400
    code = pyotp.TOTP(secret).at(clock.now)
    r = await client.post(MFA_CONFIRM, json={"mfa_token": token, "code": code})
    assert r.status_code == 423
    assert _err(r) == "ACCOUNT_LOCKED"


async def _latest_sms(app: FastAPI, mobile: str, template: str) -> SystemMessage | None:
    async with app.state.session_factory() as s:
        msg: SystemMessage | None = (
            await s.execute(
                select(SystemMessage)
                .where(SystemMessage.to_mobile == mobile, SystemMessage.template_key == template)
                .order_by(SystemMessage.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return msg


async def test_sms_flow(app: FastAPI, client: httpx.AsyncClient, clock: Clock) -> None:
    user = await _user(app, mfa_method="sms")
    r = await _login(client, user.username)
    assert r.status_code == 200
    assert r.json()["method"] == "sms"
    token = r.json()["mfa_token"]
    assert await _latest_sms(app, user.mobile, "otp") is None  # sent only on request

    sent = await client.post(MFA_SEND, json={"mfa_token": token})
    assert sent.status_code == 202, sent.text
    assert sent.json()["resend_after"] == 60
    again = await client.post(MFA_SEND, json={"mfa_token": token})
    assert again.status_code == 429
    assert _err(again) == "OTP_RESEND_TOO_SOON"

    msg = await _latest_sms(app, user.mobile, "otp")
    assert msg is not None
    code = "".join(ch for ch in msg.body if ch.isdigit())[:6]
    bad_code = "000000" if code != "000000" else "111111"
    bad = await client.post(MFA_CONFIRM, json={"mfa_token": token, "code": bad_code})
    assert bad.status_code == 400
    assert _err(bad) == "OTP_INVALID"
    assert (await _get_user(app, user.id)).failed_logins == 1  # counts toward lockout
    ok = await client.post(MFA_CONFIRM, json={"mfa_token": token, "code": code})
    assert ok.status_code == 200, ok.text
    assert "pk_session" in ok.cookies
    assert (await _get_user(app, user.id)).failed_logins == 0
    assert await _events(app, user.id) == ["mfa_required", "mfa_failed", "success"]
    assert await _session_mfa_at(app, user.id) == [clock.now]
    # The token (and with it the code) is single-use.
    reuse = await client.post(MFA_CONFIRM, json={"mfa_token": token, "code": code})
    assert reuse.status_code == 401
    assert _err(reuse) == "MFA_TOKEN_INVALID"


async def test_sms_send_rejects_totp_token(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    user = await _user(
        app, mfa_method="totp", totp_secret_sealed=_box(app).seal(pyotp.random_base32())
    )
    token = (await _login(client, user.username)).json()["mfa_token"]
    r = await client.post(MFA_SEND, json={"mfa_token": token})
    assert r.status_code == 409
    assert _err(r) == "MFA_METHOD_MISMATCH"


async def test_mfa_endpoints_csrf_exempt_logout_not(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    r = await client.post(MFA_CONFIRM, json={"mfa_token": "x", "code": "1"})
    assert r.status_code == 401  # reached the route: no CSRF needed
    r = await client.post(LOGOUT)
    assert r.status_code == 403
    assert _err(r) == "CSRF_FAILED"


# --- notice and logs --------------------------------------------------------------------


async def test_login_notice_queued_and_logs_masked(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    user = await _user(app, login_notice=True)
    r = await _login(client, user.username)
    assert r.status_code == 200
    msg = await _latest_sms(app, user.mobile, "login_notice")
    assert msg is not None
    assert "127.0.0.1" in msg.body
    assert "۱۴۰۵/۰۸/۲۲ ۲۰:۰۰" in msg.body  # Jalali date, Tehran local time
    text = caplog.text
    assert user.mobile not in text
    assert user.mobile[2:] not in text
    assert PASSWORD not in text
    notice = [rec for rec in caplog.records if rec.getMessage() == "login notice queued"]
    assert len(notice) == 1
    masked = getattr(notice[0], "mobile", "")
    assert masked and masked != user.mobile and masked.endswith(user.mobile[-4:])


async def test_no_notice_without_flag(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    user = await _user(app)
    assert (await _login(client, user.username)).status_code == 200
    assert await _latest_sms(app, user.mobile, "login_notice") is None


# --- sessions ---------------------------------------------------------------------------


async def test_logout_revokes(app: FastAPI, client: httpx.AsyncClient, clock: Clock) -> None:
    user = await _user(app)
    assert (await _login(client, user.username)).status_code == 200
    token = client.cookies["pk_session"]
    r = await client.post(LOGOUT, headers=_csrf(client))
    assert r.status_code == 204
    async with app.state.session_factory() as s:
        row = (await s.execute(select(Session).where(Session.user_id == user.id))).scalar_one()
        assert row.revoked_at == clock.now
    client.cookies.set("pk_session", token)
    r = await client.get(SESSIONS)
    assert r.status_code == 401
    assert _err(r) == "NOT_AUTHENTICATED"


async def test_session_csrf_bound_to_session(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    user = await _user(app)
    assert (await _login(client, user.username)).status_code == 200
    client.cookies.delete("pk_csrf")
    client.cookies.set("pk_csrf", "forged")
    r = await client.post(LOGOUT, headers={"X-CSRF-Token": "forged"})
    assert r.status_code == 403
    assert _err(r) == "CSRF_FAILED"


async def test_list_and_revoke_sessions(
    app: FastAPI, client: httpx.AsyncClient, other_client: httpx.AsyncClient, clock: Clock
) -> None:
    user = await _user(app)
    assert (await _login(client, user.username)).status_code == 200
    assert (await _login(other_client, user.username)).status_code == 200
    stranger = await _user(app)
    async with _client(app) as third:
        assert (await _login(third, stranger.username)).status_code == 200
        stranger_sessions = (await third.get(SESSIONS)).json()["sessions"]
    r = await client.get(SESSIONS)
    assert r.status_code == 200
    rows = r.json()["sessions"]
    assert len(rows) == 2
    assert sorted(row["current"] for row in rows) == [False, True]
    assert {"id", "ip", "user_agent", "created_at", "last_seen_at", "current"} <= set(rows[0])
    other = next(row for row in rows if not row["current"])

    r = await client.delete(f"{SESSIONS}/{other['id']}", headers=_csrf(client))
    assert r.status_code == 204
    r = await other_client.get(SESSIONS)
    assert r.status_code == 401
    assert len((await client.get(SESSIONS)).json()["sessions"]) == 1

    r = await client.delete(f"{SESSIONS}/{stranger_sessions[0]['id']}", headers=_csrf(client))
    assert r.status_code == 404
    r = await client.delete(f"{SESSIONS}/{uuid.uuid4()}", headers=_csrf(client))
    assert r.status_code == 404
    r = await client.delete(f"{SESSIONS}/{other['id']}")
    assert r.status_code == 403  # CSRF


async def test_idle_expiry_uses_setting(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    user = await _user(app)
    assert (await _login(client, user.username)).status_code == 200
    clock.advance(1799)
    assert (await client.get(SESSIONS)).status_code == 200
    clock.advance(1801)
    r = await client.get(SESSIONS)
    assert r.status_code == 401
    assert _err(r) == "NOT_AUTHENTICATED"

    await _set_setting(app, "session.idle_seconds", 100)
    try:
        assert (await _login(client, user.username)).status_code == 200
        clock.advance(101)
        assert (await client.get(SESSIONS)).status_code == 401
    finally:
        await _set_setting(app, "session.idle_seconds", 1800)


async def test_deactivated_user_session_rejected(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    user = await _user(app)
    assert (await _login(client, user.username)).status_code == 200
    async with app.state.session_factory() as s:
        row = (await s.execute(select(User).where(User.id == user.id))).scalar_one()
        row.status = "inactive"
        await s.commit()
    assert (await client.get(SESSIONS)).status_code == 401


async def test_unauthenticated_sessions_list(client: httpx.AsyncClient) -> None:
    r = await client.get(SESSIONS)
    assert r.status_code == 401
    assert _err(r) == "NOT_AUTHENTICATED"


# --- fix round 1 ----------------------------------------------------------------------


async def _sms_token(app: FastAPI, client: httpx.AsyncClient, user: User) -> tuple[str, str]:
    """(mfa_token, the sent code) for an SMS-MFA user."""
    token = (await _login(client, user.username)).json()["mfa_token"]
    assert (await client.post(MFA_SEND, json={"mfa_token": token})).status_code == 202
    msg = await _latest_sms(app, user.mobile, "otp")
    assert msg is not None
    return token, "".join(ch for ch in msg.body if ch.isdigit())[:6]


async def test_concurrent_wrong_sms_codes_all_counted(
    app: FastAPI,
    client: httpx.AsyncClient,
    other_client: httpx.AsyncClient,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _user(app, mfa_method="sms")
    token, code = await _sms_token(app, client, user)
    real_check = otp.check

    async def slow_check(*args: Any, **kwargs: Any) -> Any:
        # Widen the gap after check() commits (and so releases the user row lock).
        try:
            return await real_check(*args, **kwargs)
        finally:
            await asyncio.sleep(0.2)

    monkeypatch.setattr(otp, "check", slow_check)
    wrong = "000000" if code != "000000" else "111111"
    results = await asyncio.gather(
        client.post(MFA_CONFIRM, json={"mfa_token": token, "code": wrong}),
        other_client.post(MFA_CONFIRM, json={"mfa_token": token, "code": wrong}),
    )
    assert [r.status_code for r in results] == [400, 400]
    assert (await _get_user(app, user.id)).failed_logins == 2


async def test_concurrent_failures_lock_once(
    app: FastAPI, client: httpx.AsyncClient, other_client: httpx.AsyncClient, clock: Clock
) -> None:
    user = await _user(app, failed_logins=3)
    results = await asyncio.gather(
        _login(client, user.username, "bad"), _login(other_client, user.username, "bad")
    )
    assert [r.status_code for r in results] == [401, 401]
    fresh = await _get_user(app, user.id)
    assert fresh.locked_until == clock.now + timedelta(seconds=900)
    events = await _events(app, user.id)
    assert sorted(events) == ["bad_password", "locked"]


async def test_mfa_token_single_use(app: FastAPI, client: httpx.AsyncClient, clock: Clock) -> None:
    secret = pyotp.random_base32()
    user = await _user(app, mfa_method="totp", totp_secret_sealed=_box(app).seal(secret))
    token = (await _login(client, user.username)).json()["mfa_token"]
    code = pyotp.TOTP(secret).at(clock.now)
    assert (
        await client.post(MFA_CONFIRM, json={"mfa_token": token, "code": code})
    ).status_code == 200
    clock.advance(30)
    nxt = pyotp.TOTP(secret).at(clock.now)
    r = await client.post(MFA_CONFIRM, json={"mfa_token": token, "code": nxt})
    assert r.status_code == 401
    assert _err(r) == "MFA_TOKEN_INVALID"


async def test_sms_send_rechecks_access(app: FastAPI, clock: Clock) -> None:
    user = await _user(app, mfa_method="sms", allowed_ips=["10.0.0.0/8"])
    async with _client(app, "10.20.30.40") as inside:
        r = await _login(inside, user.username)
        assert r.status_code == 200
        token = r.json()["mfa_token"]
    async with _client(app, "192.168.1.1") as outside:
        r = await outside.post(MFA_SEND, json={"mfa_token": token})
        assert r.status_code == 403
        assert _err(r) == "LOGIN_IP_NOT_ALLOWED"
    assert await _latest_sms(app, user.mobile, "otp") is None


async def test_revoke_unknown_session_has_persian_detail(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    user = await _user(app)
    assert (await _login(client, user.username)).status_code == 200
    r = await client.delete(f"{SESSIONS}/{uuid.uuid4()}", headers=_csrf(client))
    assert r.status_code == 404
    assert _err(r) == "SESSION_NOT_FOUND"
    assert r.json()["error"]["detail"]
