"""Admin audit viewer: the hash-chained audit log, its verification and login events."""

import base64
import binascii
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from payamakyar.api.deps import SessionDep, require
from payamakyar.api.errors import validation_failed
from payamakyar.core.masking import mask_mobile
from payamakyar.db import audit
from payamakyar.db.models import AuditEvent, LoginEvent

router = APIRouter(tags=["admin-audit"], dependencies=[require("audit.view")])

PAGE_SIZE = 50


def _encode(value: int | uuid.UUID) -> str:
    raw = str(value).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _decode(cursor: str) -> str:
    try:
        return base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("ascii")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise validation_failed("نشانگر صفحه‌بندی نامعتبر است.", "/cursor") from None


def _int_cursor(cursor: str) -> int:
    raw = _decode(cursor)
    if not raw.isdigit() or len(raw) > 18:
        raise validation_failed("نشانگر صفحه‌بندی نامعتبر است.", "/cursor")
    return int(raw)


def _uuid_cursor(cursor: str) -> uuid.UUID:
    try:
        return uuid.UUID(_decode(cursor))
    except ValueError:
        raise validation_failed("نشانگر صفحه‌بندی نامعتبر است.", "/cursor") from None


def _aware(at: datetime | None, name: str) -> datetime | None:
    if at is not None and at.tzinfo is None:
        raise validation_failed(
            "زمان باید همراه با منطقه زمانی (مثلاً +03:30 یا Z) باشد.", f"/{name}"
        )
    return at


class AuditItem(BaseModel):
    id: int
    at: datetime
    actor_id: uuid.UUID | None
    actor_ip: str | None
    action: str
    target_type: str | None
    target_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str | None


class AuditPage(BaseModel):
    items: list[AuditItem]
    next_cursor: str | None


class VerifyOut(BaseModel):
    ok: bool
    first_bad_id: int | None


class LoginEventItem(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    username_tried: str | None
    ip: str | None
    user_agent: str | None
    outcome: str
    at: datetime


class LoginEventPage(BaseModel):
    items: list[LoginEventItem]
    next_cursor: str | None


Cursor = Annotated[str | None, Query(max_length=100)]
FromTime = Annotated[datetime | None, Query(alias="from")]
ToTime = Annotated[datetime | None, Query(alias="to")]


@router.get("/audit")
async def list_audit(
    s: SessionDep,
    actor: uuid.UUID | None = None,
    action: Annotated[str | None, Query(max_length=200)] = None,
    target_type: Annotated[str | None, Query(max_length=100)] = None,
    from_: FromTime = None,
    to: ToTime = None,
    cursor: Cursor = None,
) -> AuditPage:
    q = select(AuditEvent)
    if actor is not None:
        q = q.where(AuditEvent.actor_id == actor)
    if action:
        q = q.where(AuditEvent.action == action)
    if target_type:
        q = q.where(AuditEvent.target_type == target_type)
    if (lo := _aware(from_, "from")) is not None:
        q = q.where(AuditEvent.at >= lo)
    if (hi := _aware(to, "to")) is not None:
        q = q.where(AuditEvent.at < hi)
    if cursor:
        q = q.where(AuditEvent.id < _int_cursor(cursor))
    rows = list((await s.execute(q.order_by(AuditEvent.id.desc()).limit(PAGE_SIZE + 1))).scalars())
    more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]
    return AuditPage(
        items=[
            AuditItem(
                id=r.id,
                at=r.at,
                actor_id=r.actor_id,
                actor_ip=r.actor_ip,
                action=r.action,
                target_type=r.target_type,
                target_id=r.target_id,
                before=r.before,
                after=r.after,
                reason=r.reason,
            )
            for r in rows
        ],
        next_cursor=_encode(rows[-1].id) if more else None,
    )


@router.get("/audit/verify")
async def verify_audit(s: SessionDep) -> VerifyOut:
    bad = await audit.verify_chain(s)
    return VerifyOut(ok=bad is None, first_bad_id=bad)


@router.get("/login-events")
async def list_login_events(
    s: SessionDep,
    user_id: uuid.UUID | None = None,
    outcome: Annotated[str | None, Query(max_length=100)] = None,
    from_: FromTime = None,
    to: ToTime = None,
    cursor: Cursor = None,
) -> LoginEventPage:
    q = select(LoginEvent)
    if user_id is not None:
        q = q.where(LoginEvent.user_id == user_id)
    if outcome:
        q = q.where(LoginEvent.outcome == outcome)
    if (lo := _aware(from_, "from")) is not None:
        q = q.where(LoginEvent.at >= lo)
    if (hi := _aware(to, "to")) is not None:
        q = q.where(LoginEvent.at < hi)
    if cursor:
        q = q.where(LoginEvent.id < _uuid_cursor(cursor))
    rows = list((await s.execute(q.order_by(LoginEvent.id.desc()).limit(PAGE_SIZE + 1))).scalars())
    more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]
    return LoginEventPage(
        items=[
            LoginEventItem(
                id=r.id,
                user_id=r.user_id,
                username_tried=mask_mobile(r.username_tried) if r.username_tried else None,
                ip=str(r.ip) if r.ip is not None else None,
                user_agent=r.user_agent,
                outcome=r.outcome,
                at=r.at,
            )
            for r in rows
        ],
        next_cursor=_encode(rows[-1].id) if more else None,
    )
