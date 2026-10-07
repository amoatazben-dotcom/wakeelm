from aiogram import F, Router
from aiogram.filters import StateFilter

from app.bot.handlers.common import say
from app.bot.states import Chat


async def chat_message(event, user, models):
    response = await models.chat(event.text)
    for start in range(0, min(len(response), 32000), 4000):
        await say(event, response[start : start + 4000])


def build_router():
    router = Router()
    router.message.register(chat_message, Chat.active, F.text)
    # The selected model is durable; Redis conversation state may expire or be
    # cleared by menu navigation. Preserve onboarding and other explicit states.
    router.message.register(chat_message, StateFilter(None), F.text, ~F.text.startswith("/"))
    return router
