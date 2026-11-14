"""Command line: ``python -m payamakyar.api serve|worker|migrate|create-admin``."""

import argparse
import asyncio
import contextlib
import logging
import os
import secrets
import string
import sys
from collections.abc import Sequence

import uvicorn
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payamakyar.api.notifier import JOB_KIND
from payamakyar.core.logging import configure_logging
from payamakyar.core.masking import mask_mobile
from payamakyar.core.passwords import hash_password, password_problems
from payamakyar.core.phone import InvalidMobile, normalize_mobile
from payamakyar.core.settings import PanelSettings, get_settings
from payamakyar.db import audit, migrate
from payamakyar.db.engine import create_engine, session_factory
from payamakyar.db.jobs import Handler, Job, Worker
from payamakyar.db.models import Role, SystemMessage, User, UserRole

log = logging.getLogger("payamakyar.api.cli")

_USERNAME_CHARS = frozenset(string.ascii_letters + string.digits + "_.")
_SPECIALS = "!@#$%^&*-_=+?"
_PASSWORD_LENGTH = 20


class AdminBootstrapError(Exception):
    """A user-facing failure of ``create-admin`` (bad input or a duplicate)."""


def generate_password(length: int = _PASSWORD_LENGTH) -> str:
    """A random password that always satisfies ``password_problems``."""
    alphabet = string.ascii_letters + string.digits + _SPECIALS
    while True:
        candidate = "".join(secrets.choice(alphabet) for _ in range(length))
        if not password_problems(candidate):
            return candidate


async def create_admin(
    factory: async_sessionmaker[AsyncSession], username: str, mobile: str
) -> str:
    """Create an active ``admin`` user and return its one-time password.

    The admin has no second factor yet: admin routes answer ``MFA_REQUIRED`` until the
    account enables TOTP. The audit row ``user.create_admin`` carries no secret.
    """
    if not (3 <= len(username) <= 32 and set(username) <= _USERNAME_CHARS):
        raise AdminBootstrapError("username must be 3-32 chars of letters, digits, _ or .")
    try:
        canonical = normalize_mobile(mobile)
    except InvalidMobile as exc:
        raise AdminBootstrapError("invalid mobile number") from exc
    password = generate_password()
    try:
        async with factory() as s:
            role_id = (
                await s.execute(select(Role.id).where(Role.name == "admin"))
            ).scalar_one_or_none()
            if role_id is None:
                raise AdminBootstrapError("role 'admin' is missing: run `make migrate` first")
            user = User(
                username=username,
                mobile=canonical,
                password_hash=hash_password(password),
                status="active",
                kind="person",
            )
            s.add(user)
            await s.flush()
            s.add(UserRole(user_id=user.id, role_id=role_id))
            await audit.record(
                s,
                actor_id=None,
                actor_ip=None,
                action="user.create_admin",
                target_type="user",
                target_id=str(user.id),
                after={"username": username, "roles": ["admin"]},
            )
            await s.commit()
    except IntegrityError as exc:
        raise AdminBootstrapError("username or mobile is already registered") from exc
    return password


def _create_admin_main(args: argparse.Namespace) -> int:
    async def run() -> str:
        engine = create_engine(get_settings().database_url)
        try:
            return await create_admin(session_factory(engine), args.username, args.mobile)
        finally:
            await engine.dispose()

    try:
        password = asyncio.run(run())
    except AdminBootstrapError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        f"admin created: {args.username}\n"
        f"one-time password (shown once, change it after first login): {password}\n"
        "next: log in, then enable TOTP under account security; admin routes need it."
    )
    return 0


def make_system_sms_handler(settings: PanelSettings) -> Handler:
    """Phase 1 stand-in for operator dispatch: logs a masked "would send" line (dev/test).

    The message stays ``pending``. Outside dev/test it raises, so jobs retry instead of
    silently dropping OTPs until the real dispatcher exists (a later phase).
    """

    async def handle(s: AsyncSession, job: Job) -> None:
        if settings.env == "prod":
            raise NotImplementedError("system SMS dispatch is not implemented yet")
        message_id = job.payload.get("system_message_id")
        message = await s.get(SystemMessage, message_id) if message_id else None
        if message is None:
            log.warning("system message missing", extra={"job_id": str(job.id)})
            return
        log.info(
            "dev: would send system sms",
            extra={"to": mask_mobile(message.to_mobile), "template": message.template_key},
        )

    return handle


def _worker_main() -> int:
    settings = get_settings()

    async def run() -> None:
        engine = create_engine(settings.database_url)
        try:
            worker = Worker(
                [JOB_KIND],
                make_system_sms_handler(settings),
                session_factory=session_factory(engine),
                poll_interval=float(os.environ.get("PAYAMAKYAR_WORKER_POLL_SECONDS", "1.0")),
            )
            log.info("worker started", extra={"kinds": worker.kinds})
            await worker.run_forever()
        finally:
            await engine.dispose()

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run())
    return 0


def _serve_main(args: argparse.Namespace) -> int:
    uvicorn.run(
        "payamakyar.api.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        log_config=None,
        proxy_headers=False,  # trust is decided by PAYAMAKYAR_TRUSTED_PROXIES only
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m payamakyar.api")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the HTTP API (uvicorn)")
    serve.add_argument("--host", default=os.environ.get("PAYAMAKYAR_API_HOST", "127.0.0.1"))
    serve.add_argument(
        "--port", type=int, default=int(os.environ.get("PAYAMAKYAR_API_PORT", "8000"))
    )
    sub.add_parser("worker", help="run the background job worker")
    sub.add_parser("migrate", help="alembic upgrade head (PAYAMAKYAR_DATABASE_URL)")
    admin = sub.add_parser("create-admin", help="create an admin with a one-time password")
    admin.add_argument("--username", required=True)
    admin.add_argument("--mobile", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(os.environ.get("PAYAMAKYAR_LOG_LEVEL", "INFO"))
    match args.command:
        case "serve":
            return _serve_main(args)
        case "worker":
            return _worker_main()
        case "migrate":
            migrate.upgrade(get_settings().database_url)
            return 0
        case _:
            return _create_admin_main(args)
