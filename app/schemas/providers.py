import re

from pydantic import BaseModel, Field, SecretStr, field_validator

from app.providers.url import BaseURLResolver


class ProviderInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    base_url: str = Field(max_length=2048)
    api_token: SecretStr
    headers: dict[str, str] = Field(default_factory=dict)
    provider_type: str | None = None

    @field_validator("base_url")
    @classmethod
    def url(cls, value):
        return BaseURLResolver.normalize(value)

    @field_validator("api_token")
    @classmethod
    def token(cls, value):
        raw = value.get_secret_value()
        if not raw or len(raw) > 8192 or "\r" in raw or "\n" in raw:
            raise ValueError("Invalid token")
        return value

    @field_validator("headers")
    @classmethod
    def safe_headers(cls, value):
        if len(value) > 20:
            raise ValueError("Too many headers")
        for k, v in value.items():
            if (
                not re.fullmatch(r"[A-Za-z0-9-]{1,100}", k)
                or k.lower()
                in {
                    "host",
                    "content-length",
                    "connection",
                    "transfer-encoding",
                    "proxy-authorization",
                }
                or len(v) > 8192
                or "\r" in v
                or "\n" in v
            ):
                raise ValueError("Invalid header")
        return value
