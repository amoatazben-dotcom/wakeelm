from aiogram import Router
from aiogram.fsm.context import FSMContext

from app.bot.handlers.common import say
from app.bot.keyboards import back
from app.core.i18n import tr


async def fallback(event, user, state: FSMContext):
    await say(
        event,
        tr(user.language, "common.invalid")
        if await state.get_state()
        else tr(user.language, "bot.help"),
        back(user.language),
    )


def build_router():
    router = Router()
    router.message.register(fallback)
    return router
