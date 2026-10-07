import json

from pydantic import SecretStr
from sqlalchemy import select

from app.db.models import Provider
from app.db.models.integrations import GitHubConnection, MCPCredential, MCPServer
from app.integrations.sanitizer import ExternalToolOutputSanitizer


async def user_sanitizer(session, user_id, crypto, settings=None):
    secrets = list(getattr(crypto, "_key_material", ()))

    def collect(value):
        if isinstance(value, SecretStr):
            secrets.append(value.get_secret_value())
        elif isinstance(value, str):
            secrets.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                collect(item)

    for model, fields in [
        (Provider, ["encrypted_api_token", "extra_headers_encrypted"]),
        (GitHubConnection, ["encrypted_token"]),
        (MCPServer, ["encrypted_auth_config"]),
        (MCPCredential, ["encrypted_access_token", "encrypted_refresh_token"]),
    ]:
        for row in await session.scalars(select(model).where(model.user_id == user_id)):
            for field in fields:
                value = getattr(row, field)
                if value:
                    plain = crypto.decrypt(value)
                    secrets.append(plain)
                    try:
                        collect(json.loads(plain))
                    except ValueError:
                        pass
    if settings:
        for field in (
            settings.__class__.model_fields if hasattr(settings.__class__, "model_fields") else []
        ):
            value = getattr(settings, field)
            if isinstance(value, SecretStr) or (
                isinstance(value, list) and any(isinstance(v, SecretStr) for v in value)
            ):
                collect(value)
    return ExternalToolOutputSanitizer(secrets=secrets)
