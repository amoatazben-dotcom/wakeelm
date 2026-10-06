from types import SimpleNamespace

import pytest_asyncio
from cryptography.fernet import Fernet
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.limits import Limits
from app.core.security import SecretManager
from app.db.base import Base
from app.db.session import database
from app.services.provider_service import ProviderService
from app.services.user_service import ensure_user


class MockHTTP:
    def __init__(self):
        self.calls = []
        self.error = None
        self.data = {"data": [{"id": "remote/model", "name": "Remote"}]}

    async def request(self, method, url, headers, payload=None):
        self.calls.append((method, url, headers, payload))
        if self.error:
            raise self.error
        return (
            self.data
            if method == "GET"
            else {
                "choices": [{"message": {"content": "OK"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1},
            }
        )


@pytest_asyncio.fixture
async def stack(monkeypatch):
    async def public(url):
        return {"8.8.8.8"}

    monkeypatch.setattr("app.services.provider_service.public_addresses", public)
    engine, _ = database("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        user = await ensure_user(
            session, SimpleNamespace(id=123, username="tester", first_name="Test", last_name=None)
        )
        redis = FakeRedis()
        http = MockHTTP()
        secrets = SecretManager(Fernet.generate_key().decode())
        service = ProviderService(session, user.id, secrets, http, Limits(redis))
        yield SimpleNamespace(
            session=session,
            user=user,
            service=service,
            secrets=secrets,
            http=http,
            redis=redis,
            sessions=sessions,
        )
        await redis.aclose()
    await engine.dispose()
