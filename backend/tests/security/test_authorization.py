"""Authorization matrix generated from the app's routes: new routes are covered automatically."""

import re
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.context import AppContext
from app.core.permissions import PUBLIC, route_policies
from app.models import AuthSession
from tests.helpers import make_user, sign_in, write

PUBLIC_ROUTES = {
    ("GET", "/api/v1/health"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/password-reset"),
    ("POST", "/api/v1/auth/password-reset/confirm"),
    # Honeytoken: public by design, any call blocks the caller.
    ("GET", "/api/v1/debug/config"),
    # Single sign-on: browser redirects before any session exists.
    ("GET", "/api/v1/auth/methods"),
    ("GET", "/api/v1/auth/oidc/start"),
    ("GET", "/api/v1/auth/oidc/callback"),
}


def _sample(path: str) -> str:
    return re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)


def _routes(app: FastAPI) -> list[tuple[str, str]]:
    return sorted(route_policies(app))


def test_every_route_declares_exactly_one_policy(app: FastAPI) -> None:
    policies = route_policies(app)
    assert {key for key, policy in policies.items() if policy == PUBLIC} == PUBLIC_ROUTES


def test_route_without_policy_fails_startup(app: FastAPI) -> None:
    @app.get("/api/v1/undeclared")
    def undeclared() -> None:
        return None

    with pytest.raises(RuntimeError, match="access policy"):
        route_policies(app)


def test_routes_require_authentication(app: FastAPI, client: TestClient) -> None:
    for method, path in _routes(app):
        if (method, path) in PUBLIC_ROUTES:
            continue
        response = write(client, method, _sample(path), json={})
        assert response.status_code == 401, f"{method} {path} -> {response.status_code}"


def test_admin_routes_forbidden_to_users(app: FastAPI, client: TestClient, ctx: AppContext) -> None:
    sign_in(client, make_user(ctx, "bob"))
    admin_routes = [(m, p) for m, p in _routes(app) if p.startswith("/api/v1/admin/")]
    assert admin_routes
    for method, path in admin_routes:
        response = write(client, method, _sample(path), json={})
        assert response.status_code == 403, f"{method} {path} -> {response.status_code}"


def test_admin_without_mfa_cannot_reach_admin_routes(client: TestClient, ctx: AppContext) -> None:
    admin = make_user(ctx, "newadmin", role="admin", totp=False)
    response = sign_in(client, admin)
    assert response.json()["state"] == "mfa_enrollment_required"
    assert client.get("/api/v1/admin/users").status_code == 403


def test_other_users_session_is_hidden(client: TestClient, ctx: AppContext) -> None:
    alice = make_user(ctx, "alice")
    with TestClient(
        client.app, base_url="https://testserver", headers={"X-Requested-With": "XMLHttpRequest"}
    ) as other:
        sign_in(other, alice)
    with ctx.sessions() as db:
        alice_session = db.scalar(select(AuthSession.id).where(AuthSession.user_id == alice.id))
    sign_in(client, make_user(ctx, "bob"))
    assert write(client, "DELETE", f"/api/v1/me/sessions/{alice_session}").status_code == 404


def test_other_users_security_key_is_hidden(client: TestClient, ctx: AppContext) -> None:
    sign_in(client, make_user(ctx, "bob"))
    response = write(client, "DELETE", f"/api/v1/me/mfa/webauthn/{uuid.uuid4()}")
    assert response.status_code == 404
