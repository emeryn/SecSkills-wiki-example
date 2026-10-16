"""CSRF defense for API writes: custom header, Origin/Sec-Fetch-Site, session-bound token."""

import hmac
from collections.abc import Callable

from app.core.errors import error_body
from app.core.middleware import ASGIApp, Receive, Scope, Send, header, send_json
from app.core.security import csrf_token, token_hash

SESSION_COOKIE = "__Host-session"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Signing in or requesting a reset must work with a stale cookie; header and origin still apply.
TOKEN_EXEMPT_PATHS = frozenset(
    {"/api/v1/auth/login", "/api/v1/auth/password-reset", "/api/v1/auth/password-reset/confirm"}
)


def session_cookie(scope: Scope) -> str | None:
    raw = header(scope, b"cookie")
    if not raw:
        return None
    for part in raw.split(";"):
        name, _, value = part.strip().partition("=")
        if name == SESSION_COOKIE and value:
            return value
    return None


class CsrfMiddleware:
    def __init__(self, app: ASGIApp, csrf_key: bytes, public_origin: str) -> None:
        self.app = app
        self.csrf_key = csrf_key
        self.public_origin = public_origin

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] in SAFE_METHODS
            or not scope["path"].startswith("/api/")
        ):
            await self.app(scope, receive, send)
            return
        reason = self._violation(scope)
        if reason is not None:
            await send_json(
                send, 403, error_body("CSRF_FAILED", "Request blocked", {"reason": reason})
            )
            return
        await self.app(scope, receive, send)

    def _violation(self, scope: Scope) -> str | None:
        checks: list[tuple[str, Callable[[], bool]]] = [
            ("header", lambda: header(scope, b"x-requested-with") == "XMLHttpRequest"),
            ("origin", lambda: header(scope, b"origin") in (None, self.public_origin)),
            (
                "fetch-site",
                lambda: header(scope, b"sec-fetch-site") in (None, "same-origin", "none"),
            ),
        ]
        for name, check in checks:
            if not check():
                return name
        cookie = session_cookie(scope)
        if cookie and scope["path"] not in TOKEN_EXEMPT_PATHS:
            expected = csrf_token(self.csrf_key, token_hash(cookie))
            if not hmac.compare_digest(header(scope, b"x-csrf-token") or "", expected):
                return "token"
        return None
