"""Programmatic Alembic runner (also used by the test fixtures)."""

from pathlib import Path

from alembic import command
from alembic.config import Config

from payamakyar.db.engine import async_url

_INI = Path(__file__).with_name("alembic.ini")


def make_config(url: str | None = None) -> Config:
    cfg = Config(str(_INI))
    cfg.set_main_option("script_location", str(_INI.with_name("alembic")))
    if url:
        cfg.set_main_option("sqlalchemy.url", async_url(url).replace("%", "%%"))
    return cfg


def upgrade(url: str | None, revision: str = "head") -> None:
    command.upgrade(make_config(url), revision)


def downgrade(url: str | None, revision: str = "base") -> None:
    command.downgrade(make_config(url), revision)
