from datetime import timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.handlers.flow import parse_int, valid_url
from bot.keyboards import admin_menu, choices_kb, order_kb
from bot.panels import check_node
from bot.panels.base import PanelError
from bot.services.issue import remove_key
from bot.slots import MAX_DEVICES
from bot.states import AdminNode, AdminPay, AdminPlan, AdminPromo, AdminUser
from bot.timeutil import format_dt, iso, remaining_text, utcnow

router = Router()

_RIXXX_LABELS = {"naive": "NaiveProxy", "mieru": "Mieru", "hy2": "Hysteria2"}


def _is_admin(user_id: int, admin_ids: set[int]) -> bool:
    return user_id in admin_ids


@router.callback_query(F.data == "adm:nodes")
async def nodes_list(callback: CallbackQuery, db, admin_ids: set[int]):
    if not _is_admin(callback.from_user.id, admin_ids):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    nodes = db.list_nodes(enabled_only=False)
    await callback.answer()
    if not nodes:
        builder = InlineKeyboardBuilder()
        builder.button(text="Добавить", callback_data="nodeadd")
        await callback.message.answer("Нод пока нет.", reply_markup=builder.as_markup())
        return
    for node in nodes:
        tail = node["token"][-4:] if len(node["token"]) >= 4 else "••••"
        builder = InlineKeyboardBuilder()
        builder.button(text="Проверить", callback_data=f"ntest:{node['id']}")
        builder.button(text="Удалить", callback_data=f"ndel:{node['id']}")
        builder.adjust(2)
        kind = "RIXXX" if node["kind"] == "rixxx" else "3x-ui"
        await callback.message.answer(
            f"#{node['id']} {node['name']} ({kind})\n{node['base_url']}\nтокен ••••{tail}",
            reply_markup=builder.as_markup(),
        )
    builder = InlineKeyboardBuilder()
    builder.button(text="Добавить ноду", callback_data="nodeadd")
    await callback.message.answer("Добавить ещё одну локацию:", reply_markup=builder.as_markup())


@router.callback_query(F.data == "nodeadd")
async def node_add(callback: CallbackQuery, state, admin_ids: set[int]):
    if not _is_admin(callback.from_user.id, admin_ids):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await state.set_state(AdminNode.kind)
    builder = InlineKeyboardBuilder()
    builder.button(text="RIXXX (Naive/Mieru/Hy2)", callback_data="nkind:rixxx")
    builder.button(text="3x-ui", callback_data="nkind:xui")
    builder.button(text="Отмена", callback_data="flow:cancel")
    builder.adjust(1)
    await callback.answer()
    await callback.message.answer("Тип панели:", reply_markup=builder.as_markup())


@router.callback_query(AdminNode.kind, F.data.startswith("nkind:"))
async def node_kind(callback: CallbackQuery, state):
    await state.update_data(kind=callback.data.split(":")[1])
    await state.set_state(AdminNode.name)
    await callback.answer()
    await callback.message.answer("Название локации, как его увидит пользователь:")


@router.message(AdminNode.name)
async def node_name(message: Message, state):
    name = (message.text or "").strip()
    if not name:
        await message.answer("Введите название.")
        return
    await state.update_data(name=name[:64])
    await state.set_state(AdminNode.url)
    await message.answer(
        "URL панели до /api.\n"
        "RIXXX: https://panel.example.com/webBasePath\n"
        "3x-ui: https://хост:порт/секрет"
    )


@router.message(AdminNode.url)
async def node_url(message: Message, state):
    url = (message.text or "").strip()
    if not valid_url(url):
        await message.answer("Нужен адрес http:// или https://")
        return
    await state.update_data(base_url=url)
    await state.set_state(AdminNode.token)
    await message.answer("Bearer-токен панели:")


