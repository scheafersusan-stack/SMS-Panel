import asyncio

import asyncpg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection

from payamakyar.db import migrate
from payamakyar.db.base import Base

pytestmark = pytest.mark.integration

TABLES = {
    "users",
    "sessions",
    "otp_challenges",
    "login_events",
    "permissions",
    "roles",
    "role_permissions",
    "user_roles",
    "audit_events",
    "settings",
    "system_messages",
    "jobs",
}


async def _tables(url: str) -> set[str]:
    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    finally:
        await conn.close()
    return {r["tablename"] for r in rows}


async def _make_db(pg_url: str, name: str) -> str:
    conn = await asyncpg.connect(pg_url)
    try:
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()
    return pg_url.rpartition("/")[0] + "/" + name


async def _drop_db(pg_url: str, name: str) -> None:
    conn = await asyncpg.connect(pg_url)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await conn.close()


async def test_upgrade_and_downgrade_clean(pg_url: str) -> None:
    name = "pk_test_migr_roundtrip"
    url = await _make_db(pg_url, name)
    try:
        await asyncio.to_thread(migrate.upgrade, url, "head")
        assert await _tables(url) == TABLES | {"alembic_version"}
        await asyncio.to_thread(migrate.downgrade, url, "base")
        assert await _tables(url) <= {"alembic_version"}
    finally:
        await _drop_db(pg_url, name)


def test_models_match_migration(db_url: str) -> None:
    diffs = asyncio.run(_diff(db_url))
    assert diffs == []


async def _diff(url: str) -> list[object]:
    from payamakyar.db.engine import create_engine

    engine = create_engine(url)
    try:
        async with engine.connect() as conn:

            def run(sync_conn: Connection) -> list[object]:
                ctx = MigrationContext.configure(sync_conn, opts={"compare_type": True})
                return list(compare_metadata(ctx, Base.metadata))

            import payamakyar.db.models  # noqa: F401

            return await conn.run_sync(run)
    finally:
        await engine.dispose()
