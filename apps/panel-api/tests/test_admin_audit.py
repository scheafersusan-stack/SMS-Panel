import base64
import itertools
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, text

from payamakyar.api import sessions
from payamakyar.core.passwords import hash_password
from payamakyar.db import audit
from payamakyar.db.models import AuditEvent, LoginEvent, Role, User, UserRole

pytestmark = pytest.mark.integration

AUDIT = "/panel/admin/v1/audit"
LOGINS = "/panel/admin/v1/login-events"
_seq = itertools.count(1)
_HASH = hash_password("Str0ng!Passw0rd")


async def _make(
    app: FastAPI, roles: tuple[str, ...], mfa: str = "totp"
) -> tuple[User, httpx.AsyncClient]:
    n = next(_seq)
    async with app.state.session_factory() as s:
        user = User(
            username=f"aud_{n}_{uuid.uuid4().hex[:6]}",
            mobile=f"98937{n:03d}{uuid.uuid4().int % 10**4:04d}",
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
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={cfg.session_cookie_name: token, cfg.csrf_cookie_name: csrf},
        headers={"X-CSRF-Token": csrf},
    )
    return user, client


async def _seed(
    app: FastAPI, n: int, actor: uuid.UUID | None, action: str, tt: str = "thing"
) -> None:
    async with app.state.session_factory() as s:
        for i in range(n):
            await audit.record(
                s,
                actor_id=actor,
                actor_ip="1.2.3.4",
                action=action,
                target_type=tt,
                target_id=str(i),
            )
        await s.commit()


async def test_non_staff_forbidden(app: FastAPI) -> None:
    _, c = await _make(app, ())
    async with c:
        for url in (AUDIT, AUDIT + "/verify", LOGINS):
            r = await c.get(url)
            assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN", url


async def test_staff_without_mfa_gets_mfa_required(app: FastAPI) -> None:
    _, c = await _make(app, ("admin",), mfa="none")
    async with c:
        r = await c.get(AUDIT)
    assert r.json()["error"]["code"] == "MFA_REQUIRED"


async def test_staff_without_audit_view_forbidden(app: FastAPI) -> None:
    async with app.state.session_factory() as s:
        # a staff role lacking audit.view
        row = (
            await s.execute(
                text(
                    "SELECT r.name FROM roles r WHERE r.is_staff AND NOT EXISTS ("
                    "SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id "
                    "AND rp.permission_code = 'audit.view') LIMIT 1"
                )
            )
        ).scalar_one_or_none()
    if row is None:
        pytest.skip("every staff role holds audit.view")
    _, c = await _make(app, (row,))
    async with c:
        r = await c.get(AUDIT)
    assert r.status_code == 403


async def test_paging_and_cursor(app: FastAPI) -> None:
    _, c = await _make(app, ("admin",))
    marker = f"page.{uuid.uuid4().hex[:6]}"
    await _seed(app, 120, None, marker)
    async with c:
        seen: list[int] = []
        cursor: str | None = None
        pages = 0
        while True:
            params: dict[str, Any] = {"action": marker}
            if cursor:
                params["cursor"] = cursor
            r = await c.get(AUDIT, params=params)
            assert r.status_code == 200, r.text
            b = r.json()
            pages += 1
            assert len(b["items"]) <= 50
            seen += [i["id"] for i in b["items"]]
            cursor = b["next_cursor"]
            if cursor is None:
                break
    assert pages == 3 and len(seen) == 120
    assert seen == sorted(seen, reverse=True) and len(set(seen)) == 120
    item = b["items"][0]
    assert {"id", "at", "actor_id", "action", "target_type", "target_id", "before", "after"} <= set(
        item
    )
    assert "hash" not in item


async def test_exact_page_has_no_next_cursor(app: FastAPI) -> None:
    _, c = await _make(app, ("admin",))
    marker = f"exact.{uuid.uuid4().hex[:6]}"
    await _seed(app, 50, None, marker)
    async with c:
        b = (await c.get(AUDIT, params={"action": marker})).json()
    assert len(b["items"]) == 50 and b["next_cursor"] is None


async def test_filters(app: FastAPI) -> None:
    admin, c = await _make(app, ("admin",))
    other, _ = await _make(app, ())
    tag = uuid.uuid4().hex[:6]
    await _seed(app, 2, other.id, f"f.a.{tag}", "alpha")
    await _seed(app, 3, admin.id, f"f.b.{tag}", "beta")
    async with c:
        r = await c.get(AUDIT, params={"actor": str(other.id)})
        assert {i["action"] for i in r.json()["items"]} == {f"f.a.{tag}"}
        r = await c.get(AUDIT, params={"action": f"f.b.{tag}"})
        assert len(r.json()["items"]) == 3
        r = await c.get(AUDIT, params={"target_type": "alpha", "actor": str(other.id)})
        assert len(r.json()["items"]) == 2
        r = await c.get(AUDIT, params={"target_type": "beta", "action": f"f.a.{tag}"})
        assert r.json()["items"] == []


