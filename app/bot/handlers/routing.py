from aiogram import F, Router
from sqlalchemy import select

from app.bot.handlers.common import say
from app.bot.keyboards import back, keyboard
from app.core.exceptions import SafeError
from app.core.i18n import tr
from app.db.models import Model, ModelHealthCheck, Provider
from app.platform.usage import QuotaEngine
from app.routing.preferences import RoutingPreferences
from app.routing.schemas import RoutingPolicy


async def routing_menu(event, user, session, **data):
    prefs = await RoutingPreferences(session, user.id).get()
    await say(
        event,
        tr(
            user.language,
            "routing.summary",
            policy=tr(user.language, "routing." + prefs["policy"]),
            fallback=tr(
                user.language, "routing.on" if prefs["fallback_enabled"] else "routing.off"
            ),
            mode=tr(user.language, "routing.mode." + prefs["agent_mode"]),
        ),
        keyboard(
            user.language,
            [
                [("routing.policy", "routing:policies")],
                [("routing.manual", "models:all:0:0")],
                [("routing.fallback", "routing:toggle")],
                [("routing.agent_mode", "routing:modes")],
                [("routing.performance", "routing:performance")],
                [("common.back", "menu:models")],
            ],
        ),
    )


async def action(event, user, session, **data):
    prefs = RoutingPreferences(session, user.id)
    parts = event.data.split(":")
    action = parts[1]
    if action == "policies":
        return await say(
            event,
            tr(user.language, "routing.policy"),
            keyboard(
                user.language,
                [
                    [("routing." + policy.value, "routing:set:" + policy.value)]
                    for policy in RoutingPolicy
                ]
                + [[("common.back", "routing:menu")]],
            ),
        )
    if action == "modes":
        return await say(
            event,
            tr(user.language, "routing.agent_mode"),
            keyboard(
                user.language,
                [
                    [("routing.mode." + mode, "routing:mode:" + mode)]
                    for mode in ["FAST", "BALANCED", "DEEP", "MULTI_AGENT"]
                ]
                + [[("common.back", "routing:menu")]],
            ),
        )
    if action == "set":
        try:
            await prefs.set(policy=parts[2])
        except ValueError:
            raise SafeError("INVALID_INPUT") from None
    elif action == "mode":
        await prefs.set(agent_mode=parts[2])
    elif action == "toggle":
        await prefs.set(fallback_enabled=not (await prefs.get())["fallback_enabled"])
    elif action == "performance":
        checks = list(
            await session.execute(
                select(Model.display_name, ModelHealthCheck.status, ModelHealthCheck.latency_ms)
                .join(ModelHealthCheck)
                .join(Provider)
                .where(Provider.user_id == user.id)
                .order_by(ModelHealthCheck.id.desc())
                .limit(15)
            )
        )
        return await say(
            event,
            "\n".join(f"{name}: {status} / {latency} ms" for name, status, latency in checks)
            or tr(user.language, "common.empty"),
            back(user.language),
        )
    elif action != "menu":
        raise SafeError("INVALID_INPUT")
    await routing_menu(event, user, session)


async def usage_menu(event, user, session, **data):
    summary = await QuotaEngine(session, user.id).summary()
    today, month = summary["today"], summary["month"]
    await say(
        event,
        tr(
            user.language,
            "usage.summary",
            requests=today["requests"],
            tokens=today["tokens"],
            jobs=today["jobs"],
            cost=today["estimated_cost"],
            month_tokens=month["tokens"],
            month_cost=month["estimated_cost"],
            token_limit=summary["limits"]["tokens_day"],
            cost_limit=summary["limits"]["monthly_spend"],
        ),
        back(user.language),
    )


def build_router():
    router = Router()
    router.callback_query.register(action, F.data.startswith("routing:"))
    return router
