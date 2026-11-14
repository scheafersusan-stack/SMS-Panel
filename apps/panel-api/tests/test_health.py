import httpx
import pytest

pytestmark = pytest.mark.integration


async def test_health(client: httpx.AsyncClient) -> None:
    r = await client.get("/panel/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert r.headers["X-Request-Id"]


async def test_request_id_accepted_or_replaced(client: httpx.AsyncClient) -> None:
    ok = await client.get("/panel/health", headers={"X-Request-Id": "abc.123:x-y"})
    assert ok.headers["X-Request-Id"] == "abc.123:x-y"
    bad = await client.get("/panel/health", headers={"X-Request-Id": "bad id!"})
    assert bad.headers["X-Request-Id"] != "bad id!"
    assert len(bad.headers["X-Request-Id"]) == 32
