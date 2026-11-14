import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from payamakyar.api.deps import SessionDep
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