@router.message(AdminNode.token)
async def node_token(message: Message, state):
    token = (message.text or "").strip()
    if len(token) < 8:
        await message.answer("Токен слишком короткий.")
        return
    await state.update_data(token=token)
    data = await state.get_data()
    if data["kind"] == "xui":
        await state.set_state(AdminNode.sub_base)
        await message.answer(
            "Базовый URL подписки 3x-ui, без /sub/id.\n"
            "Например https://хост:2096 или https://хост:2096/секрет\n"
            "Бот добавит /sub/{subId}."
        )
        return
    await message.answer("Читаю протоколы панели…")
    await _load_choices(message, state)


@router.message(AdminNode.sub_base)
async def node_sub(message: Message, state):
    url = (message.text or "").strip()
    if not valid_url(url):
        await message.answer("Нужен адрес http:// или https://")
        return
    await state.update_data(sub_base_url=url)
    await message.answer("Читаю inbound'ы…")
    await _load_choices(message, state)


async def _load_choices(message: Message, state):
    data = await state.get_data()
    node = {
        "kind": data["kind"],
        "base_url": data["base_url"],
        "token": data["token"],
        "sub_base_url": data.get("sub_base_url") or "",
    }
    try:
        if data["kind"] == "rixxx":
            from bot.panels import open_panel
            names = await open_panel(node).protocols()
            choices = [
                {"protocol": name, "label": _RIXXX_LABELS.get(name, name), "inbound_id": None, "remark": "", "on": True}
                for name in names
            ]
        else:
            from bot.panels import open_panel
            items = await open_panel(node).list_inbounds()
            choices = [
                {
                    "protocol": item["protocol"] or "vless",
                    "label": f"{item['protocol']} · {item['remark'] or item['inbound_id']}"[:40],
                    "inbound_id": item["inbound_id"],
                    "remark": item["remark"] or "",
                    "on": True,
                }
                for item in items
            ]
    except PanelError as exc:
        await message.answer(f"Панель не ответила: {exc}\n/cancel и попробуйте снова.")
        return
    if not choices:
        await message.answer("На панели нет протоколов для продажи. /cancel")
        return
    await state.update_data(choices=choices)
    await state.set_state(AdminNode.pick)
    await message.answer("Что продавать на этой локации:", reply_markup=choices_kb(choices))


@router.callback_query(AdminNode.pick, F.data.startswith("np:"))
async def node_toggle(callback: CallbackQuery, state):
    data = await state.get_data()
    choices = data.get("choices") or []
    index = int(callback.data.split(":")[1])
    if 0 <= index < len(choices):
        choices[index]["on"] = not choices[index].get("on", True)
        await state.update_data(choices=choices)
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=choices_kb(choices))
    except Exception:
        await callback.message.answer("Что продавать:", reply_markup=choices_kb(choices))


@router.callback_query(AdminNode.pick, F.data == "nsave")
async def node_save(callback: CallbackQuery, state, db):
    data = await state.get_data()
    selected = [item for item in data.get("choices") or [] if item.get("on", True)]
    if not selected:
        await callback.answer("Выберите хотя бы один протокол", show_alert=True)
        return
    if data["kind"] == "rixxx":
        payload = [item["protocol"] for item in selected]
    else:
        payload = [
            {"inbound_id": item["inbound_id"], "protocol": item["protocol"], "remark": item.get("remark") or ""}
            for item in selected
        ]
    node_id = db.add_node(
        data["kind"], data["name"], data["base_url"], data["token"],
        data.get("sub_base_url") or "", payload,
    )
    await state.clear()
    await callback.answer("Сохранено")
    await callback.message.answer(f"Локация #{node_id} «{data['name']}» добавлена.", reply_markup=admin_menu())


@router.callback_query(F.data.startswith("ntest:"))
async def node_test(callback: CallbackQuery, db, admin_ids: set[int]):
    if not _is_admin(callback.from_user.id, admin_ids):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    node = db.get_node(int(callback.data.split(":")[1]))
    if not node:
        await callback.answer("Нода не найдена", show_alert=True)
        return
    await callback.answer("Проверяю…")
    try:
        text = await check_node(node)
    except PanelError as exc:
        text = f"Нет связи: {exc}"
    await callback.message.answer(text)


