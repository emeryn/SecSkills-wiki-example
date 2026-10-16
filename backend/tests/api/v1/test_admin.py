from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.context import AppContext
from app.models import AuditEvent, User
from tests.helpers import make_user, sign_in, write


def _admin(client: TestClient, ctx: AppContext) -> TestClient:
    sign_in(client, make_user(ctx, "root", role="admin"))
    return client


def test_create_user_with_invitation_link(client: TestClient, ctx: AppContext) -> None:
    admin = _admin(client, ctx)
    response = write(
        admin,
        "POST",
        "/api/v1/admin/users",
        json={"username": "carol", "email": "carol@example.com", "display_name": "Carol"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["email"] == "carol@example.com"
    assert body["invitation"]["url"].startswith("https://testserver/reset-password?token=")

    token = body["invitation"]["url"].split("token=")[1]
    with TestClient(
        client.app, base_url="https://testserver", headers={"X-Requested-With": "XMLHttpRequest"}
    ) as carol:
        confirm = carol.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": token, "new_password": "her very own passphrase"},
        )
        assert confirm.status_code == 204
        login = carol.post(
            "/api/v1/auth/login", json={"username": "carol", "password": "her very own passphrase"}
        )
        assert login.json()["state"] == "active"


def test_email_is_stored_encrypted_and_searchable(client: TestClient, ctx: AppContext) -> None:
    admin = _admin(client, ctx)
    make_user(ctx, "dave", email="Dave@Example.com")
    with ctx.sessions() as db:
        stored = db.scalar(select(User.email_enc).where(User.username == "dave"))
    assert stored is not None
    assert b"example" not in stored.lower()
    found = admin.get("/api/v1/admin/users", params={"q": "dave@example.com"}).json()
    assert [u["username"] for u in found["items"]] == ["dave"]
    prefix = admin.get("/api/v1/admin/users", params={"q": "da"}).json()
    assert prefix["total"] == 1


def test_duplicate_username_is_rejected(client: TestClient, ctx: AppContext) -> None:
    admin = _admin(client, ctx)
    make_user(ctx, "erin")
    response = write(admin, "POST", "/api/v1/admin/users", json={"username": "ERIN"})
    assert response.status_code == 409


def test_role_change_revokes_target_sessions(client: TestClient, ctx: AppContext) -> None:
    admin = _admin(client, ctx)
    bob = make_user(ctx, "bob")
    with TestClient(
        client.app, base_url="https://testserver", headers={"X-Requested-With": "XMLHttpRequest"}
    ) as bob_client:
        sign_in(bob_client, bob)
        response = write(admin, "PATCH", f"/api/v1/admin/users/{bob.id}", json={"role": "admin"})
        assert response.status_code == 200, response.text
        assert bob_client.get("/api/v1/auth/session").status_code == 401
    with TestClient(
        client.app, base_url="https://testserver", headers={"X-Requested-With": "XMLHttpRequest"}
    ) as again:
        assert sign_in(again, bob).json()["state"] == "mfa_enrollment_required"


def test_cannot_change_own_role_or_remove_last_admin(client: TestClient, ctx: AppContext) -> None:
    admin = _admin(client, ctx)
    with ctx.sessions() as db:
        root_id = db.scalar(select(User.id).where(User.username == "root"))
    response = write(admin, "PATCH", f"/api/v1/admin/users/{root_id}", json={"status": "disabled"})
    assert response.status_code == 409


def test_disabled_user_cannot_sign_in(client: TestClient, ctx: AppContext) -> None:
    admin = _admin(client, ctx)
    bob = make_user(ctx, "bob")
    write(admin, "PATCH", f"/api/v1/admin/users/{bob.id}", json={"status": "disabled"})
    with TestClient(
        client.app, base_url="https://testserver", headers={"X-Requested-With": "XMLHttpRequest"}
    ) as other:
        response = other.post(
            "/api/v1/auth/login", json={"username": "bob", "password": bob.password}
        )
        assert response.status_code == 401


def test_group_lifecycle_and_membership(client: TestClient, ctx: AppContext) -> None:
    admin = _admin(client, ctx)
    bob = make_user(ctx, "bob")
    group = write(admin, "POST", "/api/v1/admin/groups", json={"name": "Engineering"}).json()
    assert (
        write(admin, "POST", "/api/v1/admin/groups", json={"name": "engineering"}).status_code
        == 409
    )
    assert (
        write(admin, "PUT", f"/api/v1/admin/groups/{group['id']}/members/{bob.id}").status_code
        == 204
    )
    detail = admin.get(f"/api/v1/admin/groups/{group['id']}").json()
    assert [m["username"] for m in detail["members"]] == ["bob"]
    assert admin.get(f"/api/v1/admin/users/{bob.id}").json()["groups"][0]["name"] == "Engineering"
    renamed = write(
        admin, "PATCH", f"/api/v1/admin/groups/{group['id']}", json={"name": "Eng"}
    ).json()
    assert renamed["name"] == "Eng"
    assert (
        write(admin, "DELETE", f"/api/v1/admin/groups/{group['id']}/members/{bob.id}").status_code
        == 204
    )
    assert write(admin, "DELETE", f"/api/v1/admin/groups/{group['id']}").status_code == 204
    assert admin.get(f"/api/v1/admin/groups/{group['id']}").status_code == 404


def test_admin_actions_are_audited(client: TestClient, ctx: AppContext) -> None:
    admin = _admin(client, ctx)
    write(admin, "POST", "/api/v1/admin/groups", json={"name": "Ops"})
    with ctx.sessions() as db:
        actions = db.scalars(select(AuditEvent.action).order_by(AuditEvent.id)).all()
    assert "auth.login" in actions
    assert "group.created" in actions
