import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.client import router
from app.core.limits import Limits
from app.db.models.chat import ChatMessage
from app.schemas.providers import ProviderInput
from app.services.mobile_auth import MobileAuth, digest
from app.services.user_service import ensure_user


@pytest.mark.asyncio
async def test_pair_single_use_and_refresh_replay_revokes_family(stack):
    auth = MobileAuth(stack.redis)
    code = await auth.pair(stack.user.id)
    tokens = await auth.exchange(code)
    with pytest.raises(HTTPException):
        await auth.exchange(code)
    record = await auth.verify(tokens["access_token"])
    assert record["user_id"] == stack.user.id
    assert tokens["access_token"].encode() not in await stack.redis.get(
        "mobile:access:" + digest(tokens["access_token"])
    )
    rotated = await auth.refresh(tokens["refresh_token"])
    assert rotated["access_token"] != tokens["access_token"]
    with pytest.raises(HTTPException):
        await auth.refresh(tokens["refresh_token"])
    with pytest.raises(HTTPException):
        await auth.verify(rotated["access_token"])


@pytest.mark.asyncio
async def test_expiration_logout_and_random_token(stack):
    auth = MobileAuth(stack.redis)
    code = await auth.pair(stack.user.id)
    assert 0 < await stack.redis.ttl("mobile:pair:" + digest(code)) <= 300
    await stack.redis.delete("mobile:pair:" + digest(code))
    with pytest.raises(HTTPException):
        await auth.exchange(code)
    tokens = await auth.issue(stack.user.id)
    await auth.logout(tokens["access_token"])
    with pytest.raises(HTTPException):
        await auth.verify(tokens["access_token"])
    with pytest.raises(HTTPException):
        await auth.verify("invalid-token")


def client_app(stack):
    app = FastAPI()
    app.include_router(router)
    app.state.sessions = stack.sessions
    app.state.redis = stack.redis
    app.state.secrets = stack.secrets
    app.state.limits = Limits(stack.redis)
    app.state.settings = SimpleNamespace(
        provider_timeout=30, max_response_bytes=2000000, max_models=1000
    )
    return app


@pytest.mark.asyncio
async def test_api_account_isolation_and_secret_omission(stack):
    await stack.session.commit()
    other = await ensure_user(
        stack.session, SimpleNamespace(id=999, username="other", first_name="Other", last_name=None)
    )
    await stack.session.commit()
    app = client_app(stack)
    auth = MobileAuth(stack.redis)
    token = (await auth.issue(stack.user.id))["access_token"]
    other_token = (await auth.issue(other.id))["access_token"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        assert (await client.get("/api/v1/me")).status_code == 401
        client.headers["Authorization"] = "Bearer " + token
        assert (await client.get("/api/v1/me")).json()["id"] == stack.user.id
        created = await client.post(
            "/api/v1/providers",
            json={
                "name": "OpenRouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_token": "sensitive-provider-key",
            },
        )
        assert created.status_code == 201
        assert "sensitive-provider-key" not in created.text
        ident = created.json()["id"]
        conversation = (await client.post("/api/v1/conversations", json={"title": "Test"})).json()[
            "id"
        ]
        client.headers["Authorization"] = "Bearer " + other_token
        assert (await client.get("/api/v1/providers")).json() == []
        assert (
            await client.get(f"/api/v1/conversations/{conversation}/messages")
        ).status_code == 404
        # Foreign IDs cannot reach the actual provider gateway.
        from app.core.exceptions import SafeError

        with pytest.raises(SafeError):
            await client.post(f"/api/v1/providers/{ident}/test")


@pytest.mark.asyncio
async def test_stream_real_chunks_history_idempotency_and_encryption(stack, monkeypatch):
    from app.db.models import Model
    from app.providers.adapters.openai import OpenAICompatibleAdapter
    from app.services.model_service import ModelService

    provider = await stack.service.create(
        ProviderInput(name="Test", base_url="https://openrouter.ai/api/v1", api_token="private-key")
    )
    model = Model(provider_id=provider.id, external_model_id="test-model", display_name="Model")
    stack.session.add(model)
    await stack.session.flush()
    await ModelService(stack.service).activate(model.id)
    await stack.session.commit()
    calls = []

    async def stream(self, ident, messages, max_tokens=1800):
        calls.append(messages)
        yield "مرحبا ", {}
        await asyncio.sleep(0)
        yield "بك", {"prompt_tokens": 3, "completion_tokens": 2}

    monkeypatch.setattr(OpenAICompatibleAdapter, "stream_chat_completion", stream)
    app = client_app(stack)
    token = (await MobileAuth(stack.redis).issue(stack.user.id))["access_token"]
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        headers={"Authorization": "Bearer " + token},
    ) as client:
        cid = (await client.post("/api/v1/conversations", json={})).json()["id"]
        data = {"conversation_id": cid, "request_id": str(uuid.uuid4()), "text": "هاي"}
        response = await client.post("/api/v1/chat/stream", json=data)
        assert "event: delta" in response.text, response.text
        assert "مرحبا " in response.text and "بك" in response.text
        assert "event: done" in response.text
        replay = await client.post("/api/v1/chat/stream", json=data)
        assert "event: snapshot" in replay.text
        assert len(calls) == 1
        messages = (await client.get(f"/api/v1/conversations/{cid}/messages")).json()
        assert messages[-1]["content"] == "مرحبا بك"
        assert messages[-1]["status"] == "COMPLETED"
    async with stack.sessions() as session:
        row = await session.scalar(select(ChatMessage).where(ChatMessage.role == "assistant"))
        assert "مرحبا" not in row.content_encrypted
        assert not await stack.redis.exists(f"mobile:generation:{stack.user.id}")


