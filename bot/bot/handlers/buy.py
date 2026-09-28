import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.handlers.flow import drop_state, node_choices, notify_admins
from bot.handlers.user import show_plans
from bot.keyboards import BUY, main_menu, order_kb
from bot.pricing import discounted_price
from bot.services.issue import deliver_key, issue_order
from bot.slots import (
    MAX_DEVICES,
    can_allocate,
    flatten_entries,
    is_multi,
    label_for,
    locations_for_protocol,
    unique_protocols,
)
from bot.states import Buy

router = Router()
log = logging.getLogger(__name__)


@router.message(F.text == BUY)
async def buy_start(message: Message, state, db, admin_ids: set[int]):
    await drop_state(state, db)
    user = message.from_user
    db.upsert_user(user.id, user.username, user.full_name)
    if db.is_blocked(user.id):
        await message.answer("Аккаунт заблокирован. Напишите администратору.")
        return
    entries = flatten_entries(db.list_nodes(), node_choices)
    protocols = unique_protocols(entries)
    if not protocols:
        await message.answer("Протоколы пока не настроены. Напишите администратору.")
        return
    await state.update_data(entries=entries, renew_key_id=None)
    await state.set_state(Buy.protocol)
    builder = InlineKeyboardBuilder()
    for item in protocols:
        builder.button(text=item["label"][:60], callback_data=f"proto:{item['protocol']}")
    builder.button(text="Отмена", callback_data="flow:cancel")
    builder.adjust(1)
    await message.answer("Выберите протокол:", reply_markup=builder.as_markup())


@router.callback_query(Buy.protocol, F.data.startswith("proto:"))
async def pick_protocol(callback: CallbackQuery, state):
    protocol = callback.data.split(":", 1)[1]
    data = await state.get_data()
    locations = locations_for_protocol(data.get("entries") or [], protocol)
    if not locations:
        await callback.answer("Для этого протокола нет локаций", show_alert=True)
        return
    await state.update_data(
        protocol=protocol,
        protocol_label=label_for(protocol),
        locations=locations,
    )
    await state.set_state(Buy.location)
    builder = InlineKeyboardBuilder()
    for index, loc in enumerate(locations):
        remark = loc.get("remark") or ""
        title = loc["node_name"] if not remark else f"{loc['node_name']} · {remark}"
        builder.button(text=title[:60], callback_data=f"ln:{index}")
    builder.button(text="Отмена", callback_data="flow:cancel")
    builder.adjust(1)
    await callback.answer()
    await callback.message.answer("Выберите локацию:", reply_markup=builder.as_markup())