@router.callback_query(F.data.startswith("ndel:"))
async def node_delete_ask(callback: CallbackQuery, admin_ids: set[int]):
    if not _is_admin(callback.from_user.id, admin_ids):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    node_id = callback.data.split(":")[1]
    builder = InlineKeyboardBuilder()
    builder.button(text="Удалить", callback_data=f"ndelok:{node_id}")
    builder.button(text="Отмена", callback_data="flow:cancel")
    await callback.answer()
    await callback.message.answer(f"Удалить локацию #{node_id}?", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("ndelok:"))
async def node_delete_do(callback: CallbackQuery, db, admin_ids: set[int]):
    if not _is_admin(callback.from_user.id, admin_ids):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    err = db.delete_node(int(callback.data.split(":")[1]))
    await callback.answer("Готово" if not err else err, show_alert=bool(err))
    if not err:
        await callback.message.answer("Локация удалена.")


@router.callback_query(F.data == "adm:plans")
async def plans_list(callback: CallbackQuery, db, admin_ids: set[int]):
    if not _is_admin(callback.from_user.id, admin_ids):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    plans = db.list_plans(enabled_only=False)
    await callback.answer()
    if not plans:
        await callback.message.answer("Тарифов нет.")
    for plan in plans:
        quota = "безлимит" if not plan["quota_gb"] else f"{plan['quota_gb']} ГБ"
        builder = InlineKeyboardBuilder()
        builder.button(text="Удалить", callback_data=f"pdel:{plan['id']}")
        await callback.message.answer(
            f"#{plan['id']} {plan['name']}: {plan['days']} дн., {plan['price']} ₽, {quota}",
            reply_markup=builder.as_markup(),
        )
    builder = InlineKeyboardBuilder()
    builder.button(text="Добавить тариф", callback_data="planadd")
    await callback.message.answer("Новый тариф:", reply_markup=builder.as_markup())


@router.callback_query(F.data == "planadd")
async def plan_add(callback: CallbackQuery, state, admin_ids: set[int]):
    if not _is_admin(callback.from_user.id, admin_ids):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await state.set_state(AdminPlan.name)
    await callback.answer()
    await callback.message.answer("Название тарифа:")


@router.message(AdminPlan.name)
async def plan_name(message: Message, state):
    name = (message.text or "").strip()
    if not name:
        await message.answer("Введите название.")
        return
    await state.update_data(name=name[:64])
    await state.set_state(AdminPlan.days)
    await message.answer("Срок в днях:")


@router.message(AdminPlan.days)
async def plan_days(message: Message, state):
    days = parse_int(message.text or "")
    if days is None or days < 1 or days > 3650:
        await message.answer("Введите число дней от 1 до 3650.")
        return
    await state.update_data(days=days)
    await state.set_state(AdminPlan.price)
    await message.answer("Цена в рублях, целое число:")


@router.message(AdminPlan.price)
async def plan_price(message: Message, state):
    price = parse_int(message.text or "")
    if price is None:
        await message.answer("Введите целое число, например 300.")
        return
    await state.update_data(price=price)
    await state.set_state(AdminPlan.quota)
    await message.answer("Лимит трафика в ГБ. 0 — безлимит.")


@router.message(AdminPlan.quota)
async def plan_quota(message: Message, state, db):
    quota = parse_int(message.text or "")
    if quota is None:
        await message.answer("Введите целое число ГБ или 0.")
        return
    data = await state.get_data()
    plan_id = db.add_plan(data["name"], data["days"], data["price"], quota)
    await state.clear()
    await message.answer(f"Тариф #{plan_id} «{data['name']}» сохранён.", reply_markup=admin_menu())


@router.callback_query(F.data.startswith("pdel:"))
async def plan_delete(callback: CallbackQuery, db, admin_ids: set[int]):
    if not _is_admin(callback.from_user.id, admin_ids):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    db.delete_plan(int(callback.data.split(":")[1]))
    await callback.answer("Удалён")
    await callback.message.answer("Тариф удалён.")


