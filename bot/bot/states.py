from aiogram.fsm.state import State, StatesGroup


class Buy(StatesGroup):
    protocol = State()
    location = State()
    devices = State()
    plan = State()
    promo = State()
    proof = State()


class UserPromo(StatesGroup):
    code = State()


class AdminNode(StatesGroup):
    kind = State()
    name = State()
    url = State()
    token = State()
    sub_base = State()
    pick = State()


class AdminPlan(StatesGroup):
    name = State()
    days = State()
    price = State()
    quota = State()


class AdminPromo(StatesGroup):
    code = State()
    percent = State()
    uses = State()
    days = State()


class AdminPay(StatesGroup):
    text = State()


class AdminUser(StatesGroup):
    query = State()