@pytest.mark.asyncio
async def test_client_validation_never_echoes_submitted_token(stack):
    from cryptography.fernet import Fernet

    from app.core.config import Settings
    from app.main import create_app

    settings = Settings(
        _env_file=None,
        app_env="development",
        telegram_bot_token="123456:abcdefghijklmnopqrstuvwxyzABCDE",
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379",
        master_encryption_key=Fernet.generate_key().decode(),
    )
    app = create_app(settings, start_bot=False)
    app.state.sessions, app.state.redis, app.state.limits = (
        stack.sessions,
        stack.redis,
        Limits(stack.redis),
    )
    token = (await MobileAuth(stack.redis).issue(stack.user.id))["access_token"]
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        headers={"Authorization": "Bearer " + token},
    ) as client:
        response = await client.post(
            "/api/v1/providers",
            json={
                "name": "",
                "base_url": "https://openrouter.ai/api/v1",
                "api_token": "this-is-sensitive",
            },
        )
        assert response.status_code == 422
        assert "this-is-sensitive" not in response.text
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_stream_cancellation_closes_upstream_and_releases_lock(stack, monkeypatch):
    from starlette.requests import Request

    from app.api.client import StreamInput, chat
    from app.db.models import Model
    from app.providers.adapters.openai import OpenAICompatibleAdapter
    from app.services.model_service import ModelService

    provider = await stack.service.create(
        ProviderInput(name="Test", base_url="https://openrouter.ai/api/v1", api_token="test-key")
    )
    model = Model(provider_id=provider.id, external_model_id="cancel-model", display_name="Cancel")
    stack.session.add(model)
    await stack.session.flush()
    await ModelService(stack.service).activate(model.id)
    await stack.session.commit()
    closed = asyncio.Event()

    async def upstream(self, *args, **kwargs):
        try:
            yield "partial", {}
            await asyncio.sleep(3600)
        finally:
            closed.set()

    monkeypatch.setattr(OpenAICompatibleAdapter, "stream_chat_completion", upstream)
    app = client_app(stack)
    from app.db.models.chat import Conversation

    conversation = Conversation(id=str(uuid.uuid4()), user_id=stack.user.id, title="")
    stack.session.add(conversation)
    await stack.session.commit()
    response = await chat(
        StreamInput(conversation_id=conversation.id, request_id=uuid.uuid4(), text="hi"),
        Request({"type": "http", "app": app}),
        stack.user.id,
    )
    generator = response.body_iterator
    await anext(generator)  # started
    assert "event: delta" in await anext(generator)
    await generator.aclose()
    assert closed.is_set()
    assert not await stack.redis.exists(f"mobile:generation:{stack.user.id}")
    async with stack.sessions() as session:
        row = await session.scalar(select(ChatMessage).where(ChatMessage.role == "assistant"))
        assert row.status == "CANCELLED"
        assert stack.secrets.decrypt(row.content_encrypted) == "partial"
