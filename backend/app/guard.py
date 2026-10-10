"""A thin layer in front of every request: a body size cap, no cross-site writes, no content sniffing."""
from __future__ import annotations

from urllib.parse import urlsplit

MAX_BODY = 1024 * 1024  # bytes; a full sensor batch is about a tenth of this
LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def same_site(headers: dict[bytes, bytes]) -> bool:
    """False when a browser page from another site is making the request. Browsers always send Origin
    on cross-site POSTs and on WebSocket handshakes; tools like the sensor send none."""
    origin = headers.get(b"origin")
    if origin is None:
        return True
    parts = urlsplit(origin.decode("latin-1"))
    host = headers.get(b"host", b"").decode("latin-1").lower()
    return parts.netloc.lower() == host or parts.hostname in LOOPBACK  # a dev server on this machine is fine


class Guard:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        writes = scope["type"] == "websocket" or scope["method"] not in ("GET", "HEAD", "OPTIONS")
        if writes and not same_site(headers):
            # Another website must not be able to wipe, block, or listen in through someone's browser.
            if scope["type"] == "websocket":
                return await send({"type": "websocket.close", "code": 1008})
            return await self.refuse(send, 403, b'{"detail":"cross-site request refused"}')
        if scope["type"] == "websocket":
            return await self.app(scope, receive, send)
        declared = headers.get(b"content-length", b"0")
        if not declared.isdigit() or int(declared) > MAX_BODY:
            return await self.refuse(send, 413, b'{"detail":"request body too large"}')

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            return message if received <= MAX_BODY else {"type": "http.disconnect"}  # a body longer than it claimed

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []), (b"x-content-type-options", b"nosniff")]}
            await send(message)

        await self.app(scope, limited_receive, send_with_headers)

    @staticmethod
    async def refuse(send, status: int, body: bytes) -> None:
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
