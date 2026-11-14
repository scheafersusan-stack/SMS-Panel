import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from payamakyar.api.errors import ApiError

pytestmark = pytest.mark.integration


class Body(BaseModel):
    mobile: str


def _routes(app: FastAPI) -> None:
    @app.post("/panel/web/v1/_t/echo")
    async def echo(body: Body) -> dict[str, str]:
        return {"mobile": body.mobile}

    @app.get("/panel/web/v1/_t/api")
    async def api() -> None:
        raise ApiError(409, "TAKEN", "t", "d", pointer="/x")

    @app.get("/panel/web/v1/_t/boom")
    async def boom() -> None:
        raise RuntimeError("secret 09123456789 failure")

    @app.get("/panel/web/v1/_t/only-get")
    async def only_get() -> None:
        return None


CSRF = {"X-CSRF-Token": "tok"}


def _keys(r: httpx.Response) -> set[str]:
    return set(r.json()["error"])


async def test_unknown_route_envelope(client: httpx.AsyncClient) -> None:
    r = await client.get("/panel/nope")
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "NOT_FOUND"
    assert set(err) == {"code", "title", "detail", "source"}
    assert err["source"] is None


async def test_method_not_allowed(app: FastAPI, client: httpx.AsyncClient) -> None:
    _routes(app)
    r = await client.get("/panel/web/v1/_t/echo")
    assert r.status_code == 405
    assert r.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


async def test_validation_pointer(app: FastAPI, client: httpx.AsyncClient) -> None:
    _routes(app)
    client.cookies.set("pk_csrf", "tok")
    r = await client.post("/panel/web/v1/_t/echo", json={"nomobile": 1}, headers=CSRF)
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_FAILED"
    assert err["source"] == {"pointer": "/mobile"}


async def test_api_error(app: FastAPI, client: httpx.AsyncClient) -> None:
    _routes(app)
    r = await client.get("/panel/web/v1/_t/api")
    assert r.status_code == 409
    assert r.json()["error"] == {
        "code": "TAKEN",
        "title": "t",
        "detail": "d",
        "source": {"pointer": "/x"},
    }


async def test_unhandled_is_500_without_stack(
    app: FastAPI, client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    _routes(app)
    r = await client.get("/panel/web/v1/_t/boom")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL"
    assert "Traceback" not in r.text and "RuntimeError" not in r.text
    rid = r.headers["X-Request-Id"]
    records = [x for x in caplog.records if x.getMessage() == "unhandled exception"]
    assert len(records) == 1
    assert getattr(records[0], "request_id", None) == rid
    from payamakyar.core.logging import JsonFormatter, RedactFilter

    flt = RedactFilter()
    flt.filter(records[0])
    assert "09123456789" not in JsonFormatter().format(records[0])


async def test_csrf_missing_is_403(app: FastAPI, client: httpx.AsyncClient) -> None:
    _routes(app)
    r = await client.post("/panel/web/v1/_t/echo", json={"mobile": "1"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "CSRF_FAILED"


async def test_csrf_mismatch_and_match(app: FastAPI, client: httpx.AsyncClient) -> None:
    _routes(app)
    client.cookies.set("pk_csrf", "tok")
    bad = await client.post(
        "/panel/web/v1/_t/echo", json={"mobile": "1"}, headers={"X-CSRF-Token": "other"}
    )
    assert bad.status_code == 403
    good = await client.post("/panel/web/v1/_t/echo", json={"mobile": "1"}, headers=CSRF)
    assert good.status_code == 200


async def test_csrf_admin_prefix_and_exemptions(app: FastAPI, client: httpx.AsyncClient) -> None:
    for prefix in ("/panel/web/v1", "/panel/admin/v1"):
        r = await client.post(f"{prefix}/other")
        assert r.status_code == 403
        for exempt in ("auth/login", "auth/register/start", "auth/reset/confirm"):
            r = await client.post(f"{prefix}/{exempt}")
            # Past CSRF: 422 where the route exists (empty body), 404 where it does not yet.
            assert r.status_code == (
                422 if (prefix, exempt) == ("/panel/web/v1", "auth/register/start") else 404
            )
        r = await client.post(f"{prefix}/auth/login/extra")
        assert r.status_code == 403
        r = await client.post(f"{prefix}/auth/register")
        assert r.status_code == 403
    assert (await client.post("/panel/health")).status_code == 405  # outside CSRF scope
