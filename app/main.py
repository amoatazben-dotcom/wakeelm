import asyncio
import hmac
import uuid
from contextlib import asynccontextmanager, suppress

import structlog
from aiogram import Bot
from aiogram.types import Update
from fastapi import FastAPI, HTTPException, Request
from redis.asyncio import Redis

from app.agent.worker import AgentWorker
from app.api.health import router
from app.api.integrations import router as integrations_router
from app.bot.dispatcher import create_dispatcher
from app.core.config import Settings
from app.core.limits import Limits
from app.core.logging import configure_logging
from app.core.security import SecretManager
from app.db.session import database
from app.providers.http import SafeHTTP


def create_app(settings=None, start_bot=True):
    settings = settings or Settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app):
        engine, sessions = database(settings.async_database_url)
        redis = Redis.from_url(settings.redis_url.get_secret_value())
        bot = Bot(settings.telegram_bot_token.get_secret_value())
        app.state.engine, app.state.redis = engine, redis
        app.state.sessions = sessions
        app.state.settings = settings
        app.state.secrets = SecretManager(settings.master_encryption_key.get_secret_value())
        app.state.limits = Limits(redis)
        app.state.bot = bot
        dispatcher = create_dispatcher(
            redis,
            sessions,
            SecretManager(settings.master_encryption_key.get_secret_value()),
            SafeHTTP(settings.provider_timeout, settings.max_response_bytes),
            Limits(redis),
            settings,
        )
        app.state.dispatcher = dispatcher
        task = None
        worker_task = None

        async def notify(job):
            if not job.telegram_chat_id:
                return
            from app.core.i18n import tr
            from app.db.models import User

            async with sessions() as session:
                user = await session.get(User, job.user_id)
            if not user or not user.is_active:
                return
            from app.bot.keyboards import keyboard

            try:
                await bot.send_message(
                    job.telegram_chat_id,
                    tr(
                        user.language,
                        "agent.progress",
                        ident=job.id,
                        status=tr(user.language, "agent.state." + job.status),
                    ),
                    reply_markup=keyboard(
                        user.language, [[("agent.refresh", f"job:status:{job.id}")]]
                    ),
                )
            except Exception:
                pass

        try:
            if start_bot:
                worker = AgentWorker(
                    sessions,
                    SecretManager(settings.master_encryption_key.get_secret_value()),
                    SafeHTTP(settings.provider_timeout, settings.max_response_bytes),
                    Limits(redis),
                    settings,
                    notify,
                )
                worker_task = asyncio.create_task(worker.run())
                app.state.worker_task = worker_task
                if settings.bot_mode == "polling":
                    await bot.delete_webhook(drop_pending_updates=False)
                    task = asyncio.create_task(
                        dispatcher.start_polling(
                            bot,
                            handle_signals=False,
                            close_bot_session=False,
                            handle_as_tasks=False,
                        )
                    )
                    app.state.polling_task = task
                else:
                    await bot.set_webhook(
                        settings.public_base_url.rstrip("/") + "/telegram/webhook",
                        secret_token=settings.webhook_secret.get_secret_value(),
                        allowed_updates=dispatcher.resolve_used_update_types(),
                    )
            yield
        finally:
            if worker_task:
                worker_task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await worker_task
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task
            await bot.session.close()
            await redis.aclose()
            await engine.dispose()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.include_router(router)
    app.include_router(integrations_router)

    @app.middleware("http")
    async def request_id(request, call_next):
        request_id = uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        structlog.get_logger().info(
            "request", request_id=request_id, operation="http", status=response.status_code
        )
        return response

    @app.post("/telegram/webhook")
    async def webhook(request: Request):
        expected = settings.webhook_secret.get_secret_value() if settings.webhook_secret else ""
        if (
            settings.bot_mode != "webhook"
            or not expected
            or not hmac.compare_digest(
                request.headers.get("X-Telegram-Bot-Api-Secret-Token", ""), expected
            )
        ):
            raise HTTPException(403)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 1_000_000:
                raise HTTPException(413)
        try:
            update = Update.model_validate_json(body)
        except ValueError:
            raise HTTPException(400) from None
        # Webhook retry deduplication and processing lock across replicas.
        key = f"telegram:{app.state.bot.id}:update:{update.update_id}"
        if not await app.state.redis.set(key, "processing", nx=True, ex=300):
            value = await app.state.redis.get(key)
            if value == b"done":
                return {"ok": True}
            raise HTTPException(503)
        try:
            await app.state.dispatcher.feed_update(app.state.bot, update)
            await app.state.redis.set(key, "done", ex=86400)
        except Exception:
            await app.state.redis.delete(key)
            raise HTTPException(503) from None
        return {"ok": True}

    return app
