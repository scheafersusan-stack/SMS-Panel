import asyncio
import hashlib
import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from payamakyar.db import audit, migrate
from payamakyar.db.audit import GENESIS_HASH, record, verify_chain
from payamakyar.db.engine import create_engine, session_factory
from payamakyar.db.models import AuditEvent
from payamakyar.db.testing import _admin, with_database

pytestmark = pytest.mark.integration


async def _rec(s: AsyncSession, action: str = "t.action", **kw: object) -> int:
    return await record(
        s,
        actor_id=None,
        actor_ip="127.0.0.1",
        action=action,
        target_type="thing",
        target_id="1",
        **kw,  # type: ignore[arg-type]
    )


async def _row(s: AsyncSession, row_id: int) -> AuditEvent:
    return (
        await s.execute(
            select(AuditEvent)
            .where(AuditEvent.id == row_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def test_chain_links(db_session: AsyncSession) -> None:
    a = await _rec(db_session, before={"x": 1}, after={"x": 2, "نام": "ب"}, reason="because")
    b = await _rec(db_session)
    c = await _rec(db_session)
    await db_session.commit()
    ra, rb, rc = [await _row(db_session, i) for i in (a, b, c)]
    assert rb.prev_hash == ra.hash and rc.prev_hash == rb.hash
    assert len(ra.hash) == 64 and ra.hash != rb.hash
    first = (
        await db_session.execute(select(AuditEvent).order_by(AuditEvent.id).limit(1))
    ).scalar_one()
    assert first.prev_hash == GENESIS_HASH
    assert (
        audit.compute_hash(
            id=rb.id,
            at=rb.at,
            actor_id=rb.actor_id,
            actor_ip=rb.actor_ip,
            action=rb.action,
            target_type=rb.target_type,
            target_id=rb.target_id,
            before=rb.before,
            after=rb.after,
            reason=rb.reason,
            prev_hash=ra.hash,
        )
        == rb.hash
    )
    assert hashlib.sha256((ra.hash + "x").encode()).hexdigest() != rb.hash
    assert await verify_chain(db_session) is None
    assert await verify_chain(db_session, since_id=a) is None


async def test_update_rejected_by_trigger(db_session: AsyncSession) -> None:
    rid = await _rec(db_session)
    await db_session.commit()
    with pytest.raises(DBAPIError, match="append-only"):
        await db_session.execute(update(AuditEvent).where(AuditEvent.id == rid).values(action="x"))
    await db_session.rollback()
    with pytest.raises(DBAPIError, match="append-only"):
        await db_session.execute(delete(AuditEvent).where(AuditEvent.id == rid))
    await db_session.rollback()
    with pytest.raises(DBAPIError, match="append-only"):
        await db_session.execute(text("TRUNCATE audit_events"))
    await db_session.rollback()


async def _tamper(db_url: str, sql: str, *args: object) -> None:
    conn = await asyncpg.connect(db_url)
    try:
        async with conn.transaction():
            await conn.execute("ALTER TABLE audit_events DISABLE TRIGGER USER")
            await conn.execute(sql, *args)
            await conn.execute("ALTER TABLE audit_events ENABLE TRIGGER USER")
    finally:
        await conn.close()


@pytest.fixture
async def tamper_url(pg_url: str) -> AsyncIterator[str]:
    """A private migrated database: the tamper test permanently breaks its chain."""
    name = f"pk_test_audit_{uuid.uuid4().hex[:12]}"
    await _admin(pg_url, f'CREATE DATABASE "{name}"')
    url = with_database(pg_url, name)
    try:
        await asyncio.to_thread(migrate.upgrade, url)
        yield url
    finally:
        await _admin(pg_url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


async def test_tamper_detected(tamper_url: str) -> None:
    engine = create_engine(tamper_url)
    try:
        async with session_factory(engine)() as db_session:
            await _tamper_scenario(db_session, tamper_url)
    finally:
        await engine.dispose()


async def _tamper_scenario(db_session: AsyncSession, db_url: str) -> None:
    ids = [await _rec(db_session, after={"n": i}) for i in range(4)]
    await db_session.commit()
    assert await verify_chain(db_session) is None
    plain = db_url
    # edited content
    await _tamper(plain, "UPDATE audit_events SET action = 'evil' WHERE id = $1", ids[1])
    assert await verify_chain(db_session) == ids[1]
    await _tamper(plain, "UPDATE audit_events SET action = 't.action' WHERE id = $1", ids[1])
    assert await verify_chain(db_session) is None
    # broken link
    await _tamper(plain, "UPDATE audit_events SET prev_hash = $2 WHERE id = $1", ids[2], "f" * 64)
    assert await verify_chain(db_session) == ids[2]
    assert await verify_chain(db_session, since_id=ids[2]) is None
    # deleted row: the next row's link is broken
    await _tamper(plain, "DELETE FROM audit_events WHERE id = $1", ids[1])
    bad = await verify_chain(db_session)
    assert bad is not None and bad <= ids[2]
    assert await verify_chain(db_session, since_id=ids[2]) is None


async def test_secrets_redacted_in_after(db_session: AsyncSession) -> None:
    rid = await _rec(
        db_session,
        before={"password": "hunter2", "ok": "fine"},
        after={"password": "hunter2", "api_key": "k-123", "nested": {"token": "abc"}, "n": 3},
    )
    await db_session.commit()
    row = await _row(db_session, rid)
    assert row.after is not None and row.before is not None
    assert row.after["password"] == "****" and row.after["api_key"] == "****"
    assert row.after["nested"]["token"] == "****" and row.after["n"] == 3
    assert row.before["password"] == "****" and row.before["ok"] == "fine"
    assert "hunter2" not in str(row.after)


async def test_concurrent_records_keep_chain(db_url: str) -> None:
    engine = create_engine(db_url)
    try:
        maker = session_factory(engine)

        async def one(i: int) -> None:
            async with maker() as s:
                await _rec(s, action=f"t.conc{i}")
                await s.commit()

        await asyncio.gather(*(one(i) for i in range(8)))
        async with maker() as s:
            assert await verify_chain(s) is None
    finally:
        await engine.dispose()
