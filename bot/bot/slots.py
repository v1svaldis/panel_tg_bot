import re

MAX_DEVICES = 5
MULTI_DEVICE = {"vless", "vmess", "trojan"}

PROTOCOL_LABELS = {
    "naive": "NaiveProxy",
    "mieru": "Mieru",
    "hy2": "Hysteria2",
    "hysteria": "Hysteria",
    "vless": "VLESS",
    "vmess": "VMess",
    "trojan": "Trojan",
    "shadowsocks": "Shadowsocks",
    "ss": "Shadowsocks",
}

_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def is_multi(protocol: str) -> bool:
    return (protocol or "").lower() in MULTI_DEVICE


def key_count(protocol: str, devices: int) -> int:
    return 1 if is_multi(protocol) else devices


def limit_ip(protocol: str, devices: int) -> int:
    return devices if is_multi(protocol) else 1


def can_allocate(used: int, devices: int) -> bool:
    return 1 <= devices <= MAX_DEVICES and used + devices <= MAX_DEVICES


def label_for(protocol: str) -> str:
    return PROTOCOL_LABELS.get((protocol or "").lower(), protocol or "—")


def flatten_entries(nodes: list[dict], choices_of) -> list[dict]:
    entries = []
    for node in nodes:
        for choice in choices_of(node):
            entries.append({
                "node_id": node["id"],
                "node_name": node["name"],
                "protocol": choice["protocol"],
                "inbound_id": choice.get("inbound_id"),
                "remark": choice.get("remark") or "",
            })
    return entries


def unique_protocols(entries: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for entry in entries:
        protocol = entry["protocol"]
        if protocol in seen:
            continue
        seen.add(protocol)
        out.append({"protocol": protocol, "label": label_for(protocol)})
    return out


def locations_for_protocol(entries: list[dict], protocol: str) -> list[dict]:
    return [entry for entry in entries if entry["protocol"] == protocol]


def panel_base_name(username: str | None, tg_id: int) -> str:
    cleaned = _UNSAFE.sub("", (username or "").strip().lstrip("@"))
    if not cleaned:
        cleaned = f"tg{tg_id}"
    return cleaned[:40]


def panel_username(base: str, seq: int) -> str:
    if seq <= 1:
        return base[:64]
    suffix = f"_{seq}"
    return (base[:64 - len(suffix)] + suffix)[:64]
