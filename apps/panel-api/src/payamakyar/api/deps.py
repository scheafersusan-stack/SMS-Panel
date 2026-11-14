"""Request-scoped dependencies backed by ``app.state`` (set up in the lifespan)."""

import ipaddress
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from payamakyar.core.settings import PanelSettings

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
