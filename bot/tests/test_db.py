import tempfile
import unittest
from pathlib import Path

from bot.db import Database


class PromoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "bot.db")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_percent_bounds(self):
        self.db.add_promo("SALE5", 5, None, None)
        self.db.add_promo("FREE", 100, 1, None)
        with self.assertRaises(ValueError):
            self.db.add_promo("LOW", 4, None, None)
        with self.assertRaises(ValueError):
            self.db.add_promo("HIGH", 101, None, None)

    def test_reserve_limit(self):
        self.db.add_promo("ONCE", 50, 1, None)
        promo, err = self.db.reserve_promo("once")
        self.assertIsNone(err)
        self.assertEqual(promo["percent"], 50)
        again, err = self.db.reserve_promo("ONCE")
        self.assertIsNone(again)
        self.assertIn("нельзя", err)
        self.db.release_promo(promo["id"])
        promo, err = self.db.reserve_promo("ONCE")
        self.assertIsNone(err)
        self.assertIsNotNone(promo)


if __name__ == "__main__":
    unittest.main()
