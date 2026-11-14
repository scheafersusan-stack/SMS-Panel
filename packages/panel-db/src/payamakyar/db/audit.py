"""Append-only, hash-chained audit log.

``record`` never commits: the audit row commits or rolls back with the caller's transaction.
Each row's ``hash`` is ``sha256(prev_hash + canonical_json(row))`` so any edit, reordering or
deletion of stored rows is detectable with ``verify_chain``. A database trigger (migration
0002) additionally rejects UPDATE, DELETE and TRUNCATE.
"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from payamakyar.core.masking import redact
from payamakyar.db.models import AuditEvent

GENESIS_HASH = "0" * 64
ADVISORY_LOCK_KEY = 7701
BATCH_SIZE = 1000

__all__ = ["GENESIS_HASH", "canonical_json", "compute_hash", "record", "verify_chain"]


def canonical_json(fields: dict[str, Any]) -> str:
    return json.dumps(
        fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def _iso(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="microseconds")


def compute_hash(
    *,
    id: int,  # noqa: A002
    at: datetime,
    actor_id: UUID | None,
    actor_ip: str | None,
    action: str,
    target_type: str | None,
    target_id: str | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    reason: str | None,
    prev_hash: str,
) -> str:
    body = canonical_json(
        {
            "id": id,
            "at": _iso(at),
            "actor_id": actor_id,
            "actor_ip": actor_ip,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "before": before,
            "after": after,
            "reason": reason,
            "prev_hash": prev_hash,
        }
    )
    return hashlib.sha256((prev_hash + body).encode("utf-8")).hexdigest()


def _clean(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """Redact secrets and reduce to plain JSON types so the stored row hashes identically."""
    if value is None:
        return None
    cleaned: dict[str, Any] = json.loads(json.dumps(redact(value), default=str))
    return cleaned


async def record(
    s: AsyncSession,
    *,
    actor_id: UUID | None,
    actor_ip: str | None,
    action: str,
    target_type: str,
    target_id: str | None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
) -> int:
    await s.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": ADVISORY_LOCK_KEY})
    prev_hash = (
        await s.execute(select(AuditEvent.hash).order_by(AuditEvent.id.desc()).limit(1))
    ).scalar_one_or_none() or GENESIS_HASH
    new_id = (
        await s.execute(text("SELECT nextval(pg_get_serial_sequence('audit_events', 'id'))"))
    ).scalar_one()
    at = datetime.now(UTC)
    before_c, after_c = _clean(before), _clean(after)
    digest = compute_hash(
        id=new_id,
        at=at,
        actor_id=actor_id,
        actor_ip=actor_ip,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before=before_c,
        after=after_c,
        reason=reason,
        prev_hash=prev_hash,
    )
    s.add(
        AuditEvent(
            id=new_id,
            at=at,
            actor_id=actor_id,
            actor_ip=actor_ip,
            action=action,
            target_type=target_type,
            target_id=target_id,
            before=before_c,
            after=after_c,
            reason=reason,
            prev_hash=prev_hash,
            hash=digest,
        )
    )
    await s.flush()
    return int(new_id)


async def verify_chain(s: AsyncSession, *, since_id: int = 0) -> int | None:
    """Return the id of the first row that breaks the chain, or None if it is intact.

    Verifies rows with ``id > since_id``, anchored on the stored hash of the last row at or
    before ``since_id`` (genesis if none). A broken ``prev_hash`` link (e.g. a deleted row) or a
    ``hash`` that does not match the row contents is reported at that row's id. Deleting the
    newest rows leaves no later row to expose the gap and is not detectable here.
    """
    expected_prev = (
        await s.execute(
            select(AuditEvent.hash)
            .where(AuditEvent.id <= since_id)
            .order_by(AuditEvent.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none() or GENESIS_HASH
    last_id = since_id
    while True:
        rows = (
            (
                await s.execute(
                    select(AuditEvent)
                    .where(AuditEvent.id > last_id)
                    .order_by(AuditEvent.id)
                    .limit(BATCH_SIZE)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return None
        for row in rows:
            if row.prev_hash != expected_prev:
                return int(row.id)
            digest = compute_hash(
                id=row.id,
                at=row.at,
                actor_id=row.actor_id,
                actor_ip=row.actor_ip,
                action=row.action,
                target_type=row.target_type,
                target_id=row.target_id,
                before=row.before,
                after=row.after,
                reason=row.reason,
                prev_hash=row.prev_hash,
            )
            if digest != row.hash:
                return int(row.id)
            expected_prev = row.hash
        last_id = int(rows[-1].id)
        s.expunge_all()
