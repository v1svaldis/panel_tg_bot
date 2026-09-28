import unittest

from bot.pricing import discounted_price, validate_percent


class PricingTests(unittest.TestCase):
    def test_five_percent(self):
        self.assertEqual(discounted_price(1000, 5), 950)

    def test_half(self):
        self.assertEqual(discounted_price(1000, 50), 500)

    def test_full_discount_is_free(self):
        self.assertEqual(discounted_price(1000, 100), 0)
        self.assertEqual(discounted_price(1, 100), 0)

    def test_ten_percent(self):
        self.assertEqual(discounted_price(100, 10), 90)

    def test_rejects_out_of_range(self):
        for bad in (4, 0, 101, 200, -5):
            with self.assertRaises(ValueError):
                validate_percent(bad)
            with self.assertRaises(ValueError):
                discounted_price(100, bad)

    def test_rejects_non_int(self):
        with self.assertRaises(ValueError):
            validate_percent(5.0)
        with self.assertRaises(ValueError):
            validate_percent(True)
        with self.assertRaises(ValueError):
            discounted_price(True, 10)


if __name__ == "__main__":
    unittest.main()
