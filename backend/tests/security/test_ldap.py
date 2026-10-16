"""Directory sign-in: escaped filters, no unauthenticated bind, provisioning, step-up."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.context import AppContext
from app.models import AuditEvent, SpaceMember, User
from app.schemas.settings import LdapSettings
from app.services import ldap_service
from tests.helpers import make_space, make_user, sign_in, write
from tests.sso_helpers import FakeDirectory, configure, ldap_values

INJECTIONS = ["*", "*)(uid=*", "bob)(|(uid=*", "*)(objectClass=*))(|(uid=", "\\2a", "bob\x00"]


@pytest.fixture
def directory(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeDirectory]:
    fake = FakeDirectory()
    fake.add_user("bob", "directory passphrase", groups=["eng"])
    monkeypatch.setattr(ldap_service, "connect", fake.connect)
    configure(ctx, "ldap", **ldap_values())
    yield fake


def _login(client: TestClient, username: str, password: str) -> int:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    status: int = response.status_code
    return status


@pytest.mark.parametrize("payload", INJECTIONS)
def test_filter_values_are_escaped(payload: str) -> None:
    config = LdapSettings.model_validate(ldap_values())
    built = ldap_service.user_filter(config, payload)
    inner = built.removeprefix("(&(objectClass=person)(uid=").removesuffix("))")
    assert not set(inner) & {"*", "(", ")", "\x00"}
    assert built.count("(") == config.user_filter.count("(")


@pytest.mark.parametrize("payload", INJECTIONS)
def test_injection_payloads_never_sign_in(
    client: TestClient, directory: FakeDirectory, payload: str
) -> None:
    assert _login(client, payload, "directory passphrase") in (401, 422)


def test_directory_sign_in_provisions_and_maps_groups(
    client: TestClient, ctx: AppContext, directory: FakeDirectory
) -> None:
    owner = make_user(ctx, "owner")
    space = make_space(ctx, "Engineering", owner)
    configure(
        ctx,
        "ldap",
        **ldap_values(group_mapping=[{"group": "eng", "space": space, "role": "editor"}]),
    )
    assert _login(client, "bob", "directory passphrase") == 200
    info = client.get("/api/v1/auth/session").json()
    assert (info["user"]["username"], info["user"]["auth_source"]) == ("bob", "ldap")
    assert info["user"]["email"] == "bob@example.com"
    assert directory.binds[0] == "cn=svc,dc=example,dc=com"
    with ctx.sessions() as db:
        bob = db.scalar(select(User).where(User.username == "bob"))
        assert bob is not None and bob.external_id == "uuid-bob" and bob.password_hash is None
        member = db.scalar(select(SpaceMember).where(SpaceMember.principal_id == bob.id))
    assert member is not None and (member.role, member.source) == ("editor", "sso")


def test_wrong_password_and_unknown_user_are_indistinguishable(
    client: TestClient, directory: FakeDirectory
) -> None:
    wrong = client.post("/api/v1/auth/login", json={"username": "bob", "password": "nope"})
    unknown = client.post("/api/v1/auth/login", json={"username": "ghost", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_empty_password_never_binds(directory: FakeDirectory) -> None:
    config = LdapSettings.model_validate(ldap_values())
    assert ldap_service.authenticate(config, [], "bob", "", directory.connect) is None
    assert directory.binds == []


def test_local_account_wins_over_the_directory(
    client: TestClient, ctx: AppContext, directory: FakeDirectory
) -> None:
    make_user(ctx, "bob")
    assert _login(client, "bob", "directory passphrase") == 401
    assert directory.binds == []


def test_directory_outage_is_reported_without_details(
    client: TestClient, directory: FakeDirectory
) -> None:
    directory.available = False
    response = client.post(
        "/api/v1/auth/login", json={"username": "bob", "password": "directory passphrase"}
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DIRECTORY_UNAVAILABLE"


def test_step_up_checks_the_directory_password(
    client: TestClient, directory: FakeDirectory
) -> None:
    client.post("/api/v1/auth/login", json={"username": "bob", "password": "directory passphrase"})
    client.headers["X-CSRF-Token"] = client.get("/api/v1/auth/session").json()["csrf_token"]
    assert (
        write(client, "POST", "/api/v1/auth/reauth", json={"password": "nope"}).status_code == 401
    )
    ok = write(client, "POST", "/api/v1/auth/reauth", json={"password": "directory passphrase"})
    assert ok.status_code == 200, ok.text
    # Step-up rotates the session, and with it the CSRF token.
    client.headers["X-CSRF-Token"] = ok.json()["csrf_token"]
    password = write(
        client,
        "POST",
        "/api/v1/me/password",
        json={"current_password": "directory passphrase", "new_password": "a brand new passphrase"},
    )
    assert password.json()["error"]["code"] == "NOT_LOCAL_ACCOUNT"


def test_break_glass_only_admins_sign_in_locally(
    client: TestClient, ctx: AppContext, directory: FakeDirectory
) -> None:
    configure(ctx, "security", local_sign_in="admins_only")
    local = make_user(ctx, "carol")
    assert _login(client, local.username, local.password) == 401
    assert _login(client, "bob", "directory passphrase") == 200
    with TestClient(
        client.app, base_url="https://testserver", headers={"X-Requested-With": "XMLHttpRequest"}
    ) as admin:
        sign_in(admin, make_user(ctx, "root", role="admin"))
    with ctx.sessions() as db:
        alert = db.scalar(select(AuditEvent).where(AuditEvent.action == "auth.break_glass"))
        refused = db.scalars(
            select(AuditEvent.after).where(
                AuditEvent.action == "auth.login", AuditEvent.outcome == "failure"
            )
        ).all()
    assert alert is not None and alert.severity == "critical"
    assert {"reason": "local_sign_in_disabled"} in refused


def test_directory_admin_group_requires_a_second_factor(
    client: TestClient, ctx: AppContext, directory: FakeDirectory
) -> None:
    make_user(ctx, "root", role="admin")
    configure(ctx, "ldap", **ldap_values(admin_groups=["cn=eng,ou=groups,dc=example,dc=com"]))
    response = client.post(
        "/api/v1/auth/login", json={"username": "bob", "password": "directory passphrase"}
    )
    assert response.json()["state"] == "mfa_enrollment_required"
    with ctx.sessions() as db:
        role = db.scalar(select(User.global_role).where(User.username == "bob"))
    assert role == "admin"
