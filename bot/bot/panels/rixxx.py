import secrets
import string
from datetime import timedelta
from urllib.parse import quote

from bot.panels.base import IssuedKey
from bot.panels.http import HttpPanel
from bot.timeutil import iso, utcnow

_ALPHABET = string.ascii_letters + string.digits


def make_username(tg_id: int) -> str:
    return f"tg{tg_id}_{secrets.token_hex(3)}"


def make_password(length: int = 16) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


class RixxxPanel(HttpPanel):
    async def info(self) -> dict:
        return await self._json("GET", "/api/config")

    async def protocols(self) -> list[str]:
        stack = (await self.info()).get("stack") or {}
        return [name for name in ("naive", "mieru", "hy2") if stack.get(name)]

    async def links(self, *, panel_user_id: str, protocol: str, sub_id: str | None = None):
        sub = await self._json("GET", f"/api/users/{quote(panel_user_id, safe='')}/sub-link")
        direct = None
        if protocol in ("naive", "hy2"):
            cfg = await self._json("GET", f"/api/users/{quote(panel_user_id, safe='')}/config/{protocol}")
            direct = cfg.get("link")
        return sub["link"], direct

    async def create(self, *, tg_id: int, protocol: str, days: int, quota_gb: int, inbound_id: int | None = None, username: str | None = None, limit_ip: int = 0) -> IssuedKey:
        username = username or make_username(tg_id)
        password = make_password()
        expires = utcnow() + timedelta(days=days)
        created = await self._json("POST", "/api/users", {
            "username": username,
            "password": password,
            "expiry": iso(expires),
            "protocols": [protocol],
            "quotaGb": quota_gb or 0,
        })
        user_id = created["id"]
        link, direct = await self.links(panel_user_id=user_id, protocol=protocol)
        return IssuedKey(
            panel_user_id=user_id,
            username=created.get("username") or username,
            link=link,
            sub_id=None,
            direct_link=direct,
            expires_at=iso(expires),
        )

    async def delete(self, *, panel_user_id: str, inbound_id: int | None = None) -> None:
        await self._json("DELETE", f"/api/users/{quote(panel_user_id, safe='')}")

    async def extend(self, *, panel_user_id: str, expires_at, inbound_id: int | None = None, email: str | None = None) -> None:
        await self._json("PUT", f"/api/users/{quote(panel_user_id, safe='')}", {"expiry": iso(expires_at)})
