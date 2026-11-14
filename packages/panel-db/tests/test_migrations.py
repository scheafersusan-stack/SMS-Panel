import asyncio
import re
import uuid

import asyncpg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import CheckConstraint, Connection, inspect

from payamakyar.db import migrate
from payamakyar.db.base import Base
from payamakyar.db.testing import with_database

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
    return with_database(pg_url, name)


async def _drop_db(pg_url: str, name: str) -> None:
    conn = await asyncpg.connect(pg_url)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await conn.close()


async def test_upgrade_and_downgrade_clean(pg_url: str) -> None:
    name = f"pk_test_migr_{uuid.uuid4().hex[:12]}"
    url = await _make_db(pg_url, name)
    try:
        await asyncio.to_thread(migrate.upgrade, url, "head")
        assert await _tables(url) == TABLES | {"alembic_version"}
        await asyncio.to_thread(migrate.downgrade, url, "base")
        assert await _tables(url) <= {"alembic_version"}
    finally:
        await _drop_db(pg_url, name)


async def _fetch(url: str, sql: str, *args: object) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(url)
    try:
        return list(await conn.fetch(sql, *args))
    finally:
        await conn.close()


async def _add_user(url: str, role: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        uid = uuid.uuid4()
        await conn.execute(
            "INSERT INTO users (id, username, mobile, password_hash) VALUES ($1, $2, $3, 'x')",
            uid,
            f"u_{uid.hex[:8]}",
            f"0912{uid.int % 10**7:07d}",
        )
        await conn.execute(
            "INSERT INTO user_roles (user_id, role_id) SELECT $1, id FROM roles WHERE name = $2",
            uid,
            role,
        )
    finally:
        await conn.close()


async def test_downgrade_keeps_customer_role_and_assignments(pg_url: str) -> None:
    name = f"pk_test_migr_{uuid.uuid4().hex[:12]}"
    url = await _make_db(pg_url, name)
    try:
        await asyncio.to_thread(migrate.upgrade, url, "head")
        await _add_user(url, "customer")
        await asyncio.to_thread(migrate.downgrade, url, "0002")
        roles = await _fetch(url, "SELECT name FROM roles")
        assert [r["name"] for r in roles] == ["customer"]
        assert len(await _fetch(url, "SELECT 1 FROM user_roles")) == 1
        assert await _fetch(url, "SELECT 1 FROM role_permissions") == []
        assert await _fetch(url, "SELECT 1 FROM permissions") == []
        await asyncio.to_thread(migrate.upgrade, url, "head")
        assert len(await _fetch(url, "SELECT 1 FROM user_roles")) == 1
    finally:
        await _drop_db(pg_url, name)


async def test_downgrade_refuses_when_staff_role_in_use(pg_url: str) -> None:
    name = f"pk_test_migr_{uuid.uuid4().hex[:12]}"
    url = await _make_db(pg_url, name)
    try:
        await asyncio.to_thread(migrate.upgrade, url, "head")
        await _add_user(url, "staff_support")
        with pytest.raises(Exception, match="staff_support"):
            await asyncio.to_thread(migrate.downgrade, url, "0002")
        assert len(await _fetch(url, "SELECT 1 FROM user_roles")) == 1
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
                ctx = MigrationContext.configure(
                    sync_conn, opts={"compare_type": True, "compare_server_default": True}
                )
                return list(compare_metadata(ctx, Base.metadata))

            import payamakyar.db.models  # noqa: F401

            return await conn.run_sync(run)
    finally:
        await engine.dispose()


def _literals(sql: str) -> set[str]:
    return set(re.findall(r"'([^']*)'", sql))


async def _checks(url: str) -> dict[str, dict[str, set[str]]]:
    from payamakyar.db.engine import create_engine

    engine = create_engine(url)
    try:
        async with engine.connect() as conn:

            def run(sync_conn: Connection) -> dict[str, dict[str, set[str]]]:
                insp = inspect(sync_conn)
                return {
                    t: {c["name"]: _literals(c["sqltext"]) for c in insp.get_check_constraints(t)}  # type: ignore[misc]
                    for t in TABLES
                }

            return await conn.run_sync(run)
    finally:
        await engine.dispose()


def test_check_constraints_match_migration(db_url: str) -> None:
    import payamakyar.db.models  # noqa: F401

    actual = asyncio.run(_checks(db_url))
    expected: dict[str, dict[str, set[str]]] = {t: {} for t in TABLES}
    for table in Base.metadata.tables.values():
        for con in table.constraints:
            if isinstance(con, CheckConstraint):
                assert con.name is not None
                expected[table.name][str(con.name)] = _literals(str(con.sqltext))
    assert actual == expected
    assert sum(len(v) for v in expected.values()) >= 7
