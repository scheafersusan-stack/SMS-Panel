import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from payamakyar.core.settings import PanelSettings, get_settings


def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    for k in list(os.environ):
        if k.startswith("PAYAMAKYAR_"):
            monkeypatch.delenv(k)


def test_dev_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean(monkeypatch)
    s = PanelSettings(_env_file=None)
    assert s.env == "dev"
    # Session lifetimes live in the settings store (session.*), not the environment.
    assert not hasattr(s, "session_idle_seconds")
    assert not hasattr(s, "session_absolute_seconds")
    assert (s.csrf_cookie_name, s.session_cookie_name) == ("pk_csrf", "pk_session")
    Fernet(s.secret_key.get_secret_value())


def test_settings_prod_requires_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean(monkeypatch)
    monkeypatch.setenv("PAYAMAKYAR_ENV", "prod")
    monkeypatch.setenv("PAYAMAKYAR_DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("PAYAMAKYAR_REDIS_URL", "redis://h/0")
    monkeypatch.setenv("PAYAMAKYAR_PUBLIC_BASE_URL", "https://x.example")
    with pytest.raises(ValidationError):
        PanelSettings(_env_file=None)


@pytest.mark.parametrize("missing", ["DATABASE_URL", "REDIS_URL", "PUBLIC_BASE_URL"])
def test_prod_requires_all(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    _clean(monkeypatch)
    env = {
        "ENV": "prod",
        "SECRET_KEY": Fernet.generate_key().decode(),
        "DATABASE_URL": "postgresql+asyncpg://u:p@h/db",
        "REDIS_URL": "redis://h/0",
        "PUBLIC_BASE_URL": "https://x.example",
    }
    del env[missing]
    for k, v in env.items():
        monkeypatch.setenv(f"PAYAMAKYAR_{k}", v)
    with pytest.raises(ValidationError):
        PanelSettings(_env_file=None)


def test_prod_ok_and_bad_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean(monkeypatch)
    for k, v in {
        "ENV": "prod",
        "SECRET_KEY": Fernet.generate_key().decode(),
        "DATABASE_URL": "postgresql+asyncpg://u:p@h/db",
        "REDIS_URL": "redis://h/0",
        "PUBLIC_BASE_URL": "https://x.example",
    }.items():
        monkeypatch.setenv(f"PAYAMAKYAR_{k}", v)
    assert PanelSettings(_env_file=None).env == "prod"
    monkeypatch.setenv("PAYAMAKYAR_SECRET_KEY", "not-a-fernet-key")
    with pytest.raises(ValidationError):
        PanelSettings(_env_file=None)


def test_get_settings_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean(monkeypatch)
    get_settings.cache_clear()
    assert get_settings() is get_settings()
    get_settings.cache_clear()
