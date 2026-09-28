import json
import re

from aiogram.types import CallbackQuery, Message

_URL_RE = re.compile(r"^https?://\S+$", re.I)


async def drop_state(state, db, keep_promo: bool = False) -> None:
    data = await state.get_data()
    promo_id = data.get("promo_id")
    await state.clear()
    if promo_id and not keep_promo:
        db.release_promo(promo_id)


def valid_url(text: str) -> bool:
    return bool(_URL_RE.match((text or "").strip()))


def parse_int(text: str):
    raw = (text or "").strip()
    if not re.fullmatch(r"\d+", raw):
        return None
    return int(raw)


def node_choices(node: dict) -> list[dict]:
    raw = json.loads(node.get("protocols_json") or "[]")
    labels = {"naive": "NaiveProxy", "mieru": "Mieru", "hy2": "Hysteria2"}
    if node["kind"] == "rixxx":
        return [
            {"protocol": name, "label": labels.get(name, name), "inbound_id": None, "remark": ""}
            for name in raw
        ]
    choices = []
    for item in raw:
        protocol = item.get("protocol") or "vless"
        remark = item.get("remark") or str(item.get("inbound_id") or "")
        choices.append({
            "protocol": protocol,
            "label": f"{protocol} · {remark}"[:40],
            "inbound_id": item.get("inbound_id"),
            "remark": remark,
        })
    return choices


def order_text(order: dict) -> str:
    who = order.get("tg_name") or "—"
    username = order.get("tg_username")
    lines = [
        f"Оплата #{order['id']}",
        f"Пользователь: {who}" + (f" @{username}" if username else ""),
        f"id: {order['tg_id']}",
        f"Локация: {order['node_name']}",
        f"Протокол: {order['protocol_label']}",
        f"Тариф: {order['plan_name']}, {order['days']} дн.",
        f"Сумма: {order['price']} ₽",
    ]
    if not order.get("renew_key_id"):
        lines.append(f"Устройств: {order.get('devices') or 1}")
    if order.get("promo_code"):
        lines.append(f"Промокод: {order['promo_code']}")
    if order.get("renew_key_id"):
        lines.append(f"Продление ключа #{order['renew_key_id']}")
    if order.get("comment"):
        lines.append(f"Комментарий: {order['comment']}")
    return "\n".join(lines)


async def notify_admins(bot, admin_ids, order: dict, photo: str | None = None) -> None:
    from bot.keyboards import order_kb
    text = order_text(order)
    markup = order_kb(order["id"])
    for admin_id in admin_ids:
        try:
            if photo and len(text) <= 1000:
                await bot.send_photo(admin_id, photo, caption=text, reply_markup=markup)
            else:
                if photo:
                    await bot.send_photo(admin_id, photo)
                await bot.send_message(admin_id, text, reply_markup=markup)
        except Exception:
            continue


async def answer_to(event, text: str, **kwargs):
    if isinstance(event, CallbackQuery):
        if event.message:
            return await event.message.answer(text, **kwargs)
        return await event.bot.send_message(event.from_user.id, text, **kwargs)
    return await event.answer(text, **kwargs)


def actor(message: Message) -> tuple[int, str | None, str | None]:
    user = message.from_user
    name = " ".join(part for part in (user.first_name, user.last_name) if part)
    return user.id, user.username, name or None
