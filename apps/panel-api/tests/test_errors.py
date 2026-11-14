import uuid
from typing import Literal

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field, field_validator

from payamakyar.api.errors import ApiError, persian_validation_message, validation_pointer

pytestmark = pytest.mark.integration


class Body(BaseModel):
    mobile: str


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=3, max_length=5)
    kind: Literal["a", "b"] = "a"
    tags: list[str] = Field(default_factory=list, max_length=2)
    ref: uuid.UUID | None = None
    note: str | None = None

    @field_validator("note")
    @classmethod
    def _note(cls, v: str | None) -> str | None:
        if v == "fa":
            raise ValueError("یادداشت نامعتبر است.")
        if v == "en":
            raise ValueError("bad note")
        return v


def _routes(app: FastAPI) -> None:
    @app.post("/panel/web/v1/_t/echo")
    async def echo(body: Body) -> dict[str, str]:
        return {"mobile": body.mobile}

    @app.post("/panel/web/v1/_t/strict")
    async def strict(body: Strict) -> None:
        return None

    @app.get("/panel/web/v1/_t/q")
    async def query(page: int, flag: bool = False) -> None:
        return None

    @app.get("/panel/web/v1/_t/item/{item_id}")
    async def item(item_id: uuid.UUID) -> None:
        return None

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
    assert err["detail"] == "این فیلد الزامی است."


@pytest.mark.parametrize(
    ("body", "pointer", "detail"),
    [
        ({"name": "ab"}, "/name", "دست‌کم ۳ نویسه وارد کنید."),
        ({"name": "abcdefgh"}, "/name", "حداکثر ۵ نویسه مجاز است."),
        ({"name": "abc", "kind": "z"}, "/kind", "مقدار انتخاب‌شده مجاز نیست."),
        ({"name": "abc", "tags": ["1", "2", "3"]}, "/tags", "حداکثر ۲ مورد مجاز است."),
        ({"name": "abc", "ref": "nope"}, "/ref", "شناسه معتبر نیست."),
        ({"name": "abc", "extra": 1}, "/extra", "این فیلد مجاز نیست."),
        ({"name": "abc", "note": "fa"}, "/note", "یادداشت نامعتبر است."),
        ({"name": "abc", "note": "en"}, "/note", "مقدار واردشده معتبر نیست."),
        ({"name": 5}, "/name", "مقدار واردشده معتبر نیست."),
        ([1, 2], None, "مقدار واردشده معتبر نیست."),
    ],
)
async def test_validation_in_persian(
    app: FastAPI,
    client: httpx.AsyncClient,
    body: object,
    pointer: str | None,
    detail: str,
) -> None:
    _routes(app)
    client.cookies.set("pk_csrf", "tok")
    r = await client.post("/panel/web/v1/_t/strict", json=body, headers=CSRF)
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_FAILED"
    assert err["detail"] == detail
    assert err["source"] == ({"pointer": pointer} if pointer else None)


async def test_invalid_json_has_no_pointer(app: FastAPI, client: httpx.AsyncClient) -> None:
    _routes(app)
    client.cookies.set("pk_csrf", "tok")
    r = await client.post(
        "/panel/web/v1/_t/strict",
        content=b'{"name": ',
        headers={**CSRF, "Content-Type": "application/json"},
    )
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["detail"] == "بدنهٔ درخواست JSON معتبر نیست."
    assert err["source"] is None


async def test_query_and_path_pointers(app: FastAPI, client: httpx.AsyncClient) -> None:
    _routes(app)
    r = await client.get("/panel/web/v1/_t/q", params={"page": "x"})
    err = r.json()["error"]
    assert (r.status_code, err["source"], err["detail"]) == (
        422,
        {"pointer": "/page"},
        "یک عدد صحیح وارد کنید.",
    )
    r = await client.get("/panel/web/v1/_t/q", params={"page": "1", "flag": "maybe"})
    assert r.json()["error"]["source"] == {"pointer": "/flag"}
    assert r.json()["error"]["detail"] == "مقدار باید درست یا نادرست باشد."
    r = await client.get("/panel/web/v1/_t/q")
    assert r.json()["error"]["source"] == {"pointer": "/page"}
    r = await client.get("/panel/web/v1/_t/item/nope")
    assert r.json()["error"]["source"] == {"pointer": "/item_id"}


def test_message_mapping_units() -> None:
    assert persian_validation_message({"type": "string_too_short", "ctx": {"min_length": 1}}) == (
        "این فیلد نباید خالی باشد."
    )
    assert persian_validation_message({"type": "too_short", "ctx": {"min_length": 12}}) == (
        "دست‌کم ۱۲ مورد لازم است."
    )
    assert persian_validation_message({"type": "enum", "ctx": {}}) == "مقدار انتخاب‌شده مجاز نیست."
    assert persian_validation_message({"type": "who_knows"}) == "مقدار واردشده معتبر نیست."
    assert validation_pointer(("body",)) is None
    assert validation_pointer(("body", 7)) is None
    assert validation_pointer(("body", "a", 0, "b/c")) == "/a/0/b~1c"
    assert validation_pointer(("query", "page")) == "/page"
    assert validation_pointer(("path", "id")) == "/id"
    assert validation_pointer(()) is None


async def test_generic_401_code(app: FastAPI, client: httpx.AsyncClient) -> None:
    from starlette.exceptions import HTTPException

    @app.get("/panel/web/v1/_t/401")
    async def unauth() -> None:
        raise HTTPException(401)

    r = await client.get("/panel/web/v1/_t/401")
    assert r.json()["error"]["code"] == "NOT_AUTHENTICATED"


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
        for exempt in (
            "auth/login",
            "auth/register/start",
            "auth/reset/confirm",
            "auth/mfa/confirm",
            "auth/mfa/sms/send",
        ):
            r = await client.post(f"{prefix}/{exempt}")
            # Past CSRF: 422 where the route exists (empty body), 404 where it does not yet.
            web_routes = (
                "auth/login",
                "auth/register/start",
                "auth/mfa/confirm",
                "auth/mfa/sms/send",
            )
            exists = prefix == "/panel/web/v1" and exempt in web_routes
            assert r.status_code == (422 if exists else 404)
        r = await client.post(f"{prefix}/auth/logout")
        assert r.status_code == 403
        r = await client.post(f"{prefix}/auth/mfa")
        assert r.status_code == 403
        r = await client.post(f"{prefix}/auth/login/extra")
        assert r.status_code == 403
        r = await client.post(f"{prefix}/auth/register")
        assert r.status_code == 403
    assert (await client.post("/panel/health")).status_code == 405  # outside CSRF scope
