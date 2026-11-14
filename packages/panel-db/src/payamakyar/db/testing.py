"""Pytest fixtures for Postgres and Redis (loaded via the root ``conftest.py``).

``pg_url`` uses ``PAYAMAKYAR_TEST_DATABASE_URL`` (a superuser URL to an existing server) or
starts a throwaway cluster with ``initdb``/``pg_ctl``. When running as root, initdb is run as
the ``postgres`` OS user (or ``nobody``) inside a directory that user owns.

``redis_url`` uses ``PAYAMAKYAR_TEST_REDIS_URL`` (db 15 when the URL names none; db 0 is
refused because tests flush their db) or starts a throwaway ``redis-server``. Tests empty
Redis only through ``flush_test_redis``, which refuses db 0.

Without the servers or binaries the integration tests skip, unless
``PAYAMAKYAR_TEST_REQUIRE_SERVICES=1`` (CI, ``make ci``) turns the skip into a failure.
"""

import asyncio
import os
import pwd
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from payamakyar.db import audit, migrate
from payamakyar.db.engine import async_url, create_engine, session_factory

_BINDIR_DEFAULT = Path("/usr/lib/postgresql/16/bin")
TEST_REDIS_DB = 15
REQUIRE_SERVICES_ENV = "PAYAMAKYAR_TEST_REQUIRE_SERVICES"


def service_unavailable(reason: str) -> NoReturn:
    """Skip, or fail when ``PAYAMAKYAR_TEST_REQUIRE_SERVICES=1`` (CI must not skip)."""
    if os.environ.get(REQUIRE_SERVICES_ENV, "") == "1":
        pytest.fail(f"{reason} ({REQUIRE_SERVICES_ENV}=1)", pytrace=False)
    pytest.skip(reason)


def redis_test_url(url: str) -> str:
    """``url`` with db 15 when it names no db; a URL naming db 0 is refused."""
    parsed = urlsplit(url)
    path = parsed.path.strip("/")
    if not path:
        return urlunsplit(parsed._replace(path=f"/{TEST_REDIS_DB}"))
    if path == "0":
        raise pytest.UsageError(
            "PAYAMAKYAR_TEST_REDIS_URL names db 0: tests flush their Redis db, so point it at "
            f"a dedicated one (default /{TEST_REDIS_DB})"
        )
    return url


