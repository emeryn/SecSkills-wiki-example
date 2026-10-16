"""Error and security notifications by email and webhook, throttled per channel.

A logging handler (level ERROR) turns errors and critical audit events into notifications that one
sender thread delivers. An identical event is sent at most once every ``REPEAT_SECONDS`` per
channel and a channel sends at most ``HOURLY_LIMIT`` messages an hour; suppressed events are
counted in the next message. Stack traces stay in the logs and are never sent.
"""

import json
import logging
import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from app.core.logging import JsonFormatter
from app.core.mailer import Mailer
from app.core.outbound_url import Resolver, parse_networks, resolve_url
from app.core.runtime_settings import RuntimeSettings, Snapshot
from app.services import webhook

logger = logging.getLogger("app.notifier")

REPEAT_SECONDS = 900.0
HOURLY_LIMIT = 20
QUEUE_SIZE = 200

Kind = Literal["error", "security", "test"]
Channel = Literal["email", "webhook"]


@dataclass(frozen=True)
class Event:
    kind: Kind
    summary: str
    occurred_at: str
    details: dict[str, Any]

    @property
    def fingerprint(self) -> str:
        return f"{self.kind}:{self.summary}"


class Throttle:
    """Per channel: one message per fingerprint per window, and an hourly cap."""

    def __init__(
        self,
        repeat_seconds: float = REPEAT_SECONDS,
        hourly_limit: int = HOURLY_LIMIT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._repeat = repeat_seconds
        self._limit = hourly_limit
        self._clock = clock
        self._last_sent: dict[tuple[str, str], float] = {}
        self._sent: dict[str, deque[float]] = {}
        self._suppressed: dict[str, int] = {}
        self._lock = threading.Lock()

    def allow(self, channel: str, fingerprint: str) -> tuple[bool, int]:
        """Return ``(allowed, suppressed_since_last_message)`` and record the decision."""
        now = self._clock()
        with self._lock:
            sent = self._sent.setdefault(channel, deque())
            while sent and now - sent[0] >= 3600:  # noqa: PLR2004
                sent.popleft()
            last = self._last_sent.get((channel, fingerprint))
            if (last is not None and now - last < self._repeat) or len(sent) >= self._limit:
                self._suppressed[channel] = self._suppressed.get(channel, 0) + 1
                return False, 0
            self._last_sent[(channel, fingerprint)] = now
            sent.append(now)
            return True, self._suppressed.pop(channel, 0)


def _subject(event: Event) -> str:
    prefix = {"error": "Error", "security": "Security alert", "test": "Test"}[event.kind]
    return f"[wiki] {prefix}: {event.summary}"[:200]


def _text(event: Event, suppressed: int) -> str:
    lines = [_subject(event), "", f"Time (UTC): {event.occurred_at}"]
    lines += [f"{key}: {value}" for key, value in sorted(event.details.items())]
    if suppressed:
        lines += ["", f"{suppressed} similar notifications were suppressed (throttling)."]
    lines += ["", "Details are in the application logs and the audit trail."]
    return "\n".join(lines)


class Notifier(logging.Handler):
    """Logging handler and delivery thread; ``deliver`` is synchronous (tests, "Send test")."""

    def __init__(
        self,
        runtime: RuntimeSettings,
        mailer: Mailer,
        *,
        resolver: Resolver | None = None,
        throttle: Throttle | None = None,
    ) -> None:
        super().__init__(level=logging.ERROR)
        self.setFormatter(JsonFormatter())
        self._runtime = runtime
        self._mailer = mailer
        self._resolver = resolver
        self.throttle = throttle or Throttle()
        self._queue: queue.Queue[Event] = queue.Queue(maxsize=QUEUE_SIZE)
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()

    def channels(self, snapshot: Snapshot) -> list[Channel]:
        found: list[Channel] = []
        if snapshot.notifications.email_recipients and self._mailer.enabled:
            found.append("email")
        if snapshot.webhook.enabled:
            found.append("webhook")
        return found

    def event_from(self, record: logging.LogRecord, snapshot: Snapshot) -> Event | None:
        """The notification for ``record``, or None when nothing should be sent."""
        security = record.name == "app.audit"
        if security and not snapshot.notifications.notify_security:
            return None
        if not security and not snapshot.notifications.notify_errors:
            return None
        if not (snapshot.notifications.email_recipients or snapshot.webhook.enabled):
            return None
        entry = json.loads(self.format(record))
        entry.pop("exception", None)
        occurred_at = entry.pop("ts", datetime.now(UTC).isoformat())
        summary = str(entry.get("audit_action") if security else entry.get("message"))
        details = {k: v for k, v in entry.items() if k not in {"level", "message"}}
        return Event("security" if security else "error", summary, occurred_at, details)

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith("app.notifier"):
            return
        try:
            event = self.event_from(record, self._runtime.current())
        except Exception:
            self.handleError(record)
            return
        if event is None:
            return
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            return
        self._ensure_thread()

    def _ensure_thread(self) -> None:
        with self._thread_lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="notifier", daemon=True)
                self._thread.start()

    def _run(self) -> None:
        while True:
            event = self._queue.get()
            self.deliver(event)

    def deliver(self, event: Event) -> dict[Channel, bool]:
        """Send to every configured channel the throttle allows; returns what was sent."""
        snapshot = self._runtime.snapshot()
        results: dict[Channel, bool] = {}
        for channel in self.channels(snapshot):
            allowed, suppressed = self.throttle.allow(channel, event.fingerprint)
            if not allowed:
                continue
            try:
                self.send(channel, snapshot, event, suppressed)
                results[channel] = True
            except Exception as exc:
                results[channel] = False
                logger.warning(
                    "Notification could not be sent",
                    extra={"channel": channel, "error": type(exc).__name__},
                )
        return results

    def send(
        self,
        channel: Channel,
        snapshot: Snapshot,
        event: Event,
        suppressed: int = 0,
        recipients: list[str] | None = None,
    ) -> None:
        """Deliver through one channel now (no throttling); raises on failure."""
        if channel == "email":
            for recipient in recipients or snapshot.notifications.email_recipients:
                self._mailer.send(recipient, _subject(event), _text(event, suppressed))
            return
        config = snapshot.webhook
        if config.url is None or config.secret is None:
            raise webhook.WebhookError("The webhook is not configured")
        destination = resolve_url(
            config.url, parse_networks(snapshot.security.allowed_private_networks), self._resolver
        )
        payload = {
            "event": f"wiki.{event.kind}",
            "occurred_at": event.occurred_at,
            "summary": event.summary,
            "details": event.details,
            "suppressed": suppressed,
        }
        webhook.send(destination, config.secret, payload, config.ca_pem)


def check_event(actor: str) -> Event:
    """Event sent by the "Send test" action."""
    return Event(
        "test",
        "Notification test",
        datetime.now(UTC).isoformat(),
        {"requested_by": actor},
    )
