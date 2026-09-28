import json
import unittest
from datetime import timedelta

import httpx

from bot.panels.base import PanelError
from bot.panels.rixxx import RixxxPanel
from bot.panels.xui import XuiPanel
from bot.timeutil import parse_dt, utcnow


class RixxxTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_extend_delete(self):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.method, request.url.path, request.headers.get("authorization")))
            path = request.url.path
            if request.method == "POST" and path.endswith("/api/users"):
                body = json.loads(request.content)
                self.assertEqual(body["protocols"], ["naive"])
                self.assertTrue(body["username"].startswith("tg7_"))
                self.assertGreaterEqual(len(body["password"]), 8)
                self.assertIn("expiry", body)
                return httpx.Response(201, json={"ok": True, "id": "uid-1", "username": body["username"]})
            if request.method == "GET" and path.endswith("/sub-link"):
                return httpx.Response(200, json={"link": "https://sub.example/sub/tok", "token": "tok"})
            if request.method == "GET" and path.endswith("/config/naive"):
                return httpx.Response(200, json={"link": "naive+https://u:p@d:443"})
            if request.method == "PUT" and path.endswith("/api/users/uid-1"):
                body = json.loads(request.content)
                self.assertIn("expiry", body)
                return httpx.Response(200, json={"ok": True})
            if request.method == "DELETE" and path.endswith("/api/users/uid-1"):
                return httpx.Response(200, json={"ok": True})
            if request.method == "GET" and path.endswith("/api/config"):
                return httpx.Response(200, json={"domain": "ex.com", "stack": {"naive": True, "mieru": False, "hy2": True}})
            return httpx.Response(404, json={"error": "no"})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            panel = RixxxPanel("https://panel.example/secret", "sekret", client)
            issued = await panel.create(tg_id=7, protocol="naive", days=30, quota_gb=0)
            self.assertEqual(issued.link, "https://sub.example/sub/tok")
            self.assertEqual(issued.direct_link, "naive+https://u:p@d:443")
            self.assertEqual(issued.panel_user_id, "uid-1")
            link, direct = await panel.links(panel_user_id="uid-1", protocol="mieru")
            self.assertEqual(link, "https://sub.example/sub/tok")
            self.assertIsNone(direct)
            await panel.extend(panel_user_id="uid-1", expires_at=utcnow() + timedelta(days=10))
            await panel.delete(panel_user_id="uid-1")
            names = await panel.protocols()
        self.assertEqual(names, ["naive", "hy2"])
        self.assertTrue(all(item[2] == "Bearer sekret" for item in seen))
        paths = [item[1] for item in seen]
        self.assertNotIn("/api/users/uid-1/config/mieru", paths)

    async def test_bad_token_is_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "Unauthorized"})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            panel = RixxxPanel("https://panel.example", "nope", client)
            with self.assertRaises(PanelError):
                await panel.info()


class XuiTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_extend_delete(self):
        stored = {}

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.headers.get("authorization"), "Bearer xsecret")
            path = request.url.path
            if request.method == "GET" and path.endswith("/panel/api/inbounds/list"):
                return httpx.Response(200, json={"success": True, "obj": [
                    {"id": 3, "protocol": "vless", "remark": "NL", "enable": True, "port": 443},
                    {"id": 4, "protocol": "vmess", "remark": "off", "enable": False, "port": 8443},
                ]})
            if request.method == "POST" and path.endswith("/addClient"):
                body = json.loads(request.content)
                self.assertEqual(body["id"], 3)
                client = json.loads(body["settings"])["clients"][0]
                self.assertTrue(client["subId"])
                self.assertGreater(client["expiryTime"], 1_000_000_000_000)
                self.assertEqual(client["flow"], "xtls-rprx-vision")
                stored["client"] = client
                return httpx.Response(200, json={"success": True})
            if request.method == "GET" and path.endswith("/inbounds/get/3"):
                return httpx.Response(200, json={"success": True, "obj": {
                    "id": 3,
                    "settings": json.dumps({"clients": [stored["client"]]}),
                }})
            if request.method == "POST" and "/updateClient/" in path:
                body = json.loads(request.content)
                client = json.loads(body["settings"])["clients"][0]
                self.assertGreater(client["expiryTime"], stored["client"]["expiryTime"])
                return httpx.Response(200, json={"success": True})
            if request.method == "POST" and "/delClient/" in request.url.path:
                return httpx.Response(200, json={"success": True})
            return httpx.Response(404, json={"success": False, "msg": "missing"})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            panel = XuiPanel("https://host:2053/secret", "xsecret", "https://host:2096", client)
            inbounds = await panel.list_inbounds()
            self.assertEqual(len(inbounds), 1)
            self.assertEqual(inbounds[0]["protocol"], "vless")
            issued = await panel.create(tg_id=9, protocol="vless", days=7, quota_gb=0, inbound_id=3)
            self.assertEqual(issued.link, f"https://host:2096/sub/{issued.sub_id}")
            self.assertTrue(issued.sub_id)
            later = parse_dt(issued.expires_at) + timedelta(days=30)
            await panel.extend(panel_user_id=issued.panel_user_id, expires_at=later, inbound_id=3, email=issued.username)
            await panel.delete(panel_user_id=issued.panel_user_id, inbound_id=3)

    async def test_missing_sub_base(self):
        panel = XuiPanel("https://host", "tok", "")
        with self.assertRaises(PanelError):
            await panel.links(panel_user_id="x", protocol="vless", sub_id="abc")


if __name__ == "__main__":
    unittest.main()
