"""Notification throttling and content (no stack traces)."""

import logging
import sys

from app.core.context import AppContext
from app.core.runtime_settings import Snapshot
from app.schemas.settings import NotificationSettings, WebhookSettings
from app.services.notifier import Event, Notifier, Throttle, _text

WEBHOOK_ON = WebhookSettings(enabled=True, url="https://hooks.example.com/x", secret="s" * 32)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_identical_events_are_throttled_and_counted() -> None:
    clock = Clock()
    throttle = Throttle(repeat_seconds=900, hourly_limit=20, clock=clock)
    assert throttle.allow("email", "error:boom") == (True, 0)
    assert throttle.allow("email", "error:boom") == (False, 0)
    assert throttle.allow("email", "error:boom") == (False, 0)
    # Channels are throttled independently.
    assert throttle.allow("webhook", "error:boom") == (True, 0)
    clock.now = 901
    assert throttle.allow("email", "error:boom") == (True, 2)


def test_hourly_cap_per_channel() -> None:
    clock = Clock()
    throttle = Throttle(repeat_seconds=0, hourly_limit=3, clock=clock)
    results = [throttle.allow("email", f"error:{i}")[0] for i in range(5)]
    assert results == [True, True, True, False, False]
    clock.now = 3600
    assert throttle.allow("email", "error:new") == (True, 2)


def test_message_mentions_suppressed_events() -> None:
    event = Event("error", "Unhandled exception", "2026-10-15T10:00:00Z", {"request_id": "abc"})
    text = _text(event, suppressed=4)
    assert "4 similar notifications were suppressed" in text
    assert "request_id: abc" in text


def _error_record() -> logging.LogRecord:
    record = logging.LogRecord(
        "app.access", logging.ERROR, __file__, 1, "Unhandled exception", None, None
    )
    try:
        raise ValueError("secret detail from a stack trace")
    except ValueError:
        record.exc_info = sys.exc_info()
    return record


def test_event_never_carries_the_stack_trace(ctx: AppContext) -> None:
    event = Notifier(ctx.runtime, ctx.mailer).event_from(
        _error_record(), Snapshot(webhook=WEBHOOK_ON)
    )
    assert event is not None
    assert event.kind == "error"
    assert event.summary == "Unhandled exception"
    assert "secret detail" not in repr(event)


def test_nothing_is_queued_without_a_channel_or_when_disabled(ctx: AppContext) -> None:
    notifier = Notifier(ctx.runtime, ctx.mailer)
    assert notifier.event_from(_error_record(), Snapshot()) is None
    muted = Snapshot(webhook=WEBHOOK_ON, notifications=NotificationSettings(notify_errors=False))
    assert notifier.event_from(_error_record(), muted) is None
