from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from payamakyar.api import csrf
from payamakyar.api.deps import SessionDep, current_session
from payamakyar.api.errors import ApiError
from payamakyar.db.models import SystemMessage

pytestmark = pytest.mark.integration


def _add(app: FastAPI, path: str, tag: str, mode: str) -> None:
    @app.get(path)
    async def route(session: SessionDep) -> dict[str, bool]:
        session.add(SystemMessage(to_mobile="09121234567", template_key=tag, body="x"))
        await session.flush()
        if mode == "api":
            raise ApiError(409, "X", "t")
        if mode == "boom":
            raise RuntimeError("boom")
        if mode == "commit":

            async def bad() -> None:
                raise RuntimeError("commit failed")

            session.commit = bad  # type: ignore[method-assign]
        return {"ok": True}


async def _count(app: FastAPI, tag: str) -> int:
    async with app.state.session_factory() as s:
        rows = (
            await s.execute(select(SystemMessage).where(SystemMessage.template_key == tag))
        ).all()
        return len(rows)


async def test_commit_on_success(app: FastAPI, client: httpx.AsyncClient) -> None:
    _add(app, "/panel/web/v1/_t/ok", "dep_ok", "ok")
    assert (await client.get("/panel/web/v1/_t/ok")).status_code == 200
    assert await _count(app, "dep_ok") == 1


async def test_rollback_on_api_error_and_unhandled(app: FastAPI, client: httpx.AsyncClient) -> None:
    _add(app, "/panel/web/v1/_t/api", "dep_api", "api")
    _add(app, "/panel/web/v1/_t/boom", "dep_boom", "boom")
    assert (await client.get("/panel/web/v1/_t/api")).status_code == 409
    assert (await client.get("/panel/web/v1/_t/boom")).status_code == 500
    assert await _count(app, "dep_api") == 0
    assert await _count(app, "dep_boom") == 0


async def test_commit_failure_is_not_2xx(app: FastAPI, client: httpx.AsyncClient) -> None:
    _add(app, "/panel/web/v1/_t/commit", "dep_commit", "commit")
    r = await client.get("/panel/web/v1/_t/commit")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL"
    assert await _count(app, "dep_commit") == 0


# --- CSRF coverage ----------------------------------------------------------------------

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
# Unsafe routes outside the CSRF check (no session exists yet; see ``payamakyar.api.csrf``).
EXPECTED_EXEMPT = {
    ("POST", "/panel/web/v1/auth/login"),
    ("POST", "/panel/web/v1/auth/register/start"),
    ("POST", "/panel/web/v1/auth/register/complete"),
    ("POST", "/panel/web/v1/auth/mfa/sms/send"),
    ("POST", "/panel/web/v1/auth/mfa/confirm"),
    ("POST", "/panel/web/v1/auth/reset/start"),
    ("POST", "/panel/web/v1/auth/reset/complete"),
}


def _route_contexts(app: FastAPI) -> list[tuple[str, set[str], Any]]:
    """(path, methods, dependant) of every API route, nested routers included."""
    found: list[tuple[str, set[str], Any]] = []

    def walk(routes: Any, prefix: str = "") -> None:
        for r in routes:
            if hasattr(r, "effective_route_contexts"):
                found.extend(
                    (c.path, set(c.methods or ()), c.dependant)
                    for c in r.effective_route_contexts()
                )
            elif hasattr(r, "dependant"):
                found.append((prefix + r.path, set(r.methods or ()), r.dependant))
            elif hasattr(r, "routes"):
                walk(r.routes, prefix + getattr(r, "path", ""))

    walk(app.routes)
    return found


def _calls(dependant: Any) -> set[Any]:
    found = {dependant.call}
    for d in dependant.dependencies:
        found |= _calls(d)
    return found


def test_every_unsafe_route_is_csrf_bound_to_the_session(app: FastAPI) -> None:
    """Outside the exempt set, an unsafe route must depend on ``current_session`` (which binds
    the CSRF header to the session), not only pass the double-submit middleware."""
    exempt: set[tuple[str, str]] = set()
    checked = 0
    for path, methods, dependant in _route_contexts(app):
        for method in methods & UNSAFE:
            if not csrf.is_protected(method, path):
                exempt.add((method, path))
                continue
            checked += 1
            assert current_session in _calls(dependant), (method, path)
    assert checked >= 10
    assert exempt == EXPECTED_EXEMPT
