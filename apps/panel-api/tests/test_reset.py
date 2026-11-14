import itertools
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from payamakyar.api import otp
from payamakyar.api.deps import get_clock
from payamakyar.core.passwords import hash_password, verify_password
from payamakyar.db.models import AuditEvent, OtpChallenge, Session, SystemMessage, User
from payamakyar.db.testing import flush_test_redis

pytestmark = pytest.mark.integration

START = "/panel/web/v1/auth/reset/start"
COMPLETE = "/panel/web/v1/auth/reset/complete"
LOGIN = "/panel/web/v1/auth/login"
SESSIONS = "/panel/web/v1/account/sessions"
PASSWORD = "Str0ng!Passw0rd"
NEW_PASSWORD = "N3w!Passw0rdX"
_seq = itertools.count(1)
_HASH = hash_password(PASSWORD)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 14, 6, 30, tzinfo=UTC)

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
        "username": f"reset_{n}_{uuid.uuid4().hex[:6]}",
        "mobile": f"98936{n:03d}{uuid.uuid4().int % 10**4:04d}",
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


async def _messages(app: FastAPI, mobile: str) -> list[SystemMessage]:
    async with app.state.session_factory() as s:
        rows = await s.execute(
            select(SystemMessage)
            .where(SystemMessage.to_mobile == mobile)
            .order_by(SystemMessage.created_at)
        )
        return list(rows.scalars().all())


async def _code(app: FastAPI, mobile: str) -> str:
    otps = [m for m in await _messages(app, mobile) if m.template_key == "otp"]
    found = re.search(r"\d{6}", otps[-1].body)
    assert found is not None
    return found.group(0)


async def _actions(app: FastAPI, user_id: uuid.UUID) -> list[str]:
    async with app.state.session_factory() as s:
        rows = await s.execute(
            select(AuditEvent.action)
            .where(AuditEvent.target_id == str(user_id))
            .order_by(AuditEvent.id)
        )
        return list(rows.scalars().all())


def _err(r: httpx.Response) -> str:
    code: str = r.json()["error"]["code"]
    return code


