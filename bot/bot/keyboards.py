from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

BUY = "Купить ключ"
KEYS = "Мои ключи"
HELP = "Инструкция"
PROMO = "Промокод"
ADMIN = "Админка"


def main_menu(is_admin: bool) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=BUY), KeyboardButton(text=KEYS)],
        [KeyboardButton(text=HELP), KeyboardButton(text=PROMO)],
    ]
    if is_admin:
        rows.append([KeyboardButton(text=ADMIN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def inline(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for row in rows:
        builder.row(*(InlineKeyboardButton(text=text, callback_data=data) for text, data in row))
    return builder.as_markup()


def order_kb(order_id: int, retry: bool = False) -> InlineKeyboardMarkup:
    if retry:
        rows = [[("Повторить выдачу", f"order:retry:{order_id}")]]
    else:
        rows = [[("Подтвердить", f"order:ok:{order_id}"), ("Отклонить", f"order:no:{order_id}")]]
    return inline(rows)


def admin_menu() -> InlineKeyboardMarkup:
    return inline([
        [("Ноды", "adm:nodes")],
        [("Тарифы", "adm:plans")],
        [("Реквизиты", "adm:pay")],
        [("Промокоды", "adm:promos")],
        [("Ожидают оплаты", "adm:orders")],
        [("Пользователи", "adm:users")],
    ])


def choices_kb(choices: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for index, choice in enumerate(choices):
        mark = "✅" if choice.get("on", True) else "▫️"
        label = f"{mark} {choice['label']}"[:60]
        builder.button(text=label, callback_data=f"np:{index}")
    builder.button(text="Сохранить", callback_data="nsave")
    builder.adjust(1)
    return builder.as_markup()


def cancel_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="Отмена", callback_data="flow:cancel")]
