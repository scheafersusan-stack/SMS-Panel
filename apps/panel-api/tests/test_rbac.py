import itertools
import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from payamakyar.api import sessions
from payamakyar.api.deps import require
from payamakyar.core.passwords import hash_password
from payamakyar.core.permissions import (
    CUSTOMER_SIDE_CODES,
    PERMISSIONS,
    SYSTEM_ROLES,
    permission_codes,
)
from payamakyar.db.models import AuditEvent, Permission, Role, RolePermission, User, UserRole

pytestmark = pytest.mark.integration

ROLES = "/panel/admin/v1/roles"
PERMS = "/panel/admin/v1/permissions"
_seq = itertools.count(1)
_HASH = hash_password("Str0ng!Passw0rd")


async def _make(
    app: FastAPI, roles: list[str], mfa: str = "totp"
) -> tuple[User, httpx.AsyncClient]:
    n = next(_seq)
    async with app.state.session_factory() as s:
        user = User(
            username=f"rbac_{n}_{uuid.uuid4().hex[:6]}",
            mobile=f"98939{n:03d}{uuid.uuid4().int % 10**4:04d}",
            password_hash=_HASH,
            mfa_method=mfa,
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
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies={cfg.session_cookie_name: token, cfg.csrf_cookie_name: csrf},
        headers={"X-CSRF-Token": csrf},
    )
    return user, client


async def _role_names(app: FastAPI, user_id: uuid.UUID) -> set[str]:
    async with app.state.session_factory() as s:
        rows = await s.execute(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )
        return set(rows.scalars())


async def _audit(app: FastAPI, action: str) -> list[AuditEvent]:
    async with app.state.session_factory() as s:
        rows = await s.execute(
            select(AuditEvent).where(AuditEvent.action == action).order_by(AuditEvent.id)
        )
        return list(rows.scalars())


def _err(r: httpx.Response) -> str:
    code: str = r.json()["error"]["code"]
    return code


async def test_seed_matches_core(app: FastAPI) -> None:
    async with app.state.session_factory() as s:
        db_codes = set((await s.execute(select(Permission.code))).scalars())
        assert db_codes == permission_codes()
        titles = (await s.execute(select(Permission.title_fa, Permission.group))).all()
        assert all(t and g for t, g in titles)
        by_code = {p.code: (p.title_fa, p.group) for p in PERMISSIONS}
        rows = (await s.execute(select(Permission))).scalars().all()
        assert {p.code: (p.title_fa, p.group) for p in rows} == by_code
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}
        assert set(SYSTEM_ROLES) <= set(roles)
        for name, spec in SYSTEM_ROLES.items():
            got = set(
                (
                    await s.execute(
                        select(RolePermission.permission_code).where(
                            RolePermission.role_id == roles[name].id
                        )
                    )
                ).scalars()
            )
            assert got == set(spec.permissions), name
            assert roles[name].title_fa
            assert roles[name].is_staff == spec.is_staff


def test_catalog_shape() -> None:
    codes = [p.code for p in PERMISSIONS]
    assert len(codes) == len(set(codes)) == 29 + 11
    assert "roles.manage" in codes
    assert "resellers.subusers" in CUSTOMER_SIDE_CODES
    assert set(SYSTEM_ROLES) == {
        "customer",
        "reseller",
        "staff_moderation",
        "staff_finance",
        "staff_support",
        "admin",
    }
    assert set(SYSTEM_ROLES["admin"].permissions) == set(codes)
    assert set(SYSTEM_ROLES["customer"].permissions) == CUSTOMER_SIDE_CODES - {"resellers.subusers"}
    assert set(SYSTEM_ROLES["reseller"].permissions) == CUSTOMER_SIDE_CODES
    assert set(SYSTEM_ROLES["staff_finance"].permissions) == {
        "users.view",
        "users.credit.adjust",
        "finance.view",
        "finance.receipts.approve",
        "finance.refund",
        "pricing.manage",
        "audit.view",
    }


async def test_customer_forbidden_on_admin_routes(app: FastAPI) -> None:
    _, c = await _make(app, ["customer"], mfa="none")
    r = await c.get(ROLES)
    assert r.status_code == 403
    assert _err(r) == "FORBIDDEN"
    _, c2 = await _make(app, ["customer"], mfa="totp")
    assert _err(await c2.get(PERMS)) == "FORBIDDEN"


async def test_unauthenticated_admin_is_401(client: httpx.AsyncClient) -> None:
    assert (await client.get(ROLES)).status_code == 401


async def test_admin_without_mfa_gets_mfa_required(app: FastAPI) -> None:
    _, c = await _make(app, ["admin"], mfa="none")
    r = await c.get(ROLES)
    assert r.status_code == 403
    assert _err(r) == "MFA_REQUIRED"
    assert (await c.post(ROLES, json={})).status_code == 403


async def test_staff_missing_permission_forbidden(app: FastAPI) -> None:
    _, c = await _make(app, ["staff_support"])
    r = await c.get(ROLES)
    assert r.status_code == 403
    assert _err(r) == "FORBIDDEN"


