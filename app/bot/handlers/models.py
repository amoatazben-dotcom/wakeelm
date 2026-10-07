from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.handlers.common import say, status
from app.bot.keyboards import back, keyboard
from app.core.exceptions import SafeError
from app.core.i18n import tr


async def model_list(event, user, models):
    _, filter, raw_page, raw_provider = event.data.split(":")
    page, provider_id = int(raw_page), int(raw_provider)
    if filter == "refresh":
        for provider in (await models.providers.list())[:5]:
            if provider.status != "DISABLED":
                try:
                    await models.providers.discover(provider.id)
                except SafeError:
                    pass
        filter = "all"
    items, total = await models.page(page, filter, provider_id or None)
    buttons = [
        [
            InlineKeyboardButton(
                text=m.display_name[:45]
                + " | "
                + status(user, m.status)
                + " | "
                + status(user, m.pricing_json.get("classification", "UNKNOWN")),
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
        [("routing.probe", f"model:probe:{ident}")],
        [("common.back", f"models:all:0:{provider.id}")],
    ]
    await say(event, text, keyboard(user.language, rows))


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
    elif action == "probe":
        await state.update_data(probe_model=ident)
        await say(
            event,
            tr(user.language, "model.test.warning"),
            keyboard(
                user.language,
                [
                    [("capability." + cap, f"probe:{cap}:{ident}")]
                    for cap in ["chat", "coding", "tool_calling", "structured_output"]
                ]
                + [[("common.cancel", "cancel")]],
            ),
        )
    elif action == "details":
        # Only normalized safe metadata, no remote error text or credentials.
        text = "\n".join(
            f"{tr(user.language, 'capability.' + key)}: {status(user, value.get('state', 'UNKNOWN'))} ({status(user, value.get('source', 'NOT_TESTED'))})"
            for key, value in model.capabilities_json.items()
        )
        await say(
            event,
            text
            + "\n"
            + tr(
                user.language,
                "model.price_details",
                classification=status(user, model.pricing_json.get("classification", "UNKNOWN")),
                prompt=model.pricing_json.get("prompt", "—"),
                completion=model.pricing_json.get("completion", "—"),
            ),
            back(user.language),
        )
    else:
        await model_detail(event, user, models, ident)


async def probe(event, user, models, state: FSMContext):
    _, cap, ident = event.data.split(":")
    data = await state.get_data()
    if data.get("probe_model") != int(ident):
        raise SafeError("INVALID_INPUT")
    await state.update_data(probe_model=None)
    from app.routing.probes import ModelCapabilityProbe

    result = await ModelCapabilityProbe(models).run(int(ident), cap)
    await say(event, status(user, result["state"]), back(user.language))


def build_router():
    router = Router()
    router.callback_query.register(probe, F.data.startswith("probe:"))
    router.callback_query.register(model_list, F.data.startswith("models:"))
    router.callback_query.register(model_actions, F.data.startswith("model:"))
    return router
