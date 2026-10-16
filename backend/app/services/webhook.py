"""Outbound webhooks: JSON POSTed over https to a pinned, SSRF-checked address.

Receivers verify ``X-Signature: sha256=<hex>``, the HMAC-SHA256 of ``"<timestamp>.<body>"`` with
the shared secret, and reject timestamps (``X-Signature-Timestamp``, Unix seconds) that are too
old. Redirects are never followed.
"""

import hashlib
import hmac
import json
import time
from typing import Any

from app.core.outbound_http import (
    ConnectionFactory,
    OutboundHttpError,
    PinnedHTTPSConnection,
    request,
)
from app.core.outbound_url import Destination

SIGNATURE_HEADER = "X-Signature"
TIMESTAMP_HEADER = "X-Signature-Timestamp"


class WebhookError(RuntimeError):
    """Delivery failed; the message is safe to show to an administrator."""


def signature(secret: str, timestamp: int, body: bytes) -> str:
    message = str(timestamp).encode() + b"." + body
    return "sha256=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def send(
    destination: Destination,
    secret: str,
    payload: dict[str, Any],
    ca_pem: str | None = None,
    *,
    connection_factory: ConnectionFactory = PinnedHTTPSConnection,
) -> int:
    """POST ``payload``; returns the 2xx status or raises ``WebhookError``."""
    body = json.dumps(payload, separators=(",", ":"), default=str).encode()
    timestamp = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "wiki-webhook/1",
        TIMESTAMP_HEADER: str(timestamp),
        SIGNATURE_HEADER: signature(secret, timestamp, body),
    }
    try:
        response = request(
            destination,
            "POST",
            body=body,
            headers=headers,
            ca_pem=ca_pem,
            connection_factory=connection_factory,
        )
    except OutboundHttpError as exc:
        raise WebhookError(str(exc)) from exc
    if 300 <= response.status < 400:  # noqa: PLR2004
        raise WebhookError("The receiver answered with a redirect, which is not followed")
    if not 200 <= response.status < 300:  # noqa: PLR2004
        raise WebhookError(f"The receiver answered {response.status}")
    return response.status
