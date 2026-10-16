"""Authentication cases of the security matrix."""

import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text, update

from app.core.context import AppContext
from app.core.security import PasswordHasher
from app.models import AuthSession, PasswordResetToken, User
from app.services import account_service, audit_service
from tests.helpers import PASSWORD, make_user, sign_in, totp_code, write


def _new_client(client: TestClient) -> TestClient:
    return TestClient(
        client.app, base_url="https://testserver", headers={"X-Requested-With": "XMLHttpRequest"}
    )


def test_unknown_user_and_wrong_password_look_identical(
    client: TestClient, ctx: AppContext
) -> None:
    make_user(ctx, "bob")
    with patch.object(
        PasswordHasher, "verify", autospec=True, side_effect=PasswordHasher.verify
    ) as verify:
        unknown = client.post(
            "/api/v1/auth/login", json={"username": "nobody", "password": "x" * 20}
        )
        wrong = client.post("/api/v1/auth/login", json={"username": "bob", "password": "x" * 20})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]
    # Both paths run one Argon2id verification (dummy hash for unknown users): equal work.
    assert verify.call_count == 2


def test_repeated_failures_are_delayed(client: TestClient, ctx: AppContext) -> None:
    make_user(ctx, "bob")
    statuses = [
        client.post(
            "/api/v1/auth/login", json={"username": "bob", "password": "wrong password!"}
        ).status_code
        for _ in range(7)
    ]
    assert statuses[:6] == [401] * 6
    assert statuses[6] == 429


def test_password_change_revokes_other_sessions(client: TestClient, ctx: AppContext) -> None:
    bob = make_user(ctx, "bob")
    with _new_client(client) as other:
        sign_in(other, bob)
        sign_in(client, bob)
        new_password = "a completely new passphrase 7"
        response = write(
            client,
            "POST",
            "/api/v1/me/password",
            json={"current_password": PASSWORD, "new_password": new_password},
        )
        assert response.status_code == 200, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        assert other.get("/api/v1/auth/session").status_code == 401
        assert client.get("/api/v1/auth/session").status_code == 200


def test_common_and_short_passwords_are_rejected(client: TestClient, ctx: AppContext) -> None:
    sign_in(client, make_user(ctx, "bob"))
    for candidate in ("short", "password1234", "qwertyuiopasdfgh"):
        response = write(
            client,
            "POST",
            "/api/v1/me/password",
            json={"current_password": PASSWORD, "new_password": candidate},
        )
        assert response.status_code == 422, candidate


