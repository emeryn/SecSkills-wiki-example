"""HTTP(S) requests to SSRF-checked destinations (webhooks, OIDC, inference server).

The connection goes to the address ``core.outbound_url`` validated, while the certificate and the
``Host`` header are checked for the host name. Redirects are never followed and responses are
size-limited. Plain ``http`` is only used when the caller allows it (an allowlisted private
network); an HTTPS proxy is reached with ``CONNECT``, TLS is still verified end to end.
"""

import http.client
import socket
import ssl
from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Literal

from app.core.outbound_url import Destination, tls_context

TIMEOUT_SECONDS = 5.0
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024
Scheme = Literal["http", "https"]


class OutboundHttpError(RuntimeError):
    """The request failed; the message is safe to show to an administrator."""


class HttpStatusError(OutboundHttpError):
    """The server answered with an error status (streaming requests)."""

    def __init__(self, status: int, body: bytes) -> None:
        super().__init__(f"The server answered {status}")
        self.status = status
        self.body = body


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS to the validated address; certificate and ``Host`` are checked for the host name."""

    def __init__(self, destination: Destination, context: ssl.SSLContext, timeout: float) -> None:
        super().__init__(destination.host, destination.port, timeout=timeout, context=context)
        self._address = destination.address
        self._tls = context

    def connect(self) -> None:
        sock = socket.create_connection((self._address, self.port), self.timeout)
        self.sock = self._tls.wrap_socket(sock, server_hostname=self.host)


class PinnedHTTPConnection(http.client.HTTPConnection):
    """Plain HTTP to the validated address (allowlisted private networks only)."""

    def __init__(self, destination: Destination, timeout: float) -> None:
        super().__init__(destination.host, destination.port, timeout=timeout)
        self._address = destination.address

    def connect(self) -> None:
        self.sock = socket.create_connection((self._address, self.port), self.timeout)


ConnectionFactory = Callable[[Destination, ssl.SSLContext, float], http.client.HTTPConnection]


def open_connection(
    destination: Destination,
    *,
    scheme: Scheme = "https",
    ca_pem: str | None = None,
    proxy: Destination | None = None,
    timeout: float = TIMEOUT_SECONDS,
) -> http.client.HTTPConnection:
    if proxy is not None:
        if scheme != "https":
            raise OutboundHttpError("A proxy is only used for https destinations")
        # CONNECT through the (validated) proxy address; TLS is verified for the target host.
        connection = http.client.HTTPSConnection(
            proxy.address, proxy.port, timeout=timeout, context=tls_context(ca_pem)
        )
        connection.set_tunnel(destination.host, destination.port)
        return connection
    if scheme == "https":
        return PinnedHTTPSConnection(destination, tls_context(ca_pem), timeout)
    return PinnedHTTPConnection(destination, timeout)


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    content_type: str


def request(
    destination: Destination,
    method: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    ca_pem: str | None = None,
    connection_factory: ConnectionFactory | None = None,
    scheme: Scheme = "https",
    proxy: Destination | None = None,
    timeout: float = TIMEOUT_SECONDS,
) -> HttpResponse:
    """One request; 3xx answers are returned as they are, never followed."""
    if connection_factory is not None:
        connection = connection_factory(destination, tls_context(ca_pem), timeout)
    else:
        connection = open_connection(
            destination, scheme=scheme, ca_pem=ca_pem, proxy=proxy, timeout=timeout
        )
    try:
        connection.request(method, destination.path, body=body, headers=headers or {})
        response = connection.getresponse()
        data = response.read(MAX_RESPONSE_BYTES + 1)
        status = response.status
        content_type = response.getheader("Content-Type") or ""
    except ssl.SSLError as exc:
        raise OutboundHttpError("TLS verification failed") from exc
    except (OSError, http.client.HTTPException) as exc:
        raise OutboundHttpError("Connection failed") from exc
    finally:
        connection.close()
    if len(data) > MAX_RESPONSE_BYTES:
        raise OutboundHttpError("The response is too large")
    return HttpResponse(status, data, content_type)


def stream_lines(
    destination: Destination,
    method: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    ca_pem: str | None = None,
    scheme: Scheme = "https",
    proxy: Destination | None = None,
    timeout: float = TIMEOUT_SECONDS,
) -> Generator[bytes]:
    """Response lines as they arrive. Closing the iterator closes the connection (cancel)."""
    connection = open_connection(
        destination, scheme=scheme, ca_pem=ca_pem, proxy=proxy, timeout=timeout
    )
    try:
        connection.request(method, destination.path, body=body, headers=headers or {})
        response = connection.getresponse()
        if response.status != 200:  # noqa: PLR2004
            raise HttpStatusError(response.status, response.read(64 * 1024))
        while line := response.readline(MAX_LINE_BYTES):
            yield line
    except ssl.SSLError as exc:
        raise OutboundHttpError("TLS verification failed") from exc
    except (OSError, http.client.HTTPException) as exc:
        raise OutboundHttpError("Connection failed") from exc
    finally:
        connection.close()
