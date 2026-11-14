import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from payamakyar.db.engine import create_engine, session_factory
from payamakyar.db.jobs import Job, Worker, claim, complete, enqueue, fail

pytestmark = pytest.mark.integration


async def _get(s: AsyncSession, job_id: object) -> Job:
    await s.rollback()
    return (
        await s.execute(
            select(Job).where(Job.id == job_id).execution_options(populate_existing=True)
        )
    ).scalar_one()


async def test_enqueue_dedupe(db_session: AsyncSession) -> None:
    first = await enqueue(db_session, "t.dedupe", {"a": 1}, dedupe_key="k-dedupe")
    second = await enqueue(db_session, "t.dedupe", {"a": 2}, dedupe_key="k-dedupe")
    other = await enqueue(db_session, "t.dedupe", {"a": 3})
    await db_session.commit()
    assert first is not None and second is None and other is not None
    job = await _get(db_session, first)
    assert job.payload == {"a": 1} and job.state == "ready" and job.max_attempts == 8


async def test_enqueue_rolls_back_with_caller(db_session: AsyncSession) -> None:
    job_id = await enqueue(db_session, "t.rollback", {})
    await db_session.rollback()
    rows = (await db_session.execute(select(Job).where(Job.id == job_id))).all()
    assert rows == []


async def test_claim_skip_locked_concurrent(db_url: str) -> None:
    engine = create_engine(db_url)
    try:
        factory = session_factory(engine)
        async with factory() as seed:
            for i in range(10):
                await enqueue(seed, "t.conc", {"i": i})
            await seed.commit()
        async with factory() as a, factory() as b:
            got_a = await claim(a, ["t.conc"], limit=10, lease_seconds=60)
            got_b = await claim(b, ["t.conc"], limit=10, lease_seconds=60)
            ids_a, ids_b = {j.id for j in got_a}, {j.id for j in got_b}
            assert ids_a.isdisjoint(ids_b)
            assert len(ids_a | ids_b) == 10
            assert all(j.state == "running" and j.attempts == 1 for j in got_a + got_b)
            await a.commit()
            await b.commit()
    finally:
        await engine.dispose()


async def test_claim_respects_run_at_and_kind(db_session: AsyncSession) -> None:
    future = datetime.now(UTC) + timedelta(hours=1)
    await enqueue(db_session, "t.future", {}, run_at=future)
    await enqueue(db_session, "t.otherkind", {})
    ready = await enqueue(db_session, "t.runat", {})
    await db_session.commit()
    got = await claim(db_session, ["t.future", "t.runat"], limit=10, lease_seconds=60)
    await db_session.commit()
    assert [j.id for j in got] == [ready]


async def test_expired_lease_reclaimed(db_session: AsyncSession) -> None:
    job_id = await enqueue(db_session, "t.lease", {})
    await db_session.commit()
    (first,) = await claim(db_session, ["t.lease"], limit=1, lease_seconds=60)
    await db_session.commit()
    assert first.id == job_id
    assert await claim(db_session, ["t.lease"], limit=1, lease_seconds=60) == []
    await db_session.commit()
    await db_session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(lease_until=datetime.now(UTC) - timedelta(seconds=5))
    )
    await db_session.commit()
    (again,) = await claim(db_session, ["t.lease"], limit=1, lease_seconds=60)
    await db_session.commit()
    assert again.id == job_id and again.attempts == 2


async def test_complete(db_session: AsyncSession) -> None:
    job_id = await enqueue(db_session, "t.complete", {})
    await db_session.commit()
    await claim(db_session, ["t.complete"], limit=1, lease_seconds=60)
    await complete(db_session, job_id)  # type: ignore[arg-type]
    await db_session.commit()
    job = await _get(db_session, job_id)
    assert job.state == "done" and job.lease_until is None


async def test_fail_backoff_then_dead(db_session: AsyncSession) -> None:
    job_id = await enqueue(db_session, "t.fail", {}, max_attempts=3)
    assert job_id is not None
    await db_session.commit()
    schedule = (10.0, 100.0)
    expected = [10.0, 100.0]
    for attempt in (1, 2):
        (job,) = await claim(db_session, ["t.fail"], limit=1, lease_seconds=60)
        assert job.attempts == attempt
        before = datetime.now(UTC)
        await fail(db_session, job_id, "boom " + "x" * 5000, retry_schedule=schedule, jitter=0.1)
        await db_session.commit()
        job = await _get(db_session, job_id)
        assert job.state == "ready" and job.lease_until is None
        assert job.last_error is not None and len(job.last_error) == 2000
        delay = (job.run_at - before).total_seconds()
        base = expected[attempt - 1]
        assert base * 0.9 - 1 <= delay <= base * 1.1 + 1
        await db_session.execute(update(Job).where(Job.id == job_id).values(run_at=before))
        await db_session.commit()
    (job,) = await claim(db_session, ["t.fail"], limit=1, lease_seconds=60)
    assert job.attempts == 3
    await fail(db_session, job_id, "final", retry_schedule=schedule)
    await db_session.commit()
    job = await _get(db_session, job_id)
    assert job.state == "dead" and job.last_error == "final"


async def test_worker_run_once(db_url: str) -> None:
    engine = create_engine(db_url)
    try:
        factory = session_factory(engine)
        async with factory() as s:
            ok = await enqueue(s, "t.worker", {"n": 1})
            bad = await enqueue(s, "t.worker", {"n": 2}, max_attempts=1)
            await s.commit()
        seen: list[int] = []

        async def handler(session: AsyncSession, job: Job) -> None:
            seen.append(job.payload["n"])
            if job.payload["n"] == 2:
                raise RuntimeError("nope")

        worker = Worker(
            ["t.worker"], handler, session_factory=factory, concurrency=2, poll_interval=0.05
        )
        assert await worker.run_once() == 2
        assert sorted(seen) == [1, 2]
        async with factory() as s:
            assert (await _get(s, ok)).state == "done"
            dead = await _get(s, bad)
            assert dead.state == "dead" and dead.last_error is not None
            assert "nope" in dead.last_error
        assert await worker.run_once() == 0
    finally:
        await engine.dispose()


async def test_worker_run_forever_stops(db_url: str) -> None:
    engine = create_engine(db_url)
    try:
        factory = session_factory(engine)

        async def handler(session: AsyncSession, job: Job) -> None:
            return None

        worker = Worker(
            ["t.never"], handler, session_factory=factory, concurrency=1, poll_interval=0.01
        )
        task = asyncio.create_task(worker.run_forever())
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        await engine.dispose()
