"""Request-scoped dependencies backed by ``app.state`` (set up in the lifespan)."""

import hmac
import ipaddress
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from payamakyar.api import csrf, sessions
from payamakyar.api.errors import ApiError
from payamakyar.core.settings import PanelSettings
from payamakyar.db.models import Session, User

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_trusted_proxies(raw: str) -> list[IPNetwork]:
    return [ipaddress.ip_network(p.strip(), strict=False) for p in raw.split(",") if p.strip()]


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request: commit on success, roll back on error."""
    async with request.app.state.session_factory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
"""Function-scoped: the commit runs before the response is sent, so a failure is a 500."""


def get_redis(request: Request) -> Redis:
    redis: Redis = request.app.state.redis
    return redis


def get_settings_dep(request: Request) -> PanelSettings:
    settings: PanelSettings = request.app.state.settings
    return settings


def _utcnow() -> datetime:
    return datetime.now(UTC)


def get_clock() -> Callable[[], datetime]:
    """UTC clock; tests override this dependency to freeze time."""
    return _utcnow


def _as_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def client_ip(request: Request) -> str:
    """Peer address; ``X-Forwarded-For`` is honoured only when the peer is a trusted proxy."""
    peer = request.client.host if request.client else ""
    peer_ip = _as_ip(peer)
    nets: list[IPNetwork] = request.app.state.trusted_networks
    if peer_ip is None or not any(peer_ip in n for n in nets):
        return peer
    hops = [h for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    # Right to left: skip trusted proxies; the first other hop is the client. An invalid hop
    # ends the walk (it cannot be trusted or attributed), falling back to the last good one.
    result = peer
    for hop in reversed(hops):
        addr = _as_ip(hop)
        if addr is None:
            return result
        result = str(addr)
        if not any(addr in n for n in nets):
            return result
    return result


def _not_authenticated() -> ApiError:
    return ApiError(401, "NOT_AUTHENTICATED", "ورود لازم است", "دوباره وارد حساب شوید.")


async def current_session(
    request: Request,
    s: SessionDep,
    settings: Annotated[PanelSettings, Depends(get_settings_dep)],
    clock: Annotated[Callable[[], datetime], Depends(get_clock)],
) -> Session:
    """The live session from the ``pk_session`` cookie, or 401 ``NOT_AUTHENTICATED``.

    On unsafe methods the ``X-CSRF-Token`` header must also be this session's CSRF token
    (the middleware only checks that cookie and header agree).
    """
    token = request.cookies.get(settings.session_cookie_name, "")
    row = await sessions.resolve(s, token, now=clock()) if token else None
    if row is None:
        raise _not_authenticated()
    if request.method.upper() not in csrf.SAFE_METHODS:
        header = request.headers.get(csrf.HEADER, "")
        if not header or not hmac.compare_digest(sessions.hash_token(header), row.csrf_hash):
            raise ApiError(
                403, "CSRF_FAILED", "درخواست نامعتبر است", "توکن CSRF نامعتبر یا ناموجود است."
            )
    return row


CurrentSession = Annotated[Session, Depends(current_session)]


async def current_user(row: CurrentSession, s: SessionDep) -> User:
    user = await s.get(User, row.user_id)
    if user is None:
        raise _not_authenticated()
    return user


CurrentUser = Annotated[User, Depends(current_user)]
