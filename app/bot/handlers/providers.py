import json

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pydantic import ValidationError
from sqlalchemy import func, select

from app.bot.handlers.common import say, status
from app.bot.keyboards import back, cancel, keyboard
from app.bot.states import Onboard
from app.core.exceptions import SafeError
from app.core.i18n import tr
from app.core.security import token_hint
from app.db.models import Model
from app.providers.url import BaseURLResolver, public_addresses
from app.schemas.providers import ProviderInput


async def add_provider(event, user, state: FSMContext):
    await state.clear()
    await state.set_state(Onboard.name)
    await say(event, tr(user.language, "provider.name"), cancel(user.language))


async def provider_name(event, user, state: FSMContext):
    if not 1 <= len(event.text.strip()) <= 100:
        raise SafeError("INVALID_INPUT")
    await state.update_data(name=event.text.strip())
    await state.set_state(Onboard.url)
    await say(event, tr(user.language, "provider.url"), cancel(user.language))


async def provider_url(event, user, state: FSMContext):
    base_url = BaseURLResolver.normalize(event.text)
    await public_addresses(base_url)
    await state.update_data(base_url=base_url)
    await state.set_state(Onboard.token)
    await say(event, tr(user.language, "provider.token"), cancel(user.language))


async def delete_secret_message(event):
    try:
        await event.delete()
    except Exception:
        pass


async def provider_token(event, user, state: FSMContext, secrets):
    await delete_secret_message(event)
    data = await state.get_data()
    try:
        ProviderInput(name=data["name"], base_url=data["base_url"], api_token=event.text)
    except ValidationError:
        raise SafeError("INVALID_INPUT") from None
    await state.update_data(
        token=secrets.encrypt(event.text),
        hint=token_hint(event.text),
        headers=secrets.encrypt_headers({}),
    )
    await state.set_state(Onboard.headers_choice)
    await say(
        event,
        tr(user.language, "provider.headers.ask"),
        keyboard(
            user.language,
            [
                [("common.skip", "onboard:skip"), ("provider.headers.add", "onboard:headers")],
                [("common.cancel", "cancel")],
            ],
        ),
    )


async def summary(event, user, state):
    data = await state.get_data()
    await state.set_state(Onboard.confirm)
    await say(
        event,
        tr(
            user.language,
            "provider.summary",
            name=data["name"],
            url=data["base_url"],
            hint=data["hint"],
        ),
        keyboard(
            user.language, [[("provider.save", "onboard:save")], [("common.cancel", "cancel")]]
        ),
    )


async def skip_headers(event, user, state: FSMContext):
    await summary(event, user, state)


async def add_headers(event, user, state: FSMContext):
    await state.set_state(Onboard.headers)
    await say(event, tr(user.language, "provider.headers.input"), cancel(user.language))


async def headers_input(event, user, state: FSMContext, secrets):
    await delete_secret_message(event)
    data = await state.get_data()
    try:
        headers = json.loads(event.text)
        item = ProviderInput(
            name=data["name"],
            base_url=data["base_url"],
            api_token=secrets.decrypt(data["token"]),
            headers=headers,
        )
    except (ValueError, TypeError):
        raise SafeError("INVALID_INPUT") from None
    await state.update_data(headers=secrets.encrypt_headers(item.headers))
    await summary(event, user, state)


async def save_provider(event, user, state: FSMContext, secrets, providers, session):
    data = await state.get_data()
    item = ProviderInput(
        name=data["name"],
        base_url=data["base_url"],
        api_token=secrets.decrypt(data["token"]),
        headers=json.loads(secrets.decrypt(data["headers"])),
    )
    if data.get("edit_provider"):
        provider = await providers.update(data["edit_provider"], item)
    else:
        provider = await providers.create(item)
    # Persist credentials before network testing, so a test failure cannot lose the provider.
    await session.commit()
    await state.clear()
    error = await providers.discover(provider.id)
    await say(
        event,
        tr(user.language, "error." + error.code) if error else tr(user.language, "common.saved"),
    )
    await provider_detail(event, user, providers, session, provider.id)


async def list_providers(event, user, providers):
    rows = await providers.list()
    # Bounded menu. Provider list pagination uses ten entries per page.
    await provider_page(event, user, rows, 0)


