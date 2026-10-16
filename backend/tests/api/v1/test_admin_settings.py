"""Settings administration: SSRF on save, write-only secrets, env-managed SMTP, Send test."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update

from app.core.config import Settings
from app.core.context import AppContext
from app.core.logging import pii_masking_enabled
from app.core.outbound_url import Destination
from app.core.secrets import FileSecretsProvider
from app.main import create_app
from app.models import AuditEvent, AuthSession, Setting
from app.services import syslog_forwarder, webhook
from tests.helpers import make_user, sign_in, write

PUBLIC_IP = "93.184.216.34"
SECRET = "whsec-0123456789abcdef0123456789abcdef-tail"  # gitleaks:allow (test value)


@pytest.fixture
def admin(client: TestClient, ctx: AppContext) -> TestClient:
    sign_in(client, make_user(ctx, "root", role="admin", email="root@example.com"))
    return client


def _webhook(**values: Any) -> dict[str, Any]:
    return {"enabled": True, "url": f"https://{PUBLIC_IP}/hook", "secret": SECRET, **values}


@pytest.mark.parametrize("host", ["127.0.0.1", "169.254.169.254", "10.0.0.8", "::1"])
def test_unsafe_syslog_destination_is_refused(admin: TestClient, host: str) -> None:
    response = write(
        admin, "PUT", "/api/v1/admin/settings/syslog", json={"enabled": True, "host": host}
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "SETTING_REJECTED"


def test_webhook_url_must_be_https_and_public(admin: TestClient) -> None:
    for url in ("http://93.184.216.34/hook", "https://169.254.169.254/latest/meta-data"):
        response = write(admin, "PUT", "/api/v1/admin/settings/webhook", json=_webhook(url=url))
        assert response.status_code == 422, url


def test_private_destination_allowed_once_allowlisted(admin: TestClient) -> None:
    refused = write(
        admin,
        "PUT",
        "/api/v1/admin/settings/security",
        json={"allowed_private_networks": ["169.254.0.0/16"]},
    )
    assert refused.status_code == 422
    allowed = write(
        admin,
        "PUT",
        "/api/v1/admin/settings/security",
        json={"allowed_private_networks": ["10.0.0.0/8"]},
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["info"]["trusted_proxy_count"] == 1
    response = write(
        admin, "PUT", "/api/v1/admin/settings/syslog", json={"enabled": True, "host": "10.1.2.3"}
    )
    assert response.status_code == 200, response.text


def test_secrets_are_write_only_and_encrypted(admin: TestClient, ctx: AppContext) -> None:
    saved = write(admin, "PUT", "/api/v1/admin/settings/webhook", json=_webhook())
    assert saved.status_code == 200, saved.text
    assert saved.json()["values"]["secret"] == "••••tail"
    assert SECRET not in admin.get("/api/v1/admin/settings/webhook").text

    # Omitting the secret keeps it; null clears it (then enabling fails).
    kept = write(
        admin,
        "PUT",
        "/api/v1/admin/settings/webhook",
        json={"enabled": True, "url": f"https://{PUBLIC_IP}/v2"},
    )
    assert kept.json()["values"]["secret"] == "••••tail"
    cleared = write(admin, "PUT", "/api/v1/admin/settings/webhook", json=_webhook(secret=None))
    assert cleared.status_code == 422

    with ctx.sessions() as db:
        stored = db.scalar(select(Setting.value_enc).where(Setting.key == "webhook"))
        changes = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "settings.updated")
        ).all()
    assert stored is not None and SECRET.encode() not in stored
    assert changes and all(SECRET not in str(e.after) + str(e.before) for e in changes)
    assert changes[0].after is not None and changes[0].after["secret"] == "[set]"


def test_settings_changes_need_recent_authentication(admin: TestClient, ctx: AppContext) -> None:
    with ctx.sessions() as db:
        db.execute(update(AuthSession).values(reauth_at=None))
        db.commit()
    response = write(admin, "PUT", "/api/v1/admin/settings/webhook", json=_webhook())
    assert response.json()["error"]["code"] == "REAUTH_REQUIRED"


def test_send_test_uses_saved_settings_and_is_throttled(
    admin: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    delivered: list[Destination] = []

    def fake_send(destination: Destination, secret: str, payload: dict[str, Any], ca: Any) -> int:
        delivered.append(destination)
        return 204

    monkeypatch.setattr(webhook, "send", fake_send)
    not_enabled = write(admin, "POST", "/api/v1/admin/settings/webhook/test")
    assert not_enabled.status_code == 409
    write(admin, "PUT", "/api/v1/admin/settings/webhook", json=_webhook())
    # Three attempts per minute per administrator; the refused one above counts.
    for _ in range(2):
        response = write(admin, "POST", "/api/v1/admin/settings/webhook/test")
        assert response.json() == {"ok": True, "message": "Test message sent"}
    assert [d.address for d in delivered] == [PUBLIC_IP, PUBLIC_IP]
    assert write(admin, "POST", "/api/v1/admin/settings/webhook/test").status_code == 429


def test_send_test_failure_is_reported_not_raised(
    admin: TestClient, monkeypatch: pytest.MonkeyPatch, ctx: AppContext
) -> None:
    def unreachable(*args: Any, **kwargs: Any) -> None:
        raise ConnectionRefusedError

    monkeypatch.setattr(syslog_forwarder, "send_test", unreachable)
    write(admin, "PUT", "/api/v1/admin/settings/syslog", json={"enabled": True, "host": PUBLIC_IP})
    response = write(admin, "POST", "/api/v1/admin/settings/syslog/test")
    assert response.json() == {"ok": False, "message": "Connection failed"}
    with ctx.sessions() as db:
        tested = db.scalar(select(AuditEvent).where(AuditEvent.action == "settings.tested"))
    assert tested is not None and tested.outcome == "failure"


def test_privacy_toggle_masks_logs_and_reset_restores_defaults(admin: TestClient) -> None:
    assert write(admin, "PUT", "/api/v1/admin/settings/privacy", json={"mask_pii": True}).is_success
    assert pii_masking_enabled()
    reset = write(admin, "DELETE", "/api/v1/admin/settings/privacy")
    assert reset.json()["values"] == {"mask_pii": False}
    assert not pii_masking_enabled()


def test_unknown_fields_are_rejected(admin: TestClient) -> None:
    response = write(
        admin, "PUT", "/api/v1/admin/settings/privacy", json={"mask_pii": True, "role": "admin"}
    )
    assert response.status_code == 422


@pytest.fixture
def env_smtp_client(
    settings: Settings, engine: Engine, secrets_provider: FileSecretsProvider
) -> Iterator[TestClient]:
    app = create_app(
        settings.model_copy(update={"smtp_host": "smtp.example.com"}),
        engine=engine,
        secrets=secrets_provider,
    )
    with TestClient(
        app, base_url="https://testserver", headers={"X-Requested-With": "XMLHttpRequest"}
    ) as client:
        sign_in(client, make_user(app.state.context, "root", role="admin"))
        yield client


def test_environment_smtp_is_read_only(env_smtp_client: TestClient) -> None:
    shown = env_smtp_client.get("/api/v1/admin/settings/smtp").json()
    assert shown["managed_by_environment"] is True
    assert shown["values"]["host"] == "smtp.example.com"
    response = write(env_smtp_client, "PUT", "/api/v1/admin/settings/smtp", json={"enabled": False})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MANAGED_BY_ENVIRONMENT"
