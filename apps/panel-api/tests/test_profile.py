import itertools
import uuid
from datetime import date
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from payamakyar.api import sessions
from payamakyar.core.national_id import is_valid_company_id, is_valid_national_code
from payamakyar.core.passwords import hash_password
from payamakyar.db.models import AuditEvent, Role, User, UserRole

pytestmark = pytest.mark.integration

_seq = itertools.count(1)
_HASH = hash_password("Str0ng!Passw0rd")
NC = "0499370899"
NC2 = "0010350829"
CO = "10380284790"


async def _make(
    app: FastAPI, kind: str = "person", roles: tuple[str, ...] = (), **fields: Any
) -> tuple[User, httpx.AsyncClient]:
    n = next(_seq)
    async with app.state.session_factory() as s:
        user = User(
            username=f"prof_{n}_{uuid.uuid4().hex[:6]}",
            mobile=f"98938{n:03d}{uuid.uuid4().int % 10**4:04d}",
            password_hash=_HASH,
            kind=kind,
            **fields,
        )
        s.add(user)
        await s.flush()
        for name in roles:
            rid = (await s.execute(select(Role.id).where(Role.name == name))).scalar_one()
            s.add(UserRole(user_id=user.id, role_id=rid))
        token, csrf = await sessions.create(s, user, None, None)
        await s.commit()
        await s.refresh(user)
    cfg = app.state.settings
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={cfg.session_cookie_name: token, cfg.csrf_cookie_name: csrf},
        headers={"X-CSRF-Token": csrf},
    )
    return user, client


PERSON: dict[str, Any] = {
    "first_name": "علی",
    "last_name": "رضایی",
    "national_code": NC,
    "birth_date": "1990-05-17",
    "email": "Ali@Example.COM",
    "phone": "02112345678",
    "postal_code": "1234567890",
    "address": "تهران، خیابان آزادی",
}
COMPANY: dict[str, Any] = {
    "company_name": "شرکت نمونه",
    "company_national_id": CO,
    "economic_code": "411111111111",
    "ceo_name": "رضا احمدی",
    "ceo_national_code": NC2,
    "postal_code": "1234567890",
    "address": "تهران",
}


def test_fixture_values_valid() -> None:
    assert is_valid_national_code(NC) and is_valid_national_code(NC2)
    assert is_valid_company_id(CO)


async def test_me_fresh_user(app: FastAPI) -> None:
    user, c = await _make(app)
    async with c:
        r = await c.get("/panel/web/v1/account/me")
    assert r.status_code == 200
    b = r.json()
    assert b["id"] == str(user.id) and b["kind"] == "person"
    assert b["gates"] == {
        "registered": True,
        "profile_complete": False,
        "identity_matched": False,
        "documents_approved": False,
    }
    assert b["capabilities"] == {
        "can_send": False,
        "can_buy_line": False,
        "can_use_service_line_and_links": False,
    }
    assert b["roles"] == [] and b["permissions"] == []
    assert "password_hash" not in b and "totp_secret_sealed" not in b


async def test_me_requires_auth(client: httpx.AsyncClient) -> None:
    r = await client.get("/panel/web/v1/account/me")
    assert r.status_code == 401


async def test_me_roles_and_permissions(app: FastAPI) -> None:
    _, c = await _make(app, roles=("admin",), mfa_method="totp")
    async with c:
        b = (await c.get("/panel/web/v1/account/me")).json()
    assert b["roles"] == ["admin"] and "audit.view" in b["permissions"]


async def test_person_profile_completes_and_flips_gates(app: FastAPI) -> None:
    _, c = await _make(app)
    async with c:
        r = await c.put("/panel/web/v1/account/profile", json=PERSON)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["email"] == "ali@example.com"
        assert b["gates"]["profile_complete"] is True
        assert b["capabilities"]["can_buy_line"] is False  # identity not matched yet
        me = (await c.get("/panel/web/v1/account/me")).json()
    assert me["gates"]["profile_complete"] is True
    assert me["birth_date"] == "1990-05-17" and me["national_code"] == NC


async def test_can_buy_line_when_identity_matched(app: FastAPI) -> None:
    stored = {**PERSON, "email": "a@b.co", "birth_date": date(1990, 5, 17)}
    _, c = await _make(app, identity_state="matched", documents_state="approved", **stored)
    async with c:
        b = (await c.put("/panel/web/v1/account/profile", json={"first_name": "علی"})).json()
    assert b["capabilities"] == {
        "can_send": True,
        "can_buy_line": True,
        "can_use_service_line_and_links": True,
    }


async def test_company_profile(app: FastAPI) -> None:
    _, c = await _make(app, kind="company")
    async with c:
        r = await c.put("/panel/web/v1/account/profile", json=COMPANY)
    assert r.status_code == 200, r.text
    assert r.json()["gates"]["profile_complete"] is True


async def test_partial_update_keeps_incomplete(app: FastAPI) -> None:
    _, c = await _make(app)
    async with c:
        r = await c.put("/panel/web/v1/account/profile", json={"first_name": "علی"})
    b = r.json()
    assert r.status_code == 200 and b["first_name"] == "علی"
    assert b["gates"]["profile_complete"] is False and b["last_name"] is None


