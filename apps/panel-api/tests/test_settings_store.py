import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from payamakyar.api.notifier import OutboxNotifier
from payamakyar.db.audit import verify_chain
from payamakyar.db.models import AuditEvent, Job, SystemMessage
from payamakyar.db.settings_store import DEFAULTS, SettingsStore

pytestmark = pytest.mark.integration


async def test_default_override_audit(db_session: AsyncSession) -> None:
    store = SettingsStore(db_session)
    assert await store.get("auth.max_failed_tries") == 5
    assert DEFAULTS["auth.lockout_seconds"] == 900
    await store.set("auth.max_failed_tries", 7, None, "tighten")
    assert await store.get("auth.max_failed_tries") == 7
    await store.set("auth.max_failed_tries", 9, None, None)
    rows = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.action == "settings.update")))
        .scalars()
        .all()
    )
    assert [(r.before, r.after) for r in rows][-2:] == [
        ({"value": 5}, {"value": 7}),
        ({"value": 7}, {"value": 9}),
    ]
    assert rows[-2].target_id == "auth.max_failed_tries"
    assert rows[-2].reason == "tighten"
    assert await verify_chain(db_session) is None
    await db_session.rollback()


async def test_unknown_key(db_session: AsyncSession) -> None:
    store = SettingsStore(db_session)
    with pytest.raises(ValueError):
        await store.set("nope.nope", 1, None, None)
    assert await store.get("nope.nope", "d") == "d"


async def test_type_mismatch(db_session: AsyncSession) -> None:
    store = SettingsStore(db_session)
    for bad in ("7", True, 1.5, None):
        with pytest.raises(ValueError):
            await store.set("auth.max_failed_tries", bad, None, None)


async def test_template_errors(db_session: AsyncSession) -> None:
    n = OutboxNotifier()
    with pytest.raises(ValueError):
        await n.send_sms(db_session, "09121234567", "otp", {})
    await n.send_sms(db_session, "09121234567", "otp", {"code": "${code.__class__}"})
    await db_session.rollback()


async def test_outbox_notifier(db_session: AsyncSession) -> None:
    await OutboxNotifier().send_sms(db_session, "09121234567", "otp", {"code": "123456"})
    msg = (
        await db_session.execute(select(SystemMessage).where(SystemMessage.template_key == "otp"))
    ).scalar_one()
    assert msg.body == "کد تأیید پیامک‌یار: 123456\nاین کد را به کسی ندهید."
    assert msg.to_mobile == "09121234567"
    job = (await db_session.execute(select(Job).where(Job.kind == "system_sms.send"))).scalar_one()
    assert job.payload == {"system_message_id": str(msg.id)}
    with pytest.raises(ValueError):
        await OutboxNotifier().send_sms(db_session, "09121234567", "zzz", {})
    await db_session.rollback()