async def test_time_range_inclusive_from_exclusive_to(app: FastAPI) -> None:
    _, c = await _make(app, ("admin",))
    marker = f"t.{uuid.uuid4().hex[:6]}"
    await _seed(app, 3, None, marker)
    async with app.state.session_factory() as s:
        ids = list(
            (
                await s.execute(
                    select(AuditEvent.id).where(AuditEvent.action == marker).order_by(AuditEvent.id)
                )
            ).scalars()
        )
        ats = {
            r.id: r.at
            for r in (
                await s.execute(select(AuditEvent.id, AuditEvent.at).where(AuditEvent.id.in_(ids)))
            ).all()
        }
    async with c:
        mid = ats[ids[1]]
        r = await c.get(AUDIT, params={"action": marker, "from": mid.isoformat()})
        got = {i["id"] for i in r.json()["items"]}
        assert got == {ids[1], ids[2]}
        r = await c.get(AUDIT, params={"action": marker, "to": mid.isoformat()})
        got = {i["id"] for i in r.json()["items"]}
        assert ids[1] not in got and ids[0] in got
        far = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        r = await c.get(AUDIT, params={"action": marker, "from": far})
        assert r.json()["items"] == []


async def test_bad_params_422(app: FastAPI) -> None:
    _, c = await _make(app, ("admin",))
    async with c:
        r = await c.get(AUDIT, params={"cursor": "!!!"})
        assert r.status_code == 422 and r.json()["error"]["source"]["pointer"] == "/cursor"
        r = await c.get(AUDIT, params={"cursor": base64.urlsafe_b64encode(b"abc").decode()})
        assert r.status_code == 422
        r = await c.get(AUDIT, params={"from": "yesterday"})
        assert r.status_code == 422
        r = await c.get(AUDIT, params={"actor": "nope"})
        assert r.status_code == 422


async def test_verify_ok_and_detects_tamper(app: FastAPI) -> None:
    _, c = await _make(app, ("admin",))
    await _seed(app, 3, None, "v.x")
    async with c:
        r = await c.get(AUDIT + "/verify")
        assert r.status_code == 200 and r.json() == {"ok": True, "first_bad_id": None}
        async with app.state.session_factory() as s:
            await s.execute(text("ALTER TABLE audit_events DISABLE TRIGGER USER"))
            bad = (
                await s.execute(
                    text("SELECT id FROM audit_events ORDER BY id DESC LIMIT 1 OFFSET 1")
                )
            ).scalar_one()
            await s.execute(text("UPDATE audit_events SET reason='x' WHERE id=:i"), {"i": bad})
            await s.commit()
        try:
            r = await c.get(AUDIT + "/verify")
            assert r.json() == {"ok": False, "first_bad_id": bad}
        finally:
            async with app.state.session_factory() as s:
                await s.execute(text("UPDATE audit_events SET reason=NULL WHERE id=:i"), {"i": bad})
                await s.execute(text("ALTER TABLE audit_events ENABLE TRIGGER USER"))
                await s.commit()


async def test_login_events(app: FastAPI) -> None:
    _, c = await _make(app, ("admin",))
    u, _ = await _make(app, ())
    async with app.state.session_factory() as s:
        for i in range(55):
            s.add(
                LoginEvent(
                    user_id=u.id,
                    username_tried=u.username,
                    ip="9.9.9.9",
                    outcome="success" if i % 5 == 0 else "bad_password",
                )
            )
        await s.commit()
    async with c:
        b = (await c.get(LOGINS, params={"user_id": str(u.id)})).json()
        assert len(b["items"]) == 50 and b["next_cursor"]
        b2 = (await c.get(LOGINS, params={"user_id": str(u.id), "cursor": b["next_cursor"]})).json()
        assert len(b2["items"]) == 5 and b2["next_cursor"] is None
        ids = [i["id"] for i in b["items"] + b2["items"]]
        assert ids == sorted(ids, reverse=True)
        b3 = (await c.get(LOGINS, params={"user_id": str(u.id), "outcome": "success"})).json()
        assert len(b3["items"]) == 11
        assert {"id", "user_id", "username_tried", "ip", "outcome", "at", "user_agent"} <= set(
            b3["items"][0]
        )
        far = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        b4 = (await c.get(LOGINS, params={"user_id": str(u.id), "from": far})).json()
        assert b4["items"] == []
        r = await c.get(LOGINS, params={"cursor": "zzz"})
        assert r.status_code == 422
