"""ASGI guards that run before any route: an Origin check on mutations and request body limits."""

import json

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


async def _reject(send: Send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class OriginCheck:
    """Refuses every mutation whose Origin header is missing or not allow-listed (CSRF defence)."""

    def __init__(self, app: ASGIApp, allowed_origins: frozenset[str]):
        self.app = app
        self.allowed = allowed_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in UNSAFE_METHODS:
            origin = Headers(scope=scope).get("origin")
            if origin is None or origin.rstrip("/") not in self.allowed:
                await _reject(send, 403, "Request origin is not allowed.")
                return
        await self.app(scope, receive, send)


class _TooLarge(Exception):
    pass


class BodyLimit:
    """Rejects oversized bodies with 413 before they are parsed, by header and while streaming."""

    def __init__(self, app: ASGIApp, default_limit: int, limits: dict[str, int]):
        self.app = app
        self.default_limit = default_limit
        self.limits = limits

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in UNSAFE_METHODS:
            await self.app(scope, receive, send)
            return
        limit = self.limits.get(scope["path"], self.default_limit)
        declared = Headers(scope=scope).get("content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > limit):
            await _reject(send, 413, f"Request body is larger than {limit} bytes.")
            return

        received = 0
        exceeded = False
        started = False

        async def limited_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    raise _TooLarge
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if exceeded:
                return  # the app's error response is replaced by a 413 below
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _TooLarge:
            pass
        if exceeded and not started:
            await _reject(send, 413, f"Request body is larger than {limit} bytes.")
