"""User-scoped native client API. Reuses the platform provider/routing gateway."""

import asyncio
import json
import uuid
from contextlib import suppress
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.exceptions import SafeError
from app.db.models import Model, Provider, User
from app.db.models.chat import ChatMessage, Conversation
from app.providers.http import SafeHTTP
from app.routing.preferences import RoutingPreferences
from app.routing.schemas import RoutingPolicy
from app.schemas.providers import ProviderInput
from app.services.mobile_auth import MobileAuth
from app.services.model_service import ModelService
from app.services.provider_service import ProviderService

router = APIRouter(prefix="/api/v1")


class Credential(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    value: str = Field(min_length=20, max_length=512, repr=False)


async def auth(request: Request):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer ") or len(header) > 520:
        raise HTTPException(401, "AUTH_REQUIRED")
    record = await MobileAuth(request.app.state.redis).verify(header[7:])
    async with request.app.state.sessions() as session:
        user = await session.get(User, record["user_id"])
        if not user or not user.is_active:
            raise HTTPException(401, "AUTH_REQUIRED")
    await request.app.state.limits.window(f"mobile:user:{user.id}", 120)
    return user.id


UserId = Annotated[int, Depends(auth)]


async def services(request, user_id):
    async with request.app.state.sessions() as session:
        state = request.app.state
        providers = ProviderService(
            session,
            user_id,
            state.secrets,
            SafeHTTP(state.settings.provider_timeout, state.settings.max_response_bytes),
            state.limits,
            state.settings.max_models,
        )
        yield session, providers, ModelService(providers, state.settings)
        await session.commit()


@router.post("/auth/exchange")
async def exchange(data: Credential, request: Request):
    await request.app.state.limits.window("mobile:exchange:" + request.client.host, 10)
    return await MobileAuth(request.app.state.redis).exchange(data.value)


@router.post("/auth/refresh")
async def refresh(data: Credential, request: Request):
    await request.app.state.limits.window("mobile:refresh:" + request.client.host, 60)
    return await MobileAuth(request.app.state.redis).refresh(data.value)


@router.post("/auth/logout")
async def logout(request: Request, user_id: UserId):
    await MobileAuth(request.app.state.redis).logout(request.headers["Authorization"][7:])
    return {"ok": True}


@router.get("/me")
async def me(request: Request, user_id: UserId):
    async with request.app.state.sessions() as session:
        user = await session.get(User, user_id)
        return {
            "id": user.id,
            "name": user.first_name or user.telegram_username or "",
            "language": user.language,
        }


@router.get("/health/client")
async def health(request: Request):
    try:
        from sqlalchemy import text

        async with request.app.state.sessions() as session:
            await session.execute(text("SELECT 1"))
        await request.app.state.redis.ping()
    except Exception:
        raise HTTPException(503, "OFFLINE") from None
    return {"status": "ONLINE", "api_version": 1, "streaming": "sse"}


def provider_dto(row):
    return {
        "id": row.id,
        "name": row.name,
        "base_url": row.base_url,
        "status": row.status,
        "token_hint": row.token_hint,
    }


def model_dto(row):
    return {
        "id": row.id,
        "provider_id": row.provider_id,
        "name": row.display_name,
        "external_id": row.external_model_id,
        "status": row.status,
        "pricing": row.pricing_json,
        "capabilities": row.capabilities_json,
        "metadata": row.metadata_json,
    }


@router.get("/providers")
async def providers(request: Request, user_id: UserId):
    async for session, service, _ in services(request, user_id):
        return [provider_dto(p) for p in await service.list()]


@router.post("/providers", status_code=201)
async def add_provider(data: ProviderInput, request: Request, user_id: UserId):
    async for session, service, _ in services(request, user_id):
        row = await service.create(data)
        await session.commit()
        return provider_dto(row)


@router.put("/providers/{ident}")
async def update_provider(ident: int, data: ProviderInput, request: Request, user_id: UserId):
    async for session, service, _ in services(request, user_id):
        row = await service.update(ident, data)
        await session.commit()
        return provider_dto(row)


@router.delete("/providers/{ident}")
async def delete_provider(ident: int, request: Request, user_id: UserId):
    async for session, service, _ in services(request, user_id):
        await service.delete(ident)
        await session.commit()
        return {"ok": True}


@router.post("/providers/{ident}/test")
@router.post("/providers/{ident}/models")
async def discover(ident: int, request: Request, user_id: UserId):
    async for session, service, _ in services(request, user_id):
        await service.discover(ident)
        row = await service.owned.provider(ident)
        await session.commit()
        return provider_dto(row)


@router.get("/models")
async def models(request: Request, user_id: UserId):
    async for session, service, _ in services(request, user_id):
        rows = await session.scalars(
            select(Model)
            .join(Provider)
            .where(Provider.user_id == user_id, Provider.status != "DISABLED")
            .order_by(Model.id)
            .limit(5000)
        )
        return [model_dto(m) for m in rows]


@router.get("/models/{ident}")
async def model(ident: int, request: Request, user_id: UserId):
    async for session, service, _ in services(request, user_id):
        return model_dto(await service.owned.model(ident))


@router.post("/models/{ident}/select")
async def choose_model(ident: int, request: Request, user_id: UserId):
    async for session, service, model_service in services(request, user_id):
        await model_service.activate(ident)
        await session.commit()
        return {"active_model_id": ident}


class RoutingInput(BaseModel):
    policy: RoutingPolicy
    fallback_enabled: bool = False


@router.get("/routing/preferences")
async def routing(request: Request, user_id: UserId):
    async for session, _, model_service in services(request, user_id):
        value = dict(await RoutingPreferences(session, user_id).get())
        try:
            value["active_model_id"] = (await model_service.active()).id
        except SafeError:
            value["active_model_id"] = None
        from app.platform.flags import FeatureFlags

        value["automatic_enabled"] = await FeatureFlags(session, user_id).enabled(
            "experimental_router"
        )
        return value


@router.put("/routing/preferences")
async def set_routing(data: RoutingInput, request: Request, user_id: UserId):
    async for session, _, __ in services(request, user_id):
        if data.policy != RoutingPolicy.MANUAL_ONLY:
            from app.platform.flags import FeatureFlags

            await FeatureFlags(session, user_id).require("experimental_router")
        value = await RoutingPreferences(session, user_id).set(data.policy, data.fallback_enabled)
        await session.commit()
        return value


async def owned_conversation(session, user_id, ident):
    row = await session.scalar(
        select(Conversation).where(Conversation.id == ident, Conversation.user_id == user_id)
    )
    if row is None:
        raise HTTPException(404, "NOT_FOUND")
    return row


class ConversationInput(BaseModel):
    title: str = Field(default="", max_length=200)


@router.get("/conversations")
async def conversations(request: Request, user_id: UserId):
    async with request.app.state.sessions() as session:
        rows = await session.scalars(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .limit(200)
        )
        return [{"id": r.id, "title": r.title} for r in rows]


@router.post("/conversations", status_code=201)
async def new_conversation(data: ConversationInput, request: Request, user_id: UserId):
    async with request.app.state.sessions() as session:
        row = Conversation(id=str(uuid.uuid4()), user_id=user_id, title=data.title)
        session.add(row)
        await session.commit()
        return {"id": row.id, "title": row.title}


def message_dto(row, secrets):
    return {
        "id": row.id,
        "conversation_id": row.conversation_id,
        "request_id": row.request_id,
        "role": row.role,
        "content": secrets.decrypt(row.content_encrypted),
        "status": row.status,
    }


@router.get("/conversations/{ident}/messages")
async def messages(ident: str, request: Request, user_id: UserId):
    async with request.app.state.sessions() as session:
        await owned_conversation(session, user_id, ident)
        rows = await session.scalars(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == ident)
            .order_by(ChatMessage.created_at, ChatMessage.id)
            .limit(500)
        )
        return [message_dto(r, request.app.state.secrets) for r in rows]


