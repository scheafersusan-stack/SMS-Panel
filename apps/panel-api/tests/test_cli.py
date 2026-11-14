import logging

import pytest
from fastapi import FastAPI
from sqlalchemy import select

from payamakyar.api import cli
from payamakyar.core.passwords import password_problems, verify_password
from payamakyar.core.settings import PanelSettings
from payamakyar.db.models import AuditEvent, Job, Role, SystemMessage, User, UserRole


def test_generated_passwords_meet_policy() -> None:
    pws = {cli.generate_password() for _ in range(50)}
    assert len(pws) == 50
    assert all(password_problems(p) == [] for p in pws)


def test_parser_subcommands() -> None:
    p = cli.build_parser()
    assert p.parse_args(["serve", "--port", "9000"]).port == 9000
    assert p.parse_args(["create-admin", "--username", "a", "--mobile", "b"]).mobile == "b"
    with pytest.raises(SystemExit):
        p.parse_args(["create-admin"])


@pytest.mark.integration
async def test_create_admin(app: FastAPI) -> None:
    pw = await cli.create_admin(app.state.session_factory, "cli_admin", "۰۹۱۲۱۱۱۲۲۳۳")
    async with app.state.session_factory() as s:
        user = (await s.execute(select(User).where(User.username == "cli_admin"))).scalar_one()
        assert user.mobile == "989121112233" and user.status == "active"
        assert user.mfa_method == "none" and verify_password(user.password_hash, pw)
        roles = (
            await s.execute(
                select(Role.name)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == user.id)
            )
        ).scalars()
        assert list(roles) == ["admin"]
        ev = (
            await s.execute(select(AuditEvent).where(AuditEvent.action == "user.create_admin"))
        ).scalar_one()
        assert pw not in str(ev.after) and ev.target_id == str(user.id)
    with pytest.raises(cli.AdminBootstrapError, match="already"):
        await cli.create_admin(app.state.session_factory, "cli_admin", "09121112244")
    with pytest.raises(cli.AdminBootstrapError, match="mobile"):
        await cli.create_admin(app.state.session_factory, "cli_admin2", "12345")
    with pytest.raises(cli.AdminBootstrapError, match="username"):
        await cli.create_admin(app.state.session_factory, "x", "09121112255")


@pytest.mark.integration
async def test_system_sms_handler_masks_and_prod_refuses(
    app: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    async with app.state.session_factory() as s:
        msg = SystemMessage(to_mobile="989121112299", template_key="otp", body="کد 123456")
        s.add(msg)
        await s.flush()
        job = Job(kind="system_sms.send", payload={"system_message_id": str(msg.id)})
        dev = cli.make_system_sms_handler(PanelSettings(env="test"))
        with caplog.at_level(logging.INFO, logger="payamakyar.api.cli"):
            await dev(s, job)
        assert "989121112299" not in caplog.text and "123456" not in caplog.text
        assert "would send" in caplog.text
        prod = cli.make_system_sms_handler(PanelSettings.model_construct(env="prod"))
        with pytest.raises(NotImplementedError):
            await prod(s, job)


@pytest.mark.integration
def test_main_migrate_and_create_admin(
    db_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from payamakyar.core.settings import get_settings

    monkeypatch.setenv("PAYAMAKYAR_DATABASE_URL", db_url)
    get_settings.cache_clear()
    try:
        assert cli.main(["migrate"]) == 0
        argv = ["create-admin", "--username", "main_admin", "--mobile", "09125550000"]
        assert cli.main(argv) == 0
        out = capsys.readouterr().out
        assert "one-time password" in out
        assert cli.main(argv) == 1  # duplicate
        assert "already registered" in capsys.readouterr().err
    finally:
        get_settings.cache_clear()
