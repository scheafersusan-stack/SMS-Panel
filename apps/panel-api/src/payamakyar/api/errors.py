"""Error envelope: ``{"error": {"code", "title", "detail", "source"}}`` with a real status."""

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from payamakyar.core.masking import redact

_HTTP_CODES: dict[int, tuple[str, str]] = {
    400: ("BAD_REQUEST", "درخواست نامعتبر است"),
    401: ("UNAUTHENTICATED", "ورود لازم است"),
    403: ("FORBIDDEN", "دسترسی مجاز نیست"),
    404: ("NOT_FOUND", "یافت نشد"),
    405: ("METHOD_NOT_ALLOWED", "روش درخواست مجاز نیست"),
    409: ("CONFLICT", "تداخل در درخواست"),
}


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        title: str,
        detail: str = "",
        pointer: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(f"{status} {code}")
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.pointer = pointer
        self.headers = dict(headers or {})


def validation_failed(detail: str, pointer: str) -> ApiError:
    return ApiError(422, "VALIDATION_FAILED", "داده‌های ارسالی نامعتبر است", detail, pointer)


def error_response(
    status: int,
    code: str,
    title: str,
    detail: str = "",
    pointer: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "error": {
            "code": code,
            "title": title,
            "detail": detail,
            "source": {"pointer": pointer} if pointer is not None else None,
        }
    }
    return JSONResponse(body, status_code=status, headers=dict(headers or {}))


def internal_error_response() -> JSONResponse:
    return error_response(500, "INTERNAL", "خطای داخلی سرور", "خطایی رخ داد. دوباره تلاش کنید.")


def _pointer(loc: tuple[Any, ...]) -> str:
    parts = loc[1:] if loc and loc[0] == "body" else loc
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in parts)


async def _api_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiError):
        return internal_error_response()
    return error_response(exc.status, exc.code, exc.title, exc.detail, exc.pointer, exc.headers)


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        return internal_error_response()
    code, title = _HTTP_CODES.get(exc.status_code, ("HTTP_ERROR", "خطا"))
    detail = exc.detail if isinstance(exc.detail, str) and exc.status_code not in (404, 405) else ""
    return error_response(exc.status_code, code, title, str(redact(detail)), None, exc.headers)


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        return internal_error_response()
    errors = exc.errors()
    first = errors[0] if errors else {"loc": (), "msg": ""}
    return error_response(
        422,
        "VALIDATION_FAILED",
        "داده‌های ارسالی نامعتبر است",
        str(redact(str(first.get("msg", "")))),
        _pointer(tuple(first.get("loc", ()))),
    )


async def _unhandled(_: Request, __: Exception) -> JSONResponse:
    # Logging happens once, in the request-id middleware, which sees the exception first.
    return internal_error_response()


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled)
