import structlog
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from app.core.exceptions import SafeError
from app.core.i18n import tr
from app.services.agent_service import AgentService
from app.services.model_service import ModelService
from app.services.provider_service import ProviderService
from app.services.user_service import ensure_user
from app.services.workspace_service import WorkspaceService


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
            async with self.sessions() as session:
                user = await ensure_user(session, sender, lang)
                lang = user.language
                await self.limits.cooldown(f"bot:{sender.id}", 1)
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
                    workspaces=WorkspaceService(
                        session, user.id, self.settings, self.secrets, self.limits
                    ),
                )
                data["agents"] = AgentService(data["workspaces"], data["models"])
                result = await handler(event, data)
                await session.commit()
                return result
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
