import uuid
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import Depends, FastAPI, Request
from redis.asyncio import Redis

from payamakyar.api.deps import client_ip, get_clock
from payamakyar.api.ratelimit import RateLimiter, rate_limit

pytestmark = pytest.mark.integration


async def test_limiter_fixed_window(redis_url: str) -> None:
    redis = Redis.from_url(redis_url)
    now = [1_000_000.0]
    limiter = RateLimiter(redis, lambda: now[0])
    key = uuid.uuid4().hex
    try:
        for _ in range(3):
            assert (await limiter.hit(key, 3, 60)).allowed
        res = await limiter.hit(key, 3, 60)
        assert not res.allowed
        assert 1 <= res.retry_after <= 60
        now[0] += 60
        assert (await limiter.hit(key, 3, 60)).allowed
    finally:
        await redis.aclose()


async def test_21st_login_hit_is_429(app: FastAPI, client: httpx.AsyncClient) -> None:
    @app.get(
        "/panel/web/v1/_t/limited",
        dependencies=[
            Depends(
                rate_limit(lambda r: r.headers["x-test-key"], "auth.login_rate_per_ip_per_min", 60)
            )
        ],
    )
    async def limited() -> dict[str, bool]:
        return {"ok": True}

    h = {"X-Test-Key": uuid.uuid4().hex}
    app.dependency_overrides[get_clock] = lambda: lambda: datetime(2030, 1, 1, 0, 0, 5, tzinfo=UTC)
    for _ in range(20):
        assert (await client.get("/panel/web/v1/_t/limited", headers=h)).status_code == 200
    r = await client.get("/panel/web/v1/_t/limited", headers=h)
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "RATE_LIMITED"
    assert r.headers["Retry-After"] == "55"


async def test_client_ip_trusts_only_proxies(app: FastAPI, client: httpx.AsyncClient) -> None:
    @app.get("/panel/web/v1/_t/ip")
    async def ip(request: Request) -> dict[str, str]:
        return {"ip": client_ip(request)}

    # Test peer is 127.0.0.1 (not trusted): header ignored.
    r = await client.get("/panel/web/v1/_t/ip", headers={"X-Forwarded-For": "1.2.3.4"})
    assert r.json()["ip"] == "127.0.0.1"
    app.state.trusted_networks = [__import__("ipaddress").ip_network("127.0.0.0/8")]
    r = await client.get("/panel/web/v1/_t/ip", headers={"X-Forwarded-For": "9.9.9.9, 1.2.3.4"})
    assert r.json()["ip"] == "1.2.3.4"
    r = await client.get("/panel/web/v1/_t/ip", headers={"X-Forwarded-For": "garbage"})
    assert r.json()["ip"] == "127.0.0.1"
