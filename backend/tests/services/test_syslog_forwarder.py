"""Syslog: RFC 5424 format, RFC 5425 framing, bounded buffer, record selection."""

import logging

import pytest

from app.core.runtime_settings import Snapshot
from app.schemas.settings import LogLevelName, SyslogSettings
from app.services import syslog_forwarder
from app.services.syslog_forwarder import SyslogForwarder, format_message, frame


def test_rfc5424_header_and_octet_counting() -> None:
    message = format_message(
        '{"message":"x"}',
        levelno=logging.CRITICAL,
        audit=True,
        hostname="wiki.example.com",
        app_name="wiki",
        procid="backend",
        created=0,
    )
    # Facility 13 (log audit) * 8 + severity 2 (critical) = 106.
    assert message.startswith(
        b"<106>1 1970-01-01T00:00:00.000Z wiki.example.com wiki backend audit - "
    )
    assert b"\xef\xbb\xbf{" in message
    length, _, rest = frame(message).partition(b" ")
    assert int(length) == len(rest) == len(message)


def test_header_fields_cannot_be_forged() -> None:
    message = format_message(
        "{}",
        levelno=logging.INFO,
        audit=False,
        hostname="a b\nc",
        app_name="w",
        procid="1",
        created=0,
    )
    assert message.split(b" ")[2] == b"abc"


def _forwarder(min_level: LogLevelName = "WARNING", forward_audit: bool = True) -> SyslogForwarder:
    forwarder = SyslogForwarder("wiki.example.com", "test", start_sender=False)
    forwarder.configure(
        Snapshot(
            syslog=SyslogSettings(
                enabled=True, host="198.51.100.1", min_level=min_level, forward_audit=forward_audit
            )
        )
    )
    return forwarder


def _record(name: str, level: int) -> logging.LogRecord:
    return logging.LogRecord(name, level, __file__, 1, "message", None, None)


def test_buffer_is_bounded_and_counts_drops(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(syslog_forwarder, "BUFFER_SIZE", 3)
    forwarder = _forwarder()
    for _ in range(5):
        forwarder.enqueue(b"x")
    assert len(forwarder._buffer) == 3
    assert forwarder.dropped == 2


def test_selects_audit_events_and_level() -> None:
    forwarder = _forwarder(min_level="ERROR")
    forwarder.emit(_record("app.audit", logging.INFO))
    forwarder.emit(_record("app.pages", logging.WARNING))
    forwarder.emit(_record("app.pages", logging.ERROR))
    forwarder.emit(_record("app.syslog", logging.ERROR))
    assert len(forwarder._buffer) == 2


def test_disabling_clears_and_stops_buffering() -> None:
    forwarder = _forwarder()
    forwarder.enqueue(b"x")
    forwarder.configure(Snapshot())
    assert len(forwarder._buffer) == 0
    forwarder.emit(_record("app.audit", logging.INFO))
    assert len(forwarder._buffer) == 0
