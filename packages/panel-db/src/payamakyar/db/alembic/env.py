"""Alembic environment (async engine; URL from config or PAYAMAKYAR_DATABASE_URL)."""

import asyncio

from alembic import context
from sqlalchemy import Connection

from payamakyar.core.settings import get_settings
from payamakyar.db import models  # noqa: F401  (register tables)
from payamakyar.db.base import Base
from payamakyar.db.engine import create_engine

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    engine = create_engine(_url())
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_run_online())
