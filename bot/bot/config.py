import os
from dataclasses import dataclass
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: tuple[int, ...]
    db_path: Path


def load_config() -> Config:
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT / ".env")
    except ImportError:
        pass
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Задайте BOT_TOKEN")
    raw = os.environ.get("ADMIN_IDS", "")
    ids = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            raise SystemExit(f"ADMIN_IDS: не число «{part}»")
    if not ids:
        raise SystemExit("Задайте ADMIN_IDS")
    db_path = Path(os.environ.get("DB_PATH", "data/bot.db"))
    if not db_path.is_absolute():
        db_path = PROJECT / db_path
    return Config(bot_token=token, admin_ids=tuple(ids), db_path=db_path)
