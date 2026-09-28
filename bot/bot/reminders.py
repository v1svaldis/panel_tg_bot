from datetime import datetime, timedelta

from bot.timeutil import format_dt, parse_dt


def reminder_kind(expires_at: datetime, now: datetime, reminded_3: bool, reminded_1: bool, reminded_0: bool):
    remaining = expires_at - now
    if remaining <= timedelta(0):
        return 0 if not reminded_0 else None
    if remaining <= timedelta(days=1):
        return 1 if not reminded_1 else None
    if remaining <= timedelta(days=3):
        return 3 if not reminded_3 else None
    return None


def reminder_text(kind: int, protocol_label: str, node_name: str, expires_at: str) -> str:
    when = format_dt(expires_at)
    title = f"{protocol_label} ({node_name})"
    if kind == 3:
        return (
            f"Ключ {title} истекает {when} — осталось меньше 3 дней. "
            "Продлить можно в «Мои ключи»."
        )
    if kind == 1:
        return (
            f"Ключ {title} истекает {when} — осталось меньше суток. "
            "Продлить можно в «Мои ключи»."
        )
    return (
        f"Срок ключа {title} истёк ({when}). "
        "Чтобы продолжить, продлите его в «Мои ключи»."
    )


async def send_reminders(bot, db) -> None:
    from bot.timeutil import utcnow
    now = utcnow()
    for key in db.list_keys_all():
        kind = reminder_kind(
            parse_dt(key["expires_at"]),
            now,
            bool(key["reminded_3"]),
            bool(key["reminded_1"]),
            bool(key["reminded_0"]),
        )
        if kind is None:
            continue
        text = reminder_text(kind, key["protocol_label"], key["node_name"], key["expires_at"])
        try:
            await bot.send_message(key["tg_id"], text)
        except Exception:
            continue
        db.mark_reminded(key["id"], kind)
