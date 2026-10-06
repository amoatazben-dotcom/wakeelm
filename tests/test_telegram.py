from datetime import datetime, timezone
from types import SimpleNamespace

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, DeleteMessage, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from sqlalchemy import select

from app.bot.dispatcher import create_dispatcher
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


async def test_telegram_acceptance_flow(stack, monkeypatch):
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
        SimpleNamespace(bot_default_language="ar", max_models=1000),
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
