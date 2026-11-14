"""Users, sessions, OTP challenges and login events."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CIDR, CITEXT, INET, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from payamakyar.core.ids import new_id
from payamakyar.db.base import Base


def _ts() -> TIMESTAMP:
    return TIMESTAMP(timezone=True)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(_in("kind", ("person", "company")), name="kind"),
        CheckConstraint(_in("status", ("active", "inactive")), name="status"),
        CheckConstraint(
            _in("identity_state", ("none", "pending", "matched", "mismatch", "manual_review")),
            name="identity_state",
        ),
        CheckConstraint(
            _in("documents_state", ("none", "pending", "approved", "rejected")),
            name="documents_state",
        ),
        CheckConstraint(_in("mfa_method", ("none", "totp", "sms")), name="mfa_method"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(Text, server_default="person")
    username: Mapped[str] = mapped_column(CITEXT, unique=True)
    mobile: Mapped[str] = mapped_column(Text, unique=True)
    email: Mapped[str | None] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="active")
    send_blocked: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    document_blocked: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    identity_state: Mapped[str] = mapped_column(Text, server_default="none")
    documents_state: Mapped[str] = mapped_column(Text, server_default="none")
    first_name: Mapped[str | None] = mapped_column(Text)
    last_name: Mapped[str | None] = mapped_column(Text)
    national_code: Mapped[str | None] = mapped_column(Text)
    birth_date: Mapped[date | None] = mapped_column(Date)
    company_name: Mapped[str | None] = mapped_column(Text)
    company_national_id: Mapped[str | None] = mapped_column(Text)
    economic_code: Mapped[str | None] = mapped_column(Text)
    ceo_name: Mapped[str | None] = mapped_column(Text)
    ceo_national_code: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    postal_code: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime | None] = mapped_column(_ts())
    mfa_method: Mapped[str] = mapped_column(Text, server_default="none")
    totp_secret_sealed: Mapped[str | None] = mapped_column(Text)
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger)
    login_notice: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    allowed_ips: Mapped[list[str] | None] = mapped_column(ARRAY(CIDR))
    # [{"days": [0-6], "from": "08:00", "to": "18:00"}]
    login_hours: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    failed_logins: Mapped[int] = mapped_column(Integer, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(_ts())
    last_login_at: Mapped[datetime | None] = mapped_column(_ts())
    created_at: Mapped[datetime] = mapped_column(_ts(), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        _ts(), server_default=text("now()"), onupdate=text("now()")
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    csrf_hash: Mapped[str] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_ts(), server_default=text("now()"))
    last_seen_at: Mapped[datetime] = mapped_column(_ts(), server_default=text("now()"))
    expires_at: Mapped[datetime] = mapped_column(_ts())
    revoked_at: Mapped[datetime | None] = mapped_column(_ts())
    impersonator_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class OtpChallenge(Base):
    __tablename__ = "otp_challenges"
    __table_args__ = (
        CheckConstraint(
            _in("purpose", ("register", "login", "reset", "mobile_change")), name="purpose"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    purpose: Mapped[str] = mapped_column(Text)
    mobile: Mapped[str] = mapped_column(Text, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    code_hash: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, server_default="5")
    expires_at: Mapped[datetime] = mapped_column(_ts())
    consumed_at: Mapped[datetime | None] = mapped_column(_ts())
    created_ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(_ts(), server_default=text("now()"))


class LoginEvent(Base):
    __tablename__ = "login_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    username_tried: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(_ts(), server_default=text("now()"))
