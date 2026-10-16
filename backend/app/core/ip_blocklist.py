"""Client IPs blocked by honeytokens, cached per process and enforced on every API request."""

import ipaddress
import logging
import threading
import time
from datetime import UTC, datetime

import anyio.to_thread
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import error_body
from app.core.middleware import ASGIApp, Receive, Scope, Send, send_json
from app.models import BlockedIp

logger = logging.getLogger(__name__)

REFRESH_SECONDS = 10.0


class IpBlocklist:
    """Reloaded from ``blocked_ips`` at most every ``REFRESH_SECONDS``; local changes apply now."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions
        self._lock = threading.Lock()
        self._blocked: dict[str, datetime | None] = {}
        self._loaded_at = float("-inf")

    def refresh_if_stale(self) -> None:
        if time.monotonic() - self._loaded_at < REFRESH_SECONDS:
            return
        now = datetime.now(UTC)
        try:
            with self._sessions() as db:
                rows = db.execute(
                    select(BlockedIp.ip, BlockedIp.expires_at).where(
                        or_(BlockedIp.expires_at.is_(None), BlockedIp.expires_at > now)
                    )
                ).all()
        except Exception:
            # Keep enforcing the last known list rather than failing every request.
            logger.warning("Blocked IP list could not be reloaded")
            return
        with self._lock:
            self._blocked = {str(ip): expires for ip, expires in rows}
            self._loaded_at = time.monotonic()

    def is_blocked(self, ip: str | None) -> bool:
        if ip is None:
            return False
        try:
            key = str(ipaddress.ip_address(ip))
        except ValueError:
            return False
        with self._lock:
            if key not in self._blocked:
                return False
            expires = self._blocked[key]
        return expires is None or expires > datetime.now(UTC)

    def add(self, ip: str, expires_at: datetime | None) -> None:
        with self._lock:
            self._blocked[ip] = expires_at

    def remove(self, ip: str) -> None:
        with self._lock:
            self._blocked.pop(ip, None)


class BlockedIpMiddleware:
    """Answers 403 to API requests from a blocked client IP (resolved by the context middleware)."""

    def __init__(self, app: ASGIApp, blocklist: IpBlocklist) -> None:
        self.app = app
        self.blocklist = blocklist

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(("/api/", "/mcp")):
            await self.app(scope, receive, send)
            return
        await anyio.to_thread.run_sync(self.blocklist.refresh_if_stale)
        if self.blocklist.is_blocked(scope.get("state", {}).get("client_ip")):
            await send_json(
                send,
                403,
                error_body(
                    "ACCESS_BLOCKED",
                    "Access from your network is blocked. Contact an administrator.",
                ),
            )
            return
        await self.app(scope, receive, send)