@pytest.mark.parametrize(
    ("kind", "field", "value"),
    [
        ("person", "national_code", "0499370898"),
        ("person", "national_code", "1111111111"),
        ("person", "birth_date", "1369/02/27"),
        ("person", "birth_date", "2999-01-01"),
        ("person", "birth_date", "1990-13-40"),
        ("person", "postal_code", "12345"),
        ("person", "email", "not-an-email"),
        ("person", "phone", "abc"),
        ("person", "company_name", "x"),
        ("person", "bogus", "x"),
        ("company", "company_national_id", "10380284791"),
        ("company", "ceo_national_code", "0499370898"),
        ("company", "first_name", "x"),
    ],
)
async def test_invalid_fields_422(app: FastAPI, kind: str, field: str, value: str) -> None:
    _, c = await _make(app, kind=kind)
    async with c:
        r = await c.put("/panel/web/v1/account/profile", json={field: value})
    assert r.status_code == 422, r.text
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_FAILED" and err["detail"]
    assert err["source"]["pointer"] == f"/{field}"


async def test_persian_digits_normalised(app: FastAPI) -> None:
    _, c = await _make(app)
    async with c:
        r = await c.put(
            "/panel/web/v1/account/profile",
            json={
                "national_code": "۰۴۹۹۳۷۰۸۹۹",
                "postal_code": "۱۲۳۴۵۶۷۸۹۰",
                "phone": "۰۲۱۱۲۳۴۵۶۷۸",
                "birth_date": "۱۹۹۰-۰۵-۱۷",
            },
        )
    b = r.json()
    assert r.status_code == 200, r.text
    assert b["national_code"] == NC and b["postal_code"] == "1234567890"
    assert b["phone"] == "02112345678" and b["birth_date"] == "1990-05-17"


async def test_identity_reset_on_national_code_or_birth_date(app: FastAPI) -> None:
    user, c = await _make(app, identity_state="matched", national_code=NC, birth_date=None)
    async with c:
        # same value: no reset
        r = await c.put("/panel/web/v1/account/profile", json={"national_code": NC})
        assert r.status_code == 200
        assert (await c.get("/panel/web/v1/account/me")).json()["identity_state"] == "matched"
        r = await c.put("/panel/web/v1/account/profile", json={"first_name": "علی"})
        assert r.status_code == 200
        assert (await c.get("/panel/web/v1/account/me")).json()["identity_state"] == "matched"
        r = await c.put("/panel/web/v1/account/profile", json={"birth_date": "1990-05-17"})
        assert r.json()["identity_state"] == "none"
        async with app.state.session_factory() as s:
            u = await s.get(User, user.id)
            assert u is not None
            u.identity_state = "matched"
            await s.commit()
        r = await c.put("/panel/web/v1/account/profile", json={"national_code": NC2})
        assert r.json()["identity_state"] == "none"
        assert r.json()["gates"]["identity_matched"] is False


async def test_audit_has_changed_fields_only_and_masks_ids(app: FastAPI) -> None:
    user, c = await _make(app, national_code=NC, first_name="علی")
    async with c:
        r = await c.put(
            "/panel/web/v1/account/profile",
            json={"first_name": "علی", "national_code": NC2, "last_name": "رضایی"},
        )
    assert r.status_code == 200
    async with app.state.session_factory() as s:
        rows = (
            (await s.execute(select(AuditEvent).where(AuditEvent.action == "user.profile_update")))
            .scalars()
            .all()
        )
    mine = [e for e in rows if e.actor_id == user.id]
    assert len(mine) == 1
    e = mine[0]
    assert e.target_type == "user" and e.target_id == str(user.id)
    assert e.before is not None and e.after is not None
    assert set(e.after) >= {"national_code", "last_name"} and "first_name" not in e.after
    assert set(e.before) == set(e.after)
    blob = str(e.before) + str(e.after)
    assert NC not in blob and NC2 not in blob
    assert e.after["national_code"].endswith(NC2[-4:])


async def test_noop_update_writes_no_audit(app: FastAPI) -> None:
    user, c = await _make(app, first_name="علی")
    async with c:
        r = await c.put("/panel/web/v1/account/profile", json={"first_name": "علی"})
    assert r.status_code == 200
    async with app.state.session_factory() as s:
        rows = (
            (await s.execute(select(AuditEvent).where(AuditEvent.actor_id == user.id)))
            .scalars()
            .all()
        )
    assert rows == []


async def test_profile_requires_csrf(app: FastAPI) -> None:
    _, c = await _make(app)
    async with c:
        c.headers.pop("X-CSRF-Token")
        r = await c.put("/panel/web/v1/account/profile", json={"first_name": "x"})
    assert r.status_code == 403


@pytest.mark.parametrize("field", ["ceo_national_code", "company_national_id"])
async def test_company_identity_reset(app: FastAPI, field: str) -> None:
    _, c = await _make(app, kind="company", identity_state="matched", **COMPANY)
    new = {"ceo_national_code": NC, "company_national_id": "10380284790"}[field]
    if field == "company_national_id":
        new = "14003778990"
        assert is_valid_company_id(new)
    async with c:
        r = await c.put("/panel/web/v1/account/profile", json={field: new})
    assert r.status_code == 200, r.text
    assert r.json()["identity_state"] == "none"


@pytest.mark.parametrize("value", [None, ""])
async def test_clearing_national_code_resets_identity(app: FastAPI, value: str | None) -> None:
    _, c = await _make(app, identity_state="matched", national_code=NC)
    async with c:
        r = await c.put("/panel/web/v1/account/profile", json={"national_code": value})
    assert r.status_code == 200, r.text
    assert r.json()["identity_state"] == "none" and r.json()["national_code"] is None
