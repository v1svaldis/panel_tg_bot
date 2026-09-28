import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import load_config
from bot.db import Database
from bot.handlers import admin, buy, user
from bot.handlers.middleware import ContextMiddleware
from bot.reminders import send_reminders


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    db = Database(cfg.db_path)
    bot = Bot(cfg.bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(ContextMiddleware(db, set(cfg.admin_ids)))
    dp.include_router(user.router)
    dp.include_router(buy.router)
    dp.include_router(admin.router)
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        send_reminders, "interval", minutes=30, args=[bot, db],
        max_instances=1, next_run_time=datetime.now(),
    )
    scheduler.start()
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
