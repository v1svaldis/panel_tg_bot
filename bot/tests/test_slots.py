import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from bot.db import Database
from bot.panels.base import IssuedKey
from bot.services.issue import issue_order
from bot.slots import (
    can_allocate,
    key_count,
    label_for,
    limit_ip,
    locations_for_protocol,
    panel_base_name,
    panel_username,
    unique_protocols,
)
from bot.timeutil import iso, remaining_text, utcnow


class SlotRuleTests(unittest.TestCase):
    def test_vless_one_key_hy2_per_device(self):
        self.assertEqual(key_count("vless", 3), 1)
        self.assertEqual(limit_ip("vless", 3), 3)
        self.assertEqual(key_count("vmess", 2), 1)
        self.assertEqual(key_count("trojan", 4), 1)
        self.assertEqual(key_count("hy2", 2), 2)
        self.assertEqual(limit_ip("hy2", 2), 1)
        self.assertEqual(key_count("hysteria", 2), 2)
        self.assertEqual(key_count("naive", 2), 2)
        self.assertEqual(key_count("shadowsocks", 2), 2)
        self.assertFalse(can_allocate(5, 1))
        self.assertFalse(can_allocate(4, 2))
        self.assertFalse(can_allocate(0, 6))
        self.assertTrue(can_allocate(3, 2))

    def test_name_from_nick(self):
        self.assertEqual(panel_base_name("@Ivan.Petrov", 9), "Ivan.Petrov")
        self.assertEqual(panel_base_name("bad nick!", 9), "badnick")
        self.assertEqual(panel_base_name(None, 9), "tg9")
        self.assertEqual(panel_base_name("@", 9), "tg9")
        self.assertEqual(panel_username("Ivan", 1), "Ivan")
        self.assertEqual(panel_username("Ivan", 2), "Ivan_2")
        self.assertEqual(panel_username("Ivan", 3), "Ivan_3")

    def test_locations_follow_protocol(self):
        entries = [
            {"node_id": 1, "node_name": "NL", "protocol": "hy2", "inbound_id": None, "remark": ""},
            {"node_id": 1, "node_name": "NL", "protocol": "naive", "inbound_id": None, "remark": ""},
            {"node_id": 2, "node_name": "DE", "protocol": "vless", "inbound_id": 3, "remark": "main"},
            {"node_id": 2, "node_name": "DE", "protocol": "hy2", "inbound_id": 8, "remark": "udp"},
        ]
        protocols = [item["protocol"] for item in unique_protocols(entries)]
        self.assertEqual(protocols, ["hy2", "naive", "vless"])
        self.assertEqual(label_for("hy2"), "Hysteria2")
        places = locations_for_protocol(entries, "hy2")
        self.assertEqual([item["node_name"] for item in places], ["NL", "DE"])
        self.assertEqual(locations_for_protocol(entries, "vless")[0]["remark"], "main")

    def test_remaining(self):
        self.assertEqual(remaining_text(iso(utcnow() - timedelta(minutes=5))), "истёк")
        self.assertEqual(remaining_text(iso(utcnow() + timedelta(days=12, hours=2))), "осталось 12 дн.")
        self.assertEqual(remaining_text(iso(utcnow() + timedelta(minutes=20))), "осталось 1 ч.")


class IssueSlotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "bot.db")
        self.node_id = self.db.add_node("xui", "NL", "https://panel", "tok", "https://sub", [])
        self.db.upsert_user(5, "Ivan", "Ivan")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def _order(self, protocol, devices, inbound_id=3):
        return self.db.create_order(
            tg_id=5,
            tg_username="Ivan",
            tg_name="Ivan",
            node_id=self.node_id,
            plan_name="месяц",
            days=30,
            quota_gb=0,
            protocol=protocol,
            inbound_id=inbound_id,
            protocol_label=protocol,
            price=100,
            status="paid",
            devices=devices,
        )

    async def test_vless_and_hy2_slots_and_sixth_refused(self):
        panel = _FakePanel()
        with patch("bot.services.issue.open_panel", return_value=panel):
            vless = await issue_order(self.db, self._order("vless", 3))
            hy2 = await issue_order(self.db, self._order("hy2", 2, inbound_id=8))
            with self.assertRaises(RuntimeError):
                await issue_order(self.db, self._order("hy2", 1, inbound_id=8))
        self.assertEqual(len(vless), 1)
        self.assertEqual(vless[0]["devices"], 3)
        self.assertEqual(vless[0]["username"], "Ivan")
        self.assertEqual(panel.calls[0]["limit_ip"], 3)
        self.assertEqual(panel.calls[0]["username"], "Ivan")
        self.assertEqual(len(hy2), 2)
        self.assertEqual([item["devices"] for item in hy2], [1, 1])
        self.assertEqual([item["username"] for item in hy2], ["Ivan_2", "Ivan_3"])
        self.assertEqual(panel.calls[1]["limit_ip"], 1)
        self.assertEqual(self.db.used_slots(5), 5)
        self.assertEqual(self.db.count_keys(5), 3)

    async def test_retry_does_not_duplicate(self):
        panel = _FakePanel(fail_at=2)
        order_id = self._order("hy2", 2)
        with patch("bot.services.issue.open_panel", return_value=panel):
            with self.assertRaises(RuntimeError):
                await issue_order(self.db, order_id)
            panel.fail_at = None
            keys = await issue_order(self.db, order_id)
        self.assertEqual(len(keys), 2)
        self.assertEqual([item["username"] for item in keys], ["Ivan", "Ivan_2"])
        self.assertEqual(self.db.used_slots(5), 2)
        self.assertEqual(len(panel.calls), 3)

    def test_block_and_search_keep_tg_id(self):
        self.db.set_blocked(5, True)
        self.db.upsert_user(5, "Ivan", "Ivan Petrov")
        self.assertTrue(self.db.is_blocked(5))
        self.assertEqual(self.db.search_users("@ivan")[0]["tg_id"], 5)
        self.assertEqual(self.db.search_users("5")[0]["username"], "Ivan")
        self.db.set_blocked(5, False)
        self.assertFalse(self.db.is_blocked(5))


class _FakePanel:
    def __init__(self, fail_at=None):
        self.calls = []
        self.fail_at = fail_at

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_at is not None and len(self.calls) == self.fail_at:
            raise RuntimeError("панель недоступна")
        return IssuedKey(
            panel_user_id=f"p{len(self.calls)}",
            username=kwargs["username"],
            link=f"https://sub/{kwargs['username']}",
            inbound_id=kwargs.get("inbound_id"),
            expires_at=iso(utcnow() + timedelta(days=kwargs["days"])),
        )


if __name__ == "__main__":
    unittest.main()
