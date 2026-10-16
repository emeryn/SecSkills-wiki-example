"""Input validation, idempotency and CSRF cases of the security matrix."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.context import AppContext
from app.models import Group
from tests.helpers import make_user, sign_in, write


def _admin_client(client: TestClient, ctx: AppContext) -> TestClient:
    sign_in(client, make_user(ctx, "root", role="admin"))
    return client


def test_unknown_field_is_rejected_and_not_applied(client: TestClient, ctx: AppContext) -> None:
    user = make_user(ctx, "bob")
    response = client.post(
        "/api/v1/auth/login", json={"username": "bob", "password": user.password, "role": "admin"}
    )
    assert response.status_code == 422
    admin = _admin_client(client, ctx)
    response = write(admin, "PATCH", f"/api/v1/admin/users/{user.id}", json={"is_admin": True})
    assert response.status_code == 422


def test_page_size_over_maximum_is_rejected(client: TestClient, ctx: AppContext) -> None:
    admin = _admin_client(client, ctx)
    assert admin.get("/api/v1/admin/users", params={"page_size": 101}).status_code == 422
    assert admin.get("/api/v1/admin/users", params={"page_size": 100}).status_code == 200


def test_sort_column_is_allowlisted(client: TestClient, ctx: AppContext) -> None:
    admin = _admin_client(client, ctx)
    response = admin.get("/api/v1/admin/users", params={"sort": "password_hash"})
    assert response.status_code == 422


def test_same_idempotency_key_and_body_writes_once(client: TestClient, ctx: AppContext) -> None:
    admin = _admin_client(client, ctx)
    key = str(uuid.uuid4())
    first = write(
        admin,
        "POST",
        "/api/v1/admin/groups",
        json={"name": "Eng"},
        headers={"Idempotency-Key": key},
    )
    second = write(
        admin,
        "POST",
        "/api/v1/admin/groups",
        json={"name": "Eng"},
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert second.headers["idempotent-replayed"] == "true"
    with ctx.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Group)) == 1


def test_same_idempotency_key_with_other_body_is_rejected(
    client: TestClient, ctx: AppContext
) -> None:
    admin = _admin_client(client, ctx)
    key = str(uuid.uuid4())
    write(
        admin,
        "POST",
        "/api/v1/admin/groups",
        json={"name": "Eng"},
        headers={"Idempotency-Key": key},
    )
    response = write(
        admin,
        "POST",
        "/api/v1/admin/groups",
        json={"name": "Ops"},
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_write_without_idempotency_key_is_refused(client: TestClient, ctx: AppContext) -> None:
    admin = _admin_client(client, ctx)
    response = admin.post("/api/v1/admin/groups", json={"name": "Eng"})
    assert response.status_code == 428


def test_state_change_without_custom_header_is_blocked(client: TestClient, ctx: AppContext) -> None:
    admin = _admin_client(client, ctx)
    del admin.headers["X-Requested-With"]
    response = write(admin, "POST", "/api/v1/admin/groups", json={"name": "Eng"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_FAILED"


def test_state_change_without_csrf_token_is_blocked(client: TestClient, ctx: AppContext) -> None:
    admin = _admin_client(client, ctx)
    del admin.headers["X-CSRF-Token"]
    assert write(admin, "POST", "/api/v1/admin/groups", json={"name": "Eng"}).status_code == 403


def test_foreign_origin_is_blocked(client: TestClient, ctx: AppContext) -> None:
    admin = _admin_client(client, ctx)
    response = write(
        admin,
        "POST",
        "/api/v1/admin/groups",
        json={"name": "Eng"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403


def test_cross_site_fetch_is_blocked(client: TestClient, ctx: AppContext) -> None:
    admin = _admin_client(client, ctx)
    response = write(
        admin,
        "POST",
        "/api/v1/admin/groups",
        json={"name": "Eng"},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert response.status_code == 403


def test_authenticated_api_responses_are_not_cached(client: TestClient, ctx: AppContext) -> None:
    sign_in(client, make_user(ctx, "bob"))
    assert client.get("/api/v1/auth/session").headers["cache-control"] == "no-store"
