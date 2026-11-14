"""Pytest fixtures for Postgres and Redis (loaded via the root ``conftest.py``).

``pg_url`` uses ``PAYAMAKYAR_TEST_DATABASE_URL`` (a superuser URL to an existing server) or
starts a throwaway cluster with ``initdb``/``pg_ctl``. When running as root, initdb is run as
the ``postgres`` OS user (or ``nobody``) inside a directory that user owns.
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
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from payamakyar.db import migrate
from payamakyar.db.engine import async_url, create_engine, session_factory

_BINDIR_DEFAULT = Path("/usr/lib/postgresql/16/bin")


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
        pytest.skip("PostgreSQL binaries not found and PAYAMAKYAR_TEST_DATABASE_URL not set")
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
    pytest.skip("running as root and no unprivileged user (postgres/nobody) exists")


def _run_as(user: str | None, argv: list[str]) -> subprocess.CompletedProcess[str]:
    if user:
        argv = ["runuser", "-u", user, "--", *argv]
    return subprocess.run(argv, capture_output=True, text=True, check=True)  # noqa: S603


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
    started = False
    try:
        _run_as(user, [str(bindir / "initdb"), "-D", str(data), "-U", "postgres", "-A", "trust"])
        opts = f"-p {port} -k {root} -c listen_addresses=127.0.0.1 -c fsync=off"
        _run_as(
            user,
            [
                str(bindir / "pg_ctl"),
                "-D",
                str(data),
                "-o",
                opts,
                "-l",
                str(root / "log"),
                "-w",
                "start",
            ],
        )
        started = True
        yield f"postgresql://postgres@127.0.0.1:{port}/postgres"
    finally:
        if started:
            _run_as(user, [str(bindir / "pg_ctl"), "-D", str(data), "-m", "immediate", "stop"])
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="module")
def db_url(pg_url: str) -> Iterator[str]:
    """A fresh database (migrated to head) per test module; dropped afterwards."""
    name = f"pk_test_{uuid.uuid4().hex[:12]}"
    base, _, _ = pg_url.rpartition("/")
    asyncio.run(_admin(pg_url, f'CREATE DATABASE "{name}"'))
    url = f"{base}/{name}"
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
        yield env
        return
    exe = shutil.which("redis-server")
    if exe is None:
        pytest.skip("redis-server not found and PAYAMAKYAR_TEST_REDIS_URL not set")
    port = _free_port()
    with tempfile.TemporaryDirectory(prefix="payamakyar-redis-") as tmp:
        proc = subprocess.Popen(  # noqa: S603
            [exe, "--port", str(port), "--save", "", "--appendonly", "no", "--dir", tmp],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                    break
                except OSError:
                    time.sleep(0.05)
            yield f"redis://127.0.0.1:{port}/0"
        finally:
            proc.terminate()
            proc.wait(timeout=10)


__all__ = ["async_url", "db_session", "db_url", "pg_url", "redis_url"]
