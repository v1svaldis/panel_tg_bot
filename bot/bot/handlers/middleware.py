from aiogram import BaseMiddleware


class ContextMiddleware(BaseMiddleware):
    def __init__(self, db, admin_ids: set[int]):
        self.db = db
        self.admin_ids = admin_ids

    async def __call__(self, handler, event, data):
        data["db"] = self.db
        data["admin_ids"] = self.admin_ids
        return await handler(event, data)
