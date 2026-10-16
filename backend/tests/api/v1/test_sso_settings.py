"""SSO settings in the administration API: environment precedence, write-only secrets, tests."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from app.core.config import Settings
from app.core.context import AppContext
from app.core.secrets import FileSecretsProvider
from app.main import create_app
from app.models import AuditEvent
from app.services import oidc_service
from tests.helpers import make_space, make_user, sign_in, write
from tests.sso_helpers import CLIENT_SECRET, FakeIdP, oidc_values

PUBLIC_ISSUER = "https://93.184.216.34"


@pytest.fixture
def admin(client: TestClient, ctx: AppContext) -> TestClient:
    sign_in(client, make_user(ctx, "root", role="admin"))
    return client


def test_client_secret_is_write_only(admin: TestClient, ctx: AppContext) -> None:
    saved = write(
        admin, "PUT", "/api/v1/admin/settings/oidc", json=oidc_values(issuer=PUBLIC_ISSUER)
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["values"]["client_secret"] == "••••tail"
    assert CLIENT_SECRET not in admin.get("/api/v1/admin/settings/oidc").text
    with ctx.sessions() as db:
        audit = db.scalars(
            select(AuditEvent.after).where(AuditEvent.action == "settings.updated")
        ).all()
    assert all(CLIENT_SECRET not in str(after) for after in audit)


def test_bind_password_is_write_only(admin: TestClient) -> None:
    body = {
        "enabled": True,
        "url": "ldaps://93.184.216.34",
        "bind_dn": "cn=svc,dc=example,dc=com",
        "bind_password": "directory-service-password",
        "user_base_dn": "ou=people,dc=example,dc=com",
    }
    saved = write(admin, "PUT", "/api/v1/admin/settings/ldap", json=body)
    assert saved.status_code == 200, saved.text
    assert "directory-service-password" not in admin.get("/api/v1/admin/settings/ldap").text


@pytest.mark.parametrize(
    "body",
    [
        oidc_values(issuer="https://169.254.169.254"),
        oidc_values(issuer="http://93.184.216.34"),
        oidc_values(issuer=PUBLIC_ISSUER, id_token_algorithm="none"),
        oidc_values(issuer=PUBLIC_ISSUER, scopes=["profile"]),
        oidc_values(
            issuer=PUBLIC_ISSUER,
            group_mapping=[{"group": "eng", "space": "no-such-space", "role": "editor"}],
        ),
    ],
)
def test_invalid_oidc_settings_are_refused(admin: TestClient, body: dict[str, object]) -> None:
    assert write(admin, "PUT", "/api/v1/admin/settings/oidc", json=body).status_code == 422


def test_mapping_to_an_existing_space_is_accepted(admin: TestClient, ctx: AppContext) -> None:
    space = make_space(ctx, "Docs", make_user(ctx, "owner"))
    body = oidc_values(
        issuer=PUBLIC_ISSUER, group_mapping=[{"group": "eng", "space": space, "role": "viewer"}]
    )
    assert write(admin, "PUT", "/api/v1/admin/settings/oidc", json=body).status_code == 200


def test_connection_test_runs_discovery_and_keys(
    admin: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    idp = FakeIdP()
    monkeypatch.setattr(oidc_service, "make_transport", lambda config, allowed: idp)
    write(admin, "PUT", "/api/v1/admin/settings/oidc", json=oidc_values(issuer=PUBLIC_ISSUER))
    # The fake IdP announces another issuer than the one saved.
    mismatch = write(admin, "POST", "/api/v1/admin/settings/oidc/test").json()
    assert mismatch == {"ok": False, "message": "The discovery document names another issuer"}


@pytest.fixture
def env_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    settings: Settings,
    engine: Engine,
    secrets_provider: FileSecretsProvider,
) -> Iterator[TestClient]:
    secret = tmp_path / "secret"
    secret.write_text(CLIENT_SECRET)
    monkeypatch.setenv("BACKEND_OIDC_ISSUER", PUBLIC_ISSUER)
    monkeypatch.setenv("BACKEND_OIDC_CLIENT_SECRET_FILE", str(secret))
    app = create_app(settings, engine=engine, secrets=secrets_provider)
    with TestClient(
        app, base_url="https://testserver", headers={"X-Requested-With": "XMLHttpRequest"}
    ) as client:
        sign_in(client, make_user(app.state.context, "root", role="admin"))
        yield client


def test_environment_defined_fields_are_read_only(env_client: TestClient) -> None:
    shown = env_client.get("/api/v1/admin/settings/oidc").json()
    assert shown["managed_fields"] == ["client_secret", "issuer"]
    assert shown["values"]["issuer"] == PUBLIC_ISSUER
    assert shown["values"]["client_secret"] == "••••tail"

    conflict = write(
        env_client,
        "PUT",
        "/api/v1/admin/settings/oidc",
        json={"enabled": True, "client_id": "wiki", "issuer": "https://other.example.com"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["details"] == {"fields": ["issuer"]}

    # The rest stays editable; required fields may come from the environment.
    ok = write(
        env_client,
        "PUT",
        "/api/v1/admin/settings/oidc",
        json={"enabled": True, "client_id": "wiki"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["values"]["enabled"] is True
