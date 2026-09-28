from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_dt(value: str) -> str:
    return parse_dt(value).strftime("%d.%m.%Y %H:%M UTC")


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def remaining_text(value: str) -> str:
    delta = parse_dt(value) - utcnow()
    if delta.total_seconds() <= 0:
        return "истёк"
    if delta.days >= 1:
        return f"осталось {delta.days} дн."
    hours = max(1, delta.seconds // 3600)
    return f"осталось {hours} ч."
