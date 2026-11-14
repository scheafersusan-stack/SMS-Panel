"""Request-scoped dependencies backed by ``app.state`` (set up in the lifespan)."""

import ipaddress
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime

from fastapi import Request
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
    addrs = [_as_ip(h) for h in hops]
    if not hops or any(a is None for a in addrs):
        return peer
    chain = [a for a in addrs if a is not None]
    for addr in reversed(chain):
        if not any(addr in n for n in nets):
            return str(addr)
    return str(chain[0])
