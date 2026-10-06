from aiogram.fsm.state import State, StatesGroup


class Onboard(StatesGroup):
    name = State()
    url = State()
    token = State()
    headers_choice = State()
    headers = State()
    confirm = State()
    rename = State()


class Chat(StatesGroup):
    active = State()
