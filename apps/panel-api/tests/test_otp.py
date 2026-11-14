import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from payamakyar.api import otp
from payamakyar.api.errors import ApiError
from payamakyar.db.models import OtpChallenge

pytestmark = pytest.mark.integration

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


async def test_issue_stores_hash_not_code(db_session: AsyncSession) -> None:
    cid, code = await otp.issue(db_session, "register", "989121110001", ip="203.0.113.5", now=T0)
    assert len(code) == 6
    assert code.isdigit()
    row = (
        await db_session.execute(select(OtpChallenge).where(OtpChallenge.id == cid))
    ).scalar_one()
    assert row.code_hash == hashlib.sha256((code + str(cid)).encode()).hexdigest()
    assert code not in row.code_hash
    assert row.expires_at == T0 + timedelta(seconds=120)
    assert row.max_attempts == 5
    assert row.mobile == "989121110001"
    assert str(row.created_ip) == "203.0.113.5"
    await db_session.rollback()


async def test_check_success_consumes_and_is_single_use(db_session: AsyncSession) -> None:
    cid, code = await otp.issue(db_session, "register", "989121110002", ip=None, now=T0)
    row = await otp.check(db_session, cid, code, "register", now=T0 + timedelta(seconds=5))
    assert row.consumed_at == T0 + timedelta(seconds=5)
    with pytest.raises(ApiError) as err:
        await otp.check(db_session, cid, code, "register", now=T0 + timedelta(seconds=6))
    assert (err.value.status, err.value.code) == (400, "OTP_INVALID")
    await db_session.rollback()


async def test_wrong_purpose_and_unknown_id_invalid(db_session: AsyncSession) -> None:
    cid, code = await otp.issue(db_session, "register", "989121110003", ip=None, now=T0)
    with pytest.raises(ApiError) as err:
        await otp.check(db_session, cid, code, "login", now=T0)
    assert err.value.code == "OTP_INVALID"
    with pytest.raises(ApiError) as err2:
        await otp.check(db_session, uuid.uuid4(), code, "register", now=T0)
    assert err2.value.code == "OTP_INVALID"
    await db_session.rollback()


async def test_expired(db_session: AsyncSession) -> None:
    cid, code = await otp.issue(db_session, "register", "989121110004", ip=None, now=T0)
    with pytest.raises(ApiError) as err:
        await otp.check(db_session, cid, code, "register", now=T0 + timedelta(seconds=121))
    assert (err.value.status, err.value.code) == (400, "OTP_EXPIRED")
    await db_session.rollback()


async def test_attempts_persist_and_lock(db_session: AsyncSession) -> None:
    cid, code = await otp.issue(db_session, "register", "989121110005", ip=None, now=T0)
    await db_session.commit()
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        with pytest.raises(ApiError) as err:
            await otp.check(db_session, cid, wrong, "register", now=T0)
        assert err.value.code == "OTP_INVALID"
        await db_session.rollback()  # what the request dependency does on error
    row = (
        await db_session.execute(select(OtpChallenge).where(OtpChallenge.id == cid))
    ).scalar_one()
    assert row.attempts == 5
    # Even the right code is refused once attempts are exhausted.
    with pytest.raises(ApiError) as err2:
        await otp.check(db_session, cid, code, "register", now=T0)
    assert (err2.value.status, err2.value.code) == (400, "OTP_TOO_MANY_ATTEMPTS")
    await db_session.rollback()
