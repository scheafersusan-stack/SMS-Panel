from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from payamakyar.api.app import create_app
from payamakyar.core.settings import PanelSettings


@pytest.fixture
async def app(db_url: str, redis_url: str) -> AsyncIterator[FastAPI]:
    settings = PanelSettings(
        env="test", database_url=db_url, redis_url=redis_url, trusted_proxies="10.0.0.0/8"
    )
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
