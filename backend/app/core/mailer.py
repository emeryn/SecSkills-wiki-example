"""Outbound email over SMTPS with certificate verification. Disabled unless configured.

The transport comes from ``BACKEND_SMTP_*`` when set (operator-controlled, shown read-only in the
administration UI), otherwise from the SMTP settings section, whose host is SSRF-checked and
connected to by its validated address.
"""

import logging
import re
import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from app.core.config import Settings
from app.core.outbound_url import OutboundUrlError, parse_networks, resolve, tls_context
from app.core.runtime_settings import RuntimeSettings

logger = logging.getLogger(__name__)
_HEADER_UNSAFE = re.compile(r"[\r\n]")
TIMEOUT_SECONDS = 10


class MailerDisabledError(OSError):
    """No SMTP server is configured, or its host is refused by the outbound URL policy."""


@dataclass(frozen=True)
class SmtpTransport:
    host: str
    port: int
    from_address: str
    username: str | None
    password: str | None
    ca_pem: str | None
    ca_file: Path | None
    # Validated address to connect to; None for an operator-defined (environment) server.
    address: str | None


class _PinnedSMTP(smtplib.SMTP_SSL):
    """SMTPS to a fixed address while verifying the certificate for the host name."""

    def __init__(self, transport: SmtpTransport, context: ssl.SSLContext) -> None:
        self._pinned_address = transport.address or transport.host
        super().__init__(transport.host, transport.port, context=context, timeout=TIMEOUT_SECONDS)

    def _get_socket(self, host: str, port: int, timeout: float) -> socket.socket:
        sock = socket.create_connection((self._pinned_address, port), timeout)
        return self.context.wrap_socket(sock, server_hostname=host)


class Mailer:
    def __init__(self, settings: Settings, runtime: RuntimeSettings) -> None:
        self._settings = settings
        self._runtime = runtime

    @property
    def managed_by_environment(self) -> bool:
        return self._settings.smtp_enabled

    @property
    def enabled(self) -> bool:
        return self.managed_by_environment or self._runtime.snapshot().smtp.enabled

    def transport(self) -> SmtpTransport:
        """Effective transport; raises ``MailerDisabledError`` when none is usable."""
        settings = self._settings
        if settings.smtp_host is not None:
            password = None
            if settings.smtp_username and settings.smtp_password_file:
                password = settings.smtp_password_file.read_text(encoding="utf-8").strip()
            return SmtpTransport(
                host=settings.smtp_host,
                port=settings.smtp_port,
                from_address=settings.smtp_from,
                username=settings.smtp_username,
                password=password,
                ca_pem=None,
                ca_file=settings.smtp_ca_file,
                address=None,
            )
        snapshot = self._runtime.snapshot()
        smtp = snapshot.smtp
        if not smtp.enabled or smtp.host is None or smtp.from_address is None:
            raise MailerDisabledError
        try:
            destination = resolve(
                smtp.host, smtp.port, parse_networks(snapshot.security.allowed_private_networks)
            )
        except OutboundUrlError as exc:
            raise MailerDisabledError(exc.reason) from exc
        return SmtpTransport(
            host=destination.host,
            port=smtp.port,
            from_address=smtp.from_address,
            username=smtp.username,
            password=smtp.password,
            ca_pem=smtp.ca_pem,
            ca_file=None,
            address=destination.address,
        )

    def send(self, to: str, subject: str, body: str) -> None:
        """Send a plain-text message; header values are stripped of CR/LF."""
        transport = self.transport()
        message = EmailMessage()
        message["From"] = _HEADER_UNSAFE.sub("", transport.from_address)
        message["To"] = _HEADER_UNSAFE.sub("", to)
        message["Subject"] = _HEADER_UNSAFE.sub("", subject)
        message.set_content(body)
        context = tls_context(transport.ca_pem, transport.ca_file)
        with _PinnedSMTP(transport, context) as smtp:
            if transport.username and transport.password:
                smtp.login(transport.username, transport.password)
            smtp.send_message(message)
        logger.info("Email sent", extra={"subject": subject})
