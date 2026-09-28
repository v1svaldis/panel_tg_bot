from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.handlers.flow import answer_to, drop_state
from bot.instructions import HELP_PROTOCOLS, instruction_for
from bot.keyboards import ADMIN, HELP, KEYS, PROMO, admin_menu, main_menu
from bot.services.issue import remove_key
from bot.slots import MAX_DEVICES
from bot.states import Buy, UserPromo
from bot.timeutil import format_dt, remaining_text

router = Router()


def _menu(user_id: int, admin_ids: set[int]):
    return main_menu(user_id in admin_ids)


@router.message(CommandStart())
async def start(message: Message, state, db, admin_ids: set[int]):
    await drop_state(state, db)
    user = message.from_user
    name = " ".join(part for part in (user.first_name, user.last_name) if part)
    db.upsert_user(user.id, user.username, name or None)
    await message.answer(
        "Вы зарегистрированы. Здесь можно купить ключ, посмотреть свои ключи и инструкцию по клиентам.",
        reply_markup=_menu(user.id, admin_ids),
    )


@router.message(Command("cancel"))
@router.callback_query(F.data == "flow:cancel")
async def cancel(event, state, db, admin_ids: set[int]):
    await drop_state(state, db)
    if isinstance(event, CallbackQuery):
        await event.answer("Отменено")
        await answer_to(event, "Отменено.", reply_markup=_menu(event.from_user.id, admin_ids))
        return
    await event.answer("Отменено.", reply_markup=_menu(event.from_user.id, admin_ids))


@router.message(F.text == ADMIN)
async def admin_home(message: Message, state, db, admin_ids: set[int]):
    await drop_state(state, db)
    if message.from_user.id not in admin_ids:
        await message.answer("Недостаточно прав.")
        return
    await message.answer("Админка.", reply_markup=admin_menu())


@router.message(F.text == HELP)
async def help_menu(message: Message, state, db, admin_ids: set[int]):
    await drop_state(state, db)
    builder = InlineKeyboardBuilder()
    for key, title in HELP_PROTOCOLS:
        builder.button(text=title, callback_data=f"help:{key}")
    builder.adjust(1)
    await message.answer("Для какого протокола показать клиенты?", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("help:"))
async def help_proto(callback: CallbackQuery):
    protocol = callback.data.split(":", 1)[1]
    await callback.answer()
    await callback.message.answer(instruction_for(protocol))


@router.message(F.text == PROMO)
async def promo_start(message: Message, state, db):
    await drop_state(state, db)
    await state.set_state(UserPromo.code)
    await message.answer("Введите промокод, чтобы узнать скидку. Применить его можно при покупке.")


@router.message(UserPromo.code)
async def promo_check(message: Message, state, db):
    promo, err = db.find_promo(message.text or "")
    await state.clear()
    if err:
        await message.answer(err)
        return
    await message.answer(f"Промокод {promo['code']}: скидка {promo['percent']}%. Введите его на шаге покупки.")


@router.message(F.text == KEYS)
async def my_keys(message: Message, state, db):
    await drop_state(state, db)
    keys = db.list_keys(message.from_user.id)
    if not keys:
        await message.answer("Ключей пока нет. Нажмите «Купить ключ».")
        return
    used = db.used_slots(message.from_user.id)
    await message.answer(f"устройства: {used} из {MAX_DEVICES}")
    for key in keys[:20]:
        builder = InlineKeyboardBuilder()
        builder.button(text="Продлить", callback_data=f"renew:{key['id']}")
        builder.button(text="Удалить", callback_data=f"keydel:{key['id']}")
        builder.adjust(2)
        text = (
            f"#{key['id']} {key['protocol_label']}\n"
            f"Локация: {key['node_name']}\n"
            f"До: {format_dt(key['expires_at'])} ({remaining_text(key['expires_at'])})\n"
            f"Устройств: {key.get('devices') or 1}\n"
            f"{key['link']}"
        )
        await message.answer(text[:4000], reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("keydel:"))
async def key_delete_ask(callback: CallbackQuery, db):
    key_id = int(callback.data.split(":")[1])
    key = db.get_key(key_id)
    if not key or key["tg_id"] != callback.from_user.id:
        await callback.answer("Ключ не найден", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    builder.button(text="Удалить", callback_data=f"keydelok:{key_id}")
    builder.button(text="Отмена", callback_data="flow:cancel")
    builder.adjust(2)
    await callback.answer()
    await callback.message.answer(f"Удалить ключ #{key_id}? На панели он тоже будет удалён.", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("keydelok:"))
async def key_delete_do(callback: CallbackQuery, db):
    key_id = int(callback.data.split(":")[1])
    key = db.get_key(key_id)
    if not key or key["tg_id"] != callback.from_user.id:
        await callback.answer("Ключ не найден", show_alert=True)
        return
    await callback.answer("Удаляю…")
    try:
        await remove_key(db, key)
    except Exception as exc:
        await callback.message.answer(f"Не удалось удалить ключ: {exc}")
        return
    await callback.message.answer(f"Ключ #{key_id} удалён.")


async def show_plans(message: Message, state, db):
    plans = db.list_plans()
    if not plans:
        await message.answer("Тарифы пока не заданы. Напишите администратору.")
        return
    builder = InlineKeyboardBuilder()
    for plan in plans:
        quota = "безлимит" if not plan["quota_gb"] else f"{plan['quota_gb']} ГБ"
        builder.button(
            text=f"{plan['name']} · {plan['days']} дн. · {plan['price']} ₽ · {quota}"[:60],
            callback_data=f"pl:{plan['id']}",
        )
    builder.button(text="Отмена", callback_data="flow:cancel")
    builder.adjust(1)
    await state.set_state(Buy.plan)
    await message.answer("Выберите тариф:", reply_markup=builder.as_markup())
