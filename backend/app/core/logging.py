"""Structured JSON logging with request correlation, secret redaction and optional PII masking."""

import ipaddress
import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_SENSITIVE_KEY = re.compile(
    r"pass(word)?|secret|token|session|cookie|authorization|api[_-]?key|private[_-]?key|csrf",
    re.IGNORECASE,
)
_CONTROL_CHARS = re.compile(r"[\r\n\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_REDACTED = "[REDACTED]"
_EMAIL = re.compile(r"[^\s@<>\"'(),;:]+@([^\s@<>\"'(),;:]+\.[^\s@<>\"'(),;:]+)")
_IP_CANDIDATE = re.compile(r"(?<![\w:.])[0-9A-Fa-f:.]{2,45}(?![\w:.])")
_UNMASKED_KEYS = frozenset({"ts", "level", "logger", "request_id"})
_pii_masking = False
_RESERVED_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys() | {"message", "asctime"}
)


def sanitize(value: Any) -> Any:
    """Strip CR/LF and control characters from strings so user input cannot forge log lines."""
    if isinstance(value, str):
        return _CONTROL_CHARS.sub(" ", value)
    if isinstance(value, dict):
        # Numbers and booleans are never secrets (e.g. purged session counts): only text is masked.
        return {
            str(k): _REDACTED
            if _SENSITIVE_KEY.search(str(k)) and not isinstance(v, int | float | bool | None)
            else sanitize(v)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [sanitize(v) for v in value]
    return value


def set_pii_masking(enabled: bool) -> None:
    """Toggled from the administration UI (Privacy settings); applies to every handler."""
    global _pii_masking  # noqa: PLW0603
    _pii_masking = enabled


def pii_masking_enabled() -> bool:
    return _pii_masking


def _mask_ip(match: re.Match[str]) -> str:
    candidate = match.group(0)
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return candidate
    if isinstance(address, ipaddress.IPv4Address):
        return ".".join([*candidate.split(".")[:2], "x", "x"])
    return ":".join(address.exploded.split(":")[:2]) + ":x::"


def mask_pii(value: Any) -> Any:
    """Mask email local parts and the host part of IP addresses (IPv4 /16, IPv6 /32 kept)."""
    if isinstance(value, str):
        return _IP_CANDIDATE.sub(_mask_ip, _EMAIL.sub(r"***@\1", value))
    if isinstance(value, dict):
        return {k: v if k in _UNMASKED_KEYS else mask_pii(v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_pii(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    """One JSON object per line; extra fields are redacted by key name."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": sanitize(record.getMessage()),
        }
        request_id = request_id_var.get()
        if request_id:
            entry["request_id"] = request_id
        extra = {k: v for k, v in record.__dict__.items() if k not in _RESERVED_ATTRS}
        entry.update(sanitize(extra))
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        if _pii_masking:
            entry = mask_pii(entry)
        return json.dumps(entry, default=str)


def configure_logging(level: str) -> None:
    """Route every logger (including uvicorn's) to a single JSON handler on stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
