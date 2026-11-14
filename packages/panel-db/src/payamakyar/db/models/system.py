"""Audit log, settings, system messages and the job queue."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from payamakyar.core.ids import new_id
from payamakyar.db.base import Base


def _ts() -> TIMESTAMP:
    return TIMESTAMP(timezone=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(_ts(), server_default=text("now()"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_ip: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text, index=True)
    target_type: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[str | None] = mapped_column(Text)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    prev_hash: Mapped[str | None] = mapped_column(Text)
    hash: Mapped[str] = mapped_column(Text)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        _ts(), server_default=text("now()"), onupdate=text("now()")
    )


class SystemMessage(Base):
    __tablename__ = "system_messages"
    __table_args__ = (CheckConstraint("status IN ('pending', 'sent', 'failed')", name="status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    to_mobile: Mapped[str] = mapped_column(Text)
    template_key: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    created_at: Mapped[datetime] = mapped_column(_ts(), server_default=text("now()"))
    sent_at: Mapped[datetime | None] = mapped_column(_ts())


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("state IN ('ready', 'running', 'done', 'dead')", name="state"),
        Index("ix_jobs_state_run_at", "state", "run_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    dedupe_key: Mapped[str | None] = mapped_column(Text, unique=True)
    state: Mapped[str] = mapped_column(Text, server_default="ready")
    run_at: Mapped[datetime] = mapped_column(_ts(), server_default=text("now()"))
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, server_default="5")
    lease_until: Mapped[datetime | None] = mapped_column(_ts())
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_ts(), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        _ts(), server_default=text("now()"), onupdate=text("now()")
    )
