"""Redis fixed-window rate limiter and the FastAPI dependency factory."""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis

from payamakyar.api.deps import SessionDep, get_clock, get_redis
from payamakyar.api.errors import ApiError
from payamakyar.db.settings_store import SettingsStore


@dataclass(frozen=True)
class RateResult:
    allowed: bool
    retry_after: int


class RateLimiter:
    """Fixed-window counter; across a window boundary up to 2x the limit can pass."""

    def __init__(self, redis: Redis, clock: Callable[[], float] = time.time) -> None:
        self._redis = redis
        self._clock = clock

    async def hit(self, key: str, limit: int, window_s: int) -> RateResult:
        now = int(self._clock())
        window_start = now - now % window_s
        name = f"rl:{key}:{window_start}"
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(name)
            pipe.expire(name, window_s + 1, nx=True)
            count = int((await pipe.execute())[0])
        retry_after = max(1, window_start + window_s - now)
        return RateResult(count <= limit, 0 if count <= limit else retry_after)


def rate_limit(
    key_fn: Callable[[Request], str], limit_setting_key: str, window_s: int
) -> Callable[..., Awaitable[None]]:
    async def dependency(
        request: Request,
        session: SessionDep,
        redis: Annotated[Redis, Depends(get_redis)],
        clock: Annotated[Callable[[], datetime], Depends(get_clock)],
    ) -> None:
        limit = int(await SettingsStore(session).get(limit_setting_key))
        limiter = RateLimiter(redis, lambda: clock().timestamp())
        result = await limiter.hit(f"{limit_setting_key}:{key_fn(request)}", limit, window_s)
        if not result.allowed:
            raise ApiError(
                429,
                "RATE_LIMITED",
                "تعداد درخواست‌ها زیاد است",
                "کمی بعد دوباره تلاش کنید.",
                headers={"Retry-After": str(result.retry_after)},
            )

    return dependency
