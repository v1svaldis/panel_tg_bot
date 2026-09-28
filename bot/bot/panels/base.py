from dataclasses import dataclass


class PanelError(Exception):
    pass


@dataclass
class IssuedKey:
    panel_user_id: str
    username: str
    link: str
    sub_id: str | None = None
    inbound_id: int | None = None
    direct_link: str | None = None
    expires_at: str = ""