def test_reset_token_is_single_use_and_expires(client: TestClient, ctx: AppContext) -> None:
    bob = make_user(ctx, "bob")
    with ctx.sessions() as db:
        user = db.get(User, bob.id)
        assert user is not None
        link, _ = account_service.issue_reset_token(db, ctx, user, "reset")
        db.commit()
    token = link.split("token=")[1]
    body = {"token": token, "new_password": "brand new passphrase 99"}
    assert client.post("/api/v1/auth/password-reset/confirm", json=body).status_code == 204
    assert client.post("/api/v1/auth/password-reset/confirm", json=body).status_code == 400

    with ctx.sessions() as db:
        user = db.get(User, bob.id)
        assert user is not None
        link, _ = account_service.issue_reset_token(db, ctx, user, "reset")
        db.execute(
            update(PasswordResetToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        db.commit()
    expired = {"token": link.split("token=")[1], "new_password": "another passphrase 77"}
    assert client.post("/api/v1/auth/password-reset/confirm", json=expired).status_code == 400


def test_reset_revokes_all_sessions(client: TestClient, ctx: AppContext) -> None:
    bob = make_user(ctx, "bob")
    sign_in(client, bob)
    with ctx.sessions() as db:
        user = db.get(User, bob.id)
        assert user is not None
        link, _ = account_service.issue_reset_token(db, ctx, user, "reset")
        db.commit()
    body = {"token": link.split("token=")[1], "new_password": "brand new passphrase 99"}
    with _new_client(client) as anonymous:
        assert anonymous.post("/api/v1/auth/password-reset/confirm", json=body).status_code == 204
    assert client.get("/api/v1/auth/session").status_code == 401


def test_reset_request_response_does_not_reveal_accounts(
    client: TestClient, ctx: AppContext
) -> None:
    make_user(ctx, "bob", email="bob@example.com")
    known = client.post("/api/v1/auth/password-reset", json={"email": "bob@example.com"})
    unknown = client.post("/api/v1/auth/password-reset", json={"email": "ghost@example.com"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()


def test_totp_code_cannot_be_replayed(client: TestClient, ctx: AppContext) -> None:
    admin = make_user(ctx, "root", role="admin")
    assert admin.totp_secret is not None
    code = totp_code(admin.totp_secret)
    login = client.post("/api/v1/auth/login", json={"username": "root", "password": PASSWORD})
    client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    assert client.post("/api/v1/auth/mfa/totp", json={"code": code}).status_code == 200
    with _new_client(client) as second:
        login = second.post("/api/v1/auth/login", json={"username": "root", "password": PASSWORD})
        second.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        response = second.post("/api/v1/auth/mfa/totp", json={"code": code})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_CODE"


def test_admin_with_mfa_reaches_admin_routes(client: TestClient, ctx: AppContext) -> None:
    sign_in(client, make_user(ctx, "root", role="admin"))
    assert client.get("/api/v1/admin/users").status_code == 200


def test_session_cookie_flags(client: TestClient, ctx: AppContext) -> None:
    make_user(ctx, "bob")
    response = client.post("/api/v1/auth/login", json={"username": "bob", "password": PASSWORD})
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("__Host-session=")
    for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert flag.lower() in cookie.lower()
    assert "domain=" not in cookie.lower()


def test_session_id_rotates_after_second_factor(client: TestClient, ctx: AppContext) -> None:
    admin = make_user(ctx, "root", role="admin")
    first = client.post("/api/v1/auth/login", json={"username": "root", "password": PASSWORD})
    client.headers["X-CSRF-Token"] = first.json()["csrf_token"]
    assert admin.totp_secret is not None
    second = client.post("/api/v1/auth/mfa/totp", json={"code": totp_code(admin.totp_secret)})
    assert first.cookies["__Host-session"] != second.cookies["__Host-session"]


def test_admin_session_expires_after_one_hour_idle(client: TestClient, ctx: AppContext) -> None:
    admin = make_user(ctx, "root", role="admin")
    sign_in(client, admin)
    with ctx.sessions() as db:
        session = db.scalar(select(AuthSession).where(AuthSession.user_id == admin.id))
        assert session is not None
        assert session.idle_expires_at - session.last_seen_at <= timedelta(hours=1)
        session.idle_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/v1/auth/session").status_code == 401


def test_sensitive_action_requires_recent_authentication(
    client: TestClient, ctx: AppContext
) -> None:
    admin = make_user(ctx, "root", role="admin")
    target = make_user(ctx, "bob")
    sign_in(client, admin)
    with ctx.sessions() as db:
        db.execute(update(AuthSession).values(reauth_at=datetime.now(UTC) - timedelta(minutes=10)))
        db.commit()
    response = write(client, "POST", f"/api/v1/admin/users/{target.id}/reset-mfa")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "REAUTH_REQUIRED"
    assert admin.totp_secret is not None
    reauth = write(
        client,
        "POST",
        "/api/v1/auth/reauth",
        json={"password": PASSWORD, "totp_code": totp_code(admin.totp_secret, 1)},
    )
    assert reauth.status_code == 200, reauth.text
    client.headers["X-CSRF-Token"] = reauth.json()["csrf_token"]
    assert write(client, "POST", f"/api/v1/admin/users/{target.id}/reset-mfa").status_code == 204


def test_password_is_never_logged(
    client: TestClient, ctx: AppContext, caplog: pytest.LogCaptureFixture
) -> None:
    make_user(ctx, "bob")
    with caplog.at_level(logging.DEBUG):
        client.post("/api/v1/auth/login", json={"username": "bob", "password": PASSWORD})
        client.post(
            "/api/v1/auth/login", json={"username": "bob", "password": "wrong but secret pw"}
        )
    assert PASSWORD not in caplog.text
    assert "wrong but secret pw" not in caplog.text


def test_audit_tampering_is_detected(
    client: TestClient, ctx: AppContext, superuser_engine: Engine
) -> None:
    make_user(ctx, "bob")
    for _ in range(3):
        client.post("/api/v1/auth/login", json={"username": "bob", "password": "wrong password!"})
    with ctx.sessions() as db:
        assert audit_service.verify_chain(db) is None
    with superuser_engine.begin() as conn:
        conn.execute(text("UPDATE audit_events SET outcome = 'success' WHERE id = 2"))
    with ctx.sessions() as db:
        assert audit_service.verify_chain(db) == 2


def test_runtime_role_cannot_alter_audit_trail(ctx: AppContext, client: TestClient) -> None:
    make_user(ctx, "bob")
    client.post("/api/v1/auth/login", json={"username": "bob", "password": "wrong password!"})
    with ctx.engine.connect() as conn, pytest.raises(Exception, match="permission denied"):
        conn.execute(text("DELETE FROM audit_events"))
