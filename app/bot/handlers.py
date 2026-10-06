import json

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from pydantic import ValidationError
from sqlalchemy import func, select

from app.bot.keyboards import back, cancel, keyboard, menu
from app.bot.states import Chat, Onboard
from app.core.exceptions import SafeError
from app.core.i18n import tr
from app.core.security import token_hint
from app.db.models import AuditLog, Model
from app.providers.url import BaseURLResolver, public_addresses
from app.schemas.providers import ProviderInput
from app.services.user_service import change_language

router = Router()


def message(event):
    return event.message if isinstance(event, CallbackQuery) else event


async def say(event, text, markup=None):
    await message(event).answer(text, reply_markup=markup, parse_mode=None)


def status(user, value):
    return tr(user.language, "status." + value)


@router.message(Command("start", "help", "settings", "providers", "models", "cancel"))
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
                        InlineKeyboardButton(text="العربية 🇾🇪", callback_data="language:ar"),
                        InlineKeyboardButton(text="English 🇬🇧", callback_data="language:en"),
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
                tr(lang, "audit.row", time=str(row.created_at), action=row.action) for row in logs
            )
            or tr(lang, "common.empty"),
            back(lang),
        )
    elif target == "home":
        await say(event, tr(lang, "bot.start.title"), menu(lang))
    else:
        await say(event, tr(lang, "common.soon"), back(lang))


@router.callback_query(F.data.startswith("menu:"))
async def main_menu(event, user, state: FSMContext, **data):
    await state.clear()
    await screen(event, event.data.split(":")[1], user, state, **data)


@router.callback_query(F.data == "cancel")
async def cancelled(event, user, state: FSMContext):
    await state.clear()
    await say(event, tr(user.language, "bot.start.title"), menu(user.language))


@router.callback_query(F.data.startswith("language:"))
async def language(event, user, session):
    await change_language(session, user, event.data.split(":")[1])
    await say(event, tr(user.language, "common.saved"), menu(user.language))


@router.callback_query(F.data == "provider:add")
async def add_provider(event, user, state: FSMContext):
    await state.clear()
    await state.set_state(Onboard.name)
    await say(event, tr(user.language, "provider.name"), cancel(user.language))


@router.message(Onboard.name, F.text)
async def provider_name(event, user, state: FSMContext):
    if not 1 <= len(event.text.strip()) <= 100:
        raise SafeError("INVALID_INPUT")
    await state.update_data(name=event.text.strip())
    await state.set_state(Onboard.url)
    await say(event, tr(user.language, "provider.url"), cancel(user.language))


@router.message(Onboard.url, F.text)
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


@router.message(Onboard.token, F.text)
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


@router.callback_query(Onboard.headers_choice, F.data == "onboard:skip")
async def skip_headers(event, user, state: FSMContext):
    await summary(event, user, state)


@router.callback_query(Onboard.headers_choice, F.data == "onboard:headers")
async def add_headers(event, user, state: FSMContext):
    await state.set_state(Onboard.headers)
    await say(event, tr(user.language, "provider.headers.input"), cancel(user.language))


@router.message(Onboard.headers, F.text)
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


@router.callback_query(Onboard.confirm, F.data == "onboard:save")
async def save_provider(event, user, state: FSMContext, secrets, providers, session):
    data = await state.get_data()
    item = ProviderInput(
        name=data["name"],
        base_url=data["base_url"],
        api_token=secrets.decrypt(data["token"]),
        headers=json.loads(secrets.decrypt(data["headers"])),
    )
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
        [("provider.rename", f"provider:rename:{provider.id}")],
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


@router.callback_query(F.data.startswith("provider:"))
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


@router.message(Onboard.rename, F.text)
async def rename_provider(event, user, providers, state: FSMContext):
    data = await state.get_data()
    await providers.rename(data["provider_id"], event.text)
    await state.clear()
    await say(event, tr(user.language, "common.saved"), back(user.language))


