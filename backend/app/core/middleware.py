"""ASGI middleware: request correlation, client IP, body size limit and cache policy."""

import ipaddress
import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable, MutableMapping, Sequence
from typing import Any

import anyio.to_thread

from app.core.errors import error_body
from app.core.logging import request_id_var

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

logger = logging.getLogger("app.access")

_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{16,64}$")


def _ip_or_none(value: str | None) -> str | None:
    try:
        return str(ipaddress.ip_address(value)) if value else None
    except ValueError:
        return None


def client_ip(peer: str | None, forwarded_for: str | None, trusted_proxy_count: int) -> str | None:
    """Return the client IP, trusting exactly ``trusted_proxy_count`` hops of X-Forwarded-For."""
    if trusted_proxy_count == 0 or not forwarded_for:
        return _ip_or_none(peer)
    hops = [hop.strip() for hop in forwarded_for.split(",")]
    if len(hops) < trusted_proxy_count:
        return _ip_or_none(peer)
    return _ip_or_none(hops[-trusted_proxy_count]) or _ip_or_none(peer)


def client_ip_trusted(forwarded_for: str | None, trusted_proxy_count: int) -> bool:
    """Whether the client IP is attributable: taken from a trusted hop, or a direct connection.

    A forwarded header with no trusted proxy configured means an unknown proxy sits in front:
    the peer address would be that proxy, which must never be blocked by a honeytoken.
    """
    if trusted_proxy_count == 0:
        return not forwarded_for
    hops = [hop for hop in (forwarded_for or "").split(",") if hop.strip()]
    return len(hops) >= trusted_proxy_count


ServerErrorHook = Callable[[str, str, int, str], None]


def header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return bytes(value).decode("latin-1")
    return None


async def send_json(send: Send, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class _BodyTooLargeError(Exception):
    pass


class RequestContextMiddleware:
    """Assigns a request id, resolves the client IP, logs one access line per request."""

    def __init__(
        self,
        app: ASGIApp,
        trusted_proxy_count: int,
        on_server_error: ServerErrorHook | None = None,
    ) -> None:
        self.app = app
        self.trusted_proxy_count = trusted_proxy_count
        self.on_server_error = on_server_error

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = header(scope, b"x-request-id")
        request_id = incoming if incoming and _REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        peer = scope["client"][0] if scope.get("client") else None
        forwarded_for = header(scope, b"x-forwarded-for")
        state = scope.setdefault("state", {})
        state["client_ip"] = client_ip(peer, forwarded_for, self.trusted_proxy_count)
        state["client_ip_trusted"] = client_ip_trusted(forwarded_for, self.trusted_proxy_count)
        status = 500
        response_started = False
        started = time.perf_counter()

        async def send_with_headers(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status = message["status"]
                response_started = True
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                if scope["path"].startswith(("/api/", "/mcp")):
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:
            logger.exception("Unhandled exception")
            if response_started:
                raise
            await send_json(send_with_headers, 500, error_body("INTERNAL_ERROR", "Internal error"))
        finally:
            logger.info(
                "request",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "client_ip": scope["state"]["client_ip"],
                },
            )
            if status >= 500 and self.on_server_error is not None:  # noqa: PLR2004
                await self._report(scope["method"], scope["path"], status, request_id)
            request_id_var.reset(token)

    async def _report(self, method: str, path: str, status: int, request_id: str) -> None:
        hook = self.on_server_error
        if hook is None:
            return
        try:
            await anyio.to_thread.run_sync(hook, method, path, status, request_id)
        except Exception:
            logger.warning("Server error could not be recorded")


class BodySizeLimitMiddleware:
    """Rejects bodies above the limit, by Content-Length and while streaming (chunked).

    ``overrides`` raises the limit for specific paths (file uploads).
    """

    def __init__(
        self, app: ASGIApp, max_bytes: int, overrides: Sequence[tuple[re.Pattern[str], int]] = ()
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.overrides = overrides

    def _limit(self, path: str) -> int:
        return next(
            (limit for pattern, limit in self.overrides if pattern.match(path)), self.max_bytes
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self._limit(scope["path"])
        declared = header(scope, b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > limit):
            await self._reject(send)
            return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLargeError
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLargeError:
            if not response_started:
                await self._reject(send)

    @staticmethod
    async def _reject(send: Send) -> None:
        await send_json(send, 413, error_body("PAYLOAD_TOO_LARGE", "Request body too large"))