async def test_reset_unknown_mobile_is_202_and_sends_nothing(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    known = await _user(app)
    unknown = "989399999999"
    r1 = await client.post(START, json={"mobile": "09399999999"})
    r2 = await client.post(START, json={"mobile": "0" + known.mobile[2:]})
    assert r1.status_code == 202, r1.text
    assert r2.status_code == 202, r2.text
    assert set(r1.json()) == set(r2.json()) == {"challenge_id", "resend_after"}
    assert r1.json()["resend_after"] == r2.json()["resend_after"]
    assert await _messages(app, unknown) == []
    assert [m.template_key for m in await _messages(app, known.mobile)] == ["otp"]
    async with app.state.session_factory() as s:
        n = (
            await s.execute(
                select(func.count()).select_from(OtpChallenge).where(OtpChallenge.mobile == unknown)
            )
        ).scalar_one()
    assert n == 0
    # The fake challenge simply fails later.
    r = await client.post(
        COMPLETE,
        json={
            "challenge_id": r1.json()["challenge_id"],
            "code": "123456",
            "new_password": NEW_PASSWORD,
        },
    )
    assert r.status_code == 400
    assert _err(r) == "OTP_INVALID"


async def test_reset_resend_window_same_for_known_and_unknown(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    known = await _user(app)
    for mobile in (known.mobile, "989388888888"):
        assert (await client.post(START, json={"mobile": mobile})).status_code == 202
        again = await client.post(START, json={"mobile": mobile})
        assert again.status_code == 429
        assert _err(again) == "OTP_RESEND_TOO_SOON"
        assert not any(c.isascii() and c.isdigit() for c in again.json()["error"]["detail"])
    clock.advance(61)
    assert (await client.post(START, json={"mobile": known.mobile})).status_code == 202


async def test_reset_start_per_ip_throttle(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    for i in range(10):
        r = await client.post(START, json={"mobile": f"98937000{i:04d}"})
        assert r.status_code == 202, r.text
    r = await client.post(START, json={"mobile": "989370009999"})
    assert r.status_code == 429
    assert _err(r) == "RATE_LIMITED"
    assert "Retry-After" in r.headers


async def test_reset_start_invalid_mobile_422(client: httpx.AsyncClient, clock: Clock) -> None:
    r = await client.post(START, json={"mobile": "12345"})
    assert r.status_code == 422
    assert r.json()["error"]["source"]["pointer"] == "/mobile"


async def test_reset_complete_revokes_sessions_unlocks_and_notifies(
    app: FastAPI, clock: Clock
) -> None:
    user = await _user(app)
    async with _client(app) as a, _client(app) as b:
        assert (
            await a.post(LOGIN, json={"username": user.username, "password": PASSWORD})
        ).status_code == 200
        assert (
            await b.post(LOGIN, json={"username": user.username, "password": PASSWORD})
        ).status_code == 200
        async with app.state.session_factory() as s:
            locked = await s.get(User, user.id)
            assert locked is not None
            locked.failed_logins = 3
            locked.locked_until = clock.now + timedelta(hours=1)
            await s.commit()
        r = await a.post(START, json={"mobile": user.mobile})
        cid = r.json()["challenge_id"]
        code = await _code(app, user.mobile)
        r = await a.post(
            COMPLETE, json={"challenge_id": cid, "code": code, "new_password": NEW_PASSWORD}
        )
        assert r.status_code == 204, r.text
        assert (await a.get(SESSIONS)).status_code == 401
        assert (await b.get(SESSIONS)).status_code == 401
    fresh = await _get_user(app, user.id)
    assert verify_password(fresh.password_hash, NEW_PASSWORD)
    assert fresh.failed_logins == 0
    assert fresh.locked_until is None
    async with app.state.session_factory() as s:
        live = (
            await s.execute(
                select(func.count())
                .select_from(Session)
                .where(Session.user_id == user.id, Session.revoked_at.is_(None))
            )
        ).scalar_one()
    assert live == 0
    msgs = await _messages(app, user.mobile)
    assert msgs[-1].template_key == "password_changed"
    assert "user.password_reset" in await _actions(app, user.id)
    async with _client(app) as c:
        r = await c.post(LOGIN, json={"username": user.username, "password": NEW_PASSWORD})
        assert r.status_code == 200, r.text
        # The code is single-use.
        r = await c.post(
            COMPLETE, json={"challenge_id": cid, "code": code, "new_password": NEW_PASSWORD}
        )
        assert r.status_code == 400


async def test_reset_complete_weak_password_does_not_burn_code(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    user = await _user(app)
    cid = (await client.post(START, json={"mobile": user.mobile})).json()["challenge_id"]
    code = await _code(app, user.mobile)
    r = await client.post(COMPLETE, json={"challenge_id": cid, "code": code, "new_password": "abc"})
    assert r.status_code == 422
    assert _err(r) == "PASSWORD_WEAK"
    assert "TOO_SHORT" in r.json()["error"]["detail"]
    r = await client.post(
        COMPLETE, json={"challenge_id": cid, "code": code, "new_password": "Aa1!" + "x" * 130}
    )
    assert r.status_code == 422
    assert _err(r) == "PASSWORD_TOO_LONG"
    r = await client.post(
        COMPLETE, json={"challenge_id": cid, "code": code, "new_password": NEW_PASSWORD}
    )
    assert r.status_code == 204, r.text


async def test_reset_complete_wrong_code_and_forged_id(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    user = await _user(app)
    cid = (await client.post(START, json={"mobile": user.mobile})).json()["challenge_id"]
    code = await _code(app, user.mobile)
    wrong = "000000" if code != "000000" else "111111"
    r = await client.post(
        COMPLETE, json={"challenge_id": cid, "code": wrong, "new_password": NEW_PASSWORD}
    )
    assert r.status_code == 400
    assert _err(r) == "OTP_INVALID"
    r = await client.post(
        COMPLETE,
        json={"challenge_id": str(uuid.uuid4()), "code": code, "new_password": NEW_PASSWORD},
    )
    assert r.status_code == 400
    assert _err(r) == "OTP_INVALID"
    fresh = await _get_user(app, user.id)
    assert verify_password(fresh.password_hash, PASSWORD)


async def _challenges(app: FastAPI, user_id: uuid.UUID) -> list[OtpChallenge]:
    async with app.state.session_factory() as s:
        rows = await s.execute(
            select(OtpChallenge)
            .where(OtpChallenge.user_id == user_id, OtpChallenge.purpose == "reset")
            .order_by(OtpChallenge.created_at, OtpChallenge.id)
        )
        return list(rows.scalars().all())


def _shape(r: httpx.Response) -> tuple[int, Any]:
    return r.status_code, r.json()


async def test_reset_failures_identical_for_known_and_unknown(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    known = await _user(app)
    known_cid = (await client.post(START, json={"mobile": known.mobile})).json()["challenge_id"]
    unknown_cid = (await client.post(START, json={"mobile": "989377777777"})).json()["challenge_id"]
    assert uuid.UUID(unknown_cid).version == 7
    assert uuid.UUID(known_cid).version == 7
    code = await _code(app, known.mobile)
    wrong = "000000" if code != "000000" else "111111"

    async def attempt(cid: str) -> tuple[int, Any]:
        body = {"challenge_id": cid, "code": wrong, "new_password": NEW_PASSWORD}
        return _shape(await client.post(COMPLETE, json=body))

    for _ in range(6):
        assert await attempt(known_cid) == await attempt(unknown_cid)
    assert (await attempt(known_cid))[0] == 400
    clock.advance(600)
    assert await attempt(known_cid) == await attempt(unknown_cid)
    # Even the right code on an expired challenge looks the same.
    body = {"challenge_id": known_cid, "code": code, "new_password": NEW_PASSWORD}
    expired = _shape(await client.post(COMPLETE, json=body))
    assert expired == await attempt(unknown_cid)


async def test_reset_inactive_or_expired_user_gets_nothing(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    inactive = await _user(app, status="inactive")
    expired = await _user(app, expires_at=clock.now - timedelta(days=1))
    for user in (inactive, expired):
        r = await client.post(START, json={"mobile": user.mobile})
        assert r.status_code == 202
        assert set(r.json()) == {"challenge_id", "resend_after"}
        assert await _messages(app, user.mobile) == []
        assert await _challenges(app, user.id) == []
        assert "user.password_reset_requested" not in await _actions(app, user.id)


async def test_reset_start_audits_known_user(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    user = await _user(app)
    assert (await client.post(START, json={"mobile": user.mobile})).status_code == 202
    assert await _actions(app, user.id) == ["user.password_reset_requested"]


async def test_new_challenge_and_success_retire_older_challenges(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    user = await _user(app)
    first = (await client.post(START, json={"mobile": user.mobile})).json()["challenge_id"]
    first_code = await _code(app, user.mobile)
    clock.advance(61)
    second = (await client.post(START, json={"mobile": user.mobile})).json()["challenge_id"]
    rows = {str(c.id): c for c in await _challenges(app, user.id)}
    assert rows[first].consumed_at is not None
    assert rows[second].consumed_at is None
    r = await client.post(
        COMPLETE,
        json={"challenge_id": first, "code": first_code, "new_password": NEW_PASSWORD},
    )
    assert r.status_code == 400
    # An extra outstanding challenge (e.g. from a race) is retired by a successful reset.
    async with app.state.session_factory() as s:
        extra, _ = await otp.issue(s, "reset", user.mobile, user.id, None, now=clock.now)
        await s.commit()
    second_code = await _code(app, user.mobile)
    r = await client.post(
        COMPLETE,
        json={"challenge_id": second, "code": second_code, "new_password": NEW_PASSWORD},
    )
    assert r.status_code == 204, r.text
    assert all(c.consumed_at is not None for c in await _challenges(app, user.id))
    assert str(extra) in {str(c.id) for c in await _challenges(app, user.id)}


async def test_reset_code_bound_to_its_challenge(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    a = await _user(app)
    b = await _user(app)
    await client.post(START, json={"mobile": a.mobile})
    b_cid = (await client.post(START, json={"mobile": b.mobile})).json()["challenge_id"]
    a_code = await _code(app, a.mobile)
    if a_code == await _code(app, b.mobile):
        pytest.skip("codes collided")
    r = await client.post(
        COMPLETE, json={"challenge_id": b_cid, "code": a_code, "new_password": NEW_PASSWORD}
    )
    assert r.status_code == 400
    assert _err(r) == "OTP_INVALID"
    assert verify_password((await _get_user(app, b.id)).password_hash, PASSWORD)