@router.callback_query(Buy.location, F.data.startswith("ln:"))
async def pick_location(callback: CallbackQuery, state, db):
    data = await state.get_data()
    locations = data.get("locations") or []
    index = int(callback.data.split(":")[1])
    if index < 0 or index >= len(locations):
        await callback.answer("Локация не найдена", show_alert=True)
        return
    loc = locations[index]
    used = db.used_slots(callback.from_user.id)
    free = MAX_DEVICES - used
    if free < 1:
        await callback.answer(f"Лимит {MAX_DEVICES} устройств исчерпан", show_alert=True)
        return
    await state.update_data(node_id=loc["node_id"], inbound_id=loc.get("inbound_id"))
    await state.set_state(Buy.devices)
    builder = InlineKeyboardBuilder()
    for count in range(1, free + 1):
        builder.button(text=str(count), callback_data=f"dev:{count}")
    builder.button(text="Отмена", callback_data="flow:cancel")
    builder.adjust(5)
    rule = (
        "Один ключ на все выбранные устройства."
        if is_multi(data.get("protocol") or "")
        else "Отдельный ключ на каждое устройство."
    )
    await callback.answer()
    await callback.message.answer(
        f"Занято {used} из {MAX_DEVICES}. Сколько устройств нужно?\n{rule}",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(Buy.devices, F.data.startswith("dev:"))
async def pick_devices(callback: CallbackQuery, state, db):
    count = int(callback.data.split(":")[1])
    used = db.used_slots(callback.from_user.id)
    if not can_allocate(used, count):
        await callback.answer("Столько устройств выбрать нельзя", show_alert=True)
        return
    await state.update_data(devices=count)
    await callback.answer()
    await show_plans(callback.message, state, db)


@router.callback_query(F.data.startswith("renew:"))
async def renew_start(callback: CallbackQuery, state, db):
    await drop_state(state, db)
    key = db.get_key(int(callback.data.split(":")[1]))
    if not key or key["tg_id"] != callback.from_user.id:
        await callback.answer("Ключ не найден", show_alert=True)
        return
    if db.is_blocked(callback.from_user.id):
        await callback.answer("Аккаунт заблокирован", show_alert=True)
        return
    await state.update_data(
        node_id=key["node_id"],
        protocol=key["protocol"],
        inbound_id=key["inbound_id"],
        protocol_label=key["protocol_label"],
        renew_key_id=key["id"],
    )
    await callback.answer()
    await show_plans(callback.message, state, db)


@router.callback_query(Buy.plan, F.data.startswith("pl:"))
async def pick_plan(callback: CallbackQuery, state, db):
    plan = db.get_plan(int(callback.data.split(":")[1]))
    if not plan or not plan["enabled"]:
        await callback.answer("Тариф недоступен", show_alert=True)
        return
    data = await state.get_data()
    if data.get("promo_id"):
        db.release_promo(data["promo_id"])
    await state.update_data(
        plan_name=plan["name"],
        days=plan["days"],
        quota_gb=plan["quota_gb"],
        base_price=plan["price"],
        price=plan["price"],
        promo_id=None,
        promo_code=None,
    )
    await state.set_state(Buy.promo)
    builder = InlineKeyboardBuilder()
    builder.button(text="Без промокода", callback_data="promo:skip")
    builder.button(text="Отмена", callback_data="flow:cancel")
    builder.adjust(1)
    await callback.answer()
    await callback.message.answer(
        f"Тариф «{plan['name']}»: {plan['price']} ₽.\nВведите промокод или нажмите «Без промокода».",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(Buy.promo, F.data == "promo:skip")
async def promo_skip(callback: CallbackQuery, state, db, admin_ids: set[int]):
    await callback.answer()
    await _show_payment(callback.message, state, db, callback.from_user, admin_ids)


@router.message(Buy.promo)
async def promo_enter(message: Message, state, db, admin_ids: set[int]):
    data = await state.get_data()
    if data.get("promo_id"):
        db.release_promo(data["promo_id"])
        await state.update_data(promo_id=None, promo_code=None, price=data["base_price"])
    promo, err = db.reserve_promo(message.text or "")
    if err:
        await message.answer(f"{err}. Введите другой код или нажмите «Без промокода».")
        return
    price = discounted_price(data["base_price"], promo["percent"])
    await state.update_data(promo_id=promo["id"], promo_code=promo["code"], price=price)
    await message.answer(f"Скидка {promo['percent']}%. К оплате: {price} ₽.")
    await _show_payment(message, state, db, message.from_user, admin_ids)


async def _show_payment(message, state, db, user, admin_ids):
    data = await state.get_data()
    price = data["price"]
    if price == 0:
        await _finish_free(message, state, db, user, admin_ids)
        return
    requisites = db.get_setting("payment_text") or "Реквизиты ещё не заданы. Напишите администратору и нажмите «Я оплатил»."
    builder = InlineKeyboardBuilder()
    builder.button(text="Я оплатил", callback_data="paid:go")
    builder.button(text="Отмена", callback_data="flow:cancel")
    builder.adjust(1)
    node = db.get_node(data["node_id"])
    text = (
        f"Локация: {node['name'] if node else '—'}\n"
        f"Протокол: {data['protocol_label']}\n"
        + ("" if data.get("renew_key_id") else f"Устройств: {data.get('devices') or 1}\n")
        + f"Тариф: {data['plan_name']}, {data['days']} дн.\n"
        f"К оплате: {price} ₽\n\n"
        f"{requisites}"
    )
    await message.answer(text, reply_markup=builder.as_markup())


def _slots_full(db, data, user) -> bool:
    if data.get("renew_key_id"):
        return False
    devices = int(data.get("devices") or 1)
    return not can_allocate(db.used_slots(user.id), devices)


async def _finish_free(message, state, db, user, admin_ids):
    data = await state.get_data()
    if _slots_full(db, data, user):
        await drop_state(state, db)
        await message.answer(f"Свободных слотов не хватает. Лимит {MAX_DEVICES} устройств.")
        return
    order_id = _create_order(db, data, user, status="paid")
    await drop_state(state, db, keep_promo=True)
    await _issue_and_send(message.bot, db, admin_ids, order_id, message.chat.id)


def _create_order(db, data, user, status="pending", comment=""):
    name = " ".join(part for part in (getattr(user, "first_name", None), getattr(user, "last_name", None)) if part)
    if not name:
        name = getattr(user, "full_name", None)
    return db.create_order(
        tg_id=user.id,
        tg_username=user.username,
        tg_name=name,
        node_id=data["node_id"],
        plan_name=data["plan_name"],
        days=data["days"],
        quota_gb=data["quota_gb"],
        protocol=data["protocol"],
        inbound_id=data.get("inbound_id"),
        protocol_label=data["protocol_label"],
        promo_id=data.get("promo_id"),
        promo_code=data.get("promo_code"),
        price=data["price"],
        status=status,
        comment=comment,
        renew_key_id=data.get("renew_key_id"),
        devices=1 if data.get("renew_key_id") else int(data.get("devices") or 1),
    )


@router.callback_query(F.data == "paid:go")
async def paid_go(callback: CallbackQuery, state):
    data = await state.get_data()
    if "price" not in data or data.get("price", 0) <= 0:
        await callback.answer("Сначала выберите тариф", show_alert=True)
        return
    await state.set_state(Buy.proof)
    await callback.answer()
    await callback.message.answer("Пришлите комментарий или скрин оплаты. Если нечего приложить, отправьте /skip.")


@router.message(Buy.proof, F.photo)
async def proof_photo(message: Message, state, db, admin_ids: set[int]):
    await _submit(message, state, db, admin_ids, message.caption or "", message.photo[-1].file_id)


@router.message(Buy.proof, F.text)
async def proof_text(message: Message, state, db, admin_ids: set[int]):
    text = message.text or ""
    comment = "" if text.strip() == "/skip" else text
    await _submit(message, state, db, admin_ids, comment, None)


async def _submit(message: Message, state, db, admin_ids, comment: str, photo: str | None):
    data = await state.get_data()
    if data.get("submitting"):
        return
    await state.update_data(submitting=True)
    user = message.from_user
    if _slots_full(db, data, user):
        await drop_state(state, db)
        await message.answer(f"Свободных слотов не хватает. Лимит {MAX_DEVICES} устройств.")
        return
    order_id = _create_order(db, data, user, status="pending", comment=comment)
    await drop_state(state, db, keep_promo=True)
    order = db.get_order(order_id)
    await notify_admins(message.bot, admin_ids, order, photo)
    await message.answer(
        f"Заявка #{order_id} отправлена администратору. Ключ придёт после подтверждения оплаты.",
        reply_markup=main_menu(user.id in admin_ids),
    )


async def _issue_and_send(bot, db, admin_ids, order_id: int, chat_id: int):
    try:
        keys = await issue_order(db, order_id)
    except Exception as exc:
        log.exception("issue %s", order_id)
        db.transition(order_id, "paid", "failed")
        order = db.get_order(order_id)
        await bot.send_message(chat_id, "Не удалось выдать ключ. Администратор уже уведомлён.")
        if order:
            for admin_id in admin_ids:
                try:
                    await bot.send_message(
                        admin_id,
                        f"Не удалось выдать ключ по заказу #{order_id}: {exc}",
                        reply_markup=order_kb(order_id, retry=True),
                    )
                except Exception:
                    continue
        return
    if not db.transition(order_id, "paid", "issued"):
        return
    order = db.get_order(order_id)
    for key in keys:
        try:
            await deliver_key(bot, chat_id, key, order["node_name"] or "—")
        except Exception:
            log.exception("deliver %s", order_id)


@router.callback_query(F.data.startswith("order:"))
async def on_order(callback: CallbackQuery, db, admin_ids: set[int]):
    if callback.from_user.id not in admin_ids:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    _, action, raw_id = callback.data.split(":")
    order_id = int(raw_id)
    if action == "no":
        if not db.transition(order_id, "pending", "rejected"):
            await callback.answer("Уже обработан")
            return
        order = db.get_order(order_id)
        if order and order["promo_id"]:
            db.release_promo(order["promo_id"])
        await callback.answer("Отклонено")
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        if order:
            await callback.bot.send_message(order["tg_id"], f"Оплата заказа #{order_id} отклонена.")
        return
    if action == "ok":
        moved = db.transition(order_id, "pending", "paid")
    elif action == "retry":
        moved = db.transition(order_id, "failed", "paid")
    else:
        await callback.answer()
        return
    if not moved:
        await callback.answer("Уже обработан")
        return
    await callback.answer("Выдаю ключ…")
    order = db.get_order(order_id)
    if not order:
        await callback.message.answer("Заказ не найден.")
        return
    await _issue_and_send(callback.bot, db, admin_ids, order_id, order["tg_id"])
    fresh = db.get_order(order_id)
    if fresh and fresh["status"] == "issued":
        await callback.message.answer(f"Заказ #{order_id} выполнен, ключ отправлен.")
