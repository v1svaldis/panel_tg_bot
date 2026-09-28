import io

import qrcode


def qr_png(text: str) -> bytes:
    image = qrcode.make(text)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()