async def flush_test_redis(redis: Any) -> None:
    """``FLUSHDB`` on the test Redis, refusing db 0 (which may hold real data)."""
    db = int(redis.connection_pool.connection_kwargs.get("db", 0) or 0)
    if db == 0:
        raise RuntimeError("refusing to flush Redis db 0 in tests; use a dedicated db")
    await redis.flushdb()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _bindir() -> Path:
    if (_BINDIR_DEFAULT / "initdb").exists():
        return _BINDIR_DEFAULT
    try:
        out = subprocess.run(
            ["pg_config", "--bindir"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        service_unavailable(
            "PostgreSQL binaries not found and PAYAMAKYAR_TEST_DATABASE_URL not set"
        )
    return Path(out)


def _os_user() -> str | None:
    """Return the unprivileged OS user to run postgres as, or None if not root."""
    if os.geteuid() != 0:
        return None
    for name in ("postgres", "nobody"):
        try:
            pwd.getpwnam(name)
        except KeyError:
            continue
        return name
    service_unavailable("running as root and no unprivileged user (postgres/nobody) exists")


def with_database(url: str, name: str) -> str:
    """Return ``url`` pointing at database ``name``."""
    return make_url(url).set(database=name).render_as_string(hide_password=False)


def _run_as(
    user: str | None, argv: list[str], log: Path | None = None
) -> subprocess.CompletedProcess[str]:
    if user:
        argv = ["runuser", "-u", user, "--", *argv]
    proc = subprocess.run(argv, capture_output=True, text=True, check=False)  # noqa: S603
    if proc.returncode != 0:
        tail = ""
        if log is not None and log.exists():
            tail = "\n--- server log tail ---\n" + "\n".join(
                log.read_text(errors="replace").splitlines()[-30:]
            )
        pytest.fail(
            f"{' '.join(argv)} exited {proc.returncode}\nstdout: {proc.stdout}\n"
            f"stderr: {proc.stderr}{tail}",
            pytrace=False,
        )
    return proc


async def _admin(url: str, sql: str) -> None:
    conn = await asyncpg.connect(url.replace("+asyncpg", ""))
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def pg_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Superuser URL (``postgresql://``) of a running server."""
    env = os.environ.get("PAYAMAKYAR_TEST_DATABASE_URL")
    if env:
        yield env
        return
    bindir = _bindir()
    user = _os_user()
    root = Path(tempfile.mkdtemp(prefix="payamakyar-pg-"))
    if user:
        shutil.chown(root, user=user)
    data = root / "data"
    port = _free_port()
    log = root / "log"
    try:
        _run_as(user, [str(bindir / "initdb"), "-D", str(data), "-U", "postgres", "-A", "trust"])
        opts = f"-p {port} -k {root} -c listen_addresses=127.0.0.1 -c fsync=off"
        try:
            _run_as(
                user,
                [
                    str(bindir / "pg_ctl"),
                    "-D",
                    str(data),
                    "-o",
                    opts,
                    "-l",
                    str(log),
                    "-w",
                    "start",
                ],
                log,
            )
            yield f"postgresql://postgres@127.0.0.1:{port}/postgres"
        finally:
            if (data / "PG_VERSION").exists():
                # Always attempt a stop (a failed start may still have spawned the postmaster).
                subprocess.run(  # noqa: S603
                    [
                        *(["runuser", "-u", user, "--"] if user else []),
                        str(bindir / "pg_ctl"),
                        "-D",
                        str(data),
                        "-m",
                        "immediate",
                        "stop",
                    ],
                    capture_output=True,
                    check=False,
                )
    finally:
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="module")
def db_url(pg_url: str) -> Iterator[str]:
    """A fresh database (migrated to head) per test module; dropped afterwards."""
    name = f"pk_test_{uuid.uuid4().hex[:12]}"
    asyncio.run(_admin(pg_url, f'CREATE DATABASE "{name}"'))
    url = with_database(pg_url, name)
    try:
        migrate.upgrade(url)
        yield url
    finally:
        asyncio.run(_admin(pg_url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture
async def db_session(db_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_engine(db_url)
    try:
        async with session_factory(engine)() as session:
            yield session
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    env = os.environ.get("PAYAMAKYAR_TEST_REDIS_URL")
    if env:
        yield redis_test_url(env)
        return
    exe = shutil.which("redis-server")
    if exe is None:
        service_unavailable("redis-server not found and PAYAMAKYAR_TEST_REDIS_URL not set")
    port = _free_port()
    with tempfile.TemporaryDirectory(prefix="payamakyar-redis-") as tmp:
        proc = subprocess.Popen(  # noqa: S603
            [exe, "--port", str(port), "--save", "", "--appendonly", "no", "--dir", tmp],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 10
            while True:
                try:
                    socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                    break
                except OSError:
                    if time.monotonic() > deadline or proc.poll() is not None:
                        pytest.fail("redis-server did not become reachable within 10s")
                    time.sleep(0.05)
            yield f"redis://127.0.0.1:{port}/{TEST_REDIS_DB}"
        finally:
            proc.terminate()
            proc.wait(timeout=10)


class _WithTestActions(frozenset[str]):
    """``AUDIT_ACTIONS`` plus any action under the given test prefixes."""

    prefixes: tuple[str, ...] = ()

    def __contains__(self, item: object) -> bool:
        if frozenset.__contains__(self, item):
            return True
        return isinstance(item, str) and bool(self.prefixes) and item.startswith(self.prefixes)


@pytest.fixture
def allow_test_audit_actions(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """``allow("t.", "page.")`` lets this test record made-up actions under those prefixes;
    the real registry is restored afterwards."""

    def allow(*prefixes: str) -> None:
        registry = _WithTestActions(audit.AUDIT_ACTIONS)
        registry.prefixes = prefixes
        monkeypatch.setattr(audit, "AUDIT_ACTIONS", registry)

    return allow


__all__ = [
    "allow_test_audit_actions",
    "async_url",
    "db_session",
    "db_url",
    "flush_test_redis",
    "pg_url",
    "redis_test_url",
    "redis_url",
    "service_unavailable",
    "with_database",
]