async def test_require_dependency(app: FastAPI) -> None:
    @app.get("/panel/web/v1/_t/needs-audit", dependencies=[require("audit.view")])
    async def needs() -> dict[str, bool]:
        return {"ok": True}

    _, finance = await _make(app, ["staff_finance"])
    _, support = await _make(app, ["staff_support"])
    url = "/panel/web/v1/_t/needs-audit"
    assert (await finance.get(url)).status_code == 200
    r = await support.get(url)
    assert r.status_code == 403 and _err(r) == "FORBIDDEN"


async def test_every_admin_route_is_behind_the_gate(app: FastAPI) -> None:
    """Probe every documented admin operation with a customer: the router gate answers first."""
    _, customer = await _make(app, ["customer"])
    _, staff_nomfa = await _make(app, ["staff_support"], mfa="none")
    probed = 0
    for path, ops in app.openapi()["paths"].items():
        if not path.startswith("/panel/admin/v1"):
            continue
        url = path.replace("{role_id}", str(uuid.uuid4())).replace("{user_id}", str(uuid.uuid4()))
        for method in ops:
            r = await customer.request(method, url)
            assert (r.status_code, _err(r)) == (403, "FORBIDDEN"), (method, path)
            r = await staff_nomfa.request(method, url)
            assert (r.status_code, _err(r)) == (403, "MFA_REQUIRED"), (method, path)
            probed += 1
    assert probed >= 6


async def test_list_permissions_and_roles(app: FastAPI) -> None:
    _, c = await _make(app, ["admin"])
    r = await c.get(PERMS)
    assert r.status_code == 200
    items = r.json()["items"]
    assert {i["code"] for i in items} == permission_codes()
    assert all(i["title_fa"] and i["group"] for i in items)
    r = await c.get(ROLES)
    assert r.status_code == 200
    roles = {i["code"]: i for i in r.json()["items"]}
    assert set(SYSTEM_ROLES) <= set(roles)
    assert roles["admin"]["is_system"] is True
    assert set(roles["staff_support"]["permissions"]) == set(
        SYSTEM_ROLES["staff_support"].permissions
    )


