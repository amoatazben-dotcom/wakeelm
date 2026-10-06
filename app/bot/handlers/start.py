from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from app.bot.handlers.common import say
from app.bot.keyboards import back, keyboard, menu
from app.bot.states import Chat
from app.core.i18n import tr
from app.db.models import AuditLog
from app.services.user_service import change_language


async def commands(event: Message, user, state: FSMContext, **data):
    await state.clear()
    command = event.text.split()[0].split("@")[0][1:]
    if command == "help":
        await say(event, tr(user.language, "bot.help"), menu(user.language))
    elif command in {"settings", "providers", "models"}:
        await screen(event, command, user, state, **data)
    else:
        await say(event, tr(user.language, "bot.start.title"), menu(user.language))


async def screen(event, target, user, state, session, providers, models, **data):
    lang = user.language
    if target == "settings":
        await say(
            event,
            tr(lang, "settings.language"),
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=tr(lang, "language.ar"), callback_data="language:ar"
                        ),
                        InlineKeyboardButton(
                            text=tr(lang, "language.en"), callback_data="language:en"
                        ),
                    ],
                    [InlineKeyboardButton(text=tr(lang, "common.back"), callback_data="menu:home")],
                ]
            ),
        )
    elif target == "providers":
        rows = [
            [("provider.add", "provider:add"), ("provider.list", "provider:list")],
            [("provider.check", "provider:checkall")],
            [("common.back", "menu:home")],
        ]
        await say(event, tr(lang, "menu.providers"), keyboard(lang, rows))
    elif target == "models":
        rows = [
            [("model." + key, "models:" + key + ":0:0")]
            for key in [
                "free",
                "working",
                "tool_calling",
                "vision",
                "reasoning",
                "coding",
                "paid",
                "unknown",
                "all",
            ]
        ]
        rows += [[("model.refresh", "provider:checkall")], [("common.back", "menu:home")]]
        await say(event, tr(lang, "menu.models"), keyboard(lang, rows))
    elif target == "chat":
        await state.set_state(Chat.active)
        await say(event, tr(lang, "chat.ready"), back(lang))
    elif target == "audit":
        logs = list(
            await session.scalars(
                select(AuditLog)
                .where(AuditLog.user_id == user.id)
                .order_by(AuditLog.id.desc())
                .limit(20)
            )
        )
        await say(
            event,
            "\n".join(
                tr(
                    lang,
                    "audit.row",
                    time=str(row.created_at),
                    action=tr(lang, "audit." + row.action),
                )
                for row in logs
            )
            or tr(lang, "common.empty"),
            back(lang),
        )
    elif target == "home":
        await say(event, tr(lang, "bot.start.title"), menu(lang))
    else:
        await say(event, tr(lang, "common.soon"), back(lang))


async def main_menu(event, user, state: FSMContext, **data):
    await state.clear()
    await screen(event, event.data.split(":")[1], user, state, **data)


async def cancelled(event, user, state: FSMContext):
    await state.clear()
    await say(event, tr(user.language, "bot.start.title"), menu(user.language))


async def language(event, user, session):
    await change_language(session, user, event.data.split(":")[1])
    await say(event, tr(user.language, "common.saved"), menu(user.language))


def build_router():
    router = Router()
    router.message.register(
        commands, Command("start", "help", "settings", "providers", "models", "cancel")
    )
    router.callback_query.register(main_menu, F.data.startswith("menu:"))
    router.callback_query.register(cancelled, F.data == "cancel")
    router.callback_query.register(language, F.data.startswith("language:"))
    return router
