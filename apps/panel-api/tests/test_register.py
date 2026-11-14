import itertools
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from payamakyar.api import otp
from payamakyar.api.deps import get_clock
from payamakyar.db.audit import verify_chain
from payamakyar.db.models import (
    AuditEvent,
    OtpChallenge,
    Role,
    Session,
    SystemMessage,
    User,
    UserRole,
)
from payamakyar.db.settings_store import SettingsStore

pytestmark = pytest.mark.integration

START = "/panel/web/v1/auth/register/start"
COMPLETE = "/panel/web/v1/auth/register/complete"
GOOD_PASSWORD = "Str0ng!Passw0rd"
T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
_seq = itertools.count(1)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture(autouse=True)
async def _reset_redis(app: FastAPI) -> None:
    # Frozen clocks reuse the same rate-limit window across tests.
    await app.state.redis.flushdb()


@pytest.fixture
def clock(app: FastAPI) -> Clock:
    c = Clock()
    app.dependency_overrides[get_clock] = lambda: c
    return c


def _fresh() -> tuple[str, str, str]:
    """(local mobile, canonical mobile, username) unique per call."""
    n = next(_seq) + int(T0.timestamp()) % 1000 * 10
    local = f"0912{n:07d}"
    return local, "98" + local[1:], f"user_{n}"


async def _code_for(app: FastAPI, canonical: str) -> str:
    async with app.state.session_factory() as s:
        body = (
            await s.execute(
                select(SystemMessage.body)
                .where(SystemMessage.to_mobile == canonical)
                .order_by(SystemMessage.created_at.desc())
                .limit(1)
            )
        ).scalar_one()
    return "".join(ch for ch in body if ch.isdigit())[:6]


def _body(challenge_id: str, code: str, username: str, **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "challenge_id": challenge_id,
        "code": code,
        "username": username,
        "password": GOOD_PASSWORD,
        "first_name": "علی",
        "last_name": "رضایی",
    }
    body.update(over)
    return {k: v for k, v in body.items() if v is not None}


async def _start(client: httpx.AsyncClient, mobile: str, kind: str = "person") -> httpx.Response:
    return await client.post(START, json={"mobile": mobile, "kind": kind})


