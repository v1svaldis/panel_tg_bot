import httpx

from bot.panels.base import PanelError


class HttpPanel:
    def __init__(self, base_url: str, token: str, client: httpx.AsyncClient | None = None):
        self.base = base_url.rstrip("/")
        self.token = token
        self._client = client

    async def _request(self, method: str, path: str, json_body=None) -> httpx.Response:
        url = self.base + "/" + path.lstrip("/")
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            if self._client is not None:
                return await self._client.request(method, url, headers=headers, json=json_body)
            async with httpx.AsyncClient(timeout=30) as client:
                return await client.request(method, url, headers=headers, json=json_body)
        except httpx.HTTPError as exc:
            raise PanelError(f"Нет связи с панелью: {exc}") from exc

    async def _json(self, method: str, path: str, json_body=None):
        response = await self._request(method, path, json_body)
        try:
            data = response.json()
        except Exception:
            data = None
        if response.status_code >= 400:
            msg = ""
            if isinstance(data, dict):
                msg = str(data.get("error") or data.get("msg") or "")
            raise PanelError(msg or f"HTTP {response.status_code}: {response.text[:300]}")
        if isinstance(data, dict) and data.get("success") is False:
            raise PanelError(str(data.get("msg") or "ошибка панели"))
        if data is None:
            raise PanelError("Панель вернула не JSON")
        return data
