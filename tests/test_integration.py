"""Opt-in checks against disposable PostgreSQL and Redis services."""

import os
import uuid
from types import SimpleNamespace

import pytest
from conftest import MockHTTP
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from sqlalchemy import select

from app.core.config import Settings
from app.core.limits import Limits
from app.core.security import SecretManager
from app.db.models import Model, ModelHealthCheck, Provider, ProviderHealthCheck, UserSetting
from app.db.session import database
from app.main import create_app
from app.schemas.providers import ProviderInput
from app.services.model_service import ModelService
from app.services.provider_service import ProviderService
from app.services.user_service import ensure_user

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL") or not os.getenv("TEST_REDIS_URL"),
    reason="Set TEST_DATABASE_URL and TEST_REDIS_URL for disposable integration services",
)


def settings():
    return Settings(
        database_url=os.environ["TEST_DATABASE_URL"],
        redis_url=os.environ["TEST_REDIS_URL"],
        telegram_bot_token="123456:dummy",
        master_encryption_key=Fernet.generate_key().decode(),
        _env_file=None,
    )


def test_real_dependency_readiness():
    with TestClient(create_app(settings(), start_bot=False)) as client:
        result = client.get("/ready")
        assert result.status_code == 200 and all(result.json()["checks"].values())


async def test_real_postgres_redis_lifecycle(monkeypatch):
    async def public(url):
        return {"8.8.8.8"}

    monkeypatch.setattr("app.services.provider_service.public_addresses", public)
    config = settings()
    engine, sessions = database(config.async_database_url)
    redis = Redis.from_url(config.redis_url.get_secret_value())
    secrets = SecretManager(config.master_encryption_key.get_secret_value())
    try:
        async with sessions() as session:
            telegram_id = uuid.uuid4().int % 10**14
            user = await ensure_user(
                session,
                SimpleNamespace(
                    id=telegram_id, username=None, first_name="Integration", last_name=None
                ),
            )
            user_id = user.id
            providers = ProviderService(session, user.id, secrets, MockHTTP(), Limits(redis))
            provider = await providers.create(
                ProviderInput(
                    name="Integration",
                    base_url="https://example.com/v1",
                    api_token="integration-secret",
                )
            )
            provider_id = provider.id
            assert await providers.discover(provider_id) is None
            models = ModelService(providers)
            page, _ = await models.page()
            model_id = page[0].id
            await models.activate(model_id)
            await models.test(model_id)
            await session.commit()
        async with sessions() as fresh:
            provider = await fresh.get(Provider, provider_id)
            assert secrets.decrypt(provider.encrypted_api_token) == "integration-secret"
            assert (await fresh.get(Model, model_id)).status == "AVAILABLE"
            setting = await fresh.scalar(select(UserSetting).where(UserSetting.user_id == user_id))
            assert setting.value_json["active_model_id"] == model_id
            service = ProviderService(fresh, user_id, secrets, MockHTTP(), Limits(redis))
            assert await ModelService(service).chat("Hi") == "OK"
            await service.delete(provider_id)
            await fresh.commit()
        async with sessions() as fresh:
            assert await fresh.get(Provider, provider_id) is None
            assert await fresh.get(Model, model_id) is None
            assert not list(
                await fresh.scalars(
                    select(ProviderHealthCheck).where(
                        ProviderHealthCheck.provider_id == provider_id
                    )
                )
            )
            assert not list(
                await fresh.scalars(
                    select(ModelHealthCheck).where(ModelHealthCheck.model_id == model_id)
                )
            )
    finally:
        await redis.aclose()
        await engine.dispose()
