"""Application factory."""

import logging
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from redis.asyncio import Redis
from starlette._utils import get_route_path

from payamakyar.api import csrf
from payamakyar.api.deps import admin_gate, parse_trusted_proxies
from payamakyar.api.errors import (
    error_response,
    install_error_handlers,
    internal_error_response,
)
from payamakyar.api.routes import account, admin_rbac, auth, health
from payamakyar.core.settings import PanelSettings, get_settings
from payamakyar.db.engine import create_engine, session_factory

log = logging.getLogger("payamakyar.api")
_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")

Handler = Callable[[Request], Awaitable[Response]]


def create_app(settings: PanelSettings | None = None) -> FastAPI:
    cfg = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(cfg.database_url)
        redis = Redis.from_url(cfg.redis_url)
        app.state.engine = engine
        app.state.session_factory = session_factory(engine)
        app.state.redis = redis
        try:
            yield
        finally:
            await redis.aclose()
            await engine.dispose()

    app = FastAPI(title="Payamakyar panel API", lifespan=lifespan)
    app.state.settings = cfg
    app.state.trusted_networks = parse_trusted_proxies(cfg.trusted_proxies)
    install_error_handlers(app)

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next: Handler) -> Response:
        if csrf.is_protected(request.method, get_route_path(request.scope)) and not csrf.csrf_ok(
            request, cfg.csrf_cookie_name
        ):
            return error_response(
                403, "CSRF_FAILED", "درخواست نامعتبر است", "توکن CSRF نامعتبر یا ناموجود است."
            )
        return await call_next(request)

    @app.middleware("http")
    async def request_id(request: Request, call_next: Handler) -> Response:
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if _REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
        request.state.request_id = rid
        try:
            response = await call_next(request)
        except Exception as exc:
            log.error(
                "unhandled exception",
                exc_info=(type(exc), exc, exc.__traceback__),
                extra={"request_id": rid, "path": request.url.path},
            )
            response = internal_error_response()
        response.headers["X-Request-Id"] = rid
        return response

    web = APIRouter(prefix="/panel/web/v1")
    web.include_router(auth.router)
    web.include_router(account.router)
    admin = APIRouter(prefix="/panel/admin/v1", dependencies=[Depends(admin_gate)])
    admin.include_router(admin_rbac.router)
    app.include_router(health.router)
    app.include_router(web)
    app.include_router(admin)
    return app
