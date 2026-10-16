"""Administration dashboard: counts, errors, alerts."""

from fastapi.testclient import TestClient

from app.core.context import AppContext
from app.services import server_errors
from tests.helpers import make_space, make_user, sign_in


def test_dashboard_counts(client: TestClient, ctx: AppContext) -> None:
    root = make_user(ctx, "root", role="admin")
    make_space(ctx, "Handbook", root)
    client.post("/api/v1/auth/login", json={"username": "root", "password": "wrong" * 3})
    client.get("/api/v1/debug/config")
    server_errors.record(ctx, "request", "GET", "/api/v1/spaces", 500, "req-1")
    with TestClient(
        client.app,
        base_url="https://testserver",
        headers={"X-Requested-With": "XMLHttpRequest", "X-Forwarded-For": "203.0.113.9"},
    ) as admin:
        sign_in(admin, root)
        response = admin.get("/api/v1/admin/dashboard", params={"period": "24h"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["users"]["total"] == 1
    assert body["users"]["signed_in"] == 1
    assert body["content"]["spaces"] == 1
    assert body["content"]["pages"] == 1
    assert body["security"]["failed_sign_ins"] == 1
    assert body["errors"]["count"] == 1
    assert body["errors"]["recent"][0]["request_id"] == "req-1"
    assert body["backup"] == {"last_at": None, "size_bytes": None, "overdue": True}
    assert len(body["activity"]) in (24, 25)
    assert sum(point["sign_ins"] for point in body["activity"]) == 1


def test_period_is_validated(client: TestClient, ctx: AppContext) -> None:
    sign_in(client, make_user(ctx, "root", role="admin"))
    assert client.get("/api/v1/admin/dashboard", params={"period": "1y"}).status_code == 422
