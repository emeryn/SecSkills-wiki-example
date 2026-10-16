"""Remote syslog: RFC 5424 messages over TLS with RFC 5425 octet-counting framing.

Records wait in a bounded in-memory buffer; when it is full the oldest are dropped and counted,
and the count is reported once the server is reachable again. One sender thread connects lazily
and reconnects with backoff: logging never blocks a request. No local syslog daemon is involved.
"""

import logging
import os
import socket
import ssl
import threading
from collections import deque
from datetime import UTC, datetime

from app.core.logging import JsonFormatter
from app.core.outbound_url import (
    Network,
    OutboundUrlError,
    Resolver,
    parse_networks,
    resolve,
    tls_context,
)
from app.core.runtime_settings import Snapshot
from app.schemas.settings import SyslogSettings

logger = logging.getLogger("app.syslog")

BUFFER_SIZE = 10_000
CONNECT_TIMEOUT_SECONDS = 5.0
MAX_BACKOFF_SECONDS = 60.0
FACILITY_AUDIT = 13  # "log audit"
FACILITY_APP = 16  # local0
_SEVERITY = {
    logging.CRITICAL: 2,
    logging.ERROR: 3,
    logging.WARNING: 4,
    logging.INFO: 6,
    logging.DEBUG: 7,
}
_BOM = b"\xef\xbb\xbf"


def _printable(value: str, limit: int) -> str:
    cleaned = "".join(c for c in value if "!" <= c <= "~")
    return cleaned[:limit] or "-"


def format_message(
    body: str,
    *,
    levelno: int,
    audit: bool,
    hostname: str,
    app_name: str,
    procid: str,
    created: float,
) -> bytes:
    """``<PRI>1 TIMESTAMP HOSTNAME APP-NAME PROCID MSGID - BOM MSG`` (no structured data)."""
    severity = next((sev for level, sev in _SEVERITY.items() if levelno >= level), 7)
    priority = (FACILITY_AUDIT if audit else FACILITY_APP) * 8 + severity
    timestamp = datetime.fromtimestamp(created, UTC).isoformat(timespec="milliseconds")
    header = " ".join(
        [
            f"<{priority}>1",
            timestamp.replace("+00:00", "Z"),
            _printable(hostname, 255),
            _printable(app_name, 48),
            _printable(procid, 128),
            "audit" if audit else "app",
            "-",
        ]
    )
    return header.encode("ascii") + b" " + _BOM + body.encode("utf-8")


def frame(message: bytes) -> bytes:
    """RFC 5425 octet counting: ``MSG-LEN SP SYSLOG-MSG``."""
    return str(len(message)).encode("ascii") + b" " + message


def connect(
    config: SyslogSettings, allowed: list[Network], resolver: Resolver | None = None
) -> ssl.SSLSocket:
    """TLS connection to the validated address of the configured host."""
    if config.host is None:
        raise OutboundUrlError("No syslog host configured")
    destination = resolve(config.host, config.port, allowed, resolver)
    sock = socket.create_connection(
        (destination.address, destination.port), CONNECT_TIMEOUT_SECONDS
    )
    try:
        return tls_context(config.ca_pem).wrap_socket(sock, server_hostname=destination.host)
    except BaseException:
        sock.close()
        raise