class StreamInput(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    conversation_id: uuid.UUID
    request_id: uuid.UUID
    text: str = Field(min_length=1, max_length=16000)


def event(kind, data):
    return "event: " + kind + "\ndata: " + json.dumps(data, ensure_ascii=False) + "\n\n"


@router.post("/chat/stream")
async def chat(data: StreamInput, request: Request, user_id: UserId):
    # One active generation per account, including duplicate/reconnected requests.
    state = request.app.state
    lock_key = f"mobile:generation:{user_id}"
    lock_owner = uuid.uuid4().hex
    if not await state.redis.set(lock_key, lock_owner, nx=True, ex=240):
        raise HTTPException(409, "GENERATION_ACTIVE")

    async def generate():
        content, assistant_id = "", str(uuid.uuid4())
        async with state.sessions() as session:
            try:
                conversation = await owned_conversation(session, user_id, str(data.conversation_id))
                existing = await session.scalar(
                    select(ChatMessage).where(
                        ChatMessage.conversation_id == conversation.id,
                        ChatMessage.request_id == str(data.request_id),
                        ChatMessage.role == "assistant",
                    )
                )
                if existing:
                    # Safe reconnect retrieves persisted result, never pays for a second generation.
                    yield event("snapshot", message_dto(existing, state.secrets))
                    yield event("done", {"status": existing.status})
                    return
                providers = ProviderService(
                    session,
                    user_id,
                    state.secrets,
                    SafeHTTP(state.settings.provider_timeout, state.settings.max_response_bytes),
                    state.limits,
                    state.settings.max_models,
                )
                models = ModelService(providers, state.settings)
                await state.limits.cooldown(f"chat:{user_id}", 3)
                from app.platform.usage import QuotaEngine

                await QuotaEngine(session, user_id).reserve("message")
                selected = await models.route(data.text)
                history = list(
                    await session.scalars(
                        select(ChatMessage)
                        .where(
                            ChatMessage.conversation_id == conversation.id,
                            ChatMessage.status == "COMPLETED",
                        )
                        .order_by(ChatMessage.created_at.desc())
                        .limit(20)
                    )
                )
                history.reverse()
                prompt = [
                    {"role": r.role, "content": state.secrets.decrypt(r.content_encrypted)}
                    for r in history
                ]
                prompt.append({"role": "user", "content": data.text})
                from app.platform.redaction import user_sanitizer

                sanitizer = await user_sanitizer(session, user_id, state.secrets, state.settings)
                prompt = json.loads(sanitizer.clean(prompt))
                user_message = ChatMessage(
                    id=str(uuid.uuid4()),
                    conversation_id=conversation.id,
                    request_id=str(data.request_id),
                    role="user",
                    content_encrypted=state.secrets.encrypt(data.text),
                    status="COMPLETED",
                )
                assistant = ChatMessage(
                    id=assistant_id,
                    conversation_id=conversation.id,
                    request_id=str(data.request_id),
                    role="assistant",
                    content_encrypted=state.secrets.encrypt(""),
                    status="STREAMING",
                )
                session.add_all([user_message, assistant])
                from app.db.base import now

                conversation.updated_at = now()
                await session.commit()
                yield event("started", {"id": assistant_id, "model_id": selected.id})
                queue = asyncio.Queue(maxsize=32)

                async def invoke(chosen):
                    nonlocal content
                    # Fallback replaces partial output rather than concatenating two answers.
                    if chosen.id != selected.id:
                        content = ""
                        await queue.put(event("fallback", {"model_id": chosen.id}))
                    provider = await providers.owned.provider(chosen.provider_id)
                    adapter = providers.adapter(provider)
                    if provider.api_base_url:
                        adapter.api_url = provider.api_base_url
                    elif not provider.base_url.endswith("/v1"):
                        await adapter.discover_models()
                    usage = {}
                    async for delta, counted in adapter.stream_chat_completion(
                        chosen.external_model_id, prompt
                    ):
                        content += delta
                        usage.update(counted)
                        if len(content) > 200000:
                            raise SafeError("INVALID_RESPONSE")
                        if delta:
                            await queue.put(event("delta", {"text": delta}))
                    if not content:
                        raise SafeError("INVALID_RESPONSE")
                    from app.indexing.chunker import token_estimate

                    usage.setdefault("prompt_tokens", token_estimate(json.dumps(prompt)))
                    usage.setdefault("completion_tokens", token_estimate(content))
                    return content, usage

                async def execute():
                    from app.indexing.chunker import token_estimate

                    try:
                        await models.routing.execute(
                            selected, invoke, token_estimate(json.dumps(prompt)), 1800
                        )
                    finally:
                        if not asyncio.current_task().cancelling():
                            await queue.put(None)

                task = asyncio.create_task(execute())
                try:
                    while True:
                        try:
                            item = await asyncio.wait_for(queue.get(), timeout=10)
                        except TimeoutError:
                            yield ": keepalive\n\n"
                            continue
                        if item is None:
                            break
                        yield item
                    await task
                    assistant.content_encrypted = state.secrets.encrypt(content)
                    assistant.status = "COMPLETED"
                    await session.commit()
                    yield event("done", {"status": "COMPLETED"})
                finally:
                    if not task.done():
                        task.cancel()
                        with suppress(asyncio.CancelledError):
                            await task
            except (asyncio.CancelledError, GeneratorExit):
                await session.rollback()
                row = await session.get(ChatMessage, assistant_id)
                if row:
                    row.content_encrypted, row.status = state.secrets.encrypt(content), "CANCELLED"
                    await session.commit()
                raise
            except Exception as exc:
                await session.rollback()
                row = await session.get(ChatMessage, assistant_id)
                if row:
                    row.content_encrypted, row.status = state.secrets.encrypt(content), "FAILED"
                    await session.commit()
                yield event(
                    "error", {"code": exc.code if isinstance(exc, SafeError) else "INTERNAL"}
                )
            finally:
                # Compare-and-delete prevents an old request from releasing a newer lock.
                await state.redis.eval(
                    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
                    1,
                    lock_key,
                    lock_owner,
                )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