async def test_role_crud_with_audit(app: FastAPI) -> None:
    admin, c = await _make(app, ["admin"])
    body: dict[str, Any] = {
        "code": "staff_kyc_lite",
        "title_fa": "کارشناس احراز",
        "is_staff": True,
        "permissions": ["users.view", "kyc.review"],
    }
    r = await c.post(ROLES, json=body)
    assert r.status_code == 201, r.text
    role = r.json()
    assert role["code"] == "staff_kyc_lite" and role["is_system"] is False
    assert set(role["permissions"]) == {"users.view", "kyc.review"}
    created = (await _audit(app, "role.create"))[-1]
    assert created.before is None
    assert created.after == {
        "code": "staff_kyc_lite",
        "title_fa": "کارشناس احراز",
        "is_staff": True,
        "permissions": ["kyc.review", "users.view"],
    }
    assert created.actor_id == admin.id and created.target_id == role["id"]

    r = await c.put(
        f"{ROLES}/{role['id']}",
        json={"title_fa": "کارشناس احراز ۲", "is_staff": True, "permissions": ["users.view"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["permissions"] == ["users.view"]
    upd = (await _audit(app, "role.update"))[-1]
    assert upd.before is not None and upd.after is not None
    assert upd.before["permissions"] == ["kyc.review", "users.view"]
    assert upd.before["title_fa"] == "کارشناس احراز"
    assert upd.after["permissions"] == ["users.view"]
    assert upd.after["title_fa"] == "کارشناس احراز ۲"

    r = await c.delete(f"{ROLES}/{role['id']}")
    assert r.status_code == 204
    dele = (await _audit(app, "role.delete"))[-1]
    assert dele.after is None and dele.before is not None
    assert dele.before["code"] == "staff_kyc_lite"
    assert (await c.delete(f"{ROLES}/{role['id']}")).status_code == 404


async def test_role_create_validation(app: FastAPI) -> None:
    _, c = await _make(app, ["admin"])
    ok = {"code": "valid_one", "title_fa": "نقش", "permissions": ["users.view"]}
    for bad_code in ("Ab", "ab", "1abc", "has-dash", "UPPER", "a" * 33, "نقش_ی"):
        r = await c.post(ROLES, json={**ok, "code": bad_code})
        assert r.status_code == 422, bad_code
        assert r.json()["error"]["source"]["pointer"] == "/code"
    r = await c.post(ROLES, json={**ok, "permissions": ["users.view", "nope.x"]})
    assert r.status_code == 422
    assert _err(r) == "VALIDATION_FAILED"
    assert r.json()["error"]["source"]["pointer"] == "/permissions/1"
    assert (await c.post(ROLES, json=ok)).status_code == 201
    r = await c.post(ROLES, json=ok)
    assert r.status_code == 409 and _err(r) == "ROLE_CODE_TAKEN"
    r = await c.post(ROLES, json={**ok, "code": "admin"})
    assert r.status_code == 409 and _err(r) == "ROLE_CODE_TAKEN"


async def test_system_roles_protected(app: FastAPI) -> None:
    _, c = await _make(app, ["admin"])
    roles = {i["code"]: i for i in (await c.get(ROLES)).json()["items"]}
    for code in SYSTEM_ROLES:
        r = await c.delete(f"{ROLES}/{roles[code]['id']}")
        assert r.status_code == 409 and _err(r) == "ROLE_IS_SYSTEM", code
    admin = roles["admin"]
    reduced = [p for p in admin["permissions"] if p != "settings.manage"]
    r = await c.put(
        f"{ROLES}/{admin['id']}",
        json={"title_fa": admin["title_fa"], "is_staff": True, "permissions": reduced},
    )
    assert r.status_code == 409 and _err(r) == "ADMIN_ROLE_PROTECTED"
    # other system roles may be tuned; admin keeps the full set and may be retitled
    r = await c.put(
        f"{ROLES}/{admin['id']}",
        json={
            "title_fa": "مدیر کل",
            "is_staff": True,
            "permissions": admin["permissions"],
        },
    )
    assert r.status_code == 200 and r.json()["title_fa"] == "مدیر کل"


async def test_role_in_use_cannot_be_deleted(app: FastAPI) -> None:
    _, c = await _make(app, ["admin"])
    r = await c.post(
        ROLES, json={"code": "temp_role", "title_fa": "موقت", "permissions": ["users.view"]}
    )
    rid = r.json()["id"]
    target, _ = await _make(app, ["customer"])
    r = await c.put(f"/panel/admin/v1/users/{target.id}/roles", json={"roles": ["temp_role"]})
    assert r.status_code == 200, r.text
    r = await c.delete(f"{ROLES}/{rid}")
    assert r.status_code == 409 and _err(r) == "ROLE_IN_USE"


async def test_assign_user_roles_with_audit(app: FastAPI) -> None:
    admin, c = await _make(app, ["admin"])
    target, _ = await _make(app, ["customer"])
    url = f"/panel/admin/v1/users/{target.id}/roles"
    r = await c.put(url, json={"roles": ["customer", "staff_support"]})
    assert r.status_code == 200, r.text
    assert set(r.json()["roles"]) == {"customer", "staff_support"}
    assert await _role_names(app, target.id) == {"customer", "staff_support"}
    ev = (await _audit(app, "user.roles.update"))[-1]
    assert ev.before == {"roles": ["customer"]}
    assert ev.after == {"roles": ["customer", "staff_support"]}
    assert ev.actor_id == admin.id and ev.target_id == str(target.id)
    r = await c.put(url, json={"roles": ["customer", "ghost"]})
    assert r.status_code == 422 and r.json()["error"]["source"]["pointer"] == "/roles/1"
    r = await c.put(f"/panel/admin/v1/users/{uuid.uuid4()}/roles", json={"roles": []})
    assert r.status_code == 404
    r = await c.put(url, json={"roles": []})
    assert r.status_code == 200 and r.json()["roles"] == []


async def test_self_lockout_prevented(app: FastAPI) -> None:
    # two admins so the last-admin rule does not mask the self-lockout rule
    me, c = await _make(app, ["admin"])
    await _make(app, ["admin"])
    url = f"/panel/admin/v1/users/{me.id}/roles"
    r = await c.put(url, json={"roles": ["staff_support"]})
    assert r.status_code == 409 and _err(r) == "WOULD_LOCK_YOU_OUT"
    assert await _role_names(app, me.id) == {"admin"}
    # keeping roles.manage through another role is fine
    r = await c.post(
        ROLES,
        json={"code": "role_managers", "title_fa": "مدیر نقش", "permissions": ["roles.manage"]},
    )
    assert r.status_code == 201
    r = await c.put(url, json={"roles": ["role_managers"]})
    assert r.status_code == 200, r.text


async def test_last_admin_cannot_lose_admin(app: FastAPI) -> None:
    async with app.state.session_factory() as s:
        admin_rid = (await s.execute(select(Role.id).where(Role.name == "admin"))).scalar_one()
        await s.execute(UserRole.__table__.delete().where(UserRole.role_id == admin_rid))  # type: ignore[attr-defined]
        await s.commit()
    me, c = await _make(app, ["admin"])
    # a delegate with roles.manage but not admin tries to strip the only admin
    r = await c.post(
        ROLES,
        json={"code": "role_managers2", "title_fa": "مدیر نقش", "permissions": ["roles.manage"]},
    )
    assert r.status_code == 201
    _mgr, mc = await _make(app, ["role_managers2"])
    r = await mc.put(f"/panel/admin/v1/users/{me.id}/roles", json={"roles": ["customer"]})
    assert r.status_code == 409 and _err(r) == "LAST_ADMIN_REQUIRED"
    assert await _role_names(app, me.id) == {"admin"}
    # with a second admin it works
    other, _ = await _make(app, ["admin"])
    r = await mc.put(f"/panel/admin/v1/users/{me.id}/roles", json={"roles": ["customer"]})
    assert r.status_code == 200
    assert await _role_names(app, other.id) == {"admin"}