async def test_register_happy_path(app: FastAPI, client: httpx.AsyncClient, clock: Clock) -> None:
    local, canon, username = _fresh()
    r = await _start(client, local)
    assert r.status_code == 202
    assert r.json()["resend_after"] == 60
    code = await _code_for(app, canon)
    r = await client.post(COMPLETE, json=_body(r.json()["challenge_id"], code, username))
    assert r.status_code == 201, r.text
    user_id = r.json()["user_id"]
    assert "pk_session" in r.cookies
    assert "pk_csrf" in r.cookies
    set_cookie = r.headers.get_list("set-cookie")
    assert any(h.startswith("pk_session=") and "HttpOnly" in h for h in set_cookie)
    assert any(h.startswith("pk_csrf=") and "HttpOnly" not in h for h in set_cookie)
    async with app.state.session_factory() as s:
        user = (await s.execute(select(User).where(User.username == username))).scalar_one()
        assert str(user.id) == user_id
        assert user.mobile == canon
        assert user.kind == "person"
        assert user.status == "active"
        assert user.identity_state == "none"
        assert user.password_hash.startswith("$argon2id$")
        roles = (
            (
                await s.execute(
                    select(Role.name)
                    .join(UserRole, UserRole.role_id == Role.id)
                    .where(UserRole.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert roles == ["customer"]
        sessions_ = (await s.execute(select(Session).where(Session.user_id == user.id))).all()
        assert len(sessions_) == 1
        audit = (
            await s.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "user.register", AuditEvent.target_id == user_id
                )
            )
        ).scalar_one()
        assert audit.actor_id == user.id
        assert await verify_chain(s) is None


async def test_individual_is_an_alias_of_person(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    local, canon, username = _fresh()
    cid = (await _start(client, local, "individual")).json()["challenge_id"]
    code = await _code_for(app, canon)
    r = await client.post(COMPLETE, json=_body(cid, code, username))
    assert r.status_code == 201, r.text
    async with app.state.session_factory() as s:
        user = (await s.execute(select(User).where(User.username == username))).scalar_one()
        assert (user.kind, user.last_name) == ("person", "رضایی")


async def test_company_registration(app: FastAPI, client: httpx.AsyncClient, clock: Clock) -> None:
    local, canon, username = _fresh()
    cid = (await _start(client, local, "company")).json()["challenge_id"]
    code = await _code_for(app, canon)
    r = await client.post(
        COMPLETE,
        json=_body(cid, code, username, last_name=None, company_name="شرکت نمونه", email="a@b.ir"),
    )
    assert r.status_code == 201, r.text
    async with app.state.session_factory() as s:
        user = (await s.execute(select(User).where(User.username == username))).scalar_one()
        assert (user.kind, user.company_name, user.email) == ("company", "شرکت نمونه", "a@b.ir")


@pytest.mark.parametrize(
    ("kind", "drop", "pointer"),
    [
        ("person", "last_name", "/last_name"),
        ("individual", "last_name", "/last_name"),
        ("company", "company_name", "/company_name"),
    ],
)
async def test_kind_specific_required(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock, kind: str, drop: str, pointer: str
) -> None:
    local, canon, username = _fresh()
    cid = (await _start(client, local, kind)).json()["challenge_id"]
    code = await _code_for(app, canon)
    over: dict[str, Any] = {"last_name": None}  # no company_name either
    r = await client.post(COMPLETE, json=_body(cid, code, username, **over))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_FAILED"
    assert r.json()["error"]["source"]["pointer"] == pointer


async def test_invalid_mobile_and_kind(client: httpx.AsyncClient, clock: Clock) -> None:
    r = await _start(client, "12345")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_FAILED"
    r = await _start(client, "09121234567", "alien")
    assert r.status_code == 422


async def test_weak_password(app: FastAPI, client: httpx.AsyncClient, clock: Clock) -> None:
    local, canon, username = _fresh()
    cid = (await _start(client, local)).json()["challenge_id"]
    code = await _code_for(app, canon)
    r = await client.post(COMPLETE, json=_body(cid, code, username, password="abc"))
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "PASSWORD_WEAK"
    assert err["source"] == {"pointer": "/password"}
    for problem in ("TOO_SHORT", "NO_UPPER", "NO_DIGIT", "NO_SPECIAL"):
        assert problem in err["detail"]
    # The current minimum travels with TOO_SHORT so the page can say it.
    assert "MIN_LENGTH:8" in err["detail"].split(",")
    # The OTP was not burned by the rejected password: the same code still works.
    r = await client.post(COMPLETE, json=_body(cid, code, username))
    assert r.status_code == 201


async def test_password_too_long(app: FastAPI, client: httpx.AsyncClient, clock: Clock) -> None:
    local, canon, username = _fresh()
    cid = (await _start(client, local)).json()["challenge_id"]
    code = await _code_for(app, canon)
    long_pw = "Aa1!" + "x" * 125  # 129 chars
    r = await client.post(COMPLETE, json=_body(cid, code, username, password=long_pw))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "PASSWORD_TOO_LONG"
    assert "۱۲۸" in r.json()["error"]["detail"]
    ok_pw = "Aa1!" + "x" * 124  # exactly 128
    r = await client.post(COMPLETE, json=_body(cid, code, username, password=ok_pw))
    assert r.status_code == 201


async def test_duplicate_mobile(app: FastAPI, client: httpx.AsyncClient, clock: Clock) -> None:
    local, canon, username = _fresh()
    cid = (await _start(client, local)).json()["challenge_id"]
    code = await _code_for(app, canon)
    assert (await client.post(COMPLETE, json=_body(cid, code, username))).status_code == 201
    clock.now += timedelta(seconds=300)
    r = await _start(client, local)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "MOBILE_TAKEN"
    # Different spelling of the same number is the same number.
    r = await _start(client, "+" + canon)
    assert r.status_code == 409


async def test_duplicate_username_case_insensitive(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    local, canon, username = _fresh()
    cid = (await _start(client, local)).json()["challenge_id"]
    code = await _code_for(app, canon)
    assert (await client.post(COMPLETE, json=_body(cid, code, username))).status_code == 201
    local2, canon2, _ = _fresh()
    cid2 = (await _start(client, local2)).json()["challenge_id"]
    code2 = await _code_for(app, canon2)
    r = await client.post(COMPLETE, json=_body(cid2, code2, username.upper()))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "USERNAME_TAKEN"
    # The failed attempt did not consume the code: a free username still works.
    r = await client.post(COMPLETE, json=_body(cid2, code2, username + "_b"))
    assert r.status_code == 201


async def test_resend_limit(app: FastAPI, client: httpx.AsyncClient, clock: Clock) -> None:
    local, _canon, _ = _fresh()
    assert (await _start(client, local)).status_code == 202
    clock.now += timedelta(seconds=30)
    r = await _start(client, local)
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "OTP_RESEND_TOO_SOON"
    assert r.headers["retry-after"] == "30"
    assert r.json()["error"]["detail"] == "۳۰ ثانیهٔ دیگر دوباره تلاش کنید."
    clock.now += timedelta(seconds=31)
    assert (await _start(client, local)).status_code == 202


async def test_otp_expires_after_121_seconds(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    local, canon, username = _fresh()
    cid = (await _start(client, local)).json()["challenge_id"]
    code = await _code_for(app, canon)
    clock.now += timedelta(seconds=121)
    r = await client.post(COMPLETE, json=_body(cid, code, username))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "OTP_EXPIRED"


async def test_otp_single_use_and_attempts(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    local, canon, username = _fresh()
    cid = (await _start(client, local)).json()["challenge_id"]
    code = await _code_for(app, canon)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        r = await client.post(COMPLETE, json=_body(cid, wrong, username))
        assert (r.status_code, r.json()["error"]["code"]) == (400, "OTP_INVALID")
    r = await client.post(COMPLETE, json=_body(cid, code, username))
    assert (r.status_code, r.json()["error"]["code"]) == (400, "OTP_TOO_MANY_ATTEMPTS")

    # single use
    local2, canon2, username2 = _fresh()
    cid2 = (await _start(client, local2)).json()["challenge_id"]
    code2 = await _code_for(app, canon2)
    assert (await client.post(COMPLETE, json=_body(cid2, code2, username2))).status_code == 201
    r = await client.post(COMPLETE, json=_body(cid2, code2, username2 + "x"))
    assert (r.status_code, r.json()["error"]["code"]) == (400, "OTP_INVALID")


async def test_challenge_must_be_register_purpose(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    _local, canon, username = _fresh()
    async with app.state.session_factory() as s:
        cid, code = await otp.issue(s, "login", canon, ip=None, now=clock.now)
        await s.commit()
    r = await client.post(COMPLETE, json=_body(str(cid), code, username))
    assert (r.status_code, r.json()["error"]["code"]) == (400, "OTP_INVALID")


async def test_secrets_never_logged(
    app: FastAPI,
    client: httpx.AsyncClient,
    clock: Clock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    local, canon, username = _fresh()
    r = await _start(client, local)
    code = await _code_for(app, canon)
    password = "Zz9!secretpassword"
    await client.post(COMPLETE, json=_body(r.json()["challenge_id"], "000000", username))
    await client.post(
        COMPLETE, json=_body(r.json()["challenge_id"], code, username, password=password)
    )
    await _start(client, local)  # resend-too-soon path
    text = caplog.text
    assert code not in text
    assert password not in text
    assert canon not in text
    assert local not in text
    async with app.state.session_factory() as s:
        row = (
            await s.execute(select(OtpChallenge).where(OtpChallenge.mobile == canon))
        ).scalar_one()
        assert code not in row.code_hash


async def test_username_containing_word_mobile_maps_to_username_taken(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    local, canon, _ = _fresh()
    cid = (await _start(client, local)).json()["challenge_id"]
    code = await _code_for(app, canon)
    assert (await client.post(COMPLETE, json=_body(cid, code, "my_mobile_1"))).status_code == 201
    local2, canon2, _ = _fresh()
    cid2 = (await _start(client, local2)).json()["challenge_id"]
    code2 = await _code_for(app, canon2)
    r = await client.post(COMPLETE, json=_body(cid2, code2, "my_mobile_1"))
    assert (r.status_code, r.json()["error"]["code"]) == (409, "USERNAME_TAKEN")


async def test_mobile_taken_between_start_and_complete(
    app: FastAPI, client: httpx.AsyncClient, clock: Clock
) -> None:
    local, canon, username = _fresh()
    cid = (await _start(client, local)).json()["challenge_id"]
    code = await _code_for(app, canon)
    async with app.state.session_factory() as s:
        s.add(User(username=username + "_other", mobile=canon, password_hash="x"))
        await s.commit()
    r = await client.post(COMPLETE, json=_body(cid, code, username))
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "MOBILE_TAKEN"
    assert err["detail"]
    assert err["source"] == {"pointer": "/mobile"}


async def test_start_per_ip_throttle(app: FastAPI, client: httpx.AsyncClient, clock: Clock) -> None:
    async with app.state.session_factory() as s:
        await SettingsStore(s).set("otp.start_rate_per_ip_per_hour", 3, None)
        await s.commit()
    try:
        for _ in range(3):
            assert (await _start(client, _fresh()[0])).status_code == 202
        r = await _start(client, _fresh()[0])
        assert r.status_code == 429
        assert r.json()["error"]["code"] == "RATE_LIMITED"
        assert int(r.headers["retry-after"]) >= 1
    finally:
        async with app.state.session_factory() as s:
            await SettingsStore(s).set("otp.start_rate_per_ip_per_hour", 10, None)
            await s.commit()
