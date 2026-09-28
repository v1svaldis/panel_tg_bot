from bot.panels.base import PanelError
from bot.panels.rixxx import RixxxPanel
from bot.panels.xui import XuiPanel


def open_panel(node: dict, client=None):
    kind = node.get("kind")
    if kind == "rixxx":
        return RixxxPanel(node["base_url"], node["token"], client)
    if kind == "xui":
        return XuiPanel(node["base_url"], node["token"], node.get("sub_base_url") or "", client)
    raise PanelError("Неизвестный тип панели")


async def check_node(node: dict) -> str:
    panel = open_panel(node)
    if node["kind"] == "rixxx":
        info = await panel.info()
        return f"Связь есть. Домен: {info.get('domain') or '—'}"
    items = await panel.list_inbounds()
    return f"Связь есть. Inbound: {len(items)}"
