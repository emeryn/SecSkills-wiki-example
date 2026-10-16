"""Webhook delivery: HMAC signature, pinned address, redirects refused."""

import hashlib
import hmac
import http.client
import json
import socket
import ssl
from typing import Any, cast

import pytest

from app.core.outbound_http import ConnectionFactory, PinnedHTTPSConnection
from app.core.outbound_url import Destination
from app.services import webhook

SECRET = "s" * 40
DESTINATION = Destination(
    host="hooks.example.com", port=443, address="93.184.216.34", path="/notify"
)


class FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def read(self, amount: int) -> bytes:
        return b""

    def getheader(self, name: str) -> str | None:
        return None


class FakeConnection:
    def __init__(self, status: int) -> None:
        self.status = status
        self.sent: dict[str, Any] = {}

    def request(self, method: str, path: str, body: bytes, headers: dict[str, str]) -> None:
        self.sent = {"method": method, "path": path, "body": body, "headers": headers}

    def getresponse(self) -> FakeResponse:
        return FakeResponse(self.status)

    def close(self) -> None:
        return None


def factory(connection: FakeConnection) -> ConnectionFactory:
    return lambda destination, context, timeout: cast(http.client.HTTPConnection, connection)


def test_payload_is_signed_with_timestamp() -> None:
    connection = FakeConnection(204)
    webhook.send(
        DESTINATION, SECRET, {"event": "wiki.test"}, connection_factory=factory(connection)
    )
    headers = connection.sent["headers"]
    timestamp = headers[webhook.TIMESTAMP_HEADER]
    expected = hmac.new(
        SECRET.encode(), timestamp.encode() + b"." + connection.sent["body"], hashlib.sha256
    ).hexdigest()
    assert headers[webhook.SIGNATURE_HEADER] == f"sha256={expected}"
    assert json.loads(connection.sent["body"]) == {"event": "wiki.test"}
    assert connection.sent["path"] == "/notify"


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirects_are_not_followed(status: int) -> None:
    with pytest.raises(webhook.WebhookError, match="redirect"):
        webhook.send(DESTINATION, SECRET, {}, connection_factory=factory(FakeConnection(status)))


def test_error_status_fails() -> None:
    with pytest.raises(webhook.WebhookError, match="500"):
        webhook.send(DESTINATION, SECRET, {}, connection_factory=factory(FakeConnection(500)))


def test_connection_goes_to_the_pinned_address(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[tuple[str, int]] = []

    def create_connection(address: tuple[str, int], timeout: float) -> None:
        attempts.append(address)
        raise ConnectionRefusedError

    monkeypatch.setattr(socket, "create_connection", create_connection)
    connection = PinnedHTTPSConnection(DESTINATION, ssl.create_default_context(), timeout=1)
    with pytest.raises(ConnectionRefusedError):
        connection.connect()
    assert attempts == [("93.184.216.34", 443)]
    assert isinstance(connection, http.client.HTTPSConnection)
    assert connection.host == "hooks.example.com"
