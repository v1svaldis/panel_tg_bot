_NAIVE = (
    "Клиенты для NaiveProxy. Ссылка вида naive+https://логин:пароль@домен:443\n"
    "• iOS: Shadowrocket — https://apps.apple.com/app/shadowrocket/id932747118\n"
    "• Android: NekoBox — https://github.com/MatsuriDayo/NekoBoxForAndroid/releases\n"
    "• Windows / macOS / Linux / iOS / Android: Karing — https://github.com/KaringX/karing/releases\n"
    "• CLI: naiveproxy — https://github.com/klzgrad/naiveproxy/releases\n"
    "Удобнее импортировать подписку: клиент сам выберет формат."
)

_MIERU = (
    "Клиенты для Mieru. Импортируйте подписку или JSON-конфиг.\n"
    "• Karing (iOS / Android / Windows / macOS / Linux) — https://github.com/KaringX/karing/releases\n"
    "• sing-box — https://github.com/SagerNet/sing-box/releases\n"
    "• sing-box для iOS — https://apps.apple.com/app/sing-box/id6451272673"
)

_HY2 = (
    "Клиенты для Hysteria2. Ссылка вида hysteria2://логин:пароль@домен:443\n"
    "• iOS: Shadowrocket — https://apps.apple.com/app/shadowrocket/id932747118\n"
    "• Karing — https://github.com/KaringX/karing/releases\n"
    "• CLI: Hysteria — https://github.com/apernet/hysteria/releases"
)

_XUI = (
    "Импортируйте ссылку подписки в клиент.\n"
    "• Android: v2rayNG — https://github.com/2dust/v2rayNG/releases\n"
    "  или Hiddify — https://github.com/hiddify/hiddify-app/releases\n"
    "• Windows: v2rayN — https://github.com/2dust/v2rayN/releases\n"
    "• iOS: Streisand или Shadowrocket — https://apps.apple.com/app/shadowrocket/id932747118\n"
    "• Karing (все платформы) — https://github.com/KaringX/karing/releases"
)

TEXTS = {
    "naive": _NAIVE,
    "mieru": _MIERU,
    "hy2": _HY2,
    "vless": _XUI,
    "vmess": _XUI,
    "trojan": _XUI,
    "shadowsocks": _XUI,
    "hysteria": _HY2,
    "generic": _XUI,
}

HELP_PROTOCOLS = (
    ("naive", "NaiveProxy"),
    ("mieru", "Mieru"),
    ("hy2", "Hysteria2"),
    ("vless", "VLESS / VMess / Trojan / SS"),
)


def instruction_for(protocol: str) -> str:
    key = (protocol or "").lower()
    if key in ("ss", "shadowsocks"):
        key = "shadowsocks"
    return TEXTS.get(key, TEXTS["generic"])
