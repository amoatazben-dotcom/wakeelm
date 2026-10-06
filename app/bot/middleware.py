import structlog
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from app.core.exceptions import SafeError
from app.core.i18n import tr
from app.services.model_service import ModelService
from app.services.provider_service import ProviderService
from app.services.user_service import ensure_user


class ServicesMiddleware(BaseMiddleware):
    def __init__(self, sessions, secrets, http, limits, settings):
        self.sessions, self.secrets, self.http, self.limits, self.settings = (
            sessions,
            secrets,
            http,
            limits,
            settings,
        )

    async def __call__(self, handler, event, data):
        sender = event.from_user
        message = event.message if isinstance(event, CallbackQuery) else event
        if not sender or not isinstance(message, Message) or message.chat.type != "private":
            return
        lang = self.settings.bot_default_language
        if isinstance(event, CallbackQuery):
            await event.answer()
        try:
            await self.limits.cooldown(f"bot:{sender.id}", 1)
            async with self.sessions() as session:
                async with session.begin():
                    user = await ensure_user(session, sender, lang)
                    lang = user.language
                    if not user.is_active:
                        raise SafeError("INACTIVE")
                    providers = ProviderService(
                        session,
                        user.id,
                        self.secrets,
                        self.http,
                        self.limits,
                        self.settings.max_models,
                    )
                    data.update(
                        session=session,
                        user=user,
                        providers=providers,
                        models=ModelService(providers),
                        secrets=self.secrets,
                    )
                    return await handler(event, data)
        except SafeError as error:
            await message.answer(tr(lang, "error." + error.code))
        except Exception:
            # Deliberately do not attach raw exception text: provider/Telegram errors may contain secrets.
            structlog.get_logger().error(
                "bot_operation_failed",
                telegram_user_id=sender.id,
                status="error",
                error_code="INTERNAL",
            )
            await message.answer(tr(lang, "error.INTERNAL"))
