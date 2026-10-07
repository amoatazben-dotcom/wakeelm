from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.core.i18n import tr


def keyboard(lang, rows):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=tr(lang, key), callback_data=data) for key, data in row]
            for row in rows
        ]
    )


def menu(lang):
    return keyboard(
        lang,
        [
            [("menu." + key, "menu:" + key)]
            for key in [
                "chat",
                "providers",
                "models",
                "files",
                "projects",
                "github",
                "tools",
                "settings",
                "usage",
                "audit",
            ]
        ],
    )


def back(lang):
    return keyboard(lang, [[("common.back", "menu:home")]])


def cancel(lang):
    return keyboard(lang, [[("common.cancel", "cancel")]])
