"""Append-only, hash-chained audit log.

``record`` never commits: the audit row commits or rolls back with the caller's transaction.
Each row's ``hash`` is ``sha256(prev_hash + canonical_json(row))`` so any edit, reordering or
deletion of stored rows is detectable with ``verify_chain``. A database trigger (migration
0002) additionally rejects UPDATE, DELETE and TRUNCATE. Deleting the newest rows is not
detectable by the chain alone (no later row exposes the gap); anchor the latest hash externally.
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

AUDIT_ACTIONS: frozenset[str] = frozenset(
    {
        # sign-in and sessions
        "user.register",
        "user.login",
        "user.lock",
        "session.logout",
        "session.revoke",
        # the account owner
        "user.password_change",
        "user.password_reset_requested",
        "user.password_reset",
        "user.profile_update",
        "user.mfa_setup",
        "user.mfa_enable",
        "user.mfa_disable",
        "user.security_update",
        # staff and operations
        "user.create_admin",
        "user.roles.update",
        "role.create",
        "role.update",
        "role.delete",
        "settings.update",
    }
)
"""Every action ``record`` accepts; a new action is added here first
(``tests/test_audit_actions.py`` checks each call site against it)."""

__all__ = [
    "AUDIT_ACTIONS",
    "GENESIS_HASH",
    "canonical_json",
    "compute_hash",
    "record",
    "verify_chain",
]


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


def _normalise(value: Any) -> Any:
    """Reduce to what jsonb returns: floats become text (jsonb numeric would alter them),
    NUL characters are dropped (jsonb rejects them), unknown types become text."""
    if isinstance(value, dict):
        return {_normalise(str(k)): _normalise(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_normalise(v) for v in value]
    if isinstance(value, str):
        return value.replace("\x00", "")
    if value is None or isinstance(value, (bool, int)):
        return value
    return _normalise(str(value))


def _clean(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """Redact secrets and reduce to plain JSON types so the stored row hashes identically."""
    if value is None:
        return None
    cleaned: dict[str, Any] = _normalise(redact(value))
    return cleaned


def _clean_text(value: str | None) -> str | None:
    return None if value is None else str(_normalise(redact(value)))


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
    """Append one row; raises ``ValueError`` for an action missing from ``AUDIT_ACTIONS``."""
    if action not in AUDIT_ACTIONS:
        raise ValueError(f"unknown audit action: {action!r}")
    target_id, reason = _clean_text(target_id), _clean_text(reason)
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
    cols = AuditEvent.__table__.c
    while True:
        rows = (
            await s.execute(
                select(*cols).where(cols.id > last_id).order_by(cols.id).limit(BATCH_SIZE)
            )
        ).all()
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
