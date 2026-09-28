import logging
from datetime import timedelta

from aiogram.types import BufferedInputFile

from bot.instructions import instruction_for
from bot.panels import open_panel
from bot.qrutil import qr_png
from bot.slots import MAX_DEVICES, is_multi, key_count, limit_ip, panel_base_name, panel_username
from bot.timeutil import format_dt, iso, parse_dt, remaining_text, utcnow

log = logging.getLogger(__name__)


async def issue_order(db, order_id: int):
    order = db.get_order(order_id)
    if not order:
        raise RuntimeError("Заказ не найден")
    node = db.get_node(order["node_id"])
    if not node:
        raise RuntimeError("Локация не найдена")
    panel = open_panel(node)
    if order["renew_key_id"]:
        key = db.get_key(order["renew_key_id"])
        if not key or key["tg_id"] != order["tg_id"]:
            raise RuntimeError("Ключ для продления не найден")
        current = parse_dt(key["expires_at"])
        new_exp = max(utcnow(), current) + timedelta(days=order["days"])
        await panel.extend(
            panel_user_id=key["panel_user_id"],
            expires_at=new_exp,
            inbound_id=key["inbound_id"],
            email=key["username"],
        )
        db.update_key_expiry(key["id"], iso(new_exp))
        return [db.get_key(key["id"])]
    devices = int(order.get("devices") or 1)
    protocol = order["protocol"]
    need = key_count(protocol, devices)
    existing = db.keys_for_order(order_id)
    if len(existing) >= need:
        return existing
    allocated = sum(int(item.get("devices") or 1) for item in existing)
    if db.used_slots(order["tg_id"]) - allocated + devices > MAX_DEVICES:
        raise RuntimeError("Лимит 5 устройств")
    base = panel_base_name(order.get("tg_username"), order["tg_id"])
    per_key = devices if is_multi(protocol) else 1
    ip_limit = limit_ip(protocol, devices)
    while len(existing) < need:
        name = panel_username(base, db.count_keys(order["tg_id"]) + 1)
        issued = await panel.create(
            tg_id=order["tg_id"],
            protocol=protocol,
            days=order["days"],
            quota_gb=order["quota_gb"],
            inbound_id=order["inbound_id"],
            username=name,
            limit_ip=ip_limit,
        )
        db.add_key(
            tg_id=order["tg_id"],
            node_id=order["node_id"],
            protocol=protocol,
            protocol_label=order["protocol_label"],
            inbound_id=issued.inbound_id or order["inbound_id"],
            panel_user_id=issued.panel_user_id,
            username=issued.username,
            sub_id=issued.sub_id,
            link=issued.link,
            direct_link=issued.direct_link,
            expires_at=issued.expires_at,
            devices=per_key,
            order_id=order_id,
        )
        existing = db.keys_for_order(order_id)
    return existing


def key_text(key: dict, node_name: str) -> str:
    lines = [
        "Ключ готов.",
        f"Локация: {node_name}",
        f"Протокол: {key['protocol_label']}",
        f"Действует до: {format_dt(key['expires_at'])} ({remaining_text(key['expires_at'])})",
        f"Устройств на ключе: {key.get('devices') or 1}",
        "",
        "Подписка:",
        key["link"],
    ]
    if key.get("direct_link"):
        lines.extend(["", "Прямая ссылка:", key["direct_link"]])
    lines.extend(["", instruction_for(key["protocol"])])
    return "\n".join(lines)


async def deliver_key(bot, chat_id: int, key: dict, node_name: str) -> None:
    text = key_text(key, node_name)
    await bot.send_message(chat_id, text[:4096])
    link = key.get("direct_link") or key["link"]
    try:
        png = qr_png(link)
        await bot.send_photo(chat_id, BufferedInputFile(png, filename="qr.png"), caption="QR ключа")
    except Exception:
        log.exception("qr")


async def remove_key(db, key: dict) -> None:
    node = db.get_node(key["node_id"])
    if node:
        panel = open_panel(node)
        try:
            await panel.delete(panel_user_id=key["panel_user_id"], inbound_id=key["inbound_id"])
        except Exception as exc:
            if "404" not in str(exc):
                raise
    db.delete_key(key["id"])
