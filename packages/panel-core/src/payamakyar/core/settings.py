"""Environment-driven settings (prefix ``PAYAMAKYAR_``)."""

from functools import lru_cache
from typing import Literal, Self

from cryptography.fernet import Fernet
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Fixed throwaway Fernet key; only ever used when env is dev or test.
_DEV_SECRET_KEY = "ZGV2LW9ubHktcGF5YW1ha3lhci1rZXktMDAwMDAwMDA="  # noqa: S105
_PROD_REQUIRED = ("database_url", "redis_url", "secret_key", "public_base_url")


class PanelSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PAYAMAKYAR_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "postgresql+asyncpg://payamakyar:payamakyar@localhost:5432/payamakyar"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: SecretStr = SecretStr(_DEV_SECRET_KEY)
    public_base_url: str = "http://localhost:8000"
    csrf_cookie_name: str = "pk_csrf"
    session_cookie_name: str = "pk_session"
    trusted_proxies: str = ""  # comma-separated CIDRs allowed to set X-Forwarded-For

    @model_validator(mode="after")
    def _check_prod(self) -> Self:
        if self.env == "prod":
            missing = [f for f in _PROD_REQUIRED if f not in self.model_fields_set]
            if missing:
                raise ValueError(f"required when PAYAMAKYAR_ENV=prod: {', '.join(missing)}")
        try:
            Fernet(self.secret_key.get_secret_value())
        except ValueError as exc:
            raise ValueError("secret_key must be a valid Fernet key") from exc
        return self


@lru_cache
def get_settings() -> PanelSettings:
    return PanelSettings()
