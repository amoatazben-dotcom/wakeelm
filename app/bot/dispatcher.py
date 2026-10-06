from aiogram import Dispatcher
from aiogram.fsm.storage.redis import DefaultKeyBuilder, RedisEventIsolation, RedisStorage
from aiogram.fsm.strategy import FSMStrategy

from app.bot.handlers import chat, fallback, models, providers, start, workspaces
from app.bot.middleware import ServicesMiddleware


def create_dispatcher(redis, sessions, secrets, http, limits, settings):
    storage = RedisStorage(
        redis, key_builder=DefaultKeyBuilder(with_bot_id=True), state_ttl=1800, data_ttl=1800
    )
    isolation = RedisEventIsolation(
        redis, key_builder=DefaultKeyBuilder(with_bot_id=True), lock_kwargs={"timeout": 240}
    )
    dispatcher = Dispatcher(
        storage=storage, events_isolation=isolation, fsm_strategy=FSMStrategy.USER_IN_CHAT
    )
    middleware = ServicesMiddleware(sessions, secrets, http, limits, settings)
    dispatcher.message.outer_middleware(middleware)
    dispatcher.callback_query.outer_middleware(middleware)
    dispatcher.include_routers(
        *(
            module.build_router()
            for module in (start, providers, models, workspaces, chat, fallback)
        )
    )
    return dispatcher