async def provider_page(event, user, rows, page):
    buttons = [
        [InlineKeyboardButton(text=p.name[:60], callback_data=f"provider:view:{p.id}")]
        for p in rows[page * 10 : page * 10 + 10]
    ]
    nav = []
    if page:
        nav.append(
            InlineKeyboardButton(
                text=tr(user.language, "common.previous"), callback_data=f"provider:page:{page - 1}"
            )
        )
    if (page + 1) * 10 < len(rows):
        nav.append(
            InlineKeyboardButton(
                text=tr(user.language, "common.next"), callback_data=f"provider:page:{page + 1}"
            )
        )
    if nav:
        buttons.append(nav)
    buttons.append(
        [
            InlineKeyboardButton(
                text=tr(user.language, "common.back"), callback_data="menu:providers"
            )
        ]
    )
    await say(
        event,
        tr(user.language, "menu.providers") if rows else tr(user.language, "common.empty"),
        InlineKeyboardMarkup(inline_keyboard=buttons),
    )


async def provider_detail(event, user, providers, session, provider_id):
    provider = await providers.owned.provider(provider_id)
    count = await session.scalar(
        select(func.count()).select_from(Model).where(Model.provider_id == provider.id)
    )
    rows = [
        [("provider.models", f"models:all:0:{provider.id}")],
        [
            ("provider.refresh", f"provider:test:{provider.id}"),
            ("provider.test", f"provider:test:{provider.id}"),
        ],
        [
            ("provider.edit", f"provider:edit:{provider.id}"),
            ("provider.rename", f"provider:rename:{provider.id}"),
        ],
        [
            ("provider.disable", f"provider:disable:{provider.id}"),
            ("provider.delete", f"provider:delete:{provider.id}"),
        ],
        [("common.back", "provider:list")],
    ]
    await say(
        event,
        tr(
            user.language,
            "provider.detail",
            name=provider.name,
            url=provider.base_url,
            status=status(user, provider.status),
            count=count,
            checked=provider.last_checked_at or "—",
            hint=provider.token_hint,
        ),
        keyboard(user.language, rows),
    )


async def provider_actions(event, user, providers, session, state: FSMContext):
    parts = event.data.split(":")
    action = parts[1]
    if action == "list":
        await list_providers(event, user, providers)
        return
    if action == "page":
        page = int(parts[2])
        if page < 0:
            raise SafeError("INVALID_INPUT")
        await provider_page(event, user, await providers.list(), page)
        return
    if action == "checkall":
        # Bound external work per Telegram callback. Individual provider screens handle the rest.
        for provider in (await providers.list())[:5]:
            if provider.status != "DISABLED":
                try:
                    await providers.discover(provider.id)
                except SafeError:
                    pass
        await list_providers(event, user, providers)
        return
    ident = int(parts[2])
    await providers.owned.provider(ident)
    if action == "view":
        await provider_detail(event, user, providers, session, ident)
    elif action == "test":
        error = await providers.discover(ident)
        if error:
            await say(event, tr(user.language, "error." + error.code))
        await provider_detail(event, user, providers, session, ident)
    elif action == "edit":
        await state.clear()
        await state.update_data(edit_provider=ident)
        await state.set_state(Onboard.name)
        await say(event, tr(user.language, "provider.name"), cancel(user.language))
    elif action == "rename":
        await state.set_state(Onboard.rename)
        await state.update_data(provider_id=ident)
        await say(event, tr(user.language, "provider.name"), cancel(user.language))
    elif action == "disable":
        await providers.disable(ident)
        await provider_detail(event, user, providers, session, ident)
    elif action == "delete":
        await state.update_data(delete_provider=ident)
        await say(
            event,
            tr(user.language, "provider.confirm_delete"),
            keyboard(
                user.language,
                [
                    [("provider.yes_delete", f"provider:confirmed:{ident}")],
                    [("common.cancel", "cancel")],
                ],
            ),
        )
    elif action == "confirmed":
        data = await state.get_data()
        if data.get("delete_provider") != ident:
            raise SafeError("INVALID_INPUT")
        await providers.delete(ident)
        await state.clear()
        await list_providers(event, user, providers)


async def rename_provider(event, user, providers, state: FSMContext):
    data = await state.get_data()
    await providers.rename(data["provider_id"], event.text)
    await state.clear()
    await say(event, tr(user.language, "common.saved"), back(user.language))


def build_router():
    router = Router()
    router.callback_query.register(add_provider, F.data == "provider:add")
    router.message.register(provider_name, Onboard.name, F.text)
    router.message.register(provider_url, Onboard.url, F.text)
    router.message.register(provider_token, Onboard.token, F.text)
    router.callback_query.register(skip_headers, Onboard.headers_choice, F.data == "onboard:skip")
    router.callback_query.register(add_headers, Onboard.headers_choice, F.data == "onboard:headers")
    router.message.register(headers_input, Onboard.headers, F.text)
    router.callback_query.register(save_provider, Onboard.confirm, F.data == "onboard:save")
    router.callback_query.register(provider_actions, F.data.startswith("provider:"))
    router.message.register(rename_provider, Onboard.rename, F.text)
    return router
