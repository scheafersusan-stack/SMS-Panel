"""The test fixtures' own safety rails (dedicated Redis db, required services in CI)."""

from types import SimpleNamespace
from typing import Any

import pytest

from payamakyar.db import testing


def test_redis_url_defaults_to_db_15() -> None:
    assert testing.redis_test_url("redis://localhost:6379") == "redis://localhost:6379/15"
    assert testing.redis_test_url("redis://localhost:6379/") == "redis://localhost:6379/15"
    assert testing.redis_test_url("redis://localhost:6379/7") == "redis://localhost:6379/7"


def test_redis_url_refuses_db_0() -> None:
    with pytest.raises(pytest.UsageError, match="db 0"):
        testing.redis_test_url("redis://localhost:6379/0")


def _fake_redis(db: int) -> Any:
    calls: list[str] = []

    async def flushdb() -> None:
        calls.append("flushdb")

    pool = SimpleNamespace(connection_kwargs={"db": db})
    return SimpleNamespace(connection_pool=pool, flushdb=flushdb, calls=calls)


async def test_flush_refuses_db_0() -> None:
    fake = _fake_redis(0)
    with pytest.raises(RuntimeError, match="db 0"):
        await testing.flush_test_redis(fake)
    assert fake.calls == []
    ok = _fake_redis(15)
    await testing.flush_test_redis(ok)
    assert ok.calls == ["flushdb"]


def test_missing_service_skips_or_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PAYAMAKYAR_TEST_REQUIRE_SERVICES", raising=False)
    with pytest.raises(pytest.skip.Exception):
        testing.service_unavailable("no redis")
    monkeypatch.setenv("PAYAMAKYAR_TEST_REQUIRE_SERVICES", "1")
    with pytest.raises(pytest.fail.Exception, match="no redis"):
        testing.service_unavailable("no redis")
