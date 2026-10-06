from datetime import datetime, timezone

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, DeleteMessage, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.bot.dispatcher import create_dispatcher
from app.core.config import Settings
from app.core.limits import Limits
from app.db.models import Model, Provider, UserSetting
from app.db.models import User as DBUser


class TelegramSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.messages = []
        self.deleted = []

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, SendMessage):
            self.messages.append(method)
            return Message(
                message_id=len(self.messages),
                date=datetime.now(timezone.utc),
                chat=Chat(id=int(method.chat_id), type="private"),
                text=method.text,
            )
        if isinstance(method, DeleteMessage):
            self.deleted.append(method.message_id)
            return True
        if isinstance(method, AnswerCallbackQuery):
            return True
        raise AssertionError(type(method))

    async def stream_content(self, *args, **kwargs):
        yield b""


async def test_telegram_acceptance_flow(stack, monkeypatch, tmp_path):
    async def public(url):
        return {"8.8.8.8"}

    monkeypatch.setattr("app.bot.handlers.providers.public_addresses", public)
    await stack.session.commit()
    session = TelegramSession()
    bot = Bot("123456:dummy", session=session)
    dispatcher = create_dispatcher(
        stack.redis,
        stack.sessions,
        stack.secrets,
        stack.http,
        Limits(stack.redis),
        Settings(
            telegram_bot_token="123456:dummy",
            database_url="sqlite+aiosqlite:///:memory:",
            redis_url="redis://localhost",
            master_encryption_key=Fernet.generate_key().decode(),
            workspace_storage_root=str(tmp_path / "workspaces"),
            _env_file=None,
        ),
    )
    sender = User(id=123, is_bot=False, first_name="Test", username="tester")
    index = 0

    async def send(text=None, callback=None):
        nonlocal index
        index += 1
        await stack.redis.delete("limit:bot:123")
        msg = Message(
            message_id=index,
            date=datetime.now(timezone.utc),
            chat=Chat(id=123, type="private"),
            from_user=sender,
            text=text,
        )
        update = (
            Update(
                update_id=index,
                callback_query=CallbackQuery(
                    id=str(index),
                    from_user=sender,
                    chat_instance="test",
                    message=msg,
                    data=callback,
                ),
            )
            if callback
            else Update(update_id=index, message=msg)
        )
        await dispatcher.feed_update(bot, update)
        assert "Could not complete" not in session.messages[-1].text
        assert "تعذر إكمال" not in session.messages[-1].text

    await send("/start")
    assert "مرحبًا" in session.messages[-1].text
    await send(callback="menu:settings")
    await send(callback="language:en")
    assert session.messages[-1].text == "Saved."
    await send(callback="language:ar")
    await send(callback="menu:providers")
    await send(callback="provider:add")
    await send("Provider")
    await send("https://example.com/v1")
    await send("top-secret-api-token")
    assert index in session.deleted
    assert "top-secret-api-token" not in str(await stack.redis.keys("*"))
    for key in await stack.redis.keys("*data"):
        assert b"top-secret-api-token" not in await stack.redis.get(key)
    await send(callback="onboard:skip")
    assert "top-secret-api-token" not in session.messages[-1].text
    await send(callback="onboard:save")
    async with stack.sessions() as fresh:
        provider = await fresh.scalar(select(Provider))
        model = await fresh.scalar(select(Model))
        assert provider.status == "ONLINE" and model is not None
        assert "top-secret-api-token" not in provider.encrypted_api_token
        model_id = model.id
        provider_id = provider.id
    await send(callback="models:refresh:0:0")
    await send(callback="models:all:0:0")
    await send(callback=f"model:view:{model_id}")
    await send(callback=f"model:activate:{model_id}")
    await send(callback="menu:chat")
    await send("Hello")
    assert session.messages[-1].text == "OK"
    stack.http.error = __import__("app.core.exceptions", fromlist=["SafeError"]).SafeError(
        "AUTH_FAILED"
    )
    await stack.redis.delete("limit:chat:1")
    await send("Hello again")
    assert "المفتاح غير صالح" in session.messages[-1].text
    async with stack.sessions() as fresh:
        assert (await fresh.scalar(select(DBUser))).language == "ar"
        assert (await fresh.scalar(select(UserSetting))).value_json["active_model_id"] == model_id
    await send(callback=f"provider:delete:{provider_id}")
    async with stack.sessions() as fresh:
        assert await fresh.get(Provider, provider_id) is not None
    await send(callback=f"provider:confirmed:{provider_id}")
    async with stack.sessions() as fresh:
        assert await fresh.get(Provider, provider_id) is None
    await bot.session.close()


async def test_telegram_project_agent_queue_status_cancel(stack, tmp_path):
    from test_workspaces import project_zip

    from app.db.models.agent import AgentJob
    from app.schemas.providers import ProviderInput
    from app.services.model_service import ModelService
    from app.services.workspace_service import WorkspaceService

    provider = await stack.service.create(
        ProviderInput(
            name="Agent provider", base_url="https://example.com/v1", api_token="test-token"
        )
    )
    await stack.service.discover(provider.id)
    model = await stack.session.scalar(select(Model))
    await ModelService(stack.service).activate(model.id)
    settings = Settings(
        telegram_bot_token="123456:dummy",
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost",
        master_encryption_key=Fernet.generate_key().decode(),
        workspace_storage_root=str(tmp_path / "workspaces"),
        _env_file=None,
    )
    workspace = await WorkspaceService(
        stack.session, stack.user.id, settings, stack.secrets, Limits(stack.redis)
    ).ingest("project.zip", project_zip({"main.py": "VALUE = 1\n"}))
    await stack.session.commit()
    transport = TelegramSession()
    bot = Bot("123456:dummy", session=transport)
    dispatcher = create_dispatcher(
        stack.redis, stack.sessions, stack.secrets, stack.http, Limits(stack.redis), settings
    )
    sender = User(id=123, is_bot=False, first_name="Test")
    index = 0

    async def send(text=None, callback=None):
        nonlocal index
        index += 1
        await stack.redis.delete("limit:bot:123")
        message = Message(
            message_id=index,
            date=datetime.now(timezone.utc),
            chat=Chat(id=123, type="private"),
            from_user=sender,
            text=text,
        )
        update = (
            Update(
                update_id=index,
                callback_query=CallbackQuery(
                    id=str(index),
                    from_user=sender,
                    chat_instance="test",
                    message=message,
                    data=callback,
                ),
            )
            if callback
            else Update(update_id=index, message=message)
        )
        await dispatcher.feed_update(bot, update)
        assert "تعذر إكمال" not in transport.messages[-1].text

    await send(callback=f"agent:start:{workspace.id}")
    assert "اختر وضع" in transport.messages[-1].text
    await send(callback=f"mode:SUGGEST:{workspace.id}")
    await send("Change VALUE to 2")
    async with stack.sessions() as fresh:
        job = await fresh.scalar(select(AgentJob))
        ident = job.id
        assert (
            job.status == "QUEUED"
            and job.mode == "SUGGEST"
            and "Change VALUE" not in job.request_text
        )
    await send(callback=f"job:status:{ident}")
    await send(callback=f"job:cancel:{ident}")
    async with stack.sessions() as fresh:
        assert (await fresh.get(AgentJob, ident)).status == "CANCELLED"
    assert "أُلغيت" in transport.messages[-1].text
    await bot.session.close()
