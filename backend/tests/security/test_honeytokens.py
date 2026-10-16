"""Honeytokens: a hit blocks the client IP and records a critical audit event."""

import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from app.core.config import Settings
from app.core.context import AppContext
from app.core.secrets import FileSecretsProvider
from app.main import create_app
from app.models import AuditEvent, BlockedIp
from tests.helpers import make_user, sign_in, write

ATTACKER = "198.51.100.7"
OFFICE = "203.0.113.9"


def _client(app: object, ip: str) -> TestClient:
    return TestClient(
        app,  # type: ignore[arg-type]
        base_url="https://testserver",
        headers={"X-Requested-With": "XMLHttpRequest", "X-Forwarded-For": ip},
        raise_server_exceptions=False,
    )


@pytest.fixture
def attacker(client: TestClient) -> Iterator[TestClient]:
    with _client(client.app, ATTACKER) as attacker_client:
        yield attacker_client


def _honeytoken_events(ctx: AppContext) -> list[AuditEvent]:
    with ctx.sessions() as db:
        return list(
            db.scalars(select(AuditEvent).where(AuditEvent.action == "security.honeytoken")).all()
        )


def test_decoy_login_looks_like_a_failed_login_and_blocks(
    attacker: TestClient, ctx: AppContext, caplog: pytest.LogCaptureFixture
) -> None:
    unknown = attacker.post("/api/v1/auth/login", json={"username": "nobody", "password": "x" * 12})
    with caplog.at_level(logging.CRITICAL, logger="app.audit"):
        decoy = attacker.post(
            "/api/v1/auth/login", json={"username": "Administrator", "password": "x" * 12}
        )
    assert decoy.status_code == unknown.status_code == 401
    assert decoy.json()["error"]["code"] == unknown.json()["error"]["code"]
    assert decoy.json()["error"]["message"] == unknown.json()["error"]["message"]

    blocked = attacker.get("/api/v1/health")
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "ACCESS_BLOCKED"

    [event] = _honeytoken_events(ctx)
    assert event.severity == "critical"
    assert str(event.actor_ip) == ATTACKER
    assert event.after is not None and event.after["blocked"] is True
    assert any(r.levelno == logging.CRITICAL for r in caplog.records)
    with ctx.sessions() as db:
        assert db.get(BlockedIp, ATTACKER) is not None


def test_trap_endpoint_answers_404_and_blocks(
    attacker: TestClient, client: TestClient, ctx: AppContext
) -> None:
    response = attacker.get("/api/v1/debug/config")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert attacker.get("/api/v1/auth/session").status_code == 403
    with _client(client.app, OFFICE) as office:
        assert office.get("/api/v1/health").status_code == 200
    assert _honeytoken_events(ctx)[0].after == {
        "kind": "trap_endpoint",
        "blocked": True,
        "path": "/api/v1/debug/config",
    }


def test_real_account_with_a_decoy_name_signs_in(client: TestClient, ctx: AppContext) -> None:
    sign_in(client, make_user(ctx, "sysadmin"))
    assert _honeytoken_events(ctx) == []


def test_decoy_names_cannot_be_given_to_new_accounts(client: TestClient, ctx: AppContext) -> None:
    sign_in(client, make_user(ctx, "root", role="admin"))
    response = write(client, "POST", "/api/v1/admin/users", json={"username": "administrator"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "USERNAME_RESERVED"


@pytest.fixture
def untrusted_app_client(
    settings: Settings, engine: Engine, secrets_provider: FileSecretsProvider
) -> Iterator[TestClient]:
    """No trusted proxy, yet a forwarded header: the peer would be an unknown proxy."""
    app = create_app(
        settings.model_copy(update={"trusted_proxy_count": 0}),
        engine=engine,
        secrets=secrets_provider,
    )
    with _client(app, ATTACKER) as client:
        yield client


def test_unattributable_ip_is_never_blocked(untrusted_app_client: TestClient) -> None:
    untrusted_app_client.get("/api/v1/debug/config")
    assert untrusted_app_client.get("/api/v1/health").status_code == 200
    ctx: AppContext = untrusted_app_client.app.state.context  # type: ignore[attr-defined]
    [event] = _honeytoken_events(ctx)
    assert event.after is not None and event.after["blocked"] is False


def test_administrator_unblocks_from_another_network(
    attacker: TestClient, client: TestClient, ctx: AppContext
) -> None:
    attacker.get("/api/v1/debug/config")
    assert attacker.get("/api/v1/health").status_code == 403
    with _client(client.app, OFFICE) as office:
        sign_in(office, make_user(ctx, "root", role="admin"))
        listed = office.get("/api/v1/admin/blocked-ips").json()
        assert [row["ip"] for row in listed] == [ATTACKER]
        assert write(office, "DELETE", f"/api/v1/admin/blocked-ips/{ATTACKER}").status_code == 204
        assert write(office, "DELETE", f"/api/v1/admin/blocked-ips/{ATTACKER}").status_code == 404
    assert attacker.get("/api/v1/health").status_code == 200
    with ctx.sessions() as db:
        assert (
            db.scalar(select(AuditEvent).where(AuditEvent.action == "security.ip_unblocked"))
            is not None
        )
