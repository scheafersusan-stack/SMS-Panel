"""System SMS (OTP, login notices) written to an outbox; phase 2 delivers them."""

from string import Template
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from payamakyar.db.jobs import enqueue
from payamakyar.db.models import SystemMessage
from payamakyar.db.settings_store import SettingsStore

JOB_KIND = "system_sms.send"


class SystemNotifier(Protocol):
    async def send_sms(
        self, s: AsyncSession, to_mobile: str, template_key: str, params: dict[str, str]
    ) -> None: ...


class OutboxNotifier:
    """Renders ``system_sms.<template_key>`` and queues it. Never logs the body (it holds OTPs)."""

    async def send_sms(
        self, s: AsyncSession, to_mobile: str, template_key: str, params: dict[str, str]
    ) -> None:
        try:
            template = await SettingsStore(s).get(f"system_sms.{template_key}")
        except KeyError as exc:
            raise ValueError(f"unknown system sms template: {template_key}") from exc
        try:
            body = Template(str(template)).substitute(params)
        except (KeyError, ValueError) as exc:
            raise ValueError(f"cannot render system sms template: {template_key}") from exc
        message = SystemMessage(to_mobile=to_mobile, template_key=template_key, body=body)
        s.add(message)
        await s.flush()
        await enqueue(s, JOB_KIND, {"system_message_id": str(message.id)})


def get_notifier() -> SystemNotifier:
    """The request's notifier; tests override this dependency."""
    return OutboxNotifier()


Notifier = Annotated[SystemNotifier, Depends(get_notifier)]