@router.callback_query(F.data == "adm:pay")
async def pay_show(callback: CallbackQuery, state, db, admin_ids: set[int]):
    if not _is_admin(callback.from_user.id, admin_ids):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    current = db.get_setting("payment_text") or "не задан"
    await state.set_state(AdminPay.text)
    await callback.answer()
    await callback.message.answer(f"Сейчас реквизиты:\n{current}\n\nПришлите новый текст одним сообщением.")


@router.message(AdminPay.text)
async def pay_save(message: Message, state, db):
    db.set_setting("payment_text", (message.text or "").strip()[:2000])
    await state.clear()
    await message.answer("Реквизиты сохранены.", reply_markup=admin_menu())


@router.callback_query(F.data == "adm:promos")
async def promos_list(callback: CallbackQuery, db, admin_ids: set[int]):
    if not _is_admin(callback.from_user.id, admin_ids):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    promos = db.list_promos()
    await callback.answer()
    if not promos:
        await callback.message.answer("Промокодов нет.")
    for promo in promos:
        limit = "без лимита" if promo["max_uses"] is None else f"{promo['used']}/{promo['max_uses']}"
        till = format_dt(promo["expires_at"]) if promo["expires_at"] else "без срока"
        builder = InlineKeyboardBuilder()
        builder.button(text="Удалить", callback_data=f"cpdel:{promo['id']}")
        await callback.message.answer(
            f"{promo['code']}: {promo['percent']}% · {limit} · {till}",
            reply_markup=builder.as_markup(),
        )
    builder = InlineKeyboardBuilder()
    builder.button(text="Создать промокод", callback_data="promoadd")
    await callback.message.answer("Новый промокод:", reply_markup=builder.as_markup())


@router.callback_query(F.data == "promoadd")
async def promo_add(callback: CallbackQuery, state, admin_ids: set[int]):
    if not _is_admin(callback.from_user.id, admin_ids):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await state.set_state(AdminPromo.code)
    await callback.answer()
    await callback.message.answer("Код латиницей, без пробелов:")


@router.message(AdminPromo.code)
async def promo_code(message: Message, state):
    await state.update_data(code=(message.text or "").strip())
    await state.set_state(AdminPromo.percent)
    await message.answer("Скидка целым числом от 5 до 100:")


@router.message(AdminPromo.percent)
async def promo_percent(message: Message, state):
    percent = parse_int(message.text or "")
    if percent is None or percent < 5 or percent > 100:
        await message.answer("Нужно целое число от 5 до 100.")
        return
    await state.update_data(percent=percent)
    await state.set_state(AdminPromo.uses)
    await message.answer("Сколько раз можно применить. 0 — без лимита.")


@router.message(AdminPromo.uses)
async def promo_uses(message: Message, state):
    uses = parse_int(message.text or "")
    if uses is None:
        await message.answer("Введите целое число или 0.")
        return
    await state.update_data(max_uses=None if uses == 0 else uses)
    await state.set_state(AdminPromo.days)
    await message.answer("Сколько дней код действует. 0 — без срока.")


@router.message(AdminPromo.days)
async def promo_days(message: Message, state, db):
    days = parse_int(message.text or "")
    if days is None:
        await message.answer("Введите целое число или 0.")
        return
    data = await state.get_data()
    expires = iso(utcnow() + timedelta(days=days)) if days else None
    try:
        promo_id = db.add_promo(data["code"], data["percent"], data["max_uses"], expires)
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await state.clear()
    await message.answer(f"Промокод #{promo_id} сохранён.", reply_markup=admin_menu())


@router.callback_query(F.data.startswith("cpdel:"))
async def promo_delete(callback: CallbackQuery, db, admin_ids: set[int]):
    if not _is_admin(callback.from_user.id, admin_ids):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    db.delete_promo(int(callback.data.split(":")[1]))
    await callback.answer("Удалён")
    await callback.message.answer("Промокод удалён.")


