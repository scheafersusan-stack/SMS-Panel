"""Environment-driven settings (prefix ``PAYAMAKYAR_``)."""

from functools import lru_cache
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Fixed throwaway Fernet key; only ever used when env is dev or test.
DEV_SECRET_KEY = "ZGV2LW9ubHktcGF5YW1ha3lhci1rZXktMDAwMDAwMDA="  # noqa: S105
# Password of the dev database URL default; never acceptable in prod.
DEV_DB_PASSWORD = "payamakyar"  # noqa: S105
_PROD_REQUIRED = ("database_url", "redis_url", "secret_key", "public_base_url")


class PanelSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PAYAMAKYAR_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "postgresql+asyncpg://payamakyar:payamakyar@localhost:5432/payamakyar"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: SecretStr = SecretStr(DEV_SECRET_KEY)
    public_base_url: str = "http://localhost:8000"
    csrf_cookie_name: str = "pk_csrf"
    session_cookie_name: str = "pk_session"
    trusted_proxies: str = ""  # comma-separated CIDRs allowed to set X-Forwarded-For
    api_host: str = "127.0.0.1"
    api_port: Annotated[int, Field(ge=1, le=65535)] = 8000
    worker_poll_seconds: Annotated[float, Field(gt=0, le=3600)] = 1.0

    @model_validator(mode="after")
    def _check_prod(self) -> Self:
        if self.env == "prod":
            missing = [f for f in _PROD_REQUIRED if f not in self.model_fields_set]
            if missing:
                raise ValueError(f"required when PAYAMAKYAR_ENV=prod: {', '.join(missing)}")
        if self.env == "prod":
            if self.secret_key.get_secret_value() == DEV_SECRET_KEY:
                raise ValueError("PAYAMAKYAR_SECRET_KEY is the public dev key: set a real secret")
            if urlsplit(self.database_url).password == DEV_DB_PASSWORD:
                raise ValueError("PAYAMAKYAR_DATABASE_URL uses the dev database password")
        try:
            Fernet(self.secret_key.get_secret_value())
        except ValueError as exc:
            raise ValueError("secret_key must be a valid Fernet key") from exc
        return self


@lru_cache
def get_settings() -> PanelSettings:
    return PanelSettings()
