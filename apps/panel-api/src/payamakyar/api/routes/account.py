"""The signed-in user's own account: active sessions."""

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy import select

from payamakyar.api import sessions
from payamakyar.api.deps import (
    CurrentSession,
    SessionDep,
    client_ip,
    get_clock,
    get_settings_dep,
)
from payamakyar.api.errors import ApiError
from payamakyar.core.settings import PanelSettings
from payamakyar.db import audit
from payamakyar.db.models import Session

router = APIRouter(prefix="/account", tags=["account"])

Clock = Annotated[Callable[[], datetime], Depends(get_clock)]


class SessionOut(BaseModel):
    id: uuid.UUID
    ip: str | None
    user_agent: str | None
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    current: bool
    impersonated: bool


class SessionList(BaseModel):
    sessions: list[SessionOut]


@router.get("/sessions")
async def list_sessions(current: CurrentSession, s: SessionDep, clock: Clock) -> SessionList:
    now = clock()
    idle = await sessions.idle_lifetime(s)
    rows = (
        (
            await s.execute(
                select(Session)
                .where(
                    Session.user_id == current.user_id,
                    Session.revoked_at.is_(None),
                    Session.expires_at > now,
                    Session.last_seen_at > now - timedelta(seconds=idle),
                )
                .order_by(Session.last_seen_at.desc(), Session.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return SessionList(
        sessions=[
            SessionOut(
                id=row.id,
                ip=str(row.ip) if row.ip is not None else None,
                user_agent=row.user_agent,
                created_at=row.created_at,
                last_seen_at=row.last_seen_at,
                expires_at=row.expires_at,
                current=row.id == current.id,
                impersonated=row.impersonator_id is not None,
            )
            for row in rows
        ]
    )


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(
    session_id: uuid.UUID,
    current: CurrentSession,
    request: Request,
    response: Response,
    s: SessionDep,
    clock: Clock,
    settings: Annotated[PanelSettings, Depends(get_settings_dep)],
) -> None:
    row = (
        await s.execute(
            select(Session).where(Session.id == session_id, Session.user_id == current.user_id)
        )
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        raise ApiError(
            404,
            "SESSION_NOT_FOUND",
            "نشست یافت نشد",
            "این نشست وجود ندارد یا پیش‌تر بسته شده است.",
            "/session_id",
        )
    row.revoked_at = clock()
    await audit.record(
        s,
        actor_id=current.user_id,
        actor_ip=client_ip(request) or None,
        action="session.revoke",
        target_type="session",
        target_id=str(row.id),
    )
    if row.id == current.id:
        sessions.clear_cookies(response, settings)
