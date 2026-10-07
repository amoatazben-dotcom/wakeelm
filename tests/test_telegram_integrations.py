from datetime import datetime, timezone

from aiogram import Bot
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from sqlalchemy import select
from test_github_stage5 import settings
from test_telegram import TelegramSession

from app.bot.dispatcher import create_dispatcher
from app.core.limits import Limits
from app.db.models.agent import AgentJob
from app.db.models.integrations import MCPServer


async def test_telegram_github_pat_and_mcp_onboarding_are_private_queued_owned(
    stack, tmp_path, monkeypatch
):
    async def public(url):
        return {"8.8.8.8"}

    monkeypatch.setattr("app.integrations.http.public_addresses", public)
    await stack.session.commit()
    session = TelegramSession()
    bot = Bot("123456:dummy", session=session)
    dispatcher = create_dispatcher(
        stack.redis,
        stack.sessions,
        stack.secrets,
        stack.http,
        Limits(stack.redis),
        settings(tmp_path),
    )
    sender = User(id=123, is_bot=False, first_name="Test")
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
        assert "تعذر إكمال" not in session.messages[-1].text
        return session.messages[-1]

    await send("/start")
    await send(callback="menu:github")
    await send(callback="gh:connect:0")
    await send(callback="gh:pat:0")
    await send("github_pat_" + "a" * 30)
    job = await stack.session.scalar(select(AgentJob))
    assert job.kind == "GITHUB_VERIFY_PAT" and job.status == "QUEUED"
    assert "github_pat_" not in job.payload_encrypted and session.deleted
    await send(callback="menu:tools")
    await send(callback="mc:add:0")
    await send("Controlled MCP")
    await send(callback="mc:transport:0")
    await send("https://mcp.example.test/mcp")
    server = await stack.session.scalar(select(MCPServer))
    assert server.user_id == stack.user.id and server.status == "PENDING"
    await send(callback="mc:server:" + server.id)
    await send(callback="mc:token:" + server.id)
    await send("narrow-scoped-test-token")
    await stack.session.refresh(server)
    assert (
        server.auth_type == "TOKEN"
        and "narrow-scoped-test-token" not in server.encrypted_auth_config
    )
    await send(callback="mc:remove:" + server.id)
    await send(callback="mc:remove_yes:" + server.id)
    await stack.session.refresh(server)
    assert server.status == "REMOVED" and server.encrypted_auth_config is None
    await bot.session.close()
    await dispatcher.storage.close()
