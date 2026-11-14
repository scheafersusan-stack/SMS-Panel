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


def _prod_env(monkeypatch: pytest.MonkeyPatch, **over: str) -> None:
    _clean(monkeypatch)
    env = {
        "ENV": "prod",
        "SECRET_KEY": Fernet.generate_key().decode(),
        "DATABASE_URL": "postgresql+asyncpg://u:Real-Pw-1@h/db",
        "REDIS_URL": "redis://h/0",
        "PUBLIC_BASE_URL": "https://x.example",
        **over,
    }
    for k, v in env.items():
        monkeypatch.setenv(f"PAYAMAKYAR_{k}", v)


def test_prod_rejects_dev_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from payamakyar.core.settings import DEV_SECRET_KEY

    _prod_env(monkeypatch, SECRET_KEY=DEV_SECRET_KEY)
    with pytest.raises(ValidationError, match="dev key"):
        PanelSettings(_env_file=None)


def test_prod_rejects_dev_database_password(monkeypatch: pytest.MonkeyPatch) -> None:
    _prod_env(monkeypatch, DATABASE_URL="postgresql+asyncpg://payamakyar:payamakyar@h/db")
    with pytest.raises(ValidationError, match="dev database password"):
        PanelSettings(_env_file=None)


def test_dev_secrets_fine_outside_prod_and_real_ones_pass_in_prod(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prod_env(monkeypatch)
    assert PanelSettings(_env_file=None).env == "prod"
    _clean(monkeypatch)
    assert PanelSettings(_env_file=None).env == "dev"


def test_serve_and_worker_settings_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean(monkeypatch)
    s = PanelSettings(_env_file=None)
    assert (s.api_host, s.api_port, s.worker_poll_seconds) == ("127.0.0.1", 8000, 1.0)
    monkeypatch.setenv("PAYAMAKYAR_API_PORT", "70000")
    with pytest.raises(ValidationError):
        PanelSettings(_env_file=None)
    monkeypatch.setenv("PAYAMAKYAR_API_PORT", "9000")
    monkeypatch.setenv("PAYAMAKYAR_WORKER_POLL_SECONDS", "0")
    with pytest.raises(ValidationError):
        PanelSettings(_env_file=None)


def test_validation_error_does_not_echo_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings errors end up in logs: they must not quote the offending input values."""
    _clean(monkeypatch)
    secret = "S3cr3tK"  # short, so pydantic would not truncate it away
    monkeypatch.setenv("PAYAMAKYAR_SECRET_KEY", secret)
    monkeypatch.setenv("PAYAMAKYAR_DATABASE_URL", "postgresql://u:Pw9@db/x")
    with pytest.raises(ValidationError) as info:  # model validator: not a Fernet key
        PanelSettings(_env_file=None)
    assert "Fernet" in str(info.value)
    assert secret not in str(info.value)
    assert "Pw9" not in str(info.value)
    monkeypatch.setenv("PAYAMAKYAR_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("PAYAMAKYAR_API_PORT", secret)  # a secret pasted into the wrong variable
    with pytest.raises(ValidationError) as info:
        PanelSettings(_env_file=None)
    assert "api_port" in str(info.value)
    assert secret not in str(info.value)
