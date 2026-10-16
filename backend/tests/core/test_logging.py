import json
import logging

from app.core.logging import JsonFormatter, mask_pii, request_id_var, set_pii_masking


def _format(message: str, **extra: object) -> dict[str, object]:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, message, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return json.loads(JsonFormatter().format(record))  # type: ignore[no-any-return]


def test_output_is_single_line_json_with_utc_timestamp() -> None:
    entry = _format("hello")
    assert entry["message"] == "hello"
    assert str(entry["ts"]).endswith("+00:00")


def test_crlf_in_user_values_cannot_forge_lines() -> None:
    entry = _format("user=alice\r\nlevel=CRITICAL fake", path="/x\n/y")
    assert "\n" not in str(entry["message"])
    assert "\n" not in str(entry["path"])


def test_sensitive_fields_are_redacted() -> None:
    entry = _format(
        "login",
        password="hunter2",
        session_id="abc",
        body={"new_password": "x", "username": "alice"},
    )
    serialized = json.dumps(entry)
    assert "hunter2" not in serialized
    assert entry["session_id"] == "[REDACTED]"
    assert entry["body"] == {"new_password": "[REDACTED]", "username": "alice"}


def test_request_id_is_included() -> None:
    token = request_id_var.set("req-123")
    try:
        assert _format("x")["request_id"] == "req-123"
    finally:
        request_id_var.reset(token)


def test_counts_under_sensitive_names_stay_readable() -> None:
    entry = _format("purged", purged={"sessions": 3, "reset_tokens": 0}, token="abc")
    assert entry["purged"] == {"sessions": 3, "reset_tokens": 0}
    assert entry["token"] == "[REDACTED]"


def test_pii_masking_hides_emails_and_ip_hosts() -> None:
    entry = {
        "ts": "2026-10-15T10:00:00.000+00:00",
        "message": "Reset sent to alice@example.com from 198.51.100.23",
        "client_ip": "2001:db8:85a3::8a2e:370:7334",
        "duration_ms": 12.5,
        "version": "10:00:00",
    }
    masked = mask_pii(entry)
    assert masked["message"] == "Reset sent to ***@example.com from 198.51.x.x"
    assert masked["client_ip"] == "2001:0db8:x::"
    assert masked["ts"] == entry["ts"]
    assert masked["duration_ms"] == 12.5
    assert masked["version"] == "10:00:00"


def test_formatter_masks_only_when_enabled() -> None:
    record = logging.LogRecord("app", logging.INFO, __file__, 1, "from 198.51.100.23", None, None)
    try:
        set_pii_masking(True)
        assert "198.51.x.x" in JsonFormatter().format(record)
    finally:
        set_pii_masking(False)
    assert "198.51.100.23" in JsonFormatter().format(record)
