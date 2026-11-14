"""Transactional job queue on PostgreSQL (``FOR UPDATE SKIP LOCKED`` with leases).

``enqueue``, ``claim``, ``complete`` and ``fail`` never commit: the caller owns the
transaction, so a job is enqueued if and only if the surrounding business change commits.
"""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payamakyar.core.ids import new_id
from payamakyar.db.models import Job

log = logging.getLogger("payamakyar.db.jobs")

DEFAULT_RETRY_SCHEDULE: tuple[float, ...] = (1, 5, 30, 120, 600, 1800, 3600, 7200)
MAX_ERROR_LENGTH = 2000

__all__ = ["Job", "Worker", "claim", "complete", "enqueue", "fail"]


async def enqueue(
    s: AsyncSession,
    kind: str,
    payload: dict[str, Any],
    *,
    run_at: datetime | None = None,
    dedupe_key: str | None = None,
    max_attempts: int = 8,
) -> UUID | None:
    """Insert a ready job; return its id, or ``None`` when ``dedupe_key`` already exists."""
    values: dict[str, Any] = {
        "id": new_id(),
        "kind": kind,
        "payload": payload,
        "dedupe_key": dedupe_key,
        "max_attempts": max_attempts,
    }
    if run_at is not None:
        values["run_at"] = run_at
    stmt = (
        insert(Job)
        .values(**values)
        .on_conflict_do_nothing(index_elements=[Job.dedupe_key])
        .returning(Job.id)
    )
    return (await s.execute(stmt)).scalar_one_or_none()


async def claim(
    s: AsyncSession, kinds: Sequence[str], *, limit: int, lease_seconds: int
) -> list[Job]:
    """Lease up to ``limit`` due jobs (or running ones whose lease expired)."""
    due = or_(
        and_(Job.state == "ready", Job.run_at <= func.now()),
        and_(Job.state == "running", Job.lease_until < func.now()),
    )
    ids = (
        select(Job.id)
        .where(Job.kind.in_(list(kinds)), due)
        .order_by(Job.run_at, Job.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    stmt = (
        update(Job)
        .where(Job.id.in_(ids))
        .values(
            state="running",
            attempts=Job.attempts + 1,
            lease_until=func.now() + timedelta(seconds=lease_seconds),
            updated_at=func.now(),
        )
        .returning(Job)
        .execution_options(populate_existing=True, synchronize_session=False)
    )
    rows = (await s.execute(stmt)).scalars().all()
    return sorted(rows, key=lambda j: (j.run_at, j.created_at))


async def complete(s: AsyncSession, job_id: UUID) -> None:
    await s.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(state="done", lease_until=None, updated_at=func.now())
        .execution_options(synchronize_session=False)
    )


def _delay(attempts: int, schedule: Sequence[float], jitter: float) -> float:
    base = schedule[min(max(attempts, 1) - 1, len(schedule) - 1)]
    return max(0.0, base * (1 + random.uniform(-jitter, jitter)))  # noqa: S311


async def fail(
    s: AsyncSession,
    job_id: UUID,
    error: str,
    *,
    retry_schedule: Sequence[float] = DEFAULT_RETRY_SCHEDULE,
    jitter: float = 0.1,
) -> None:
    """Reschedule with backoff, or mark ``dead`` once ``max_attempts`` is reached."""
    job = (
        await s.execute(
            select(Job)
            .where(Job.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    values: dict[str, Any] = {
        "last_error": error[:MAX_ERROR_LENGTH],
        "lease_until": None,
        "updated_at": func.now(),
    }
    if job.attempts >= job.max_attempts:
        values["state"] = "dead"
    else:
        values["state"] = "ready"
        values["run_at"] = datetime.now(UTC) + timedelta(
            seconds=_delay(job.attempts, retry_schedule, jitter)
        )
    await s.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(**values)
        .execution_options(synchronize_session=False)
    )


Handler = Callable[[AsyncSession, Job], Awaitable[None]]


class Worker:
    """Polls for jobs and runs ``handler`` once per job, each in its own transaction."""

    def __init__(
        self,
        kinds: Sequence[str],
        handler: Handler,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        concurrency: int = 4,
        poll_interval: float = 1.0,
        lease_seconds: int = 300,
    ) -> None:
        self.kinds = list(kinds)
        self.handler = handler
        self.session_factory = session_factory
        self.concurrency = concurrency
        self.poll_interval = poll_interval
        self.lease_seconds = lease_seconds

    async def _run_job(self, job: Job) -> None:
        job_id, kind = job.id, job.kind
        try:
            async with self.session_factory() as s:
                await self.handler(s, job)
                await complete(s, job_id)
                await s.commit()
        except Exception as exc:
            log.warning(
                "job failed", extra={"job_id": str(job_id), "kind": kind, "error": str(exc)}
            )
            async with self.session_factory() as s:
                await fail(s, job_id, f"{type(exc).__name__}: {exc}")
                await s.commit()

    async def run_once(self) -> int:
        """Claim up to ``concurrency`` jobs, run them, and return how many were processed."""
        async with self.session_factory() as s:
            jobs = await claim(
                s, self.kinds, limit=self.concurrency, lease_seconds=self.lease_seconds
            )
            await s.commit()
        if jobs:
            await asyncio.gather(*(self._run_job(j) for j in jobs))
        return len(jobs)

    async def run_forever(self) -> None:
        while True:
            try:
                n = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("job worker poll failed")
                n = 0
            if n == 0:
                await asyncio.sleep(self.poll_interval)