class SyslogForwarder(logging.Handler):
    """Forwards audit events and log records at or above the configured level."""

    def __init__(
        self,
        hostname: str,
        procid: str,
        resolver: Resolver | None = None,
        *,
        start_sender: bool = True,
    ) -> None:
        super().__init__(level=logging.DEBUG)
        self._start_sender = start_sender
        self.setFormatter(JsonFormatter())
        self.hostname = hostname
        self.procid = procid
        self._resolver = resolver
        self._config = SyslogSettings()
        self._allowed: list[Network] = []
        self._buffer: deque[bytes] = deque(maxlen=BUFFER_SIZE)
        self._dropped = 0
        self._generation = 0
        self._cond = threading.Condition()
        self._thread: threading.Thread | None = None

    @property
    def dropped(self) -> int:
        return self._dropped

    def configure(self, snapshot: Snapshot) -> None:
        """Settings listener: a new configuration closes the current connection."""
        try:
            allowed = parse_networks(snapshot.security.allowed_private_networks)
        except OutboundUrlError:
            allowed = []
        with self._cond:
            if snapshot.syslog == self._config and allowed == self._allowed:
                return
            self._config = snapshot.syslog
            self._allowed = allowed
            self._generation += 1
            if not self._config.enabled:
                self._buffer.clear()
            self._cond.notify_all()
        if self._config.enabled and self._thread is None and self._start_sender:
            self._thread = threading.Thread(target=self._run, name="syslog-sender", daemon=True)
            self._thread.start()

    def _accepts(self, record: logging.LogRecord) -> bool:
        if record.name.startswith("app.syslog"):
            return False
        if record.name == "app.audit":
            return self._config.forward_audit
        return record.levelno >= logging.getLevelNamesMapping()[self._config.min_level]

    def emit(self, record: logging.LogRecord) -> None:
        config = self._config
        if not config.enabled or not self._accepts(record):
            return
        try:
            message = format_message(
                self.format(record),
                levelno=record.levelno,
                audit=record.name == "app.audit",
                hostname=self.hostname,
                app_name=config.app_name,
                procid=self.procid,
                created=record.created,
            )
        except Exception:
            self.handleError(record)
            return
        self.enqueue(message)

    def enqueue(self, message: bytes) -> None:
        with self._cond:
            if len(self._buffer) == self._buffer.maxlen:
                self._dropped += 1
            self._buffer.append(message)
            self._cond.notify()

    def _dropped_notice(self) -> bytes:
        record = logging.LogRecord(
            "app.syslog",
            logging.WARNING,
            __file__,
            0,
            "%d log messages were dropped while the syslog server was unreachable",
            (self._dropped,),
            None,
        )
        return format_message(
            self.format(record),
            levelno=logging.WARNING,
            audit=False,
            hostname=self.hostname,
            app_name=self._config.app_name,
            procid=self.procid,
            created=record.created,
        )

    def _run(self) -> None:
        sock: ssl.SSLSocket | None = None
        generation = -1
        backoff = 1.0
        while True:
            with self._cond:
                while not (self._config.enabled and self._buffer):
                    self._cond.wait()
                if generation != self._generation and sock is not None:
                    sock.close()
                    sock = None
                generation = self._generation
                config, allowed = self._config, self._allowed
            try:
                if sock is None:
                    sock = connect(config, allowed, self._resolver)
                    backoff = 1.0
                    if self._dropped:
                        sock.sendall(frame(self._dropped_notice()))
                        self._dropped = 0
                self._drain(sock, generation)
            except (OSError, OutboundUrlError, ssl.SSLError) as exc:
                if sock is not None:
                    sock.close()
                    sock = None
                logger.warning("Syslog server unreachable", extra={"error": type(exc).__name__})
                with self._cond:
                    self._cond.wait(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

    def _drain(self, sock: ssl.SSLSocket, generation: int) -> None:
        while True:
            with self._cond:
                if not self._buffer or generation != self._generation:
                    return
                message = self._buffer.popleft()
            try:
                sock.sendall(frame(message))
            except OSError:
                with self._cond:
                    self._buffer.appendleft(message)
                raise


def send_test(
    config: SyslogSettings, allowed: list[Network], hostname: str, resolver: Resolver | None = None
) -> None:
    """Synchronously deliver one notice-level message; raises on any failure."""
    body = '{"message":"Test message from the wiki administration"}'
    message = format_message(
        body,
        levelno=logging.WARNING,
        audit=False,
        hostname=hostname,
        app_name=config.app_name,
        procid=str(os.getpid()),
        created=datetime.now(UTC).timestamp(),
    )
    with connect(config, allowed, resolver) as sock:
        sock.sendall(frame(message))
