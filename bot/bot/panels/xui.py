import json
import secrets
import string
import uuid
from datetime import timedelta
from urllib.parse import quote

from bot.panels.base import IssuedKey, PanelError
from bot.panels.http import HttpPanel
from bot.timeutil import iso, utcnow

_ALPHABET = string.ascii_letters + string.digits


def _clients(inbound: dict) -> list:
    settings = inbound.get("settings")
    if isinstance(settings, str):
        settings = json.loads(settings or "{}")
    if not isinstance(settings, dict):
        return []
    clients = settings.get("clients") or []
    return list(clients)


def _find_client(clients, panel_user_id: str, email: str | None):
    for client in clients:
        if not isinstance(client, dict):
            continue
        if client.get("id") == panel_user_id or client.get("password") == panel_user_id:
            return client
        if email and client.get("email") == email:
            return client
    return None


class XuiPanel(HttpPanel):
    def __init__(self, base_url: str, token: str, sub_base_url: str = "", client=None):
        super().__init__(base_url, token, client)
        self.sub_base = (sub_base_url or "").rstrip("/")

    async def list_inbounds(self) -> list[dict]:
        data = await self._json("GET", "/panel/api/inbounds/list")
        items = []
        for inbound in data.get("obj") or []:
            if inbound.get("enable") is False:
                continue
            items.append({
                "inbound_id": inbound.get("id"),
                "protocol": inbound.get("protocol") or "",
                "remark": inbound.get("remark") or "",
                "port": inbound.get("port"),
            })
        return items

    async def links(self, *, panel_user_id: str, protocol: str, sub_id: str | None = None):
        if not sub_id:
            raise PanelError("Нет subId для ссылки подписки")
        if not self.sub_base:
            raise PanelError("У ноды не задан URL подписки")
        return f"{self.sub_base}/sub/{sub_id}", None

    async def create(self, *, tg_id: int, protocol: str, days: int, quota_gb: int, inbound_id: int | None = None, username: str | None = None, limit_ip: int = 0) -> IssuedKey:
        if not inbound_id:
            raise PanelError("Не выбран inbound")
        email = username or f"tg{tg_id}_{secrets.token_hex(3)}"
        client_id = str(uuid.uuid4())
        password = "".join(secrets.choice(_ALPHABET) for _ in range(16))
        sub_id = secrets.token_hex(8)
        expires = utcnow() + timedelta(days=days)
        client = {
            "id": client_id,
            "flow": "xtls-rprx-vision" if protocol == "vless" else "",
            "email": email,
            "limitIp": limit_ip,
            "totalGB": (quota_gb or 0) * 1024 ** 3,
            "expiryTime": int(expires.timestamp() * 1000),
            "enable": True,
            "tgId": str(tg_id),
            "subId": sub_id,
            "comment": "",
            "reset": 0,
            "password": password,
        }
        await self._json("POST", "/panel/api/inbounds/addClient", {
            "id": inbound_id,
            "settings": json.dumps({"clients": [client]}),
        })
        link, direct = await self.links(panel_user_id=client_id, protocol=protocol, sub_id=sub_id)
        return IssuedKey(
            panel_user_id=client_id,
            username=email,
            link=link,
            sub_id=sub_id,
            inbound_id=inbound_id,
            direct_link=direct,
            expires_at=iso(expires),
        )

    async def delete(self, *, panel_user_id: str, inbound_id: int | None = None) -> None:
        if not inbound_id:
            raise PanelError("Не указан inbound")
        client_id = quote(str(panel_user_id), safe="")
        await self._json("POST", f"/panel/api/inbounds/{inbound_id}/delClient/{client_id}")

    async def extend(self, *, panel_user_id: str, expires_at, inbound_id: int | None = None, email: str | None = None) -> None:
        if not inbound_id:
            raise PanelError("Не указан inbound")
        data = await self._json("GET", f"/panel/api/inbounds/get/{inbound_id}")
        inbound = data.get("obj") or {}
        client = _find_client(_clients(inbound), panel_user_id, email)
        if not client:
            raise PanelError("Клиент на панели не найден")
        client["expiryTime"] = int(expires_at.timestamp() * 1000)
        client["enable"] = True
        target = quote(str(client.get("id") or panel_user_id), safe="")
        await self._json("POST", f"/panel/api/inbounds/updateClient/{target}", {
            "id": inbound_id,
            "settings": json.dumps({"clients": [client]}),
        })
