import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from bot.db import Database
from bot.reminders import reminder_kind, send_reminders
from bot.timeutil import iso, utcnow


class KindTests(unittest.TestCase):
    def test_windows(self):
        now = utcnow()
        self.assertEqual(reminder_kind(now + timedelta(days=3), now, False, False, False), 3)
        self.assertIsNone(reminder_kind(now + timedelta(days=3, seconds=1), now, False, False, False))
        self.assertEqual(reminder_kind(now + timedelta(days=1), now, False, False, False), 1)
        self.assertEqual(reminder_kind(now + timedelta(hours=12), now, False, False, False), 1)
        self.assertIsNone(reminder_kind(now + timedelta(hours=12), now, False, True, False))
        self.assertEqual(reminder_kind(now - timedelta(minutes=1), now, False, False, False), 0)
        self.assertIsNone(reminder_kind(now - timedelta(minutes=1), now, False, False, True))
        self.assertEqual(reminder_kind(now + timedelta(days=2), now, False, False, False), 3)


class SendTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "bot.db")
            node_id = db.add_node("rixxx", "NL", "https://panel.example", "tokentoken", "", ["naive"])
            db.add_key(
                tg_id=42,
                node_id=node_id,
                protocol="naive",
                protocol_label="NaiveProxy",
                panel_user_id="u1",
                link="https://sub.example/sub/abc",
                expires_at=iso(utcnow() + timedelta(days=2)),
            )

            class Bot:
                def __init__(self):
                    self.sent = []

                async def send_message(self, chat_id, text):
                    self.sent.append((chat_id, text))

            bot = Bot()
            try:
                await send_reminders(bot, db)
                self.assertEqual(len(bot.sent), 1)
                self.assertIn("меньше 3 дней", bot.sent[0][1])
                self.assertEqual(bot.sent[0][0], 42)
                await send_reminders(bot, db)
                self.assertEqual(len(bot.sent), 1)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
