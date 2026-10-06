from typing import Literal

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    app_name: str = "Telegram AI Agent"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    telegram_bot_token: SecretStr
    database_url: SecretStr
    redis_url: SecretStr
    master_encryption_key: SecretStr
    bot_mode: Literal["polling", "webhook"] = "polling"
    bot_default_language: Literal["ar", "en"] = "ar"
    log_level: str = "INFO"
    public_base_url: str | None = None
    webhook_secret: SecretStr | None = None
    provider_timeout: float = Field(default=30, gt=0, le=60)
    max_response_bytes: int = Field(default=2_000_000, ge=1024, le=10_000_000)
    max_models: int = Field(default=1000, ge=1, le=10000)

    @field_validator("master_encryption_key")
    @classmethod
    def valid_key(cls, value):
        Fernet(value.get_secret_value().encode())
        return value

    @model_validator(mode="after")
    def webhook_config(self):
        if self.bot_mode == "webhook" and (
            not self.public_base_url
            or not self.public_base_url.startswith("https://")
            or not self.webhook_secret
        ):
            raise ValueError("Webhook requires HTTPS PUBLIC_BASE_URL and WEBHOOK_SECRET")
        if self.webhook_secret:
            import re

            if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", self.webhook_secret.get_secret_value()):
                raise ValueError("Invalid webhook secret format")
        return self

    @property
    def async_database_url(self):
        url = self.database_url.get_secret_value()
        if url.startswith(("postgres://", "postgresql://")):
            return "postgresql+asyncpg://" + url.split("://", 1)[1]
        return url