@router.callback_query(F.data == "adm:orders")
async def orders_list(callback: CallbackQuery, db, admin_ids: set[int]):
    if not _is_admin(callback.from_user.id, admin_ids):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    orders = db.list_orders("pending")
    await callback.answer()
    if not orders:
        await callback.message.answer("Нет заявок, которые ждут подтверждения.")
        return
    for order in orders:
        await callback.message.answer(
            f"#{order['id']} {order['plan_name']} · {order['price']} ₽ · {order['node_name']}\n"
            f"{order['protocol_label']} · id {order['tg_id']}",
            reply_markup=order_kb(order["id"]),
        )


def _user_card(db, tg_id: int) -> tuple[str, InlineKeyboardBuilder] | None:
    user = db.get_user(tg_id)
    if not user:
        return None
    keys = db.list_keys(tg_id)
    used = db.used_slots(tg_id)
    nick = f"@{user['username']}" if user.get("username") else "—"
    status = "заблокирован" if user.get("blocked") else "активен"
    lines = [
        f"id: {tg_id}",
        f"ник: {nick}",
        f"устройства: {used} из {MAX_DEVICES}",
        f"статус: {status}",
    ]
    if not keys:
        lines.append("Ключей нет.")
    for key in keys:
        lines.append(
            f"#{key['id']} {key['protocol_label']} · {key['node_name']} · "
            f"{remaining_text(key['expires_at'])} · устройств {key.get('devices') or 1}"
        )
    builder = InlineKeyboardBuilder()
    for key in keys[:15]:
        builder.button(text=f"Удалить #{key['id']}", callback_data=f"ukdel:{key['id']}")
    if user.get("blocked"):
        builder.button(text="Разблокировать", callback_data=f"ublk:0:{tg_id}")
    else:
        builder.button(text="Заблокировать", callback_data=f"ublk:1:{tg_id}")
    builder.adjust(1)
    return "\n".join(lines)[:4000], builder


@router.callback_query(F.data == "adm:users")
async def users_ask(callback: CallbackQuery, state, admin_ids: set[int]):
    if not _is_admin(callback.from_user.id, admin_ids):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await state.set_state(AdminUser.query)
    await callback.answer()
    await callback.message.answer("Введите Telegram ID или ник:")


@router.message(AdminUser.query)
async def users_search(message: Message, state, db, admin_ids: set[int]):
    if not _is_admin(message.from_user.id, admin_ids):
        await state.clear()
        return
    found = db.search_users(message.text or "")
    await state.clear()
    if not found:
        await message.answer("Никого не нашёл.", reply_markup=admin_menu())
        return
    for user in found:
        card = _user_card(db, user["tg_id"])
        if card:
            text, builder = card
            await message.answer(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("ukdel:"))
async def user_key_delete(callback: CallbackQuery, db, admin_ids: set[int]):
    if not _is_admin(callback.from_user.id, admin_ids):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    key = db.get_key(int(callback.data.split(":")[1]))
    if not key:
        await callback.answer("Ключ не найден", show_alert=True)
        return
    await callback.answer("Удаляю…")
    try:
        await remove_key(db, key)
    except Exception as exc:
        await callback.message.answer(f"Не удалось удалить ключ: {exc}")
        return
    card = _user_card(db, key["tg_id"])
    if not card:
        await callback.message.answer("Ключ удалён.")
        return
    text, builder = card
    await callback.message.answer(f"Ключ удалён.\n\n{text}", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("ublk:"))
async def user_block(callback: CallbackQuery, db, admin_ids: set[int]):
    if not _is_admin(callback.from_user.id, admin_ids):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    _, flag, raw_id = callback.data.split(":")
    tg_id = int(raw_id)
    if not db.get_user(tg_id):
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    db.set_blocked(tg_id, flag == "1")
    await callback.answer("Готово")
    card = _user_card(db, tg_id)
    if not card:
        return
    text, builder = card
    await callback.message.answer(text, reply_markup=builder.as_markup())
