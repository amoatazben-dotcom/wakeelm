from aiogram.types import CallbackQuery

from app.core.i18n import tr


def message(event):
    return event.message if isinstance(event, CallbackQuery) else event


async def say(event, text, markup=None):
    await message(event).answer(text, reply_markup=markup, parse_mode=None)


def status(user, value):
    return tr(user.language, "status." + value)
