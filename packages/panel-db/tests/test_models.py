import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from payamakyar.db.models import AuditEvent, Job, Role, User

pytestmark = pytest.mark.integration


def _user(username: str, mobile: str) -> User:
    return User(username=username, mobile=mobile, password_hash="x")


async def test_username_case_insensitive_unique(db_session: AsyncSession) -> None:
    db_session.add(_user("Ali", "09120000001"))
    await db_session.commit()
    db_session.add(_user("ALI", "09120000002"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
    found = (await db_session.execute(select(User).where(User.username == "ali"))).scalar_one()
    assert found.username == "Ali"
    await db_session.delete(found)
    await db_session.commit()


async def test_user_defaults_and_check_constraint(db_session: AsyncSession) -> None:
    u = _user("defaults", "09120000003")
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    assert (u.kind, u.status, u.identity_state, u.mfa_method) == (
        "person",
        "active",
        "none",
        "none",
    )
    assert u.failed_logins == 0 and u.created_at.tzinfo is not None
    u.status = "bogus"
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_user_json_and_network_columns(db_session: AsyncSession) -> None:
    u = _user("netcols", "09120000004")
    u.allowed_ips = ["10.0.0.0/8", "192.168.1.5/32"]
    u.login_hours = [{"days": [0, 1], "from": "08:00", "to": "18:00"}]
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    assert u.login_hours[0]["to"] == "18:00"
    assert [str(n) for n in u.allowed_ips] == ["10.0.0.0/8", "192.168.1.5/32"]


async def test_job_dedupe_and_audit_bigserial(db_session: AsyncSession) -> None:
    db_session.add(Job(kind="k", dedupe_key="d1"))
    await db_session.commit()
    db_session.add(Job(kind="k", dedupe_key="d1"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
    a = AuditEvent(action="x", hash="h")
    db_session.add(a)
    await db_session.commit()
    assert isinstance(a.id, int)
    r = Role(name="r1", title_fa="نقش")
    db_session.add(r)
    await db_session.commit()
    assert r.is_staff is False
    assert r.id is not None and r.price is None