@router.callback_query(F.data.startswith("models:"))
async def model_list(event, user, models):
    _, filter, raw_page, raw_provider = event.data.split(":")
    page, provider_id = int(raw_page), int(raw_provider)
    items, total = await models.page(page, filter, provider_id or None)
    buttons = [
        [
            InlineKeyboardButton(
                text=m.display_name[:45] + " | " + status(user, m.status),
                callback_data=f"model:view:{m.id}",
            )
        ]
        for m in items
    ]
    nav = []
    if page:
        nav.append(
            InlineKeyboardButton(
                text=tr(user.language, "common.previous"),
                callback_data=f"models:{filter}:{page - 1}:{provider_id}",
            )
        )
    if (page + 1) * 10 < total:
        nav.append(
            InlineKeyboardButton(
                text=tr(user.language, "common.next"),
                callback_data=f"models:{filter}:{page + 1}:{provider_id}",
            )
        )
    if nav:
        buttons.append(nav)
    buttons.append(
        [InlineKeyboardButton(text=tr(user.language, "common.back"), callback_data="menu:models")]
    )
    await say(
        event,
        tr(user.language, "models.page", page=page + 1, total=total),
        InlineKeyboardMarkup(inline_keyboard=buttons),
    )


async def model_detail(event, user, models, ident):
    model = await models.owned.model(ident)
    provider = await models.owned.provider(model.provider_id)
    def cap(key):
        return status(user, model.capabilities_json.get(key, {}).get("state", "UNKNOWN"))
    text = tr(
        user.language,
        "model.detail",
        name=model.display_name,
        id=model.external_model_id,
        provider=provider.name,
        status=status(user, model.status),
        pricing=status(user, model.pricing_json.get("classification", "UNKNOWN")),
        tools=cap("tool_calling"),
        vision=cap("vision"),
        reasoning=cap("reasoning"),
        checked=model.last_checked_at or "—",
    )
    rows = [
        [("model.activate", f"model:activate:{ident}")],
        [("model.test", f"model:test:{ident}"), ("model.details", f"model:details:{ident}")],
        [("common.back", f"models:all:0:{provider.id}")],
    ]
    await say(event, text, keyboard(user.language, rows))


@router.callback_query(F.data.startswith("model:"))
async def model_actions(event, user, models, state: FSMContext):
    _, action, raw_id = event.data.split(":")
    ident = int(raw_id)
    model = await models.owned.model(ident)
    if action == "activate":
        await models.activate(ident)
        await say(event, tr(user.language, "common.saved"), back(user.language))
    elif action == "test":
        await state.update_data(test_model=ident)
        await say(
            event,
            tr(user.language, "model.test.warning"),
            keyboard(
                user.language,
                [[("common.confirm", f"model:confirmed:{ident}")], [("common.cancel", "cancel")]],
            ),
        )
    elif action == "confirmed":
        data = await state.get_data()
        if data.get("test_model") != ident:
            raise SafeError("INVALID_INPUT")
        await state.update_data(test_model=None)
        error = await models.test(ident)
        if error:
            await say(event, tr(user.language, "error." + error.code))
        await model_detail(event, user, models, ident)
    elif action == "details":
        # Only normalized safe metadata, no remote error text or credentials.
        text = "\n".join(
            f"{key}: {status(user, value.get('state', 'UNKNOWN'))} ({status(user, value.get('source', 'NOT_TESTED'))})"
            for key, value in model.capabilities_json.items()
        )
        await say(
            event,
            text + "\n" + json.dumps(model.pricing_json, ensure_ascii=False),
            back(user.language),
        )
    else:
        await model_detail(event, user, models, ident)


@router.message(Chat.active, F.text)
async def chat_message(event, user, models):
    response = await models.chat(event.text)
    for start in range(0, min(len(response), 32000), 4000):
        await say(event, response[start : start + 4000])


@router.message()
async def fallback(event, user, state: FSMContext):
    await say(
        event,
        tr(user.language, "common.invalid")
        if await state.get_state()
        else tr(user.language, "bot.help"),
        back(user.language),
    )
